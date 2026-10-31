"""让 app 里那些「SQLite 写法」的 SQL 直接跑在 MySQL 上。

思路：**不在 app 里改 SQL**（390 条、533 个占位符，手改必漏），
而是在连接层做一层薄适配，把差异全部收在 mysqldialect.py 里。

这一层要做的事：
    1. 连接：用 pymysql，等价于 sqlite3.connect() 的用法
    2. 游标：DictCursor → 行对象支持 row["列名"] / dict(row) / row.keys()，
       这正是 `conn.row_factory = sqlite3.Row` 提供的能力
    3. execute/executemany：把 ? 换成 %s，并处理字面 %
    4. executescript：拆语句 + 翻译 DDL（PRAGMA / CREATE TABLE / CREATE INDEX）
    5. lastrowid / rowcount / description / commit / rollback / close：语义一致
    6. 事务：InnoDB + autocommit=False，和 sqlite3 默认的「显式 commit」一致

⚠️ 一个必须说清的差异：MySQL 的默认排序规则是**大小写不敏感**（utf8mb4_0900_ai_ci），
   而 SQLite 的 `=` 比较是**大小写敏感**的。
   已核对过：本库所有唯一列（username / phone / code / invite_code / k / token）
   都不存在「仅大小写不同」的重复值，所以这个差异不会改变现有数据的行为。
"""
from __future__ import annotations

import re
from decimal import Decimal

import mysqldialect as dialect


def _convert(v):
    """把 MySQL 特有的返回类型转成 SQLite 会返回的等价类型。

    最关键的差异：**聚合函数**。
        SQLite：SUM(整数列) → INTEGER
        MySQL ：SUM(整数列) → DECIMAL（PyMySQL 给 decimal.Decimal）
    Decimal 不能直接被 JSON 序列化，Flask 会把它写成**字符串**，
    于是接口里 `"today": 0` 变成 `"today": "0"` —— 客户端拿到的类型就变了。

    这个库里的聚合都是计数（SUM(CASE WHEN … THEN 1 ELSE 0 END)），
    整数值必须还原成 int，和 SQLite 行为对齐。
    """
    if isinstance(v, Decimal):
        return int(v) if v == v.to_integral_value() else float(v)
    return v


def _row(row):
    if row is None:
        return None
    if isinstance(row, dict):
        return {(k if isinstance(k, str) else k): _convert(v) for k, v in row.items()}
    if isinstance(row, (tuple, list)):
        return tuple(_convert(v) for v in row)
    return row


def _prepare(sql, params, debug=False):
    """返回 (stmt, args)：翻译语句 + 占位符，并决定是否要转义字面 %。"""
    stmt = dialect.translate_statement(sql)
    if stmt == 'SELECT 1':
        # PRAGMA 的静默替身，不需要任何参数处理
        return stmt, None
    has_params = params is not None and len(params) > 0
    stmt = dialect.to_paramstyle(stmt, escape_percent=has_params)
    if debug:
        print('[mysql] %s  <- %s' % (stmt[:160], sql[:100]), flush=True)
    return stmt, (tuple(params) if has_params else None)


class CompatCursor:
    """包住 pymysql 的 DictCursor，补齐 sqlite3 游标的常用接口。

    ⚠️ sqlite3 里 `conn.cursor().execute(...)` 是很常规的写法，
    所以 execute/executemany 必须挂在**游标**上（不能只挂在连接上）。
    """

    __slots__ = ('_cur', '_debug')

    def __init__(self, cur, debug=False):
        self._cur = cur
        self._debug = debug

    # ---- 执行
    def execute(self, sql, params=None):
        stmt, args = _prepare(sql, params, self._debug)
        self._cur.execute(stmt, args)
        return self

    def executemany(self, sql, seq):
        seq = list(seq)
        stmt, _ = _prepare(sql, seq[0] if seq else None, self._debug)
        self._cur.executemany(stmt, seq)
        return self

    def close(self):
        try:
            self._cur.close()
        except Exception:
            pass

    # ---- 取值
    def fetchone(self):
        return _row(self._cur.fetchone())

    def fetchall(self):
        return [_row(r) for r in self._cur.fetchall()]

    def fetchmany(self, size=None):
        rows = self._cur.fetchmany(size) if size else self._cur.fetchmany()
        return [_row(r) for r in rows]

    def __iter__(self):
        return iter([_row(r) for r in self._cur.fetchall()])

    # ---- 元信息
    @property
    def lastrowid(self):
        return self._cur.lastrowid

    @property
    def rowcount(self):
        return self._cur.rowcount

    @property
    def description(self):
        return self._cur.description

    @property
    def arraysize(self):
        return self._cur.arraysize


class CompatConnection:
    """把 pymysql 连接伪装成 sqlite3 连接。"""

    def __init__(self, raw, debug: bool = False):
        self._raw = raw
        # DictCursor 已在 connect(cursorclass=DictCursor) 时指定，这里不再传参
        # （PyMySQL 1.1+ 起 cursor() 的参数语义有变化，少传一个参数最稳）
        self._cur = raw.cursor()
        self._debug = debug

    # ---- sqlite3 里可写、这里忽略的属性
    @property
    def row_factory(self):
        return None

    @row_factory.setter
    def row_factory(self, _value):
        # app 会写 conn.row_factory = sqlite3.Row；
        # MySQL 侧由 DictCursor 直接提供同样的能力，无需设置。
        pass

    @property
    def total_changes(self):
        return 0

    # ---- 执行
    def execute(self, sql, params=None):
        stmt, args = _prepare(sql, params, self._debug)
        self._cur.execute(stmt, args)
        return CompatCursor(self._cur, self._debug)

    def executemany(self, sql, seq):
        seq = list(seq)
        stmt, _ = _prepare(sql, seq[0] if seq else None, self._debug)
        self._cur.executemany(stmt, seq)
        return CompatCursor(self._cur, self._debug)

    def executescript(self, script):
        """对应 sqlite3 的 executescript：整段脚本，逐条翻译后执行。

        幂等性：SQLite 的 `CREATE TABLE IF NOT EXISTS` 在 MySQL 里原生支持，
        但 `CREATE INDEX IF NOT EXISTS` 不支持 —— 上面翻译时会把它剥掉，
        重复建索引会抛 1061。这里把「已存在」类的错误当成正常跳过，
        等价于 IF NOT EXISTS 的语义，也保证 init_db() 可以反复执行。
        """
        benign = {1050, 1061, 1826}      # 表已存在 / 索引名重复 / 外键名重复
        applied = skipped = 0
        for stmt in dialect.translate_script(script):
            if not stmt.strip():
                continue
            try:
                self._cur.execute(stmt)
                applied += 1
            except Exception as exc:
                if getattr(exc, 'args', (None,))[0] in benign:
                    skipped += 1
                    continue
                raise
        return applied, skipped

    def cursor(self, *args, **kwargs):
        return CompatCursor(self._cur, self._debug)

    # ---- 事务
    def commit(self):
        self._raw.commit()

    def rollback(self):
        self._raw.rollback()

    def close(self):
        try:
            self._cur.close()
        finally:
            self._raw.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self.commit()
        else:
            self.rollback()
        return False


def connect(host, port, user, password, database, charset='utf8mb4',
            debug=False, connect_timeout=10):
    """建一条 MySQL 连接（DictCursor 版）。"""
    import pymysql
    from pymysql.cursors import DictCursor

    raw = pymysql.connect(
        host=host, port=int(port), user=user, password=password,
        database=database, charset=charset, autocommit=False,
        cursorclass=DictCursor, connect_timeout=connect_timeout,
    )
    return CompatConnection(raw, debug=debug)
