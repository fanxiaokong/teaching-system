#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""打包 Windows 客户端源代码为 zip（排除 node_modules / dist），用于网站「源代码下载」。

安全约定（重要）：
  1. tools/ 下除白名单外的文件一律不进包 —— tools/ssh_run.py、tools/publish_app.py
     会用到服务器凭据，虽然走环境变量，但没必要把运维脚本放出去。
  2. server/ 是本地维护时从服务器拉下来的站点副本，不进包。
  3. 打完包再做一次敏感串扫描，命中就中止并报错，避免凭据泄露。
"""
import os
import zipfile

SRC = "~/build/teaching-system-windows-source"
OUT = "~/build/teaching-system-windows-source/teaching-system-windows-source.zip"

# 目录：整目录排除
SKIP_DIRS = {
    "node_modules", "dist", ".git", "__pycache__",
    "server", "src.bak-before-bilibili", "src.bak",
}
# 顶层文件：排除
SKIP_TOP = {"teaching-system-windows-source.zip", ".DS_Store", "package-lock.json"}
# 任意层级同名文件：排除
SKIP_NAMES = {".DS_Store"}
# tools/ 白名单：只有这些允许进包
TOOLS_ALLOW = {
    "tools/make_source_zip.py",
    "tools/probe_shell.js",
}
# 敏感串：命中即中止。故意拆开拼装，避免扫描器匹配到本文件里的规则本身。
# 注：LC_PASS 只是环境变量名（README 里是 export LC_PASS='...' 占位符），不算秘密，
# 所以只拦真正的密码形态。
SECRET_MARKERS = (
    b"Netlab" + b"@",
    b"sshpass" + b" -p",
)


def should_skip(rel, name):
    if rel in SKIP_TOP or name in SKIP_NAMES:
        return True
    if rel.startswith("tools/"):
        return rel not in TOOLS_ALLOW
    return False


def main():
    if os.path.isfile(OUT):
        os.remove(OUT)
    entries = []
    for root, dirs, files in os.walk(SRC):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            full = os.path.join(root, f)
            rel = os.path.relpath(full, SRC)
            if should_skip(rel, f):
                continue
            entries.append((full, rel))

    hits = []
    for full, rel in entries:
        try:
            with open(full, "rb") as fh:
                blob = fh.read()
        except OSError:
            continue
        for m in SECRET_MARKERS:
            if m in blob:
                hits.append((rel, m.decode("utf-8", "replace")))
    if hits:
        print("!!! 检测到敏感内容，已中止打包：")
        for rel, m in hits:
            print("    %s  <- %s" % (rel, m))
        raise SystemExit(1)

    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
        for full, rel in entries:
            z.write(full, rel)

    print("打包完成：%s （%d 个文件，%.1f MB）"
          % (OUT, len(entries), os.path.getsize(OUT) / 1048576.0))


if __name__ == "__main__":
    main()
