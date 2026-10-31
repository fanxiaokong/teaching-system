#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""password-plain.py —— 把 users.password_hash 从 PBKDF2 哈希切到明文。

背景
----
站点的口令原本存 PBKDF2 哈希（pbkdf2_sha256$盐$摘要），**哈希不可逆**，
所以"把老密码转成明文"这件事在数学上做不到——只能给它**换一个新的明文密码**。

因此本工具提供两条路：
  · --set <用户> <明文>      只把某个人换成明文（其他人不动）
  · --convert-all <明文>     把**所有**还是哈希的账号统一改成同一个明文
                             （会先备份整张 users 表；不加 -y 只演不写）

站点侧兼容性
------------
server/app/db.py 的 verify_password() 同时认「明文」和「老哈希」，
所以：
  * 没转的人，用原来的密码照样能登录；
  * 转过的人，密码就是你给的明文；
  * 每个人第一次在站点里改密码时，会自动落成明文。

用法
----
  # 1) 看现状：谁还是哈希、谁已经是明文（不打印明文内容，只看类型）
  python3 tools/password-plain.py status

  # 2) 把 admin 换成明文
  python3 tools/password-plain.py set admin 'CHANGE_ME_PASSWORD'

  # 3) 所有还是哈希的账号，统一改成 123456（先演一遍）
  python3 tools/password-plain.py convert-all 123456
  python3 tools/password-plain.py convert-all 123456 -y

  # 4) 换目标：默认连云上的 MySQL；--sqlite 指向本地文件
  python3 tools/password-plain.py --sqlite server/data/netlab.db status
  python3 tools/password-plain.py --host 127.0.0.1 --port 3306 --db netlab_practice status

备份
----
任何写操作前，整张 users 表会被导出成
    backups/passwords/<时间戳>-users-before-plain.sql
里面是完整的 INSERT/UPDATE 恢复语句，随时能改回去。
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BACKUP_DIR = os.path.join(ROOT, "backups", "passwords")

DEFAULTS = {
    "host": os.environ.get("NETLAB_MYSQL_HOST", "db.example.com"),
    "port": int(os.environ.get("NETLAB_MYSQL_PORT", "13306")),
    "user": os.environ.get("NETLAB_MYSQL_USER", "admin"),
    "password": os.environ.get("NETLAB_MYSQL_PASSWORD", "CHANGE_ME_PASSWORD"),
    "database": os.environ.get("NETLAB_MYSQL_DATABASE", "netlab"),
}

OK, BAD, WARN = "✅", "❌", "⚠️ "


def say(msg=""):
    print(msg)


def is_hashed(v) -> bool:
    return isinstance(v, str) and v.startswith("pbkdf2_sha256$")


# ---------------------------------------------------------------- 连接层
class Conn:
    """MySQL / SQLite 的最小公共壳：query / execute / placeholder。"""

    def __init__(self, kind, **kw):
        self.kind = kind
        if kind == "mysql":
            import pymysql
            self.raw = pymysql.connect(
                host=kw["host"], port=kw["port"], user=kw["user"],
                password=kw["password"], database=kw["database"],
                charset="utf8mb4", connect_timeout=15,
                cursorclass=pymysql.cursors.DictCursor,
            )
            self.label = f"MySQL {kw['host']}:{kw['port']}/{kw['database']}"
        else:
            self.raw = sqlite3.connect(kw["path"])
            self.raw.row_factory = sqlite3.Row
            self.label = f"SQLite {kw['path']}"

    @property
    def ph(self):
        return "%s" if self.kind == "mysql" else "?"

    def query(self, sql, args=None):
        cur = self.raw.cursor()
        # args 必须真的是 None：PyMySQL 只要拿到非 None 就做 %-格式化，
        # 遇到 SQL 里字面量的 '%'（比如 LIKE 'pbkdf2_sha256$%'）会炸
        # "not enough arguments for format string"。
        cur.execute(sql, args) if args is not None else cur.execute(sql)
        return [dict(r) for r in cur.fetchall()]

    def execute(self, sql, args=None):
        cur = self.raw.cursor()
        cur.execute(sql, args) if args is not None else cur.execute(sql)
        return cur.rowcount

    def commit(self):
        self.raw.commit()

    def close(self):
        self.raw.close()


def connect(args) -> Conn:
    if args.sqlite:
        path = args.sqlite if os.path.isabs(args.sqlite) else os.path.join(ROOT, args.sqlite)
        if not os.path.exists(path):
            say(f"{BAD} 找不到 SQLite 文件：{path}")
            sys.exit(1)
        return Conn("sqlite", path=path)
    return Conn("mysql", host=args.host, port=args.port, user=args.user,
                password=args.password, database=args.db)


