"""SQLite → MySQL 8 方言翻译。

这个模块被两处共用，是**唯一**的翻译逻辑来源：
  1. `tools/mysql/migrate_sqlite_to_mysql.py` —— 一次性把老库搬过去
  2. `mysqldb.py` —— 运行时让 app 里 390 条 SQLite 写法的 SQL 直接跑在 MySQL 上

为什么不手工改 app 里那 390 条 SQL：
    533 个 `?` 占位符、27 处 LIKE、42 条 CREATE TABLE……
    手改必然漏，而且漏了不一定报错（比如 % 转义），会变成静默的数据错误。
    用一层翻译把差异收在**一个文件**里，可审计、可测试、可回退。

翻译规则（每条都对应库里真实出现过的东西）：
    INTEGER PRIMARY KEY AUTOINCREMENT → INT NOT NULL AUTO_INCREMENT PRIMARY KEY
    INTEGER / INT                     → INT（字节数列 → BIGINT，见 BYTE_LIKE_NAMES）
    REAL / FLOAT                      → DOUBLE
    TEXT（主键/唯一/被索引）           → VARCHAR(255)   MySQL 不能给 TEXT 建无前缀索引
    TEXT DEFAULT 'x'                  → TEXT DEFAULT ('x')   ⚠️ 必须带括号（表达式默认值）
    BLOB                              → LONGBLOB
    PRAGMA table_info(t)              → 查 information_schema（要保留 name 列名）
    PRAGMA 其它                       → SELECT 1（静默忽略，MySQL 无对应概念）
    INSERT OR IGNORE                  → INSERT IGNORE
    INSERT OR REPLACE                 → REPLACE
    ?                                 → %s（仅引号外；引号内的 ? 是普通字符）
    字面 %                            → %%（仅在有参数时；pymysql 用 %s 做客户端插值）
"""
from __future__ import annotations

import re

# ------------------------------------------------------------------ 类型

INT_MAX = 2147483647          # MySQL INT 有符号上限
INT_MIN = -2147483648

TYPE_MAP = {
    'INTEGER': 'INT', 'INT': 'INT', 'BIGINT': 'BIGINT', 'SMALLINT': 'SMALLINT',
    'REAL': 'DOUBLE', 'FLOAT': 'DOUBLE', 'DOUBLE': 'DOUBLE', 'NUMERIC': 'DECIMAL(20,6)',
    'TEXT': 'TEXT', 'CLOB': 'TEXT', 'VARCHAR': 'VARCHAR(255)', 'CHAR': 'CHAR(1)',
    'BLOB': 'LONGBLOB', 'BOOLEAN': 'TINYINT',
}

INDEXABLE_REPLACEMENT = 'VARCHAR(255)'

# 按列名语义直接给 BIGINT。SQLite 的 INTEGER 是 64 位、MySQL 的 INT 是 32 位，
# 这个库里有 3.9GB 的课件包（4,187,501,629 字节），远超 INT 上限。
BYTE_LIKE_NAMES = {'size', 'file_size', 'bytes', 'content_length', 'total_size'}

TABLE_SUFFIX = 'ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci'

Q = lambda ident: '`' + str(ident).replace('`', '``') + '`'      # noqa: E731


# ------------------------------------------------------------------ 词法

def strip_sql_comments(s: str) -> str:
    """剥掉 `-- 行注释`，但不动字符串字面量里的内容。

    MySQL 只在 `-- `（后面跟空白）时才算注释，SQLite 更宽松 ——
    schema 里那些 `-- ongoing | submitted` 尾注释必须清掉，否则行为不一致。
    """
    out, i, n = [], 0, len(s)
    while i < n:
        ch = s[i]
        if ch in ("'", '"', '`'):
            q = ch
            out.append(ch); i += 1
            while i < n:
                if s[i] == q:
                    if i + 1 < n and s[i + 1] == q:
                        out.append(s[i:i + 2]); i += 2; continue
                    out.append(q); i += 1; break
                out.append(s[i]); i += 1
            continue
        if ch == '-' and i + 1 < n and s[i + 1] == '-':
            j = s.find('\n', i)
            if j == -1:
                break
            i = j
            continue
        out.append(ch); i += 1
    return ''.join(out)


