#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MySQL 侧的「结构覆盖 + 漂移」报告。

判据（这才是能不能切 MySQL 的关键）：
    把 app 的 db.SCHEMA 经运行时翻译器翻一遍，再加上 init_db() 里所有
    ensure_column() 要补的列，得到「应用需要的最小结构」。
    这份结构必须被目标库**完全覆盖** —— 因为 init_db() 用的是
    CREATE TABLE IF NOT EXISTS，对已存在的表它什么都不做，
    表结构的真实来源就是目标库本身。

三种差异分开对待：
    ❌ 缺列/缺表   —— 应用会报错，必须修
    ⚠️  约束松紧不同（NOT NULL / 默认值 / 索引列）—— 老库本来就与 SCHEMA 漂移，
       不影响运行，只作为提示
    ℹ️  目标库多出来的列 —— 正常（历次 ad-hoc 加的），列出来备案

用法：
    server/.venv/bin/python tools/mysql/verify_fresh_schema.py \
        --host 127.0.0.1 --port 3306 --user admin --password '...'
"""
from __future__ import annotations

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, 'server', 'app'))

import mysqldialect as dialect      # noqa: E402

# init_db() 里 ensure_column() 要补的列（表, 列, sqlite 列定义）
ENSURE_COLUMNS = [
    ('files', 'assignment_id', 'assignment_id INTEGER'),
    ('users', 'quota_mb', 'quota_mb INTEGER DEFAULT 200'),
    ('users', 'student_no', "student_no TEXT DEFAULT ''"),
    ('challenge_records', 'elapsed_ms', 'elapsed_ms INTEGER DEFAULT 0'),
    ('videos', 'duration', "duration TEXT DEFAULT ''"),
    ('videos', 'subtitle', "subtitle TEXT DEFAULT ''"),
    ('videos', 'subtitle_name', "subtitle_name TEXT DEFAULT ''"),
    ('app_versions', 'platform', "platform TEXT NOT NULL DEFAULT 'android'"),
    ('app_versions', 'sha512', "sha512 TEXT DEFAULT ''"),
]


def required_structure():
    """应用需要的最小结构：db.SCHEMA 翻译 + ensure_column 补的列。"""
    import db as appdb
    stmts = dialect.translate_script(appdb.SCHEMA)
    need = {}
    for s in [x for x in stmts if x.upper().startswith('CREATE TABLE')]:
        m = __import__('re').search(r'CREATE TABLE `([^`]+)` \((.*)\) [A-Z]', s, __import__('re').S)
        if not m:
            continue
        t, body = m.group(1), m.group(2)
        for line in dialect.split_top_level(body):
            line = line.strip()
            if not line or __import__('re').match(
                    r'^(PRIMARY|UNIQUE|KEY|CONSTRAINT|CHECK|FOREIGN)', line, __import__('re').I):
                continue
            cm = __import__('re').match(r'`([^`]+)`', line)
            if cm:
                need.setdefault(t, {})[cm.group(1)] = line
    for t, c, ddl in ENSURE_COLUMNS:
        need.setdefault(t, {})[c] = dialect.translate_column_def(ddl, None, t)
    return need


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--host', default='127.0.0.1')
    ap.add_argument('--port', type=int, default=3306)
    ap.add_argument('--user', default='admin')
    ap.add_argument('--password', default='')
    ap.add_argument('--database', default='netlab')
    args = ap.parse_args()

    import pymysql
    from pymysql.cursors import DictCursor
    conn = pymysql.connect(host=args.host, port=args.port, user=args.user,
                           password=args.password, charset='utf8mb4',
                           cursorclass=DictCursor, autocommit=True)
    cur = conn.cursor()

    cur.execute("""SELECT TABLE_NAME AS t, COLUMN_NAME AS c, COLUMN_TYPE AS ty,
                          IS_NULLABLE AS nul, COLUMN_DEFAULT AS dflt, COLUMN_KEY AS ckey
                     FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=%s""", (args.database,))
    have = {}
    for r in cur.fetchall():
        have.setdefault(r['t'], {})[r['c']] = r

    need = required_structure()

    print('目标：%s@%s:%d/%s' % (args.user, args.host, args.port, args.database))
    print('应用需要 %d 张表 / %d 个列' % (len(need), sum(len(v) for v in need.values())))
    print('目标库有 %d 张表 / %d 个列'
          % (len(have), sum(len(v) for v in have.values())))
    print()

    missing_tables = sorted(set(need) - set(have))
    missing_cols = []
    for t in sorted(set(need) & set(have)):
        for c in sorted(set(need[t]) - set(have[t])):
            missing_cols.append((t, c, need[t][c]))
    extra_cols = []
    for t in sorted(set(need) & set(have)):
        for c in sorted(set(have[t]) - set(need[t])):
            extra_cols.append((t, c))

    # ── 硬失败项
    if missing_tables:
        print('❌ 目标库缺少这些表：')
        for t in missing_tables:
            print('     ' + t)
    if missing_cols:
        print('❌ 目标库缺少这些列（应用运行会报错）：')
        for t, c, ddl in missing_cols:
            print('     %-20s %-18s 需要: %s' % (t, c, ddl))
    if not missing_tables and not missing_cols:
        print('✅ 应用需要的表与列，目标库全部具备')

    # ── 提示项：约束松紧
    soft = 0
    for t in sorted(set(need) & set(have)):
        for c in sorted(set(need[t]) & set(have[t])):
            line = need[t][c].upper()
            h = have[t][c]
            want_nn = 'NOT NULL' in line
            got_nn = h['nul'] == 'NO'
            if want_nn != got_nn:
                soft += 1
    if soft:
        print()
        print('⚠️  %d 个列的 NOT NULL 与 db.SCHEMA 不一致（老库早于 SCHEMA 漂移，不影响运行）' % soft)

    if extra_cols:
        print()
        print('ℹ️  目标库多出 %d 个列（历次 ad-hoc 加的，保留原样）：' % len(extra_cols))
        for t, c in extra_cols:
            print('     %-20s %s' % (t, c))

    print()
    if missing_tables or missing_cols:
        print('结论：❌ 不能切换 —— 先建缺的表/列')
        return 1
    print('结论：✅ 可以切换')
    return 0


if __name__ == '__main__':
    sys.exit(main())
