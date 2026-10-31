#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 SQLite 库（netlab.db）完整迁移到 MySQL 8。

⚠️ 翻译逻辑**全部**来自 `server/app/mysqldialect.py`，不在本文件里另写一份。
   运行时（app 连 MySQL）和离线迁移（本脚本）必须用同一套规则，否则
   「新装一台机器」和「迁移过来的机器」会长出不一样的表结构。

本文件只负责迁移特有的事：
    1. 数据驱动的类型放宽 —— 扫真实数据，决定哪些整数列必须 BIGINT
       （SQLite 的 INTEGER 是 64 位，MySQL 的 INT 只有 32 位；
        本库 files.size 最大 4,187,501,629 字节，直接超 INT 上限）
    2. 数据驱动的索引放宽 —— 被索引的短 TEXT 列改成 VARCHAR(255)
       （MySQL 不能给 TEXT 建无前缀索引）
    3. 建库、建表、逐表搬数据、逐表哈希校验

用法：
    server/.venv/bin/python tools/mysql/migrate_sqlite_to_mysql.py \
        --sqlite server/data/netlab.db --password '...' --database netlab \
        --create-database --drop-existing

    # 只看翻译出来的 DDL
    ... --dry-run --ddl-out /tmp/schema.sql
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
# 默认按仓库布局找 mysqldialect；服务器上 app 目录不在 <root>/server/app，
# 可用 NETLAB_APP_DIR 显式指定（例如 /opt/websystem/app）。
APP_DIR = os.environ.get('NETLAB_APP_DIR') or os.path.join(ROOT, 'server', 'app')
sys.path.insert(0, APP_DIR)

import mysqldialect as dialect      # noqa: E402
from mysqldialect import (          # noqa: E402
    BYTE_LIKE_NAMES, INDEXABLE_REPLACEMENT, INT_MAX, INT_MIN, Q, TABLE_SUFFIX,
)

# ------------------------------------------------------------------ 数据驱动


def sqlite_tables(conn):
    return [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name")]


def int_width_overrides(conn):
    """扫真实数据，决定哪些整数列必须放宽成 BIGINT。"""
    over = {}
    for t in sqlite_tables(conn):
        for c in conn.execute('PRAGMA table_info("%s")' % t):
            name, decl = c[1], c[2].upper()
            if not decl.startswith(('INT', 'BOOLEAN')):
                continue
            lo, hi = conn.execute('SELECT min("%s"), max("%s") FROM "%s"'
                                  % (name, name, t)).fetchone() or (None, None)
            need = name.lower() in BYTE_LIKE_NAMES
            for v in (lo, hi):
                if isinstance(v, (int, float)) and (v > INT_MAX or v < INT_MIN):
                    need = True
            if need:
                over[(t, name)] = 'BIGINT'
    return over


def text_index_overrides(conn):
    """被索引的 TEXT 列：值够短就 VARCHAR(255)，太长则留给前缀索引。"""
    indexed = set()
    for (sql,) in conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='index' AND sql IS NOT NULL"):
        indexed |= dialect.indexed_columns_from_script([sql])
    over, need_prefix = {}, set()
    for t, c in sorted(indexed):
        cols = {x[1]: x[2].upper() for x in conn.execute('PRAGMA table_info("%s")' % t)}
        if not cols.get(c, '').startswith(('TEXT', 'CLOB')):
            continue
        mlen = conn.execute('SELECT max(length("%s")) FROM "%s"' % (c, t)).fetchone()[0] or 0
        if mlen <= 255:
            over[(t, c)] = INDEXABLE_REPLACEMENT
        else:
            need_prefix.add((t, c))
            print('    ⚠️  %s.%s 被索引但最长 %d 字符 > 255，改用前缀索引 %s(191)'
                  % (t, c, mlen, c))
    return over, need_prefix


# ------------------------------------------------------------------ 数据搬运

def normalize(v):
    if v is None:
        return None
    if isinstance(v, bytes):
        return 'X' + v.hex()
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, float):
        return repr(float(v))
    if isinstance(v, int):
        return int(v)
    return str(v)


def coerce(v, declared):
    """SQLite 动态类型 → MySQL 严格类型。"""
    if v is None:
        return None
    base = declared.upper().split('(')[0].strip()
    if base in ('INTEGER', 'INT', 'BIGINT', 'SMALLINT', 'BOOLEAN'):
        if isinstance(v, str):
            s = v.strip()
            return int(float(s)) if s not in ('', 'None') else 0
        return int(v)
    if base in ('REAL', 'FLOAT', 'DOUBLE', 'NUMERIC'):
        if isinstance(v, str):
            s = v.strip()
            return float(s) if s else 0.0
        return float(v)
    if isinstance(v, (int, float)):
        return str(v)
    return v


def fingerprint(rows):
    h = hashlib.sha256()
    for line in sorted(repr(tuple(normalize(v) for v in r)) for r in rows):
        h.update(line.encode('utf-8'))
        h.update(b'\n')
    return h.hexdigest()[:32]


# ------------------------------------------------------------------ 主流程