def split_top_level(s: str, sep: str = ',') -> list[str]:
    """按 sep 在「括号 / 引号之外」切分。"""
    parts, buf, depth, i, n = [], [], 0, 0, len(s)
    while i < n:
        ch = s[i]
        if ch in ("'", '"', '`'):
            q = ch
            buf.append(ch); i += 1
            while i < n:
                buf.append(s[i])
                if s[i] == q:
                    if i + 1 < n and s[i + 1] == q:
                        buf.append(s[i + 1]); i += 2; continue
                    i += 1; break
                i += 1
            continue
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
        if ch == sep and depth == 0:
            parts.append(''.join(buf).strip()); buf = []; i += 1; continue
        buf.append(ch); i += 1
    tail = ''.join(buf).strip()
    if tail:
        parts.append(tail)
    return parts


def split_script(script: str) -> list[str]:
    """把多语句脚本按顶层 `;` 切成单条语句（跳过注释）。"""
    out, buf, i, n = [], [], 0, len(script)
    while i < n:
        ch = script[i]
        if ch in ("'", '"', '`'):
            q = ch
            buf.append(ch); i += 1
            while i < n:
                buf.append(script[i])
                if script[i] == q:
                    if i + 1 < n and script[i + 1] == q:
                        buf.append(script[i + 1]); i += 2; continue
                    i += 1; break
                i += 1
            continue
        if ch == '-' and i + 1 < n and script[i + 1] == '-':
            j = script.find('\n', i)
            i = n if j == -1 else j
            continue
        if ch == ';':
            stmt = ''.join(buf).strip()
            if stmt:
                out.append(stmt)
            buf = []; i += 1; continue
        buf.append(ch); i += 1
    tail = ''.join(buf).strip()
    if tail:
        out.append(tail)
    return out


# ------------------------------------------------------------------ 占位符

def to_paramstyle(sql: str, escape_percent: bool) -> str:
    """`?` → `%s`；并在有参数时把字面 `%` 转义成 `%%`。

    ⚠️ 两个都只在「引号之外」处理的是 `?`；`%` 必须**连引号内一起**转义 ——
    因为 pymysql 是用 Python 的 `query % args` 做插值的，它不管引号，
    字符串字面量里的 `%` 同样会被当成格式符。
    （本库实测 SQL 文本里没有字面 %，27 处 LIKE 的 % 都在参数值里，此处分文
     处理是防御性的，不影响现有行为。）
    """
    out, i, n = [], 0, len(sql)
    while i < n:
        ch = sql[i]
        if ch in ("'", '"', '`'):
            q = ch
            out.append(ch); i += 1
            while i < n:
                c2 = sql[i]
                if c2 == '%' and escape_percent:
                    out.append('%%'); i += 1; continue
                out.append(c2)
                if c2 == q:
                    if i + 1 < n and sql[i + 1] == q:
                        out.append(sql[i + 1]); i += 2; continue
                    i += 1; break
                i += 1
            continue
        if ch == '%' and escape_percent:
            out.append('%%'); i += 1; continue
        if ch == '?':
            out.append('%s'); i += 1; continue
        out.append(ch); i += 1
    return ''.join(out)


# ------------------------------------------------------------------ DDL

def indexed_columns_from_script(statements) -> set:
    """从一批 CREATE INDEX 语句里解析出 (表, 列)。

    ⚠️ 必须容忍 `IF NOT EXISTS`：app 的 db.SCHEMA 里写的是
       `CREATE INDEX IF NOT EXISTS idx_x ON t(c)`，而 `\\S+` 会把 `IF` 当成索引名，
       匹配不到后面的 ON → 整条解析失败 → 该列不会被识别为「被索引」，
       于是 TEXT 列不会变成 VARCHAR(255)，建索引时报 1170。
    """
    out = set()
    for sql in statements:
        s = strip_sql_comments(sql).strip().rstrip(';')
        s = re.sub(r'^CREATE\s+(UNIQUE\s+)?INDEX\s+IF\s+NOT\s+EXISTS\b',
                   lambda g: 'CREATE ' + (g.group(1) or '') + 'INDEX', s, flags=re.I)
        m = re.match(r'CREATE\s+(?:UNIQUE\s+)?INDEX\s+\S+\s+ON\s+'
                     r'("[^"]+"|`[^`]+`|\[[^\]]+\]|\S+)\s*\((.*)\)\s*$', s, re.S | re.I)
        if not m:
            continue
        t = m.group(1).strip('"`[]')
        for c in split_top_level(m.group(2)):
            name = re.split(r'\s+', c.strip())[0].strip('"`[]')
            if name:
                out.add((t, name))
    return out


