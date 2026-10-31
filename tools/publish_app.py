#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""发布客户端安装包到 teaching-system 服务器，并登记进 app_versions 表。

为什么有这个脚本：
    desktop/windows/README.md 里引用的 tools/publish_app.py 在服务器下发的
    源码包中并不存在（make_source_zip.py 只打包了白名单文件），而网站后台的
    「版本管理」页只提供 android / windows / windows-portable 三个渠道，
    **没有 mac / ios**。本脚本补齐这两个缺口，行为与后台页保持一致。

    android 走整数 versionCode（须与 APK 内部一致），
    windows / windows-portable / mac / ios 走三段式版本名自动推导 versionCode
    （1.4.8 -> 1004008，与 db.semver_code 完全一致）。

用法示例：
    # 首次先干跑，只打印计划、不碰服务器
    python tools/publish_app.py --platform windows --version 1.4.9 \
        --file dist/教学管理系统-安装版-1.4.9.exe --notes "修复若干问题" --dry-run

    # 确认无误后去掉 --dry-run 真正发布
    python tools/publish_app.py --platform mac --version 1.0.9 \
        --file dist/教学管理系统-1.0.9-arm64.dmg --notes-file release-notes.txt

    # 安卓：versionCode 必须填（= build.gradle.kts 里的 versionCode）
    python tools/publish_app.py --platform android --version 1.19 --version-code 20 \
        --file app-debug.apk

    注意：站点已经迁到 MySQL，本脚本的落库也走 MySQL（复用站点自己的
    /opt/websystem/db-backend.env，谁都不敢两边漂移）。若站点回滚到 SQLite，
    本脚本会直接拒绝写入并报错，而不是悄悄写进废弃的 .db 快照。

服务器连接信息可用环境变量覆盖：
    LC_HOST (默认 YOUR_SERVER_IP)   LC_KEY (默认 ~/.ssh/teaching_system_deploy)
    LC_STATIC_DIR /opt/websystem/app/static/app   LC_BACKEND_ENV /opt/websystem/db-backend.env
    LC_REMOTE_PY /opt/websystem/venv/bin/python
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import subprocess
import sys

HOST = os.environ.get("LC_HOST", "YOUR_SERVER_IP")
KEY = os.environ.get("LC_KEY", os.path.expanduser("~/.ssh/teaching_system_deploy"))
STATIC_DIR = os.environ.get("LC_STATIC_DIR", "/opt/websystem/app/static/app")
# 站点数据库后端开关文件（迁移后由它决定写 MySQL 还是 SQLite）
BACKEND_ENV = os.environ.get("LC_BACKEND_ENV", "/opt/websystem/db-backend.env")
REMOTE_PY = os.environ.get("LC_REMOTE_PY", "/opt/websystem/venv/bin/python")

PLATFORMS = ("android", "ios", "windows", "windows-portable", "macos", "mac")
LABELS = {
    "android": "安卓 APK",
    "ios": "iOS",
    "windows": "Windows 安装版",
    "windows-portable": "Windows 绿色版",
    "macos": "macOS",
    "mac": "macOS",
}


def semver_code(version_name: str) -> int:
    """与 server/app/db.py 的 semver_code 保持一致：major*1_000_000+minor*1_000+patch。"""
    text = str(version_name or "").strip().lstrip("vV")
    if not text:
        return 0
    parts = []
    for chunk in text.split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    while len(parts) < 3:
        parts.append(0)
    major, minor, patch = parts[0], parts[1], parts[2]
    return major * 1_000_000 + minor * 1_000 + patch


def display_name_for(platform: str, version_name: str, local_file: str) -> str:
    """下载页「完整文件名」那一栏展示的名字（跟磁盘真实文件名无关）。

    沿用线上历史惯例，别让用户在下载页看到 app-debug.apk 这种构建产物名。
    """
    if platform == "android":
        return "教学管理系统-v%s.apk" % version_name
    if platform == "windows":
        return "教学管理系统-安装版-%s.exe" % version_name
    if platform == "windows-portable":
        return "教学管理系统-绿色版-%s.exe" % version_name
    if platform in ("macos", "mac"):
        return "teaching-system-mac-%s-arm64.dmg" % version_name
    if platform == "ios":
        return "教学管理系统-%s.ipa" % version_name
    return os.path.basename(local_file)


def sha512_of(path: str) -> str:
    h = hashlib.sha512()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return "%.2f %s" % (n, unit) if unit != "B" else "%d B" % n
        n /= 1024.0


