"""微信小程序 JSON API（/api/v1）。

与网页端 session 认证相互独立，改用 token 认证（登录后签发，14 天有效），
但共用同一套用户表与业务逻辑。小程序拿到 token 后放请求头：
    Authorization: Bearer <token>
文件下载等不便带请求头的场景，也支持 ?token= 查询参数。

统一响应格式：
    成功  {"ok": true, "data": {...}}
    失败  {"ok": false, "error": "...", "code": 401/403/404/...}
"""
from __future__ import annotations

import functools
import mimetypes
import os
import re
import secrets

from flask import Blueprint, g, jsonify, request, send_file
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

import db
import throttle
from core import app, get_db

from views_auth import PHONE_RE, STUDENT_RE, USERNAME_RE

bp = Blueprint("api", __name__, url_prefix="/api/v1")

TOKEN_MAX_AGE = 60 * 60 * 24 * 14   # 14 天


# ---------------------------------------------------------------- token 认证

def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(app.secret_key, salt="miniapp-api-v1")


def _make_token(user_id: int) -> str:
    return _serializer().dumps({"uid": user_id})


def _read_token(token: str | None) -> int | None:
    if not token:
        return None
    try:
        data = _serializer().loads(token, max_age=TOKEN_MAX_AGE)
        return int(data.get("uid") or 0) or None
    except (BadSignature, SignatureExpired):
        return None


def _extract_token() -> str | None:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:].strip()
    return request.args.get("token")


def api_user():
    """返回当前 token 对应的用户（已缓存在 g），无则 None。"""
    if "api_user" not in g:
        uid = _read_token(_extract_token())
        g.api_user = None
        if uid:
            g.api_user = get_db().execute(
                "SELECT * FROM users WHERE id = ? AND is_active = 1", (uid,)
            ).fetchone()
    return g.api_user


def login_required(view):
    @functools.wraps(view)
    def wrapper(*args, **kwargs):
        if api_user() is None:
            return jsonify({"ok": False, "error": "未登录或登录已过期", "code": 401}), 401
        return view(*args, **kwargs)
    return wrapper


def course_access_required(view):
    """**课程级**门禁：按请求里能定位到的课程判断该用户的激活范围。

    定位顺序与 core._course_id_for_request 一致：course_id 参数 > ?course= >
    video_id / assignment_id / file_id 反查课程。
    """
    @functools.wraps(view)
    def wrapper(*args, **kwargs):
        user = api_user()
        if user is None:
            return jsonify({"ok": False, "error": "未登录或登录已过期", "code": 401}), 401
        if user["is_admin"]:
            return view(*args, **kwargs)
        conn = get_db()
        from core import _course_id_for_request
        course_id = _course_id_for_request(conn, kwargs)
        if course_id is not None and db.user_course_access(conn, user["id"], course_id):
            return view(*args, **kwargs)
        if course_id is None:
            return jsonify({"ok": False, "error": "这个内容没有关联到具体课程", "code": 403}), 403
        if not db.user_activated(conn, user["id"]):
            return jsonify({"ok": False, "error": "这门课程需先输入激活码解锁", "code": 403}), 403
        return jsonify({"ok": False,
                        "error": "你的激活码不包含这门课程，请联系管理员补充权限",
                        "code": 403}), 403
    return wrapper


def _ok(data=None):
    return jsonify({"ok": True, "data": data})


def _err(msg, code=400):
    return jsonify({"ok": False, "error": msg, "code": code}), code


def _user_dict(row) -> dict:
    if row is None:
        return None
    conn = get_db()
    is_admin = bool(row["is_admin"])
    # is_activated 的含义已随"按课程范围解锁"调整：
    # 从「用过任意一个激活码」改成「已解锁全部课程」——
    # 这样旧版 App 读它来决定要不要提示"去激活"时，部分解锁的用户仍会被正确引导。
    all_unlocked = is_admin or db.user_has_all_courses(conn, row["id"])
    total = conn.execute("SELECT COUNT(*) c FROM courses WHERE is_open = 1").fetchone()["c"]
    return {
        "id": row["id"],
        "username": row["username"],
        "nickname": row["nickname"] or row["username"],
        "phone": row["phone"],
        "is_admin": is_admin,
        "is_activated": all_unlocked,
        # 新版 App 用来显示"已解锁 x/y 门课程"
        "unlocked_courses": total if is_admin else len(db.user_accessible_courses(conn, row["id"])),
        "total_courses": total,
        "has_any_code": is_admin or db.user_activated(conn, row["id"]),
        "quota_mb": row["quota_mb"] if row["quota_mb"] is not None else 200,
        "created_at": row["created_at"],
    }


# ---------------------------------------------------------------- 认证

@bp.post("/login")
def login():
    data = request.get_json(silent=True) or {}
    identifier = (data.get("identifier") or "").strip()
    password = data.get("password") or ""
    if not identifier or not password:
        return _err("请输入账号和密码")

    # 防爆破：同一 IP 打同一账号 5 分钟最多 8 次
    wait = throttle.login_gate(identifier)
    if wait:
        return _err(f"尝试太频繁了，请等 {wait} 秒后再试", 429)

    conn = get_db()
    row = conn.execute(
        "SELECT * FROM users WHERE username = ? OR phone = ? OR student_no = ?", (identifier, identifier, identifier)
    ).fetchone()
    if not row or not row["is_active"] or not db.verify_password(password, row["password_hash"]):
        return _err("用户名 / 手机号或密码不正确", 401)
    throttle.login_ok(identifier)
    conn.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (db.now(), row["id"]))
    conn.commit()
    db.record_study_day(conn, row["id"])
    return _ok({"token": _make_token(row["id"]), "user": _user_dict(row)})


