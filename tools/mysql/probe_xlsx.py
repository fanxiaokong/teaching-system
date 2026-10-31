#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""定点探针：把 /admin/progress.xlsx 在两个后端各取两次，拆包逐文件比对。

目的：确认 SQLite 与 MySQL 生成的 xlsx 差异，究竟是
  (a) 每次生成都变的「制品噪声」（时间戳 / zip 元数据），还是
  (b) 由数据库后端真正影响内容（如行序、数字格式）。
"""
from __future__ import annotations

import io
import os
import signal
import sys
import time
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import regress_compare as rc  # noqa: E402
import hashlib  # noqa: E402


def unzip_map(blob: bytes):
    z = zipfile.ZipFile(io.BytesIO(blob))
    return {n: z.read(n) for n in z.namelist()}


def diff_maps(a, b, tag):
    ka, kb = set(a), set(b)
    if ka != kb:
        print('  [%s] 内部文件集合不同: 仅A=%s 仅B=%s'
              % (tag, sorted(ka - kb), sorted(kb - ka)))
    diffs = []
    for n in sorted(ka & kb):
        if a[n] != b[n]:
            diffs.append(n)
    print('  [%s] 内容不同的内部文件: %s' % (tag, diffs or '（无）'))
    return diffs


def show_text_parts(m, names, tag):
    for n in names:
        if n not in m:
            continue
        txt = m[n].decode('utf-8', 'replace')
        print('  [%s] %s (%d 字节):' % (tag, n, len(m[n])))
        print('    ' + txt[:1200].replace('\n', '\n    '))


def main():
    pw = sys.argv[1] if len(sys.argv) > 1 else 'CHANGE_ME_PASSWORD'
    rc.prepare(pw)
    rc.set_passwords(pw)
    ps = rc.start_server(8801, 'sqlite', pw)
    pm = rc.start_server(8802, 'mysql', pw)
    procs = [ps, pm]
    try:
        if not (rc.wait_up(8801) and rc.wait_up(8802)):
            print('实例没起来'); return 2
        cs, cm = rc.Client(8801), rc.Client(8802)
        assert cs.login('admin', rc.ADMIN_PW)[0]
        assert cm.login('admin', rc.ADMIN_PW)[0]

        s1 = cs.get('/admin/progress.xlsx')[1]
        s2 = cs.get('/admin/progress.xlsx')[1]
        m1 = cm.get('/admin/progress.xlsx')[1]
        m2 = cm.get('/admin/progress.xlsx')[1]

        def sha(b): return hashlib.sha256(b).hexdigest()[:16]
        print('== 原始字节 ==')
        print('  sqlite #1=%s (%d)  #2=%s (%d)' % (sha(s1), len(s1), sha(s2), len(s2)))
        print('  mysql  #1=%s (%d)  #2=%s (%d)' % (sha(m1), len(m1), sha(m2), len(m2)))
        print('  >> SQLite 自身两次是否一致 :', s1 == s2)
        print('  >> MySQL  自身两次是否一致 :', m1 == m2)

        us, um = unzip_map(s1), unzip_map(m1)
        print('== 拆包比对：sqlite#1 vs mysql#1 ==')
        diff_maps(us, um, 'S-vs-M')
        print('== 拆包比对：mysql#1 vs mysql#2（后端内部自比）==')
        diff_maps(unzip_map(m1), unzip_map(m2), 'M1-vs-M2')
        print('== 拆包比对：sqlite#1 vs sqlite#2（后端内部自比）==')
        diff_maps(unzip_map(s1), unzip_map(s2), 'S1-vs-S2')

        # 看一眼 sheet1 的共享字符串与工作表内容（最容易暴露数字格式差异）
        for tag, m in (('sqlite', us), ('mysql', um)):
            show_text_parts(m, ['xl/sharedStrings.xml'], tag)
        for tag, m in (('sqlite', us), ('mysql', um)):
            show_text_parts(m, ['xl/worksheets/sheet1.xml'], tag)
        for tag, m in (('sqlite', us), ('mysql', um)):
            show_text_parts(m, ['docProps/core.xml', 'docProps/app.xml'], tag)
    finally:
        for p in procs:
            try: p.send_signal(signal.SIGTERM)
            except Exception: pass
        time.sleep(1)
        for p in procs:
            try: p.kill()
            except Exception: pass


if __name__ == '__main__':
    sys.exit(main())