# ---------------------------------------------------------------- 备份
def backup_users(conn: Conn, tag: str) -> str:
    rows = conn.query("SELECT * FROM users ORDER BY id")
    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = os.path.join(BACKUP_DIR, f"{stamp}-users-before-{tag}.sql")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(f"-- users 表快照，{stamp}（{conn.label}）\n")
        fh.write(f"-- 回滚：把下面每行 UPDATE 执行一遍即可恢复原 password_hash\n\n")
        for r in rows:
            old = str(r.get("password_hash") or "").replace("'", "''")
            fh.write(f"UPDATE users SET password_hash = '{old}' WHERE id = {r['id']};\n")
    os.chmod(path, 0o600)
    return path


# ---------------------------------------------------------------- 子命令
def cmd_status(conn: Conn) -> int:
    rows = conn.query(
        "SELECT id, username, is_admin, is_active, password_hash FROM users ORDER BY id"
    )
    total = len(rows)
    hashed = [r for r in rows if is_hashed(r["password_hash"])]
    plain = [r for r in rows if not is_hashed(r["password_hash"])]

    say("")
    say(f"\033[1m目标库\033[0m  {conn.label}")
    say("")
    say(f"  账号总数 {total}   加密(PBKDF2) {len(hashed)}   明文 {len(plain)}")
    say("")
    say(f"  {'ID':<5}{'用户名':<16}{'管理员':<8}{'状态':<9}{'口令存储'}")
    say(f"  {'-' * 5}{'-' * 16}{'-' * 8}{'-' * 9}{'-' * 30}")
    for r in rows:
        kind = "加密(PBKDF2)" if is_hashed(r["password_hash"]) else "明文"
        value = "" if is_hashed(r["password_hash"]) else f"  = {r['password_hash']}"
        kind = kind + value
        admin = "是" if r["is_admin"] else "-"
        active = "启用" if r["is_active"] else "已停用"
        say(f"  {r['id']:<5}{r['username']:<16}{admin:<8}{active:<9}{kind}")
    say("")
    if hashed:
        say(f"  还有 {len(hashed)} 个账号是哈希。哈希不可逆，转明文 = 给它换一个新密码：")
        say(f"      python3 tools/password-plain.py convert-all <统一新密码> -y")
        say(f"      或单独来：python3 tools/password-plain.py set <用户名> <新密码>")
    else:
        say("  全部已是明文，直接改就行。")
    say("")
    return 0


def cmd_set(conn: Conn, user: str, password: str, dry: bool, yes: bool) -> int:
    ph = conn.ph
    rows = conn.query(
        f"SELECT id, username, password_hash FROM users "
        f"WHERE username = {ph} OR phone = {ph} OR student_no = {ph}",
        (user, user, user),
    )
    if not rows:
        say(f"{BAD} 找不到用户：{user}（用户名 / 手机号 / 学号都试过）")
        return 1
    if len(rows) > 1:
        say(f"{BAD} 匹配到 {len(rows)} 个人，用「用户名」精确指定：")
        for r in rows:
            say(f"      id={r['id']}  {r['username']}")
        return 1
    r = rows[0]
    old = r["password_hash"]
    old_kind = "加密(PBKDF2)" if is_hashed(old) else "明文"

    say("")
    say(f"  目标：id={r['id']}  用户名={r['username']}  当前口令存储={old_kind}")
    if not is_hashed(old):
        say(f"  当前明文 = {old}")
    if dry:
        say(f"{WARN} --dry-run：只演不写")
        return 0
    if not yes:
        if input(f"  把它的口令改成明文 {password!r}？[y/N] ").strip().lower() not in ("y", "yes"):
            say("  已取消。")
            return 0

    bak = backup_users(conn, f"set-{r['username']}")
    conn.execute(f"UPDATE users SET password_hash = {ph} WHERE id = {ph}", (password, r["id"]))
    conn.commit()

    back = conn.query(f"SELECT password_hash FROM users WHERE id = {ph}", (r["id"],))[0]["password_hash"]
    if back != password:
        say(f"{BAD} 回读不一致！期望 {password!r} 实际 {back!r}")
        say(f"     → 回滚：备份在 {bak}")
        return 1
    say(f"{OK} 已写入并回读校验通过 —— 现在库里就是明文，可直接改")
    say(f"  备份：{os.path.relpath(bak, ROOT)}")
    say("")
    return 0