@bp.post("/register")
def register():
    data = request.get_json(silent=True) or {}
    conn = get_db()
    if db.get_setting(conn, "register_open", "1") != "1":
        return _err("注册通道已关闭，请联系管理员")
    username = (data.get("username") or "").strip()
    phone = (data.get("phone") or "").strip()
    student_no = (data.get("student_no") or "").strip()
    password = data.get("password") or ""
    confirm = data.get("confirm") or ""
    nickname = (data.get("nickname") or "").strip()[:20]

    if not USERNAME_RE.match(username):
        return _err("用户名需 3-20 位，可用中文、字母、数字、下划线")
    if not PHONE_RE.match(phone):
        return _err("请填写 11 位手机号")
    if not STUDENT_RE.match(student_no):
        return _err("请填写正确的学号（4-30 位字母或数字）")
    if len(password) < 6:
        return _err("密码至少 6 位")
    if password != confirm:
        return _err("两次输入的密码不一致")
    if conn.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
        return _err("这个用户名已经被注册了")
    if conn.execute("SELECT 1 FROM users WHERE phone = ?", (phone,)).fetchone():
        return _err("这个手机号已经被注册了")
    if conn.execute("SELECT 1 FROM users WHERE student_no = ?", (student_no,)).fetchone():
        return _err("这个学号已经被注册了")

    cur = conn.execute(
        "INSERT INTO users (username, phone, student_no, password_hash, nickname, is_active, created_at) "
        "VALUES (?, ?, ?, ?, ?, 1, ?)",
        (username, phone, student_no, db.hash_password(password), nickname, db.now()))
    conn.commit()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (cur.lastrowid,)).fetchone()
    db.record_study_day(conn, row["id"])
    return _ok({"token": _make_token(row["id"]), "user": _user_dict(row)})


@bp.post("/activate")
@login_required
def activate():
    """输入激活码。允许**累加**：用过码之后仍可再输一个新码叠加权限。"""
    user = api_user()
    conn = get_db()
    if user["is_admin"]:
        return _ok({"activated": True, "scope_all": True, "unlocked": None})
    code = (request.get_json(silent=True) or {}).get("code", "").strip()
    err = db.redeem_code(conn, code, user["id"])
    if err is not None:
        return _err(err)
    scope = db.user_course_scope(conn, user["id"])
    return _ok({
        "activated": True,
        "scope_all": bool(scope["all"]),
        "unlocked": db.user_course_count(conn, user["id"]),
    })


@bp.get("/activate/status")
@login_required
def activate_status():
    """当前解锁进度 + 自己用过的码（App 的激活页用来显示「还缺哪些」）。"""
    user = api_user()
    conn = get_db()
    if user["is_admin"]:
        return _ok({"activated": True, "scope_all": True,
                    "unlocked": None, "total": None, "codes": []})
    scope = db.user_course_scope(conn, user["id"])
    total = conn.execute("SELECT COUNT(*) c FROM courses WHERE is_open = 1").fetchone()["c"]
    mine = conn.execute(
        "SELECT code, scope_kind, scope_categories, scope_courses, used_at "
        "FROM activation_codes WHERE used_by = ? ORDER BY used_at, id", (user["id"],)).fetchall()
    return _ok({
        "activated": db.user_activated(conn, user["id"]),
        "scope_all": bool(scope["all"]),
        "unlocked": total if scope["all"] else len(db.user_accessible_courses(conn, user["id"])),
        "total": total,
        "codes": [{"code": r["code"], "scope": db.code_scope_label(r),
                   "used_at": r["used_at"]} for r in mine],
    })


# ---------------------------------------------------------------- 首页

@bp.get("/home")
def home():
    conn = get_db()
    settings = db.all_settings(conn)
    bucket: dict[str, list] = {}
    first_order: dict[str, int] = {}
    for row in conn.execute(
        "SELECT * FROM nav_links WHERE group_name <> ? ORDER BY sort_order, id",
        (db.FRIENDLY_GROUP,),
    ):
        name = row["group_name"] or "其他"
        bucket.setdefault(name, []).append(dict(row))
        first_order[name] = min(first_order.get(name, row["sort_order"]), row["sort_order"])
    tile_groups = [
        {"name": name, "links": bucket[name]}
        for name in sorted(bucket, key=lambda n: (first_order[n], n))
    ]
    stats = db.join_stats(conn)
    return _ok({
        "site_title": settings.get("site_title", "教学管理系统"),
        "site_subtitle": settings.get("site_subtitle", ""),
        "site_intro": settings.get("site_intro", ""),
        "hero_tag": settings.get("hero_tag", ""),
        "hero_title": settings.get("hero_title", ""),
        "hero_desc": settings.get("hero_desc", ""),
        "tile_groups": tile_groups,
        "stats": stats,
        "join_open": settings.get("join_open", "1") == "1",
        "group_qrcode": settings.get("group_qrcode", ""),
    })


