"""意见反馈：用户提交（文字 + 截图）、查看自己的反馈并追问；管理员查看全部并回复。

路由分两组：
    前台  /feedback           页面（提交 / 我的反馈 两个选项卡）
          /feedback/submit    提交（multipart，可带多张截图）
          /feedback/mine      我的反馈列表 JSON
          /feedback/<id>      单条详情 JSON（含图片、回复流）
          /feedback/<id>/reply       回复（管理员或本人）
          /feedback/img/<img_id>     读取截图（鉴权）
    管理  /admin/feedback     管理页
          /admin/feedback/list        全部反馈 JSON（可按状态筛选）
          /admin/feedback/<id>/status 标记已处理 / 重新打开
"""
from __future__ import annotations

import mimetypes
import os
import secrets

from flask import (Blueprint, abort, jsonify, render_template, request, send_file, url_for)

import db
from core import (admin_required, current_user, get_db, login_required)

bp = Blueprint("feedback", __name__)

ALLOWED_IMG_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
MAX_IMAGES = 5
MAX_IMAGE_SIZE = 10 * 1024 * 1024
CATEGORIES = ("功能异常", "功能建议", "使用问题", "内容纠错", "其他")


def _is_admin(u) -> bool:
    return bool(u and u["is_admin"])


def _rows_images(conn, feedback_ids):
    """一次性取出多条反馈的截图，返回 {feedback_id: [img, ...]}。"""
    if not feedback_ids:
        return {}
    marks = ",".join("?" * len(feedback_ids))
    out = {}
    for r in conn.execute(
            f"SELECT * FROM feedback_images WHERE feedback_id IN ({marks}) "
            "ORDER BY id", tuple(feedback_ids)):
        out.setdefault(r["feedback_id"], []).append(r)
    return out


def _rows_replies(conn, feedback_ids):
    if not feedback_ids:
        return {}
    marks = ",".join("?" * len(feedback_ids))
    out = {}
    for r in conn.execute(
            "SELECT r.*, u.username, u.nickname FROM feedback_replies r "
            "LEFT JOIN users u ON u.id = r.user_id "
            f"WHERE r.feedback_id IN ({marks}) ORDER BY r.id", tuple(feedback_ids)):
        out.setdefault(r["feedback_id"], []).append(r)
    return out


def _pack(conn, rows, with_images=True, with_replies=True):
    """把反馈行打包成前端直接能用的 dict。"""
    ids = [r["id"] for r in rows]
    imgs = _rows_images(conn, ids) if with_images else {}
    reps = _rows_replies(conn, ids) if with_replies else {}
    out = []
    for r in rows:
        d = {
            "id": r["id"],
            "user_id": r["user_id"],
            "title": r["title"] or "",
            "category": r["category"] or "",
            "content": r["content"] or "",
            "status": r["status"] or "open",
            "created_at": r["created_at"] or "",
            "updated_at": r["updated_at"] or "",
            "replied_at": r["replied_at"] or "",
            "username": r["username"] if "username" in r.keys() else "",
            "nickname": r["nickname"] if "nickname" in r.keys() else "",
            "images": [],
            "replies": [],
        }
        for im in imgs.get(r["id"], []):
            d["images"].append({
                "id": im["id"],
                "url": url_for("feedback.fb_image", img_id=im["id"]),
                "name": im["original_name"] or "截图",
                "size": im["size"] or 0,
            })
        for rp in reps.get(r["id"], []):
            d["replies"].append({
                "id": rp["id"],
                "user_id": rp["user_id"],
                "is_admin": bool(rp["is_admin"]),
                "content": rp["content"] or "",
                "created_at": rp["created_at"] or "",
                "who": (rp["nickname"] or rp["username"] or ("管理员" if rp["is_admin"] else "用户")),
            })
        out.append(d)
    return out


