#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全站路由/模板健康扫描（只读，跑在本地临时 data 目录上，不碰线上数据）。

用法（在 server/app 下）：
    DATA_DIR=/tmp/netlab-scan-data ../../server/.venv/bin/python  ../../tools/route-scan.py
或直接：
    ~/teaching-system/server/.venv/bin/python ~/teaching-system/tools/route-scan.py

做三件事：
  1) 枚举 app.url_map 里所有 GET 规则，分别在【匿名】【管理员登录】两态各打一遍，
     记录 HTTP 状态码，标出 5xx（真崩）与意外 404。
  2) 扫描 app/templates/**.html 中所有 href / action / src 里的站内路径，
     用 url_map 反查是否能匹配到规则（死链检测）。
  3) 检测模板里 render_template 引用但磁盘不存在的模板名。
"""
from __future__ import annotations
import os
import re
import sys
import glob
import collections

HERE = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.join(os.path.dirname(HERE), "server", "app")
sys.path.insert(0, APP_DIR)
os.environ.setdefault("DATA_DIR", "/tmp/netlab-scan-data")
os.environ.setdefault("FLASK_ENV", "development")

import core  # noqa: E402

app = core.create_app()
client = app.test_client()

# ---------- 1) 路由探活 ----------
RULES = [r for r in app.url_map.iter_rules()]
GET_PATHS: list[tuple[str, str]] = []          # (url, rule)
for r in sorted(RULES, key=lambda x: str(x)):
    if "GET" not in r.methods:
        continue
    url = str(r)
    if url.startswith("/static/"):
        continue
    GET_PATHS.append((url, url))


def probe(tag: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for url, _ in GET_PATHS:
        # 带参数的规则：换成一个"大概率存在"的具体值 1
        target = re.sub(r"<(?:int:|path:|)?.+?>", "1", url)
        target = re.sub(r"<[^>]+>", "1", target)
        try:
            resp = client.get(target, follow_redirects=False)
            out[url] = resp.status_code
        except Exception as exc:  # noqa: BLE001
            out[url] = -1
            print(f"  [EXC] {target}: {type(exc).__name__}: {exc}")
    return out


print("=" * 72)
print("一、路由探活（匿名）")
print("=" * 72)
anon = probe("anon")
bad_anon = {u: c for u, c in anon.items() if c >= 500}
notfound_anon = {u: c for u, c in anon.items() if c == 404 and "1" not in u}
for u, c in sorted(anon.items()):
    flag = ""
    if c >= 500:
        flag = "  <== 5xx 崩溃"
    elif c == 404:
        flag = "  <== 404"
    print(f"  {c}  {u}{flag}")
print(f"  -- 匿名态 5xx: {len(bad_anon)} 个")

# ---------- 登录态 ----------
print("=" * 72)
print("二、路由探活（管理员登录态）")
print("=" * 72)
with client.session_transaction() as sess:
    sess["uid"] = 1
auth = probe("auth")
bad_auth = {u: c for u, c in auth.items() if c >= 500}
for u, c in sorted(auth.items()):
    if c >= 500:
        print(f"  {c}  {u}  <== 5xx 崩溃")
print(f"  -- 登录态 5xx: {len(bad_auth)} 个")
if not bad_auth:
    print("  （无）")

# ---------- 2) 模板死链 ----------
print("=" * 72)
print("三、模板站内链接死链检测")
print("=" * 72)
TEMPLATE_DIR = os.path.join(APP_DIR, "templates")
rule_strs = [str(r) for r in RULES if not str(r).startswith("/static/")]


def resolver_for(rule_str: str) -> re.Pattern:
    pat = re.sub(r"<[^>]+>", "__X__", rule_str)
    pat = re.escape(pat).replace("__X__", "[^/]+")
    return re.compile("^" + pat + "$")


RESOLVERS = [(r, resolver_for(r)) for r in rule_strs]

LINK_RE = re.compile(r"""(?:href|action|src)\s*=\s*["']([^"'#][^"']*)["']""")
skipped_scheme = re.compile(r"^(?:https?:|mailto:|tel:|javascript:|data:|#)")


def matches_rule(clean: str) -> bool:
    """这个站内路径能不能被某条路由匹配？

    除了精确匹配，还要放行一种常见写法：模板里用 JS 拼出来的地址，
    例如 login.html 里  src = '/scan/qr/' + token，
    正则只会抓到 '/scan/qr/' 这一段，它本身匹配不了 '/scan/qr/<token>'。
    做法：如果它正好是某条规则的"前缀 + 一段占位符"，就算它有效。
    """
    for rule_str, rx in RESOLVERS:
        if rx.match(clean):
            return True
        if "<" in rule_str:
            # 把规则按占位符切开，逐段比对前缀
            head = rule_str.split("<", 1)[0]
            if head and clean.rstrip("/") == head.rstrip("/") and rule_str.startswith(head):
                return True
    return False


found_links: list[tuple[str, str, int]] = []
for path in sorted(glob.glob(os.path.join(TEMPLATE_DIR, "**", "*.html"), recursive=True)):
    rel = os.path.relpath(path, TEMPLATE_DIR)
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    for m in LINK_RE.finditer(text):
        val = m.group(1).strip()
        if not val or skipped_scheme.match(val):
            continue
        if val.startswith("/static/") or val.startswith("{{") or val.startswith("{%"):
            continue
        clean = val.split("?")[0].split("#")[0]
        if not clean.startswith("/"):
            continue
        if not matches_rule(clean):
            line_no = text[:m.start()].count("\n") + 1
            found_links.append((rel, clean, line_no))

if found_links:
    grouped = collections.defaultdict(list)
    for rel, val, ln in found_links:
        grouped[val].append(f"{rel}:{ln}")
    for val in sorted(grouped):
        print(f"  [死链] {val}")
        for loc in grouped[val]:
            print(f"          <- {loc}")
    print(f"  -- 死链种类: {len(grouped)}，出现处: {len(found_links)}")
else:
    print("  （无死链）")

# ---------- 3) 模板存在性 ----------
print("=" * 72)
print("四、render_template 引用存在性")
print("=" * 72)
tpl_names = set()
for path in sorted(glob.glob(os.path.join(APP_DIR, "*.py"))):
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        src = fh.read()
    for m in re.finditer(r"render_template\(\s*[\"']([^\"']+)[\"']", src):
        tpl_names.add(m.group(1))
missing = []
for name in sorted(tpl_names):
    if not os.path.exists(os.path.join(TEMPLATE_DIR, name)):
        missing.append(name)
if missing:
    for name in missing:
        print(f"  [缺失] {name}")
else:
    print("  （全部存在）")
print(f"  -- 引用模板 {len(tpl_names)} 个")

print("=" * 72)
print("扫描结束")
print("=" * 72)