def ssh(args: list[str], stdin: bytes | None = None) -> str:
    base = [
        "ssh",
        "-i", KEY,
        "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=/dev/null",
        "-o", "ConnectTimeout=15",
        "root@" + HOST,
    ]
    proc = subprocess.run(base + args, input=stdin, capture_output=True)
    if proc.returncode != 0:
        raise SystemExit("SSH 失败：%s" % proc.stderr.decode("utf-8", "replace").strip())
    return proc.stdout.decode("utf-8", "replace")


def scp(local: str, remote: str) -> None:
    cmd = [
        "scp", "-q",
        "-i", KEY,
        "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=/dev/null",
        local, "root@%s:%s" % (HOST, remote),
    ]
    if subprocess.run(cmd).returncode != 0:
        raise SystemExit("scp 上传失败")


# 远端落库脚本：读 stdin 的 JSON，写 app_versions。
# 站点已迁 MySQL：这里直接读站点自己的 db-backend.env 拿连接串，保证与站点同源。
# 与后台页逻辑一致：先把同平台旧记录 is_latest 置 0，再插入新的 is_latest=1。
REMOTE_SNIPPET = r'''
import json, sys
d = json.load(sys.stdin)

env = {}
try:
    with open(d["env"], encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
except FileNotFoundError:
    pass

backend = (env.get("NETLAB_DB_BACKEND") or "mysql").strip().lower()
if backend != "mysql":
    print("REFUSING: 站点当前后端是 %r，不是 mysql。本脚本只写 MySQL，"
          "避免把版本记录写进已废弃的 netlab.db 快照。" % backend, file=sys.stderr)
    sys.exit(3)

import pymysql
conn = pymysql.connect(
    host=env.get("NETLAB_MYSQL_HOST", "127.0.0.1"),
    port=int(env.get("NETLAB_MYSQL_PORT", "3306")),
    user=env.get("NETLAB_MYSQL_USER", "admin"),
    password=env.get("NETLAB_MYSQL_PASSWORD", ""),
    database=env.get("NETLAB_MYSQL_DATABASE", "netlab"),
    charset="utf8mb4",
)
cur = conn.cursor()
cur.execute("UPDATE app_versions SET is_latest = 0 WHERE platform = %s", (d["platform"],))
cur.execute(
    "INSERT INTO app_versions (version_code, version_name, release_notes, "
    "file_name, file_size, download_url, is_latest, created_at, platform, sha512) "
    "VALUES (%s, %s, %s, %s, %s, %s, 1, %s, %s, %s)",
    (d["version_code"], d["version_name"], d["notes"], d["display_name"],
     d["size"], d["url"], d["created_at"], d["platform"], d["sha512"]),
)
conn.commit()
cur.execute(
    "SELECT id, platform, version_code, version_name, is_latest, download_url "
    "FROM app_versions WHERE platform = %s ORDER BY version_code DESC, id DESC LIMIT 3",
    (d["platform"],),
)
print(json.dumps([list(r) for r in cur.fetchall()], ensure_ascii=False))
cur.close()
conn.close()
'''