# ---------------------------------------------------------------- 报名

@bp.post("/join")
def join():
    """小程序端报名，与网页端共用 join_requests 表和校验规则。"""
    conn = get_db()
    if db.get_setting(conn, "join_open", "1") != "1":
        return _err("报名通道已关闭，请联系实验室管理员")
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    college = "人工智能学院"  # 学院固定，忽略用户输入
    contact = db.normalize_contact(data.get("contact"))
    wants_group = 1 if data.get("join_group") in ("1", "yes", "on", True) else 0
    note = (data.get("note") or "").strip()[:200]

    if len(name) < 2:
        return _err("请填写真实姓名（至少 2 个字）")
    if len(name) > 20:
        return _err("姓名太长了，请只填姓名")
    if len(college) < 2:
        return _err("请填写学院")
    if len(college) > 40:
        return _err("学院名称太长了")
    if len(contact) < 5:
        return _err("请填写有效的联系方式（手机号 / 微信 / QQ）")
    if len(contact) > 60:
        return _err("联系方式太长了")

    existing = conn.execute(
        "SELECT * FROM join_requests WHERE contact = ? ORDER BY id DESC LIMIT 1",
        (contact,)).fetchone()
    if existing:
        return _ok({"duplicate": True, "request_no": existing["id"],
                    "name": existing["name"],
                    "join_group": bool(existing["join_group"]),
                    "created_at": existing["created_at"]})

    cur = conn.execute(
        "INSERT INTO join_requests (name, college, contact, join_group, note, created_at, ip) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (name, college, contact, wants_group, note, db.now(),
         request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0].strip()))
    conn.commit()
    return _ok({"duplicate": False, "request_no": cur.lastrowid, "name": name,
                "join_group": bool(wants_group), "created_at": db.now()})


# ---------------------------------------------------------------- 课程

@bp.get("/courses")
@login_required
def course_list():
    """课程列表：全部返回，但给没解锁的课程打 locked 标记（App 显示🔒）。"""
    conn = get_db()
    keyword = (request.args.get("keyword") or request.args.get("q") or "").strip()
    category = (request.args.get("category") or "").strip()
    sql = ("SELECT c.*, "
           "(SELECT COUNT(*) FROM files f WHERE f.kind='resource' AND f.course_id=c.id) AS file_count, "
           "(SELECT COUNT(*) FROM videos v WHERE v.course_id=c.id) AS video_count, "
           "(SELECT COUNT(*) FROM assignments a WHERE a.course_id=c.id) AS hw_count "
           "FROM courses c WHERE c.is_open = 1")
    params: list = []
    if keyword:
        sql += " AND (c.title LIKE ? OR c.summary LIKE ?)"
        params += [f"%{keyword}%"] * 2
    if category:
        sql += " AND c.category = ?"
        params.append(category)
    sql += " ORDER BY c.sort_order, c.id DESC"
    rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    categories = [r["category"] for r in conn.execute(
        "SELECT DISTINCT category FROM courses WHERE category <> '' ORDER BY category").fetchall()]

    user = api_user()
    unlocked = db.user_accessible_courses(conn, user["id"]) if not user["is_admin"] else None
    for r in rows:
        r["locked"] = False if unlocked is None else (int(r["id"]) not in unlocked)
    return _ok({
        "courses": rows,
        "categories": categories,
        "unlocked_count": len(rows) if unlocked is None
                          else sum(1 for r in rows if not r["locked"]),
        "total": len(rows),
        "scope_all": unlocked is None or bool(db.user_course_scope(conn, user["id"])["all"]),
    })


@bp.get("/courses/<int:course_id>")
@course_access_required
def course_detail(course_id: int):
    conn = get_db()
    course = conn.execute("SELECT * FROM courses WHERE id = ?", (course_id,)).fetchone()
    if not course or not course["is_open"]:
        return _err("课程不存在", 404)
    files = conn.execute(
        "SELECT * FROM files WHERE kind = 'resource' AND course_id = ? ORDER BY id DESC",
        (course_id,)).fetchall()
    bundle = next((f for f in files if f["category"] == "打包"), None)
    files = [f for f in files if f["category"] != "打包"]
    videos = db.course_videos(conn, course_id)
    assignments = db.course_assignments(conn, course_id, api_user()["id"])
    return _ok({
        "course": dict(course),
        "files": [dict(f) for f in files],
        "bundle": dict(bundle) if bundle else None,
        "videos": [dict(v) for v in videos],
        "assignments": [dict(a) for a in assignments],
    })


# ---------------------------------------------------------------- 文件

