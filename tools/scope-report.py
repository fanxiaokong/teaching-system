#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""查看每个账号的课程解锁情况，以及每个激活码的范围。

用途：在数据库里手工改过 activation_codes 之后，用它确认改动真的生效、
以及解析出来到底解锁了哪些课（手工填的 JSON 写坏时能立刻看出来）。

在服务器上跑：
    cd /opt/websystem/app && /opt/websystem/venv/bin/python /opt/websystem/tools/scope-report.py

只看某个账号：
    ... scope-report.py --user 59
查看某门课的课程 id 对照表：
    ... scope-report.py --courses
"""
import argparse
import os
import sys
import zipfile

APP_DIR = os.environ.get("NETLAB_APP_DIR", "/opt/websystem/app")
DB_ENV_FILE = os.environ.get("NETLAB_DB_ENV_FILE", "/opt/websystem/db-backend.env")


def _load_db_env(path):
    """把 KEY=VALUE 文件读进 os.environ。

    **这一步不能省**：线上跑的是 MySQL，而「用哪个后端」是 wsgi_entry.py 在启动时
    从 db-backend.env 读进来的。脚本单独跑没有这个过程 → 会退回 SQLite（旧快照），
    查出来的账号和激活码全是历史数据，结论完全错。
    """
    try:
        with open(path, "r", encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError:
        return False
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ[key.strip()] = val.strip().strip('"').strip("'")
    return True


_loaded = _load_db_env(DB_ENV_FILE)
os.environ.setdefault("DATA_DIR", "/opt/websystem/data")

if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

import core  # noqa: E402
import db    # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", help="只看某个账号（用户名、昵称或 id）")
    ap.add_argument("--courses", action="store_true", help="列出课程 id 对照表")
    args = ap.parse_args()

    app = core.create_app()          # 触发建表 / 迁移
    with app.app_context():
        conn = db.connect()
        # 明确报出用的是哪个后端 —— 读错库会让整份报告毫无意义
        backend = "MySQL" if getattr(db, "USE_MYSQL", False) else "SQLite(本地快照)"
        print(f"数据来源：{backend}"
              f"{'' if _loaded else '  ⚠️ 没读到 ' + DB_ENV_FILE + '，可能查的是旧库！'}")
        courses = conn.execute(
            "SELECT id, title, category FROM courses WHERE is_open = 1 "
            "ORDER BY category, sort_order, id").fetchall()
        total = len(courses)
        by_id = {int(c["id"]): c for c in courses}

        if args.courses:
            print(f"开放中的课程共 {total} 门：")
            cat = None
            for c in courses:
                if c["category"] != cat:
                    cat = c["category"]
                    print(f"\n[{cat or '未分类'}]")
                print(f"  {c['id']:>4}  {c['title']}")
            return

        # 1) 每个账号的解锁情况
        users = conn.execute(
            "SELECT id, username, nickname, is_admin FROM users ORDER BY id").fetchall()
        print("=" * 78)
        print("账号解锁情况")
        print("=" * 78)
        print(f"{'id':>4}  {'账号':<16} {'解锁':>9}   访问范围")
        print("-" * 78)
        for u in users:
            uid = int(u["id"])
            if u["is_admin"]:
                print(f"{uid:>4}  {(u['username'] or '')[:16]:<16} {'全部(管理员)':>9}   —")
                continue
            scope = db.user_course_scope(conn, uid)
            if scope["all"]:
                n, desc = total, "全部课程"
            else:
                acc = db.user_accessible_courses(conn, uid)
                n = len(acc)
                parts = []
                if scope["categories"]:
                    parts.append("标签：" + "、".join(sorted(scope["categories"])))
                if scope["courses"]:
                    names = [by_id[i]["title"] for i in sorted(scope["courses"]) if i in by_id]
                    parts.append("课程：" + ("、".join(names) if names else "(含已下架/不存在的 id)"))
                desc = " + ".join(parts) if parts else "无"
            flag = "" if n == 0 else ""
            print(f"{uid:>4}  {(u['username'] or '')[:16]:<16} {n:>4}/{total:<4}   {desc}{flag}")

        # 2) 激活码与其范围
        print()
        print("=" * 78)
        print("激活码范围（scope_kind='limited' 时看后两列）")
        print("=" * 78)
        rows = conn.execute(
            "SELECT c.*, u.username AS uname, u.nickname AS unick FROM activation_codes c "
            "LEFT JOIN users u ON u.id = c.used_by ORDER BY c.used_by IS NULL, c.id").fetchall()
        print(f"{'id':>4}  {'激活码':<14} {'使用者':<12} {'界面显示的范围':<28} 原始字段")
        print("-" * 78)
        for r in rows:
            who = (r["unick"] or r["uname"] or "—")[:12]
            label = db.code_scope_label(r)
            raw_kind = str(db._row_get(r, "scope_kind", "") or "")
            raw_cat = str(db._row_get(r, "scope_categories", "") or "")
            raw_crs = str(db._row_get(r, "scope_courses", "") or "")
            warn = "  ⚠️JSON写坏" if (raw_kind.strip().lower() == "limited"
                                   and label.startswith("未指定")) else ""
            print(f"{r['id']:>4}  {r['code']:<14} {who:<12} {label:<28} "
                  f"{raw_kind}/{raw_cat}/{raw_crs}{warn}")

        # 3) 只看某个账号时，把他的码和实际能看的课都列出来
        if args.user:
            key = args.user.strip()
            row = conn.execute(
                "SELECT * FROM users WHERE username = ? OR nickname = ? OR id = ?",
                (key, key, int(key) if key.isdigit() else -1)).fetchone()
            if row is None:
                print(f"\n找不到账号：{key}")
                return
            uid = int(row["id"])
            print()
            print("=" * 78)
            print(f"账号 {row['username']}（{row['nickname'] or ''}，id={uid}）明细")
            print("=" * 78)
            mine = conn.execute(
                "SELECT * FROM activation_codes WHERE used_by = ? ORDER BY id", (uid,)).fetchall()
            if not mine:
                print("  该账号没有绑定任何激活码 → 只能看 0 门课")
            for r in mine:
                print(f"  码 {r['code']}  范围={db.code_scope_label(r)}")
            acc = sorted(db.user_accessible_courses(conn, uid))
            print(f"\n  实际可访问 {len(acc)}/{total} 门：")
            for i in acc:
                if i in by_id:
                    print(f"    {i:>4}  {by_id[i]['title']}  [{by_id[i]['category']}]")


if __name__ == "__main__":
    main()