def translate_column_def(defn: str, overrides: dict | None = None,
                         table: str | None = None,
                         indexed: set | None = None) -> str:
    """翻译单个列定义（CREATE TABLE 里的一项，或 ALTER TABLE ADD COLUMN 的列部分）。"""
    overrides = overrides or {}
    indexed = indexed or set()

    cm = re.match(r'\s*("[^"]+"|`[^`]+`|\[[^\]]+\]|[A-Za-z_][A-Za-z0-9_]*)\s+(.*)$', defn, re.S)
    if not cm:
        raise ValueError('认不出的列定义：' + defn[:80])
    col = cm.group(1).strip('"`[]')
    rest = cm.group(2).strip()

    tm = re.match(r'([A-Za-z]+(?:\s*\([^)]*\))?)\s*(.*)$', rest, re.S)
    if not tm:
        raise ValueError('认不出的列类型：' + defn[:80])
    col_type, rest = tm.group(1).upper(), tm.group(2)
    col_type = TYPE_MAP.get(col_type.split('(')[0].strip(), col_type)

    # ① 数据驱动的类型覆盖（迁移工具用；运行时为空）
    if table is not None and (table, col) in overrides:
        col_type = overrides[(table, col)]
    # ② 按列名语义：字节数一律 BIGINT
    elif col_type in ('INT', 'BIGINT') and col.lower() in BYTE_LIKE_NAMES:
        col_type = 'BIGINT'

    is_pk = bool(re.search(r'\bPRIMARY\s+KEY\b', rest, re.I))
    is_uq = bool(re.search(r'\bUNIQUE\b', rest, re.I))
    # ③ TEXT 参与主键/唯一/索引 → VARCHAR(255)
    if col_type == 'TEXT' and (is_pk or is_uq or (table, col) in indexed):
        col_type = INDEXABLE_REPLACEMENT

    auto_inc = bool(re.search(r'\bAUTOINCREMENT\b', rest, re.I))
    not_null = bool(re.search(r'\bNOT\s+NULL\b', rest, re.I))

    dm = re.search(r"\bDEFAULT\s+('(?:[^']|'')*'|\"[^\"]*\"|[^\s,]+)", rest, re.I)
    default_sql = None
    if dm:
        raw = dm.group(1)
        if raw.upper() == 'NULL':
            default_sql = 'NULL'
        elif raw.startswith(("'", '"')):
            lit = raw[1:-1].replace("''", "'").replace('"', '"')
            body = lit.replace('\\', '\\\\').replace("'", "''")
            # ⚠️ TEXT 必须用表达式默认值 DEFAULT ('x')，MySQL 才接受
            default_sql = "('" + body + "')" if col_type == 'TEXT' else "'" + body + "'"
        else:
            default_sql = raw if re.match(r'^-?[\d.]+$', raw) else '(' + raw + ')'

    pieces = [Q(col), col_type]
    if not_null:
        pieces.append('NOT NULL')
    if default_sql is not None:
        pieces.append('DEFAULT ' + default_sql)
    if auto_inc:
        pieces.append('AUTO_INCREMENT')
    if is_uq and not is_pk:
        pieces.append('UNIQUE')
    return ' '.join(pieces)