def cmd_convert_all(conn: Conn, password: str, dry: bool, yes: bool) -> int:
    rows = conn.query("SELECT id, username, password_hash FROM users ORDER BY id")
    hashed = [r for r in rows if is_hashed(r["password_hash"])]
    say("")
    say(f"  目标库 {conn.label}")
    say(f"  账号总数 {len(rows)}，其中还是哈希的 {len(hashed)} 个")
    if not hashed:
        say(f"{OK} 已经没有哈希了，不需要转换。")
        return 0

    say("")
    say(f"{WARN} 哈希不可逆——下面这些人会被统一改成同一个明文密码：")
    say("")
    for r in hashed:
        say(f"      id={r['id']:<5} {r['username']}")
    say("")
    say(f"  统一新密码：{password!r}")
    say(f"  {WARN} 他们原来的密码会失效，需要你另行告知。")
    say("")

    if dry:
        say(f"{WARN} --dry-run：只演不写（加 -y 才真改）")
        return 0
    if not yes:
        ans = input(f"  确认把上面 {len(hashed)} 个人的密码都改成 {password!r}？输入 yes 继续：").strip()
        if ans.lower() != "yes":
            say("  已取消，什么都没改。")
            return 0

    bak = backup_users(conn, "convert-all")
    ph = conn.ph
    n = 0
    for r in hashed:
        conn.execute(f"UPDATE users SET password_hash = {ph} WHERE id = {ph}", (password, r["id"]))
        n += 1
    conn.commit()

    still = conn.query(
        "SELECT COUNT(*) c FROM users WHERE LEFT(password_hash, 14) = 'pbkdf2_sha256$'"
    )[0]["c"]
    if still:
        say(f"{BAD} 还有 {still} 个没转成功，回滚：{bak}")
        return 1
    say(f"{OK} 已转换 {n} 个账号，全表现在都是明文")
    say(f"  备份：{os.path.relpath(bak, ROOT)}")
    say("")
    return 0


# ---------------------------------------------------------------- main
def build_parser():
    """参数解析。

    坑：位置参数如果叫 user / password，会和连接选项 --user / --password
    撞同一个 dest，把数据库凭证覆盖成用户名，直接 1045。
    所以位置参数改叫 target / newpass / plain，并且
    连接选项用一个"预解析器"接住——写在子命令前面后面都认。
    """
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--sqlite")
    pre.add_argument("--host")
    pre.add_argument("--port", type=int)
    pre.add_argument("--user")
    pre.add_argument("--password")
    pre.add_argument("--db")
    known, rest = pre.parse_known_args()

    flags = argparse.ArgumentParser(add_help=False)
    flags.add_argument("--dry-run", action="store_true", default=None, help="只演不写")
    flags.add_argument("-y", "--yes", action="store_true", default=None, help="不再确认")

    ap = argparse.ArgumentParser(
        description="把 users.password_hash 从 PBKDF2 哈希切成明文",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "连接选项（写在子命令前后都行）：\n"
            "  --sqlite <路径>        改本地 SQLite 文件\n"
            "  --host/--port/--user/--password/--db   MySQL 连接（默认连云上生产库）\n"
            "  不给 --host 就指 db.example.com:13306/netlab；\n"
            "  给 127.0.0.1 则自动改用 3306 / netlab_practice（本机沙盒）\n"
        ),
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", parents=[flags], help="看谁还是哈希、谁已是明文")
    p_set = sub.add_parser("set", parents=[flags], help="把某个用户改成明文密码")
    p_set.add_argument("target", metavar="用户名")
    p_set.add_argument("newpass", metavar="新密码")
    p_all = sub.add_parser("convert-all", parents=[flags], help="所有哈希账号统一改成一个明文")
    p_all.add_argument("plain", metavar="统一新密码")

    args = ap.parse_args(rest)

    # 合并"写在子命令前面"的连接选项（子命令里没有这些 dest，这里补上）
    for key in ("sqlite", "host", "port", "user", "password", "db"):
        setattr(args, key, getattr(known, key, None))
    args.dry_run = bool(getattr(args, "dry_run", None))
    args.yes = bool(getattr(args, "yes", None))

    if args.host is None:
        args.host = DEFAULTS["host"]
    _local = args.host in ("127.0.0.1", "localhost", "::1")
    if args.port is None:
        args.port = 3306 if _local else DEFAULTS["port"]
    if args.db is None:
        args.db = "netlab_practice" if _local else DEFAULTS["database"]
    if args.user is None:
        args.user = DEFAULTS["user"]
    if args.password is None:
        args.password = DEFAULTS["password"]
    return args


def main() -> int:
    args = build_parser()

    try:
        conn = connect(args)
    except Exception as exc:  # noqa: BLE001
        say(f"{BAD} 连不上：{type(exc).__name__}: {exc}")
        if not args.sqlite:
            say("     → 跑 ./tools/db-cloud-check.sh 看是哪一环断了")
        return 1

    try:
        who = conn.query("SELECT VERSION() v")[0]["v"] if conn.kind == "mysql" else "sqlite"
        if args.cmd == "status":
            return cmd_status(conn)
        if args.cmd == "set":
            return cmd_set(conn, args.target, args.newpass, args.dry_run, args.yes)
        if args.cmd == "convert-all":
            return cmd_convert_all(conn, args.plain, args.dry_run, args.yes)
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