def main() -> int:
    ap = argparse.ArgumentParser(description='SQLite → MySQL 8 迁移（翻译逻辑复用 mysqldialect）')
    ap.add_argument('--sqlite', required=True)
    ap.add_argument('--host', default='127.0.0.1')
    ap.add_argument('--port', type=int, default=3306)
    ap.add_argument('--user', default='admin')
    ap.add_argument('--password', default='')
    ap.add_argument('--database', default='netlab')
    ap.add_argument('--charset', default='utf8mb4')
    ap.add_argument('--create-database', action='store_true')
    ap.add_argument('--drop-existing', action='store_true')
    ap.add_argument('--ddl-out')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--batch', type=int, default=200)
    ap.add_argument('--quiet', action='store_true')
    args = ap.parse_args()

    def say(*a):
        if not args.quiet:
            print(*a, flush=True)

    lite = sqlite3.connect(args.sqlite)
    lite.text_factory = str

    say('==> 1/5 分析数据，决定类型放宽')
    overrides = int_width_overrides(lite)
    text_over, need_prefix = text_index_overrides(lite)
    overrides.update(text_over)
    if overrides:
        say('    BIGINT/VARCHAR 放宽：%s' % ', '.join('%s.%s' % k for k in sorted(overrides)))

    rows = lite.execute(
        "SELECT type, name, sql FROM sqlite_master WHERE sql IS NOT NULL "
        "AND name NOT LIKE 'sqlite_%' "
        "ORDER BY CASE type WHEN 'table' THEN 1 ELSE 2 END, name").fetchall()
    table_ddl, index_ddl = [], []
    for typ, name, sql in rows:
        if typ == 'table':
            table_ddl.append(dialect.translate_create_table(sql, overrides, name))
        elif typ == 'index':
            index_ddl.append(dialect.translate_index(sql, need_prefix))
    say('    翻译出 %d 张表 / %d 个索引' % (len(table_ddl), len(index_ddl)))

    if args.ddl_out:
        with open(args.ddl_out, 'w', encoding='utf-8') as f:
            f.write('-- 由 tools/mysql/migrate_sqlite_to_mysql.py 生成（翻译规则见 server/app/mysqldialect.py）\n\n')
            f.write(';\n\n'.join(table_ddl) + ';\n\n')
            f.write(';\n'.join(index_ddl) + ';\n')

    if args.dry_run:
        for s in table_ddl[:3]:
            print('\n' + s)
        print('\n…（共 %d 张表，完整内容见 --ddl-out）' % len(table_ddl))
        return 0

    import pymysql
    if args.create_database:
        boot = pymysql.connect(host=args.host, port=args.port, user=args.user,
                               password=args.password, charset=args.charset,
                               autocommit=True)
        with boot.cursor() as c:
            c.execute('CREATE DATABASE IF NOT EXISTS %s DEFAULT CHARACTER SET utf8mb4 '
                      'DEFAULT COLLATE utf8mb4_0900_ai_ci' % Q(args.database))
        boot.close()

    my = pymysql.connect(host=args.host, port=args.port, user=args.user,
                         password=args.password, database=args.database,
                         charset=args.charset, autocommit=False)
    cur = my.cursor()

    say('==> 2/5 建表（%s@%s:%d/%s）' % (args.user, args.host, args.port, args.database))
    if args.drop_existing:
        cur.execute('SET FOREIGN_KEY_CHECKS=0')
        for t in reversed(sqlite_tables(lite)):
            cur.execute('DROP TABLE IF EXISTS ' + Q(t))
        cur.execute('SET FOREIGN_KEY_CHECKS=1')
    benign = {1050, 1061, 1826}
    for s in table_ddl + index_ddl:
        try:
            cur.execute(s)
        except Exception as exc:
            if exc.args and exc.args[0] in benign:
                continue
            say('    ❌ %s\n       %s' % (s.split('\n')[0][:90], exc))
            return 2
    my.commit()
    say('    OK')

    say('==> 3/5 搬运数据')
    total = 0
    for t in sqlite_tables(lite):
        info = list(lite.execute('PRAGMA table_info("%s")' % t))
        cols = [c[1] for c in info]
        decls = {c[1]: c[2] for c in info}
        data = lite.execute('SELECT * FROM "%s"' % t).fetchall()
        if data:
            stmt = 'INSERT INTO %s (%s) VALUES (%s)' % (
                Q(t), ', '.join(Q(c) for c in cols), ', '.join(['%s'] * len(cols)))
            payload = [tuple(coerce(v, decls[c]) for c, v in zip(cols, r)) for r in data]
            for i in range(0, len(payload), args.batch):
                cur.executemany(stmt, payload[i:i + args.batch])
        total += len(data)
        say('    %-22s %5d 行' % (t, len(data)))
    my.commit()
    say('    合计 %d 行' % total)

    say('==> 4/5 校验（行数 + 内容哈希）')
    bad = 0
    for t in sqlite_tables(lite):
        cols = [c[1] for c in lite.execute('PRAGMA table_info("%s")' % t)]
        srows = lite.execute('SELECT * FROM "%s"' % t).fetchall()
        cur.execute('SELECT %s FROM %s' % (', '.join(Q(c) for c in cols), Q(t)))
        mrows = cur.fetchall()
        sf, mf = fingerprint(srows), fingerprint(mrows)
        ok = len(srows) == len(mrows) and sf == mf
        if not ok:
            bad += 1
        say('    %s %-22s sqlite %5d / mysql %5d   %s  %s'
            % ('✅' if ok else '❌', t, len(srows), len(mrows), sf[:12], mf[:12]))

    say('==> 5/5 完成，%d 张表不一致' % bad)
    my.close()
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
