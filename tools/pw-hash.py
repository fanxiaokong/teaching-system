#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按 teaching-system 的口令格式生成 / 校验密码哈希。

站点用的是自己实现的 PBKDF2-HMAC-SHA256，不是 bcrypt：
    algo   = "pbkdf2_sha256"（固定前缀）
    salt   = secrets.token_hex(16)     → 32 位十六进制
    digest = pbkdf2_hmac("sha256", 密码, salt, 120000).hex()  → 64 位十六进制
    存储   = f"{algo}${salt}${digest}"

所以「改密码」不是解密，而是**写入一个新的哈希**。本脚本生成的哈希
可直接 UPDATE 进 users.password_hash，与站点登录校验完全兼容。

用法：
    python3 tools/pw-hash.py 'CHANGE_ME_PASSWORD'          # 生成哈希
    python3 tools/pw-hash.py --verify '明文' 'pbkdf2_sha256$...'   # 校验
    python3 tools/pw-hash.py --sql demo_user 'CHANGE_ME_PASSWORD'  # 直接给 UPDATE 语句
"""

from __future__ import annotations

import argparse
import hashlib
import secrets
import sys

ALGO = "pbkdf2_sha256"
ITERATIONS = 120_000


def hash_password(password: str) -> str:
    """与 server/app/db.py 的 hash_password() 完全一致。"""
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), ITERATIONS).hex()
    return f"{ALGO}${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    """与 server/app/db.py 的 verify_password() 完全一致。

    站点已切到明文存储，所以这里同样**两种格式都认**：
    形如 pbkdf2_sha256$盐$摘要 的走 PBKDF2，其余按明文比对。
    """
    if stored is None:
        return False
    if not isinstance(stored, str):
        stored = str(stored)
    if not stored.startswith(f"{ALGO}$"):
        return secrets.compare_digest(stored, password)
    try:
        _, salt, digest = stored.split("$", 2)
    except ValueError:
        return False
    check = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), ITERATIONS).hex()
    return secrets.compare_digest(check, digest)


def main() -> int:
    ap = argparse.ArgumentParser(description="生成/校验 teaching-system 口令（明文或哈希）")
    ap.add_argument("password", nargs="?", help="明文密码")
    ap.add_argument("--verify", nargs=2, metavar=("明文", "存储的值"), help="校验是否匹配")
    ap.add_argument("--sql", nargs=2, metavar=("用户名", "明文密码"),
                    help="输出可直接执行的 UPDATE 语句")
    ap.add_argument("--mode", choices=("plain", "hash"), default="plain",
                    help="要生成哪种（默认 plain，与站点当前口径一致）")
    args = ap.parse_args()

    if args.verify:
        plain, stored = args.verify
        ok = verify_password(plain, stored)
        print("✅ 匹配" if ok else "❌ 不匹配")
        return 0 if ok else 1

    def render(plain: str) -> str:
        return plain if args.mode == "plain" else hash_password(plain)

    if args.sql:
        username, plain = args.sql
        value = render(plain)
        assert verify_password(plain, value), "自校验失败（不该发生）"
        print(f"UPDATE users SET password_hash = '{value}' WHERE username = '{username}';")
        return 0

    if not args.password:
        ap.print_help()
        return 1

    value = render(args.password)
    # 自校验：生成的值必须能验回原文，否则宁可报错也不给你一个坏的
    if not verify_password(args.password, value):
        print("❌ 自校验失败", file=sys.stderr)
        return 1
    print(value)
    return 0


if __name__ == "__main__":
    sys.exit(main())
