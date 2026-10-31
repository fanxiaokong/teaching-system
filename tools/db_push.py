#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把「在 Navicat 里改过的镜像」以【行级差异】方式同步到线上生产库。

为什么不是直接覆盖文件：
    覆盖整个 .db 会连带把「你编辑期间线上产生的新数据」一起冲掉。
    本脚本改成逐行比对，只生成真正变化的那几行的 UPDATE / INSERT / DELETE。

为什么安全：
    1. 默认只做「干跑」—— 打印差异与 SQL，不碰服务器
    2. 冲突检测：动手前会重新拉一份**当前线上库**，逐行核对
       「你要改的那些行，线上是否也已经被人改过了」。有冲突就整体中止。
    3. 真正执行时，先在服务器上自动备份带时间戳的库
    4. 全程包在一个事务里，出错整体回滚

用法：
    python3 tools/db_push.py                      # 干跑：看差异 + 冲突检测
    python3 tools/db_push.py --apply              # 真正执行
    python3 tools/db_push.py --apply --force      # 忽略冲突强行执行（慎用）

工作流：
    ./tools/db-pull.sh          # 拉最新镜像（同时存下基线）
    → 在 Navicat 里改镜像（连接「线上生产库(镜像)」）
    → python3 tools/db_push.py  # 看差异，确认无误
    → python3 tools/db_push.py --apply