@bp.get("/files")
@login_required
def file_list():
    """资料清单：登录即可查看（不再要求激活码）。"""
    conn = get_db()
    keyword = (request.args.get("q") or "").strip()
    course = (request.args.get("course") or "").strip()
    sql = ("SELECT f.*, u.username AS owner, c.title AS course_title "
           "FROM files f LEFT JOIN users u ON u.id = f.owner_id "
           "LEFT JOIN courses c ON c.id = f.course_id "
           "WHERE f.kind = 'resource'")
    params: list = []
    if keyword:
        sql += " AND (f.title LIKE ? OR f.description LIKE ? OR f.original_name LIKE ?)"
        params += [f"%{keyword}%"] * 3
    if course.isdigit():
        sql += " AND f.course_id = ?"
        params.append(int(course))
    elif course == "none":
        sql += " AND f.course_id IS NULL"
    sql += " ORDER BY f.id DESC"
    rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    tabs = [dict(r) for r in conn.execute(
        "SELECT c.id, c.title, c.icon, COUNT(f.id) AS n FROM courses c "
        "JOIN files f ON f.course_id = c.id AND f.kind = 'resource' "
        "WHERE c.is_open = 1 GROUP BY c.id, c.title, c.icon, c.sort_order "
        "ORDER BY c.sort_order, c.id").fetchall()]
    total = conn.execute("SELECT COUNT(*) c FROM files WHERE kind = 'resource'").fetchone()["c"]
    return _ok({"files": rows, "tabs": tabs, "total": total})


@bp.get("/videos/<int:video_id>/stream")
def video_stream(video_id: int):
    """在线播放课程视频。支持 Range（拖动进度条）。支持 ?token= 便于 video 组件直接播放。"""
    conn = get_db()
    row = conn.execute("SELECT * FROM videos WHERE id = ?", (video_id,)).fetchone()
    if not row:
        return _err("视频不存在", 404)
    user = api_user()
    if user is None:
        return _err("请先登录", 401)
    # 视频属于某门课 → 按该课程判解锁范围（不再是"有码就能看全部"）
    if not user["is_admin"] and not db.user_course_access(conn, user["id"], int(row["course_id"])):
        if not db.user_activated(conn, user["id"]):
            return _err("这门课程需先输入激活码解锁", 403)
        return _err("你的激活码不包含这门课程", 403)
    path = os.path.join(db.FILE_DIR, row["stored_name"])
    if not os.path.isfile(path):
        return _err("视频文件已失效", 404)
    mimetype = mimetypes.guess_type(row["stored_name"])[0] or "video/mp4"
    return send_file(path, mimetype=mimetype, conditional=True)


@bp.get("/files/<int:file_id>/download")
def file_download(file_id: int):
    conn = get_db()
    row = conn.execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone()
    if not row:
        return _err("文件不存在", 404)
    user = api_user()
    if row["kind"] in ("submission", "drive"):
        if user is None or (user["id"] != row["owner_id"] and not user["is_admin"]):
            return _err("无权下载", 403)
    else:
        if user is None:
            return _err("请先登录", 401)
        # 挂在课程下的资料算课程内容，按该课程判；公共资料登录即可下载
        if row["course_id"] and not user["is_admin"]:
            if not db.user_course_access(conn, user["id"], int(row["course_id"])):
                if not db.user_activated(conn, user["id"]):
                    return _err("这份资料属于课程内容，需先输入激活码", 403)
                return _err("这份资料属于你未解锁的课程", 403)
    path = os.path.join(db.FILE_DIR, row["stored_name"])
    if not os.path.isfile(path):
        return _err("文件已失效", 404)
    _ext = os.path.splitext(row["original_name"])[1].lower()
    if _ext in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"):
        return send_file(path)
    return send_file(path, as_attachment=True, download_name=row["original_name"])


def _save_upload(file_storage, prefix: str = ""):
    """保存上传文件，返回 (存储名, 原始名, 字节数)。"""
    original = os.path.basename(file_storage.filename or "file")
    ext = os.path.splitext(original)[1].lower()
    stored = f"{prefix}{secrets.token_hex(8)}{ext}"
    path = os.path.join(db.FILE_DIR, stored)
    file_storage.save(path)
    return stored, original, os.path.getsize(path)


# ---------------------------------------------------------------- 云盘

@bp.get("/drive")
@login_required
def drive():
    conn = get_db()
    user = api_user()
    files = conn.execute(
        "SELECT * FROM files WHERE kind = 'drive' AND owner_id = ? ORDER BY id DESC",
        (user["id"],)).fetchall()
    usage = db.drive_usage(conn, user["id"])
    quota = int(user["quota_mb"]) if user["quota_mb"] is not None else 200
    return _ok({
        "files": [dict(f) for f in files],
        "usage": usage,
        "quota": quota,
    })


@bp.post("/drive/upload")
@login_required
def drive_upload():
    user = api_user()
    conn = get_db()
    uploads = [f for f in request.files.getlist("file") if f and f.filename]
    if not uploads:
        return _err("请选择要上传的文件")
    quota = int(user["quota_mb"]) if user["quota_mb"] is not None else 200
    used = conn.execute(
        "SELECT COALESCE(SUM(size), 0) s FROM files WHERE kind = 'drive' AND owner_id = ?",
        (user["id"],)).fetchone()["s"]
    ok = 0
    skipped = 0
    for upload_file in uploads:
        stored, original, size = _save_upload(upload_file, prefix="dv_")
        if used + size > quota * 1024 * 1024:
            os.remove(os.path.join(db.FILE_DIR, stored))
            skipped += 1
        else:
            conn.execute(
                "INSERT INTO files (kind, title, description, stored_name, original_name, "
                "size, owner_id, created_at) VALUES ('drive', ?, '', ?, ?, ?, ?, ?)",
                (original, stored, original, size, user["id"], db.now()))
            used += size
            ok += 1
    conn.commit()
    msg = f"已上传 {ok} 个文件"
    if skipped:
        msg += f"，{skipped} 个因空间不足跳过"
    return _ok({"uploaded": ok, "skipped": skipped, "message": msg})