def _save_images(conn, feedback_id, files):
    saved = 0
    for f in files:
        if not f or not f.filename:
            continue
        if saved >= MAX_IMAGES:
            break
        ext = os.path.splitext(f.filename)[1].lower()
        if ext not in ALLOWED_IMG_EXT:
            continue
        f.stream.seek(0, os.SEEK_END)
        size = f.stream.tell()
        f.stream.seek(0)
        if size <= 0 or size > MAX_IMAGE_SIZE:
            continue
        stored = "fb_%s%s" % (secrets.token_hex(8), ext)
        path = os.path.join(db.FEEDBACK_DIR, stored)
        f.save(path)
        conn.execute(
            "INSERT INTO feedback_images (feedback_id, stored_name, original_name, size, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (feedback_id, stored, os.path.basename(f.filename), os.path.getsize(path), db.now()))
        saved += 1
    return saved


# ---------------------------------------------------------------- 前台

@bp.route("/feedback")
@login_required
def index():
    conn = get_db()
    u = current_user()
    mine = conn.execute(
        "SELECT f.*, u.username, u.nickname FROM feedback f "
        "LEFT JOIN users u ON u.id = f.user_id "
        "WHERE f.user_id = ? ORDER BY f.id DESC LIMIT 50", (u["id"],)).fetchall()
    return render_template("feedback.html",
                           items=_pack(conn, mine),
                           categories=CATEGORIES,
                           max_images=MAX_IMAGES)


@bp.post("/feedback/submit")
@login_required
def submit():
    u = current_user()
    title = (request.form.get("title") or "").strip()[:80]
    category = (request.form.get("category") or "").strip()[:20]
    content = (request.form.get("content") or "").strip()
    if not content:
        return jsonify({"ok": False, "error": "请填写反馈内容"}), 400
    if len(content) > 4000:
        return jsonify({"ok": False, "error": "内容太长了（最多 4000 字）"}), 400
    if category and category not in CATEGORIES:
        category = "其他"

    conn = get_db()
    now = db.now()
    cur = conn.execute(
        "INSERT INTO feedback (user_id, title, category, content, status, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, 'open', ?, ?)",
        (u["id"], title, category, content, now, now))
    fid = cur.lastrowid
    files = request.files.getlist("images")
    n = _save_images(conn, fid, files)
    conn.commit()
    return jsonify({"ok": True, "id": fid, "images": n})


@bp.get("/feedback/mine")
@login_required
def mine():
    conn = get_db()
    u = current_user()
    rows = conn.execute(
        "SELECT f.*, u.username, u.nickname FROM feedback f "
        "LEFT JOIN users u ON u.id = f.user_id "
        "WHERE f.user_id = ? ORDER BY f.id DESC LIMIT 100", (u["id"],)).fetchall()
    return jsonify({"ok": True, "items": _pack(conn, rows)})


@bp.get("/feedback/<int:fid>")
@login_required
def detail(fid: int):
    conn = get_db()
    u = current_user()
    row = conn.execute(
        "SELECT f.*, u.username, u.nickname FROM feedback f "
        "LEFT JOIN users u ON u.id = f.user_id WHERE f.id = ?", (fid,)).fetchone()
    if not row:
        return jsonify({"ok": False, "error": "反馈不存在"}), 404
    if row["user_id"] != u["id"] and not _is_admin(u):
        return jsonify({"ok": False, "error": "无权查看"}), 403
    return jsonify({"ok": True, "item": _pack(conn, [row])[0]})


@bp.post("/feedback/<int:fid>/reply")
@login_required
def reply(fid: int):
    u = current_user()
    content = (request.form.get("content") or (request.get_json(silent=True) or {}).get("content") or "").strip()
    if not content:
        return jsonify({"ok": False, "error": "回复内容不能为空"}), 400
    if len(content) > 2000:
        return jsonify({"ok": False, "error": "回复太长了（最多 2000 字）"}), 400

    conn = get_db()
    row = conn.execute("SELECT * FROM feedback WHERE id = ?", (fid,)).fetchone()
    if not row:
        return jsonify({"ok": False, "error": "反馈不存在"}), 404
    is_admin = _is_admin(u)
    if row["user_id"] != u["id"] and not is_admin:
        return jsonify({"ok": False, "error": "无权回复"}), 403

    now = db.now()
    conn.execute(
        "INSERT INTO feedback_replies (feedback_id, user_id, is_admin, content, created_at) "
        "VALUES (?, ?, ?, ?, ?)", (fid, u["id"], 1 if is_admin else 0, content, now))
    # 管理员回复 → 标记已回复；用户追问 → 重新回到待处理
    if is_admin:
        conn.execute("UPDATE feedback SET status='replied', replied_at=?, replied_by=?, updated_at=? "
                     "WHERE id=?", (now, u["id"], now, fid))
    else:
        conn.execute("UPDATE feedback SET status='open', updated_at=? WHERE id=?", (now, fid))
    conn.commit()
    return jsonify({"ok": True, "id": fid,
                    "reply": {"is_admin": is_admin, "content": content, "created_at": now,
                              "who": u["nickname"] or u["username"]}})


@bp.get("/feedback/img/<int:img_id>")
@login_required
def fb_image(img_id: int):
    u = current_user()
    conn = get_db()
    row = conn.execute("SELECT * FROM feedback_images WHERE id = ?", (img_id,)).fetchone()
    if not row:
        abort(404)
    fb = conn.execute("SELECT user_id FROM feedback WHERE id = ?", (row["feedback_id"],)).fetchone()
    if not fb or (fb["user_id"] != u["id"] and not _is_admin(u)):
        abort(403)
    path = os.path.join(db.FEEDBACK_DIR, row["stored_name"])
    if not os.path.exists(path):
        abort(404)
    mime = mimetypes.guess_type(row["original_name"] or "")[0] or "image/png"
    return send_file(path, mimetype=mime, max_age=3600)


# ---------------------------------------------------------------- 管理端

@bp.get("/admin/feedback")
@login_required
@admin_required
def admin_page():
    return render_template("admin_feedback.html")


@bp.get("/admin/feedback/list")
@login_required
@admin_required
def admin_list():
    conn = get_db()
    status = (request.args.get("status") or "").strip()
    kw = (request.args.get("kw") or "").strip()
    where, args = [], []
    if status and status != "all":
        where.append("f.status = ?")
        args.append(status)
    if kw:
        where.append("(f.content LIKE ? OR f.title LIKE ? OR u.username LIKE ? OR u.nickname LIKE ?)")
        args += ["%" + kw + "%"] * 4
    sql = ("SELECT f.*, u.username, u.nickname FROM feedback f "
           "LEFT JOIN users u ON u.id = f.user_id ")
    if where:
        sql += "WHERE " + " AND ".join(where) + " "
    sql += "ORDER BY f.id DESC LIMIT 200"
    rows = conn.execute(sql, tuple(args)).fetchall()
    total = conn.execute("SELECT COUNT(*) c FROM feedback").fetchone()["c"]
    open_n = conn.execute("SELECT COUNT(*) c FROM feedback WHERE status='open'").fetchone()["c"]
    replied_n = conn.execute("SELECT COUNT(*) c FROM feedback WHERE status='replied'").fetchone()["c"]
    return jsonify({"ok": True, "items": _pack(conn, rows),
                    "stat": {"total": total, "open": open_n, "replied": replied_n}})


@bp.post("/admin/feedback/<int:fid>/status")
@login_required
@admin_required
def admin_status(fid: int):
    data = request.get_json(silent=True) or request.form or {}
    status = (data.get("status") or "").strip()
    if status not in ("open", "replied", "closed"):
        return jsonify({"ok": False, "error": "状态无效"}), 400
    conn = get_db()
    row = conn.execute("SELECT id FROM feedback WHERE id = ?", (fid,)).fetchone()
    if not row:
        return jsonify({"ok": False, "error": "反馈不存在"}), 404
    conn.execute("UPDATE feedback SET status=?, updated_at=? WHERE id=?", (status, db.now(), fid))
    conn.commit()
    return jsonify({"ok": True, "id": fid, "status": status})