def main() -> int:
    ap = argparse.ArgumentParser(description="发布客户端安装包并登记版本")
    ap.add_argument("--file", required=True, help="本地安装包路径")
    ap.add_argument("--platform", required=True, choices=PLATFORMS)
    ap.add_argument("--version", required=True, help="版本名，如 1.4.9 / 1.19")
    ap.add_argument("--version-code", type=int, default=0,
                    help="整数版本号；android 必填；其余平台留空则按版本名推导")
    ap.add_argument("--notes", default="", help="更新说明")
    ap.add_argument("--notes-file", default="", help="从文件读更新说明")
    ap.add_argument("--name", default="", help="覆盖服务器上的文件名（默认按「渠道+版本名」自动推导）")
    ap.add_argument("--display-name", default="",
                    help="下载页展示的完整文件名（默认按渠道惯例推导，如 教学管理系统-v1.19.apk）")
    ap.add_argument("--dry-run", action="store_true", help="只打印计划，不连服务器")
    args = ap.parse_args()

    if not os.path.isfile(args.file):
        raise SystemExit("找不到文件：%s" % args.file)

    notes = args.notes
    if args.notes_file:
        with open(args.notes_file, encoding="utf-8") as fh:
            notes = fh.read().strip()

    platform = args.platform
    version_name = args.version.strip()
    version_code = args.version_code

    if platform == "android":
        if not version_code:
            raise SystemExit("android 必须用 --version-code 指定整数版本号（见 build.gradle.kts）")
        # 与后台页同一道闸：读 APK 内真实的 versionCode/versionName，不符就拒发。
        # 这是「客户端反复提示更新」死循环的唯一根因（库里写的和包里装的对不上）。
        try:
            from pyaxmlparser import APK as _Apk
        except ImportError:
            print("!! 本地没装 pyaxmlparser，跳过 APK 内部版本号校验（后台仍会兜底）", file=sys.stderr)
        else:
            _apk = _Apk(args.file)
            real_vc, real_vn = int(_apk.version_code), str(_apk.version_name)
            if real_vc != version_code or real_vn != version_name:
                raise SystemExit(
                    "版本不一致：APK 内部实际是 v%s (versionCode=%s)，"
                    "与命令给的 v%s (versionCode=%s) 不符。\n"
                    "先改 build.gradle.kts 的 versionCode/versionName 重新构建，再来发布。"
                    % (real_vn, real_vc, version_name, version_code))
            print("✓ APK 内部版本核对通过：v%s (versionCode=%s)" % (real_vn, real_vc))
    else:
        if not version_code:
            version_code = semver_code(version_name)
            if version_code <= 0:
                raise SystemExit("版本名必须是三段式，如 1.4.9")
        if version_name.count(".") < 2:
            raise SystemExit("%s 的版本名必须是三段式（如 1.4.9），当前是 %s"
                             % (LABELS.get(platform, platform), version_name))

    # 服务器上的真实文件名：与后台页 views_admin.app_version_publish 用同一套命名，
    # 用「渠道 + 版本名」推导（不是用本地原文件名，也不用 version_code）。
    # 原因见后台那段注释：两套命名并存会让旧包永远不被覆盖、越堆越多。
    if args.name:
        safe_name = args.name
    elif platform in ("windows", "windows-portable"):
        flavor = "portable" if platform == "windows-portable" else "setup"
        safe_name = "teaching-system-win-%s-v%s.exe" % (flavor, version_name)
    elif platform in ("macos", "mac"):
        safe_name = "teaching-system-mac-v%s.dmg" % version_name
    elif platform == "ios":
        safe_name = "teaching-system-ios-v%s.ipa" % version_name
    else:
        safe_name = "teaching-system-android-v%s.apk" % version_name

    size = os.path.getsize(args.file)
    digest = sha512_of(args.file)
    url = "/static/app/" + safe_name
    created_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    print("=" * 62)
    print("  发布计划")
    print("=" * 62)
    print("  渠道      : %s (%s)" % (LABELS.get(platform, platform), platform))
    print("  版本      : %s   version_code = %d" % (version_name, version_code))
    print("  本地文件  : %s" % args.file)
    print("  体积      : %s" % human(size))
    print("  SHA-512   : %s" % digest[:32] + "…")
    print("  服务器名  : %s" % safe_name)
    print("  展示名    : %s" % (args.display_name or display_name_for(platform, version_name, args.file)))
    print("  下载地址  : %s" % url)
    print("  更新时间  : %s" % created_at)
    print("  更新说明  : %s" % (notes.replace("\n", " / ") or "(空)"))
    print("=" * 62)

    if args.dry_run:
        print("干跑模式，未连接服务器。确认无误后去掉 --dry-run。")
        return 0

    remote_path = "%s/%s" % (STATIC_DIR, safe_name)
    print("→ 上传 %s …" % safe_name)
    scp(args.file, remote_path)
    ssh(["chown", "www-data:www-data", remote_path])

    payload = json.dumps({
        "env": BACKEND_ENV, "platform": platform, "version_code": version_code,
        "version_name": version_name, "notes": notes,
        "display_name": args.display_name or display_name_for(platform, version_name, args.file),
        "size": size, "url": url, "created_at": created_at,
        "sha512": digest,
    }, ensure_ascii=False).encode("utf-8")

    print("→ 登记 app_versions …")
    return _register(payload, platform)


def _register(payload: bytes, platform: str) -> int:
    """把远端脚本 + JSON 一起喂给服务器上的 python。"""
    script = REMOTE_SNIPPET.encode("utf-8")
    # 用 base64 传递，避免任何引号/换行在不同 shell 间的转义问题
    import base64
    b64 = base64.b64encode(script).decode("ascii")
    cmd = "%s -c \"import base64,sys;exec(base64.b64decode('%s').decode('utf-8'))\"" % (REMOTE_PY, b64)
    rows = ssh([cmd], stdin=payload)
    data = json.loads(rows.strip().splitlines()[-1])
    print("✅ 发布完成，当前 %s 渠道最近的版本：" % platform)
    for r in data:
        flag = "  ← 最新" if r[4] else ""
        print("   #%s  v%s (code=%s)  %s%s" % (r[0], r[3], r[2], r[5], flag))
    print("\n网站 https://your-server.example.com/download 已更新；已装客户端下次检查时收到更新提示。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