@bp.post("/drive/<int:file_id>/delete")
@login_required
def drive_delete(file_id: int):
    conn = get_db()
    user = api_user()
    row = conn.execute(
        "SELECT * FROM files WHERE id = ? AND kind = 'drive' AND owner_id = ?",
        (file_id, user["id"])).fetchone()
    if not row:
        return _err("文件不存在", 404)
    path = os.path.join(db.FILE_DIR, row["stored_name"])
    if os.path.isfile(path):
        os.remove(path)
    conn.execute("DELETE FROM files WHERE id = ?", (file_id,))
    conn.commit()
    return _ok({})


# ---------------------------------------------------------------- 社区

@bp.post("/community/upload")
@login_required
def community_upload():
    user = api_user()
    f = request.files.get("file")
    if not f or not f.filename:
        return _err("请选择文件")
    stored, original, size = _save_upload(f, prefix="pa_")
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO files (kind, title, description, stored_name, original_name, "
        "size, owner_id, created_at) VALUES ('post_attachment', ?, '', ?, ?, ?, ?, ?)",
        (original, stored, original, size, user["id"], db.now()))
    conn.commit()
    return _ok({"file_id": cur.lastrowid, "original_name": original, "size": size})


@bp.get("/community")
def community():
    conn = get_db()
    rows = conn.execute(
        "SELECT p.*, u.nickname, u.username, "
        "(SELECT COUNT(*) FROM replies r WHERE r.post_id = p.id) AS reply_count "
        "FROM posts p LEFT JOIN users u ON u.id = p.user_id "
        "ORDER BY p.is_top DESC, p.id DESC").fetchall()
    return _ok({"posts": [dict(r) for r in rows]})


@bp.get("/community/<int:post_id>")
def post_detail(post_id: int):
    conn = get_db()
    post = conn.execute(
        "SELECT p.*, u.nickname, u.username, u.id AS author_id FROM posts p "
        "LEFT JOIN users u ON u.id = p.user_id WHERE p.id = ?", (post_id,)).fetchone()
    if not post:
        return _err("帖子不存在", 404)
    conn.execute("UPDATE posts SET views = views + 1 WHERE id = ?", (post_id,))
    conn.commit()
    replies = conn.execute(
        "SELECT r.*, u.nickname, u.username FROM replies r LEFT JOIN users u ON u.id = r.user_id "
        "WHERE r.post_id = ? ORDER BY r.id", (post_id,)).fetchall()
    attachments = conn.execute(
        "SELECT f.* FROM files f JOIN post_attachments pa ON pa.file_id = f.id "
        "WHERE pa.post_id = ? ORDER BY pa.id", (post_id,)).fetchall()
    return _ok({"post": dict(post), "replies": [dict(r) for r in replies],
                "attachments": [dict(a) for a in attachments]})


@bp.post("/community")
@login_required
def post_new():
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    content = (data.get("content") or "").strip()
    if not title or not content:
        return _err("标题和内容都要填")
    conn = get_db()
    user = api_user()
    cur = conn.execute(
        "INSERT INTO posts (user_id, title, content, created_at) VALUES (?, ?, ?, ?)",
        (user["id"], title, content, db.now()))
    post_id = cur.lastrowid
    atts = data.get("attachments") or []
    if isinstance(atts, list):
        for fid in atts:
            if not isinstance(fid, int):
                continue
            row = conn.execute(
                "SELECT id FROM files WHERE id = ? AND kind = 'post_attachment' AND owner_id = ?",
                (fid, user["id"])).fetchone()
            if row:
                conn.execute(
                    "INSERT INTO post_attachments (post_id, file_id, created_at) VALUES (?, ?, ?)",
                    (post_id, fid, db.now()))
    conn.commit()
    return _ok({"post_id": post_id})


@bp.post("/community/<int:post_id>/reply")
@login_required
def post_reply(post_id: int):
    conn = get_db()
    post = conn.execute("SELECT id FROM posts WHERE id = ?", (post_id,)).fetchone()
    if not post:
        return _err("帖子不存在", 404)
    content = ((request.get_json(silent=True) or {}).get("content") or "").strip()
    if not content:
        return _err("回复内容不能为空")
    conn.execute(
        "INSERT INTO replies (post_id, user_id, content, created_at) VALUES (?, ?, ?, ?)",
        (post_id, api_user()["id"], content, db.now()))
    conn.commit()
    return _ok({"reply_id": None})


# ---------------------------------------------------------------- 挑战

@bp.get("/challenges")
def challenge_list():
    conn = get_db()
    rows = conn.execute(
        "SELECT id, title, summary, difficulty, deadline, is_open, sort_order, created_at "
        "FROM challenges WHERE is_open = 1 ORDER BY sort_order, id DESC").fetchall()
    return _ok({"challenges": [dict(r) for r in rows]})