"""

from __future__ import annotations

import argparse
import base64
import datetime
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

HOST = os.environ.get("LC_HOST", "YOUR_SERVER_IP")
KEY = os.environ.get("LC_KEY", os.path.expanduser("~/.ssh/teaching_system_deploy"))
# 允许用环境变量指到别的库（自测用；平时不要设）
REMOTE_DB = os.environ.get("LC_REMOTE_DB", "/opt/websystem/data/netlab.db")

BASELINE = os.path.join(ROOT, "server/data/netlab-server-baseline.db")
EDITED = os.path.join(ROOT, "server/data/netlab-server-mirror.db")

SSH_OPTS = ["-i", KEY, "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null", "-o", "ConnectTimeout=15"]


def ssh(cmd: str, stdin: bytes | None = None) -> str:
    p = subprocess.run(["ssh"] + SSH_OPTS + ["root@" + HOST, cmd],
                       input=stdin, capture_output=True)
    if p.returncode != 0:
        raise SystemExit("SSH 失败：" + p.stderr.decode("utf-8", "replace").strip())
    return p.stdout.decode("utf-8", "replace")


def pull_remote(dest: str) -> None:
    """把当前线上库以 WAL 安全方式取到 dest。"""
    tmp = "/tmp/netlab-push-%d.db" % os.getpid()
    ssh("sqlite3 %s \".backup '%s'\"" % (REMOTE_DB, tmp))
    p = subprocess.run(["scp", "-q"] + SSH_OPTS + ["root@%s:%s" % (HOST, tmp), dest],
                       capture_output=True)
    ssh("rm -f " + tmp)
    if p.returncode != 0:
        raise SystemExit("scp 失败：" + p.stderr.decode("utf-8", "replace").strip())


# ------------------------------------------------------------------ 行读取

def table_meta(conn: sqlite3.Connection, table: str):
    cols = list(conn.execute('PRAGMA table_info("%s")' % table))
    pk = [c[1] for c in sorted(cols, key=lambda c: c[5]) if c[5]]
    names = [c[1] for c in cols]
    return names, pk


def read_rows(conn: sqlite3.Connection, table: str, names, pk):
    out = {}
    for row in conn.execute('SELECT * FROM "%s"' % table):
        key = tuple(row[names.index(k)] for k in pk)
        out[key] = tuple(row)
    return out


def sql_value(v) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, bytes):
        return "X'" + v.hex() + "'"
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, (int, float)):
        return repr(v)
    return "'" + str(v).replace("'", "''") + "'"


def where_clause(pk, key) -> str:
    return " AND ".join('"%s" IS %s' % (k, sql_value(v)) for k, v in zip(pk, key))


# ------------------------------------------------------------------ 主流程

def main() -> int:
    ap = argparse.ArgumentParser(description="把镜像的行级改动推到线上生产库")
    ap.add_argument("--apply", action="store_true", help="真正执行（默认只干跑）")
    ap.add_argument("--force", action="store_true", help="忽略冲突强行执行")
    ap.add_argument("--baseline", default=BASELINE)
    ap.add_argument("--edited", default=EDITED)
    args = ap.parse_args()

    for f, label in ((args.baseline, "基线"), (args.edited, "编辑后镜像")):
        if not os.path.isfile(f):
            raise SystemExit("找不到%s：%s\n（先跑一次 ./tools/db-pull.sh 生成）" % (label, f))

    print("==> 1/5 读取本地两份副本")
    base_conn = sqlite3.connect(args.baseline)
    edit_conn = sqlite3.connect(args.edited)

    t_base = {r[0] for r in base_conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
    t_edit = {r[0] for r in edit_conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
    if t_base != t_edit:
        print("❌ 两份副本的表结构不一致，为避免误判已中止：", file=sys.stderr)
        print("   仅基线有：%s" % sorted(t_base - t_edit), file=sys.stderr)
        print("   仅镜像有：%s" % sorted(t_edit - t_base), file=sys.stderr)
        return 2

    print("==> 2/5 计算行级差异")
    plan = []          # (table, kind, sql, key, changed_cols, base_row)
    for table in sorted(t_base):
        names, pk = table_meta(base_conn, table)
        if not pk:
            print("  ⚠️  跳过无主键表 %s（无法定位行）" % table)
            continue
        b = read_rows(base_conn, table, names, pk)
        e = read_rows(edit_conn, table, names, pk)

        for key in e.keys() - b.keys():
            cols = ", ".join('"%s"' % c for c in names)
            vals = ", ".join(sql_value(v) for v in e[key])
            plan.append((table, "INSERT",
                         'INSERT INTO "%s" (%s) VALUES (%s);' % (table, cols, vals),
                         key, None, None))
        for key in b.keys() & e.keys():
            if b[key] == e[key]:
                continue
            changed = [n for n, x, y in zip(names, b[key], e[key]) if x != y]
            if not changed:
                continue
            sets = ", ".join('"%s" = %s' % (c, sql_value(e[key][names.index(c)])) for c in changed)
            plan.append((table, "UPDATE",
                         'UPDATE "%s" SET %s WHERE %s;' % (table, sets, where_clause(pk, key)),
                         key, changed, b[key]))
        for key in b.keys() - e.keys():
            plan.append((table, "DELETE",
                         'DELETE FROM "%s" WHERE %s;' % (table, where_clause(pk, key)),
                         key, None, b[key]))

    if not plan:
        print("\n✅ 没有任何差异 —— 你在 Navicat 里还没改动，或改动还没保存。")
        return 0

    print("\n差异汇总：")
    stat = {}
    for t, kind, *_ in plan:
        stat.setdefault(t, {}).setdefault(kind, 0)
        stat[t][kind] += 1
    for t in sorted(stat):
        parts = ["%s %d" % (k, v) for k, v in sorted(stat[t].items())]
        print("   %-24s %s" % (t, " · ".join(parts)))
    print("   共 %d 处改动" % len(plan))

    print("\n==> 3/5 冲突检测（重新拉一份当前线上库）")
    tmp_prod = tempfile.mktemp(suffix=".db")
    try:
        pull_remote(tmp_prod)
        prod_conn = sqlite3.connect(tmp_prod)
        conflicts = []
        for table, kind, sql, key, changed, base_row in plan:
            if kind == "INSERT":
                names, pk = table_meta(prod_conn, table)
                rows = read_rows(prod_conn, table, names, pk)
                if key in rows:
                    conflicts.append("%s 主键 %s 在线上已存在（插入会冲突）" % (table, key))
                continue
            names, pk = table_meta(prod_conn, table)
            rows = read_rows(prod_conn, table, names, pk)
            cur = rows.get(key)
            if cur is None:
                conflicts.append("%s 主键 %s 在线上已不存在（可能已被删除）" % (table, key))
                continue
            if kind == "UPDATE":
                # 线上这一行，在「我们要改的列」上是否还是基线值？
                for c in changed:
                    if cur[names.index(c)] != base_row[names.index(c)]:
                        conflicts.append(
                            "%s 主键 %s 的字段 %s 在线上已被改动"
                            "（基线=%r，线上=%r）" % (table, key, c,
                                                   base_row[names.index(c)], cur[names.index(c)]))
            else:  # DELETE
                if cur != base_row:
                    conflicts.append("%s 主键 %s 在线上已被修改（删除会丢改动）" % (table, key))

        if conflicts:
            print("\n⚠️  检测到 %d 处冲突：" % len(conflicts))
            for c in conflicts[:20]:
                print("   · " + c)
            if len(conflicts) > 20:
                print("   … 另有 %d 处" % (len(conflicts) - 20))
            if not args.force:
                print("\n已中止。建议：重新 ./tools/db-pull.sh 拉一份最新的再改。")
                print("确实要以你的版本为准，才加 --force。")
                return 3
            print("\n（--force 已指定，继续）")
        else:
            print("   ✅ 无冲突")
    finally:
        if os.path.exists(tmp_prod):
            os.remove(tmp_prod)

    sql_text = "PRAGMA foreign_keys=OFF;\nBEGIN;\n" + "\n".join(p[2] for p in plan) + "\nCOMMIT;\n"

    if not args.apply:
        print("\n==> 4/5 干跑模式，即将执行的 SQL（前 40 行）：")
        for line in sql_text.splitlines()[:40]:
            print("   " + line)
        if len(sql_text.splitlines()) > 40:
            print("   … 共 %d 行" % len(sql_text.splitlines()))
        print("\n未做任何改动。确认无误后加 --apply 执行。")
        return 0

    print("\n==> 4/5 备份线上库并执行")
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    ssh("cp %s %s.bak-push-%s && echo 备份完成: %s.bak-push-%s" % (REMOTE_DB, REMOTE_DB, ts, REMOTE_DB, ts))

    b64 = base64.b64encode(sql_text.encode("utf-8")).decode("ascii")
    remote = ("echo %s | base64 -d > /tmp/.push-%d.sql && "
              "cp /tmp/.push-%d.sql /tmp/.push-%d.applied.sql && "
              "sqlite3 %s < /tmp/.push-%d.sql; RC=$?; "
              "rm -f /tmp/.push-%d.sql; exit $RC" % (b64, os.getpid(), os.getpid(),
                                                     os.getpid(), REMOTE_DB, os.getpid(),
                                                     os.getpid()))
    ssh(remote)

    print("==> 5/5 复核线上库")
    check = ssh("sqlite3 %s \"PRAGMA integrity_check;\"" % REMOTE_DB).strip()
    print("   完整性：%s" % check)
    if check != "ok":
        print("❌ 完整性校验未通过，请立刻用刚生成的备份回滚！", file=sys.stderr)
        return 4
    print("   ✅ 已应用 %d 处改动" % len(plan))
    print("\n下一步：./tools/db-pull.sh 重新拉一份，基线就与新状态对齐了。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