def translate_create_table(sql: str, overrides: dict | None = None,
                           table: str | None = None,
                           indexed: set | None = None) -> str:
    """把一条 CREATE TABLE 从 SQLite 翻成 MySQL。"""
    indexed = indexed or set()
    s = strip_sql_comments(sql).strip().rstrip(';')
    m = re.match(r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?'
                 r'("[^"]+"|`[^`]+`|\[[^\]]+\]|\S+)\s*\((.*)\)\s*$', s, re.S | re.I)
    if not m:
        raise ValueError('认不出的 CREATE TABLE：' + s[:120])
    name = m.group(1).strip('"`[]')
    tname = table or name
    items = split_top_level(m.group(2))

    # 先扫表级主键/唯一，供列内联判断用
    pk_cols, uq_cols = set(), set()
    for it in items:
        up = it.upper()
        if up.startswith(('PRIMARY KEY', 'UNIQUE')):
            g = re.search(r'\((.*)\)', it, re.S)
            if not g:
                continue
            names = {c.strip().strip('"`[]') for c in split_top_level(g.group(1))}
            if up.startswith('PRIMARY KEY'):
                pk_cols.update(names)
            else:
                uq_cols.update(names)

    cols_out, constraints = [], []
    # 表级 PRIMARY KEY / UNIQUE 里的 TEXT 列同样要变 VARCHAR(255)，
    # 所以把它们并进「(表, 列)」集合一起交给列翻译。
    # ⚠️ pk_cols / uq_cols 里存的是**列名**，索引集合里存的是 (表, 列) 元组，
    #    必须先归一化，否则 ('t','col') in colset 永远为假 —— 复合主键里的
    #    TEXT 列就会被漏掉，建表时报 1170。
    colset = set(indexed)
    colset |= {(tname, c) for c in pk_cols}
    colset |= {(tname, c) for c in uq_cols}
    for it in items:
        up = it.upper()
        if re.match(r'^(PRIMARY\s+KEY|UNIQUE|CHECK|FOREIGN\s+KEY|CONSTRAINT)\b', up):
            constraints.append(it)
            continue
        colname = re.match(r'\s*("[^"]+"|`[^`]+`|\[[^\]]+\]|[A-Za-z_][A-Za-z0-9_]*)', it)
        cname = colname.group(1).strip('"`[]') if colname else ''
        out = translate_column_def(it, overrides, tname, colset)
        # 单列主键补内联 PRIMARY KEY（复合主键由表级约束负责）
        if (cname in pk_cols or re.search(r'\bPRIMARY\s+KEY\b', it, re.I)) \
                and len(pk_cols) <= 1 and not any(
                    re.match(r'^PRIMARY\s+KEY', c, re.I) for c in constraints):
            if 'PRIMARY KEY' not in out.upper():
                out += ' PRIMARY KEY'
        cols_out.append('  ' + out)

    body = ',\n'.join(cols_out + ['  ' + c for c in constraints])
    return 'CREATE TABLE %s (\n%s\n) %s' % (Q(tname), body, TABLE_SUFFIX)


def translate_index(sql: str, need_prefix: set | None = None) -> str:
    """翻译 CREATE INDEX；对无法建索引的长 TEXT 列补前缀长度。

    ⚠️ MySQL **不支持** `CREATE INDEX IF NOT EXISTS`（那是 MariaDB 的扩展），
       这里必须剥掉；幂等性改由执行的兼容层容错（重复索引名 1061 直接跳过）。
    """
    need_prefix = need_prefix or set()
    s = strip_sql_comments(sql).strip().rstrip(';')
    s = re.sub(r'^CREATE\s+(UNIQUE\s+)?INDEX\s+IF\s+NOT\s+EXISTS\b',
               lambda g: 'CREATE ' + (g.group(1) or '') + 'INDEX', s, flags=re.I)
    m = re.match(r'(CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?\S+\s+ON\s+'
                 r'("[^"]+"|`[^`]+`|\[[^\]]+\]|\S+)\s*)\((.*)\)\s*$', s, re.S | re.I)
    if not m:
        return s
    head, t_raw, colpart = m.group(1), m.group(2), m.group(3)
    t = t_raw.strip('"`[]')
    cols = []
    for c in split_top_level(colpart):
        raw = c.strip()
        cname = re.split(r'\s+', raw)[0].strip('"`[]')
        if (t, cname) in need_prefix and not re.search(r'\(\s*\d+\s*\)', raw):
            raw = raw.replace(cname, '%s(191)' % cname, 1)
        cols.append(raw)
    return head + '(' + ', '.join(cols) + ')'


# ------------------------------------------------------------------ 语句级

_RE_PRAGMA_TABLE_INFO = re.compile(
    r'^PRAGMA\s+table_info\s*\(\s*["`\[]?([A-Za-z_][A-Za-z0-9_]*)["`\]]?\s*\)\s*;?$', re.I)
_RE_ALTER_ADD_COL = re.compile(
    r'^(ALTER\s+TABLE\s+("[^"]+"|`[^`]+`|\[[^\]]+\]|\S+)\s+ADD\s+(?:COLUMN\s+)?)(.+)$', re.I | re.S)
_RE_CREATE_TABLE = re.compile(r'^CREATE\s+TABLE\b', re.I)