@bp.get("/challenges/<int:challenge_id>")
def challenge_detail(challenge_id: int):
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM challenges WHERE id = ? AND is_open = 1", (challenge_id,)).fetchone()
    if not row:
        return _err("挑战不存在", 404)
    return _ok({"challenge": dict(row)})


# ---------------------------------------------------------------- 个人中心

@bp.get("/me")
@login_required
def me():
    conn = get_db()
    user = api_user()
    stats = db.study_stats(conn, user["id"])
    progress = conn.execute(
        "SELECT cp.*, c.title, c.icon, c.category FROM course_progress cp "
        "LEFT JOIN courses c ON c.id = cp.course_id WHERE cp.user_id = ? "
        "ORDER BY cp.updated_at DESC", (user["id"],)).fetchall()
    records = conn.execute(
        "SELECT r.*, ch.title, ch.difficulty, ch.id AS cid FROM challenge_records r "
        "LEFT JOIN challenges ch ON ch.id = r.challenge_id WHERE r.user_id = ? "
        "ORDER BY r.id DESC", (user["id"],)).fetchall()
    posts = conn.execute(
        "SELECT * FROM posts WHERE user_id = ? ORDER BY id DESC LIMIT 10", (user["id"],)).fetchall()

    done = sum(1 for p in progress if p["status"] == "done")
    passed = sum(1 for r in records if r["passed"])
    achievements = [
        {"name": "初次启程", "desc": "完成第一次访问学习", "got": stats["total"] >= 1},
        {"name": "坚持不懈", "desc": "连续学习 3 天", "got": stats["streak"] >= 3},
        {"name": "七日之约", "desc": "连续学习 7 天", "got": stats["streak"] >= 7},
        {"name": "课程达人", "desc": "完成 3 门课程", "got": done >= 3},
        {"name": "挑战者", "desc": "通过 1 个挑战", "got": passed >= 1},
        {"name": "闯关高手", "desc": "通过 5 个挑战", "got": passed >= 5},
    ]
    return _ok({
        "user": _user_dict(user),
        "stats": stats,
        "achievements": achievements,
        "progress": [dict(p) for p in progress],
        "records": [dict(r) for r in records],
        "posts": [dict(p) for p in posts],
        "done": done,
        "passed": passed,
    })


# ---------------------------------------------------------------- 改密码

@bp.post("/me/password")
@login_required
def change_password():
    """自助改密码：必须提供**原密码**，验过才允许改。

    站点当前是明文存储（管理员要求），但校验统一走 db.verify_password()，
    老账号的 PBKDF2 哈希同样能验过 —— 所以这个接口对两种存量都可用。

    请求：JSON 或表单
        { "old_password": "...", "new_password": "...", "confirm_password": "..." }
    返回：
        200 {"ok": true, "data": {"updated": true}}
        400 参数问题 / 403 原密码不对 / 401 未登录
    """
    conn = get_db()
    user = api_user()
    data = request.get_json(silent=True) or {}
    old = data.get("old_password") or request.form.get("old_password") or ""
    new = data.get("new_password") or request.form.get("new_password") or ""
    confirm = data.get("confirm_password") or request.form.get("confirm_password") or ""

    if not db.verify_password(old, user["password_hash"]):
        return _err("原密码不正确", 403)
    if len(new) < 6:
        return _err("新密码至少 6 位")
    if len(new) > 128:
        return _err("新密码太长了（最多 128 位）")
    if confirm and new != confirm:
        return _err("两次输入的新密码不一致")

    conn.execute("UPDATE users SET password_hash = ? WHERE id = ?",
                 (db.hash_password(new), user["id"]))
    conn.commit()

    # 回读校验：写进去的必须能验回来，否则宁可报错也不要留下一个登不进去的账号
    back = conn.execute("SELECT password_hash FROM users WHERE id = ?",
                        (user["id"],)).fetchone()["password_hash"]
    if not db.verify_password(new, back):
        return _err("密码写入后校验失败，请重试", 500)
    return _ok({"updated": True})


# ---------------------------------------------------------------- 通用

@bp.get("/ping")
def ping():
    return _ok({"time": db.now()})


# ---------------------------------------------------------------- 找回密码

@bp.post("/password/forgot")
def password_forgot():
    """忘记密码（无需登录）。

    一个接口两种动作，靠 action 区分，App 端因此不必维护跨请求状态：

        action = "find"   找账号 → {"found": bool, "answer_type": "student_no"|"nickname"|"",
                                   "account_hint": "小测"}
        action = "reset"  改密码 → 需 identifier + answer + old_password + new_password
                                  + confirm_password

    与网页端 /forgot 走的是同一套规则（identity 核对 + **必须验原密码**），
    只是网页端用 session 串两步，App 端靠客户端自己带上一步的 identifier。

    为什么 reset 必须带原密码：站点约定任何改密动作都要过原密码这道闸，
    这里不做"绕过原密码"的旁路。真忘了原密码的用户，只能联系管理员重置。
    """
    from views_auth import _find_account, _identity_matches, _identity_question

    data = request.get_json(silent=True) or {}
    action = (data.get("action") or "find").strip().lower()
    identifier = (data.get("identifier") or "").strip()

    if not identifier:
        return _err("请输入手机号、用户名或学号")

    conn = get_db()

    # ---- 找账号 ----
    if action == "find":
        wait = throttle.forgot_gate(identifier)
        if wait:
            return _err(f"尝试太频繁了，请等 {wait} 秒后再试", 429)
        row = _find_account(identifier)
        if row is None:
            return _err("没有找到这个账号，请检查手机号 / 用户名 / 学号是否填对", 404)
        if not row["is_active"]:
            return _err("该账号已被停用，请联系管理员", 403)
        # 只回一个能帮用户确认"是我的账号"的展示名，不回手机号等敏感字段
        return _ok({
            "found": True,
            "answer_type": _identity_question(row),
            "account_hint": str(row["nickname"] or row["username"] or ""),
        })

    # ---- 重置密码 ----
    if action != "reset":
        return _err("不支持的操作")

    row = _find_account(identifier)
    if row is None:
        # 不区分「账号不存在」与「核对失败」，避免被用来枚举账号
        return _err("账号或身份信息不正确", 403)
    wait = throttle.forgot_gate("uid%d" % row["id"])
    if wait:
        return _err(f"尝试太频繁了，请等 {wait} 秒后再试", 429)

    answer = data.get("answer") or ""
    old = data.get("old_password") or ""
    new = data.get("new_password") or ""
    confirm = data.get("confirm_password") or ""

    if not _identity_matches(row, answer):
        return _err("学号 / 昵称核对不通过，请再试一次", 403)
    if not db.verify_password(old, row["password_hash"]):
        return _err("原密码不正确", 403)
    if len(new) < 6:
        return _err("新密码至少 6 位")
    if len(new) > 128:
        return _err("新密码太长了（最多 128 位）")
    if confirm and new != confirm:
        return _err("两次输入的新密码不一致")
    if new == old:
        return _err("新密码不能和原密码相同")

    conn.execute("UPDATE users SET password_hash = ? WHERE id = ?",
                 (db.hash_password(new), row["id"]))
    conn.commit()
    # 回读校验：写进去的必须能验回来，否则宁可报错也别留个登不进的账号
    back = conn.execute("SELECT password_hash FROM users WHERE id = ?",
                        (row["id"],)).fetchone()["password_hash"]
    if not db.verify_password(new, back):
        return _err("密码写入后校验失败，请重试", 500)
    throttle.forgot_ok("uid%d" % row["id"])
    return _ok({"updated": True})


# ---------------------------------------------------------------- 公告
@bp.get("/announcements/latest")
@login_required
def announcement_latest():
    """当前要弹给用户的公告（登录后客户端调一次）。

    返回 {"announcement": {...}} 或 {"announcement": null}。
    客户端应把 (id, updated_at) 记成「已读过」：值没变就不再弹，
    管理员改了内容 → updated_at 变了 → 会再弹一次。
    """
    row = db.announcement_latest(get_db())
    if row is None:
        return _ok({"announcement": None})
    return _ok({"announcement": {
        "id": row["id"],
        "title": row["title"],
        "body": row["body"],
        "level": db.normalize_level(row["level"]),
        "link_text": row["link_text"] or "",
        "link_url": row["link_url"] or "",
        "updated_at": row["updated_at"] or row["created_at"] or "",
    }})


# ---------------------------------------------------------------- 报到（report）

@bp.get("/report")
@login_required
def report_get():
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM reports WHERE user_id = ? ORDER BY id DESC LIMIT 1",
        (api_user()["id"],)).fetchone()
    return _ok({"report": dict(row) if row else None})