def translate_statement(sql: str, indexed: set | None = None,
                        overrides: dict | None = None) -> str:
    """把一条 SQLite 语句翻成 MySQL 语句（不含占位符处理）。"""
    indexed = indexed or set()
    s = sql.strip().rstrip(';')

    # ① PRAGMA
    m = _RE_PRAGMA_TABLE_INFO.match(s)
    if m:
        # 保留 name / type / notnull / dflt_value / pk 这套 SQLite 列名，
        # 因为 db.py 的 ensure_column 用的是 row["name"]
        return (
            "SELECT COLUMN_NAME AS name, DATA_TYPE AS type, "
            "IF(IS_NULLABLE='NO',1,0) AS notnull, "
            "COLUMN_DEFAULT AS dflt_value, IF(COLUMN_KEY='PRI',1,0) AS pk "
            "FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = '%s' "
            "ORDER BY ORDINAL_POSITION" % m.group(1))
    if re.match(r'^PRAGMA\b', s, re.I):
        # journal_mode / foreign_keys / wal_checkpoint … MySQL 无对应概念。
        # 返回一行空结果，让调用方（不 fetch）不报错。
        return 'SELECT 1'

    # ② INSERT OR …
    s = re.sub(r'^INSERT\s+OR\s+IGNORE\b', 'INSERT IGNORE', s, flags=re.I)
    s = re.sub(r'^INSERT\s+OR\s+REPLACE\b', 'REPLACE', s, flags=re.I)
    s = re.sub(r'^INSERT\s+OR\s+(?:ABORT|FAIL|ROLLBACK)\b', 'INSERT', s, flags=re.I)
    s = re.sub(r'^UPDATE\s+OR\s+IGNORE\b', 'UPDATE', s, flags=re.I)

    # ②b upsert：SQLite 的 ON CONFLICT … DO UPDATE 在 MySQL 里是 ON DUPLICATE KEY UPDATE
    #     SQLite 用 `excluded.列` 指代「本来要插入的值」；MySQL 里对应 VALUES(列)。
    #     语义等价的前提：ON DUPLICATE KEY UPDATE 会对**任意**唯一键冲突生效，
    #     而这三处（settings.k / study_days.(user_id,day) / course_progress.(user_id,course_id)）
    #     表上只有这一个主键，所以行为和 ON CONFLICT(指定列) 完全一致。
    #     （MySQL 8.0.20+ 把 VALUES() 标为 deprecated，官方推荐行别名 `AS new`；
    #       这里仍用 VALUES()，因为它同时兼容 MySQL 8 与 MariaDB，且 8.0 上仍然可用。）
    s = re.sub(r'\s+ON\s+CONFLICT\s*\([^)]*\)\s+DO\s+NOTHING\b', '', s, flags=re.I)
    m = re.search(r'\s+ON\s+CONFLICT\s*\([^)]*\)\s+DO\s+UPDATE\s+SET\s+', s, re.I)
    if m:
        head, tail = s[:m.start()], s[m.end():]
        tail = re.sub(r'\bexcluded\s*\.\s*("[^"]*"|`[^`]*`|\w+)',
                      lambda g: 'VALUES(%s)' % g.group(1), tail, flags=re.I)
        s = head + ' ON DUPLICATE KEY UPDATE ' + tail

    # ③ ALTER TABLE … ADD COLUMN <sqlite 列定义>
    m = _RE_ALTER_ADD_COL.match(s)
    if m:
        # 分组：1=前缀(含表名) 2=表名 3=列定义
        tbl = m.group(2).strip('"`[]')
        return m.group(1) + translate_column_def(m.group(3), overrides, tbl, indexed)

    # ④ CREATE TABLE
    if _RE_CREATE_TABLE.match(s):
        return translate_create_table(s, overrides, None, indexed)

    # ⑤ CREATE INDEX
    if re.match(r'^CREATE\s+(?:UNIQUE\s+)?INDEX\b', s, re.I):
        return translate_index(s)

    return s


def translate_script(script: str, overrides: dict | None = None) -> list[str]:
    """把多语句脚本整体翻译成 MySQL 语句列表（跳过 PRAGMA）。

    整体翻译而不是逐条：这样 CREATE INDEX 里的列能被 CREATE TABLE 用到
    （决定 TEXT 列要不要变 VARCHAR(255)）。
    """
    stmts = split_script(script)
    indexed = indexed_columns_from_script(stmts)
    out = []
    for s in stmts:
        if re.match(r'^\s*PRAGMA\b', s, re.I):
            continue
        out.append(translate_statement(s, indexed, overrides))
    return out