@bp.post("/report")
@login_required
def report_submit():
    conn = get_db()
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    college = "人工智能学院"  # 学院固定，忽略用户输入
    major_class = (data.get("major_class") or "").strip()
    joined_qq = 1 if data.get("joined_qq") in ("1", "yes", "on", True) else 0

    if len(name) < 2:
        return _err("请填写真实姓名（至少 2 个字）")
    if len(college) < 2:
        return _err("请填写学院")
    if len(major_class) < 2:
        return _err("请填写专业班级")

    existing = conn.execute(
        "SELECT * FROM reports WHERE user_id = ? ORDER BY id DESC LIMIT 1",
        (api_user()["id"],)).fetchone()
    if existing and existing["status"] == "pending":
        return _err("你已提交过报到申请，正在审核中")
    if existing and existing["status"] == "approved":
        return _err("你的报到已通过，无需重复提交")

    cur = conn.execute(
        "INSERT INTO reports (user_id, name, college, major_class, joined_qq, status, created_at) "
        "VALUES (?, ?, ?, ?, ?, 'pending', ?)",
        (api_user()["id"], name, college, major_class, joined_qq, db.now()))
    conn.commit()
    row = conn.execute("SELECT * FROM reports WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _ok({"report": dict(row)})



# ---------------------------------------------------------------- App 版本更新
@bp.get("/app/version")
def app_version():
    """返回指定渠道最新可更新的版本。无需登录，供各端启动时检查更新。

    渠道参数（platform）：
        android（默认）— 安卓 APK，沿用 is_latest 标记，老客户端不带参数即可继续工作
        windows        — Windows 桌面客户端安装包（exe）
        ios            — iOS 安装链接（TestFlight / App Store / 企业分发）

    可选参数 version_code=当前客户端版本号，传入后会额外给出 need_update，
    不传则兼容老逻辑（只回 has_update + 最新版本号，由客户端自行比较）。
    """
    conn = get_db()
    platform = db.normalize_platform(request.args.get("platform") or "android")
    row = db.app_latest(conn, platform)
    if row is None:
        return _ok({
            "platform": platform,
            "version_code": 0,
            "version_name": "",
            "has_update": False,
            "need_update": False,
        })

    keys = row.keys()
    need_update = True
    current = (request.args.get("version_code") or "").strip()
    if current.isdigit():
        need_update = int(current) < int(row["version_code"])

    return _ok({
        "platform": platform,
        "version_code": row["version_code"],
        "version_name": row["version_name"],
        "release_notes": row["release_notes"],
        "download_url": row["download_url"],
        "file_size": row["file_size"],
        "file_name": (row["file_name"] if "file_name" in keys else "") or "",
        "sha512": ((row["sha512"] if "sha512" in keys else "") or "").strip(),
        "published_at": row["created_at"],
        "has_update": True,
        "need_update": need_update,
    })


# ---------------------------------------------------------------- 扫码登录
@bp.get("/scan/create")
def scan_create():
    import datetime
    token = secrets.token_urlsafe(32)
    exp = (datetime.datetime.now() + datetime.timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
    conn = get_db()
    conn.execute(
        "INSERT INTO scan_logins (token, status, created_at, expires_at) VALUES (?, 'pending', ?, ?)",
        (token, db.now(), exp),
    )
    conn.commit()
    return _ok({"token": token})


@bp.post("/scan/confirm")
@login_required
def scan_confirm():
    data = request.get_json(silent=True) or {}
    token = (data.get("token") or "").strip()
    if not token:
        return _err("参数错误")
    conn = get_db()
    row = conn.execute("SELECT * FROM scan_logins WHERE token = ?", (token,)).fetchone()
    if row is None:
        return _err("二维码已失效，请刷新重试")
    if row["expires_at"] and row["expires_at"] < db.now():
        return _err("二维码已过期，请刷新重试")
    user = api_user()
    conn.execute("UPDATE scan_logins SET status='confirmed', user_id=? WHERE token=?", (user["id"], token))
    conn.commit()
    return _ok({"confirmed": True})


# ---------------------------------------------------------------- 视频字幕（App / 小程序）
# 由 patch_subtitle.py 追加
import subtitle as subtitle_mod


@bp.post("/account/cancel")
@login_required
def account_cancel():
    """App 端自助注销账号。做法与网页端 /me/cancel 一致：
    身份信息匿名化 + is_active=0（token 靠 is_active 校验，下一个请求即失效）。"""
    data = request.get_json(silent=True) or {}
    password = data.get("password") or ""
    user = api_user()
    if not password or not db.verify_password(password, user["password_hash"]):
        return _err("密码不正确", 403)
    if user["is_admin"]:
        return _err("管理员账号不能自助注销，请让其他管理员处理", 403)
    conn = get_db()
    anon = f"deleted-{user['id']}-{db.now()[:10].replace('-', '')}"
    conn.execute(
        "UPDATE users SET username = ?, phone = ?, student_no = '', nickname = '已注销用户', "
        "password_hash = ?, is_active = 0, quota_mb = 0 WHERE id = ?",
        (anon, anon, db.hash_password(secrets.token_urlsafe(24)), user["id"]))
    conn.commit()
    return _ok({})


@bp.get("/videos/<int:video_id>/subtitle")
def video_subtitle(video_id: int):
    """课程视频字幕（WebVTT）。支持 ?token= 方便播放器直接拼 URL 加载。"""
    conn = get_db()
    user = api_user()
    if user is None:
        return _err("请先登录", 401)
    row = conn.execute("SELECT course_id, subtitle FROM videos WHERE id = ?", (video_id,)).fetchone()
    # 字幕跟随视频所属课程：不是"有码就能看全部"
    if (not user["is_admin"] and row and row["course_id"] is not None
            and not db.user_course_access(conn, user["id"], int(row["course_id"]))):
        return _err("这门课程需先输入激活码解锁", 403)
    if not row or not row["subtitle"]:
        return _err("该视频暂无字幕", 404)
    path = os.path.join(db.FILE_DIR, row["subtitle"])
    if not os.path.isfile(path):
        return _err("字幕文件已失效", 404)
    return subtitle_mod.vtt_response(path)


# ---------------------------------------------------------------- App 内 WebView 换 session
# 由 patch_weblogin.py 追加
from core import login_user as _login_user
from flask import redirect as _redirect


@bp.get("/web-login")
def web_login():
    """拿 API token 换一张网页 session 票，给 App 内嵌的 WebView 用。

    WebView 里没有登录 cookie，直接开课件页会被弹回登录页。
    这里校验 token 后种上 session，再跳到目标页（只允许站内地址）。
    """
    user = api_user()
    if user is None:
        return _err("未登录或登录已过期", 401)
    nxt = request.args.get("next") or "/"
    if not nxt.startswith("/") or nxt.startswith("//"):
        nxt = "/"                      # 防开放重定向
    _login_user(user)
    return _redirect(nxt)
