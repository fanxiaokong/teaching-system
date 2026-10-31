"""前台：首页、课程、挑战、社区、文件下载/上传、用户中心。"""
from __future__ import annotations

import json
import math
import os
import mimetypes
import secrets
import shutil
import struct
import subprocess
import sys
import time
import zipfile

from flask import (Blueprint, abort, current_app, flash, jsonify, redirect, render_template,
                   request, send_file, send_from_directory, session, url_for)

import db
from core import (admin_required, attachment_response, course_access_required, current_user,
                  get_db, human_size, login_required, logout_user, safe_ascii_name)

bp = Blueprint("main", __name__)

_human_size = human_size          # 供 views_admin 复用

ALLOWED_UPLOAD_EXT = {
    ".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".txt", ".md", ".csv",
    ".zip", ".rar", ".7z", ".tar", ".gz", ".png", ".jpg", ".jpeg", ".gif", ".webp",
    ".mp4", ".mp3", ".pcap", ".pcapng", ".cfg", ".conf", ".py", ".js", ".java", ".c",
    ".cpp", ".go", ".sh", ".sql", ".json", ".xml", ".html",
}

# 课程视频：浏览器能直接在线播放的格式。mp4(H.264) 兼容性最好。
VIDEO_EXT = {".mp4", ".m4v", ".webm", ".mov", ".ogg", ".ogv"}


# ---------------------------------------------------------------- 工具

def save_upload(file_storage, prefix: str = ""):
    """保存上传文件，返回 (存储名, 原始名, 字节数)。"""
    original = os.path.basename(file_storage.filename or "file")
    ext = os.path.splitext(original)[1].lower()
    stored = f"{prefix}{secrets.token_hex(8)}{ext}"
    path = os.path.join(db.FILE_DIR, stored)
    file_storage.save(path)
    return stored, original, os.path.getsize(path)


def probe_media_duration(path: str) -> float | None:
    """纯 Python 读取视频时长（秒），不依赖 ffmpeg。

    只解析 mp4/m4v 的 moov→mvhd 盒子（timescale + duration）。
    服务器没装 ffmpeg，这是唯一能自动算时长的办法；读不到返回 None。
    """
    ext = os.path.splitext(path)[1].lower()
    if ext not in (".mp4", ".m4v", ".mov"):
        return None
    try:
        with open(path, "rb") as f:
            data = f.read()
        i = data.find(b"moov")
        if i < 0:
            return None
        j = data.find(b"mvhd", i, i + 200)
        if j < 0:
            return None
        ver = data[j + 4]
        if ver == 0:
            ts = struct.unpack(">I", data[j + 16:j + 20])[0]
            dur = struct.unpack(">I", data[j + 20:j + 24])[0]
        elif ver == 1:
            ts = struct.unpack(">I", data[j + 24:j + 28])[0]
            dur = struct.unpack(">Q", data[j + 28:j + 36])[0]
        else:
            return None
        return round(dur / ts) if ts else None
    except Exception:
        return None


def format_duration(seconds) -> str:
    """把秒数格式化成时长字符串。≥1 小时用 H:MM:SS，否则 M:SS。None/空→''。"""
    if seconds is None:
        return ""
    try:
        s = int(seconds)
    except (TypeError, ValueError):
        return ""
    if s >= 3600:
        return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"
    return f"{s // 60}:{s % 60:02d}"


def record_submission(conn, user, assignment, upload_file) -> str | None:
    """把一次作业提交写进 files 表（kind=submission，靠 assignment_id 关联）。

    成功返回 None，失败返回给用户看的错误提示。
    课程页的提交入口和「作业文件传输」页共用这一份逻辑。
    """
    if not upload_file or not upload_file.filename:
        return "请先选择要提交的文件"
    ext = os.path.splitext(upload_file.filename)[1].lower()
    if ext and ext not in ALLOWED_UPLOAD_EXT:
        return f"暂不支持 {ext} 类型的文件"
    stored, original, size = save_upload(upload_file, prefix="hw_")
    conn.execute(
        "INSERT INTO files (kind, title, description, stored_name, original_name, size, "
        "course_id, assignment_id, owner_id, created_at) "
        "VALUES ('submission', ?, '', ?, ?, ?, ?, ?, ?, ?)",
        (assignment["title"], stored, original, size,
         assignment["course_id"], assignment["id"], user["id"], db.now()))
    conn.commit()
    return None


def _safe_extract(zip_path: str, dest: str) -> None:
    """解压时防目录穿越。"""
    dest_real = os.path.realpath(dest)
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.namelist():
            if member.endswith("/"):
                continue
            target = os.path.realpath(os.path.join(dest, member))
            if target != dest_real and not target.startswith(dest_real + os.sep):
                continue
            zf.extract(member, dest)


def _find_entry(folder: str) -> str:
    """在解压后的目录里找入口 HTML：优先 index.html，其次任意 html。"""
    candidates = []
    for root, _dirs, files in os.walk(folder):
        for name in files:
            if name.lower().endswith((".html", ".htm")):
                rel = os.path.relpath(os.path.join(root, name), folder).replace(os.sep, "/")
                candidates.append(rel)
    if not candidates:
        return ""
    for rel in candidates:
        if os.path.basename(rel).lower() in ("index.html", "index.htm"):
            return rel
    return sorted(candidates, key=lambda p: (p.count("/"), len(p)))[0]


# ---------------------------------------------------------------- 首页

@bp.get("/")
def home():
    conn = get_db()
    settings = db.all_settings(conn)
    # 磁贴按「分组」分成若干块显示。用 Python 分组而不是靠 SQL 的连续分组，
    # 这样同一组的磁贴排序号中间夹了别的组也不会被拆成两块。
    bucket: dict[str, list] = {}
    first_order: dict[str, int] = {}
    for row in conn.execute(
        "SELECT * FROM nav_links WHERE group_name <> ? ORDER BY sort_order, id",
        (db.FRIENDLY_GROUP,),
    ):
        name = row["group_name"] or "其他"
        bucket.setdefault(name, []).append(row)
        first_order[name] = min(first_order.get(name, row["sort_order"]), row["sort_order"])
    tile_groups = [
        {"name": name, "links": bucket[name]}
        for name in sorted(bucket, key=lambda n: (first_order[n], n))
    ]
    return render_template(
        "home.html",
        stats=db.join_stats(conn),
        tile_groups=tile_groups,
        join_open=settings.get("join_open", "1") == "1",
        points=parse_points(settings.get("join_points", "")),
    )


def parse_points(text: str) -> list[dict]:
    """把设置里的多行文本解析成卖点卡片。

    每行一条，格式 `标题｜说明`（竖线中英文都认）；只写标题也可以。
    """
    out = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        for sep in ("｜", "|"):
            if sep in line:
                title, desc = line.split(sep, 1)
                break
        else:
            title, desc = line, ""
        title = title.strip()
        if title:
            out.append({"title": title, "desc": desc.strip()})
    return out


# ---------------------------------------------------------------- 加入我们

@bp.route("/join", methods=["GET", "POST"])
def join():
    conn = get_db()
    join_open = db.get_setting(conn, "join_open", "1") == "1"
    qrcode = db.get_setting(conn, "group_qrcode", "")

    if request.method == "POST":
        if not join_open:
            flash("报名通道已关闭，请联系实验室管理员。")
            return redirect(url_for("main.join"))

        name = (request.form.get("name") or "").strip()
        college = "人工智能学院"  # 学院固定，忽略用户输入
        contact = db.normalize_contact(request.form.get("contact"))
        wants_group = 1 if request.form.get("join_group") in ("1", "yes", "on", "是") else 0
        note = (request.form.get("note") or "").strip()[:200]

        errors = _validate_join(name, college, contact)
        if errors:
            for msg in errors:
                flash(msg)
            return render_template("join.html", join_open=join_open, form=request.form,
                                   qrcode=qrcode)

        existing = conn.execute(
            "SELECT * FROM join_requests WHERE contact = ? ORDER BY id DESC LIMIT 1",
            (contact,)).fetchone()
        if existing:
            return render_template("join_ok.html", duplicate=True, name=existing["name"],
                                   request_no=existing["id"], wants_group=existing["join_group"],
                                   created_at=existing["created_at"], qrcode=qrcode)

        cursor = conn.execute(
            "INSERT INTO join_requests (name, college, contact, join_group, note, created_at, ip) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (name, college, contact, wants_group, note, db.now(),
             request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0].strip()),
        )
        conn.commit()
        return render_template("join_ok.html", duplicate=False, name=name,
                               request_no=cursor.lastrowid, wants_group=wants_group,
                               created_at=db.now(), qrcode=qrcode)

    return render_template("join.html", join_open=join_open, form=None, qrcode=qrcode)


def _validate_join(name: str, college: str, contact: str) -> list[str]:
    """返回错误提示列表，空列表代表通过。"""
    errors = []
    if len(name) < 2:
        errors.append("请填写真实姓名（至少 2 个字）")
    elif len(name) > 20:
        errors.append("姓名太长了，请只填姓名")
    if len(college) < 2:
        errors.append("请填写学院")
    elif len(college) > 40:
        errors.append("学院名称太长了")
    if len(contact) < 5:
        errors.append("请填写有效的联系方式（手机号 / 微信 / QQ）")
    elif len(contact) > 60:
        errors.append("联系方式太长了")
    return errors


@bp.get("/index")
def index_entry():
    """管理员入口：your-server.example.com/index"""
    user = current_user()
    if user and user["is_admin"]:
        return redirect(url_for("admin.dashboard"))
    return redirect(url_for("auth.login", next=url_for("admin.dashboard")))


@bp.get("/uploads/<path:name>")
def uploaded_file(name: str):
    """站点图片（目前是官方群二维码）。send_from_directory 自带目录穿越防护。"""
    return send_from_directory(db.UPLOAD_DIR, name)


# ---------------------------------------------------------------- 激活码

@bp.route("/activate", methods=["GET", "POST"])
@login_required
def activate():
    """成员激活页：输入管理员发放的激活码，解锁对应的课程。

    允许**累加**：用过码之后仍然可以再输一个，把权限叠加上去
    （比如先用「网络基础」标签的码，再用某门单独课的码）。
    """
    conn = get_db()
    user = current_user()
    if user["is_admin"]:
        flash("管理员账号无需激活，可直接访问全部课程")
        return redirect(url_for("main.course_list"))

    if request.method == "POST":
        code_input = (request.form.get("code") or "").strip()
        error = db.redeem_code(conn, code_input, user["id"])
        if error is None:
            scope = db.user_course_scope(conn, user["id"])
            if scope["all"]:
                flash("激活成功！全部课程已向你开放 🎉")
            else:
                flash("激活成功！你现在可以访问 %d 门课程 🎉"
                      % db.user_course_count(conn, user["id"]))
            return redirect(url_for("main.course_list"))
        # 失败时把当前进度一并回显，方便用户判断自己还缺哪部分权限
        return render_template("activate.html", error=error, code=code_input,
                               scoped=_activation_view(conn, user))

    return render_template("activate.html", error=None, code="",
                           scoped=_activation_view(conn, user))


def _activation_view(conn, user) -> dict:
    """激活页要展示的状态：已解锁多少门课 / 是否全部 / 自己用过的码。"""
    scope = db.user_course_scope(conn, user["id"])
    total = conn.execute("SELECT COUNT(*) c FROM courses WHERE is_open = 1").fetchone()["c"]
    mine = conn.execute(
        "SELECT code, scope_kind, scope_categories, scope_courses, used_at "
        "FROM activation_codes WHERE used_by = ? ORDER BY used_at, id", (user["id"],)).fetchall()
    my_codes = [{"code": r["code"], "label": db.code_scope_label(r),
                 "used_at": r["used_at"]} for r in mine]
    return {
        "all": scope["all"],
        "unlocked": total if scope["all"] else len(db.user_accessible_courses(conn, user["id"])),
        "total": total,
        "codes": my_codes,
        "has_any": bool(my_codes),
    }


# ---------------------------------------------------------------- 课程

@bp.get("/courses")
@login_required
def course_list():
    """课程列表：**全部课程都显示**，但没解锁的带🔒标记。

    这里刻意不做 activation 门禁 —— 让学生看得到"有哪些课"，
    点进去时才由 course_access_required 拦住并引导激活。
    """
    conn = get_db()
    keyword = (request.args.get("q") or "").strip()
    category = (request.args.get("category") or "").strip()
    # 每个课程是一个独立的资料入口：顺带查出各自的资料数 / 视频数 / 作业数
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
    rows = conn.execute(sql, params).fetchall()
    categories = [r["category"] for r in conn.execute(
        "SELECT DISTINCT category FROM courses WHERE category <> '' ORDER BY category").fetchall()]
    total_count = conn.execute(
        "SELECT COUNT(*) c FROM courses WHERE is_open = 1").fetchone()["c"]
    cat_counts = {r["category"]: r["c"] for r in conn.execute(
        "SELECT category, COUNT(*) c FROM courses WHERE is_open = 1 AND category <> '' GROUP BY category").fetchall()}

    # 一次算出有权限的课程集合，渲染时给没权限的加锁标记
    user = current_user()
    unlocked = None                      # None = 不显示锁（未登录也标锁更清楚，所以下面统一算）
    if user and user["is_admin"]:
        unlocked = {int(r["id"]) for r in rows}
    elif user:
        unlocked = db.user_accessible_courses(conn, user["id"])
    else:
        unlocked = set()                 # 未登录：全部视为未解锁

    progress = {}
    if user:
        progress = {r["course_id"]: r for r in conn.execute(
            "SELECT * FROM course_progress WHERE user_id = ?", (user["id"],)).fetchall()}
    unlocked_count = len(unlocked & {int(r["id"]) for r in rows})
    return render_template("course_list.html", rows=rows, categories=categories,
                           keyword=keyword, category=category, progress=progress,
                           total_count=total_count, cat_counts=cat_counts,
                           unlocked=unlocked, unlocked_count=unlocked_count)


@bp.get("/courses/<int:course_id>")
@course_access_required
def course_detail(course_id: int):
    conn = get_db()
    course = conn.execute("SELECT * FROM courses WHERE id = ?", (course_id,)).fetchone()
    if not course or not course["is_open"]:
        abort(404)
    user = current_user()
    progress = None
    if user:
        progress = conn.execute(
            "SELECT * FROM course_progress WHERE user_id = ? AND course_id = ?",
            (user["id"], course_id)).fetchone()
    files = conn.execute(
        "SELECT * FROM files WHERE kind = 'resource' AND course_id = ? ORDER BY id DESC",
        (course_id,)).fetchall()
    # 分类为「打包」的那一条是整包下载，单独提出来放在资料区最上方
    bundle = next((f for f in files if f["category"] == "打包"), None)
    files = [f for f in files if f["category"] != "打包"]
    videos = db.course_videos(conn, course_id)
    # 作业区放在课程页最下面
    assignments = db.course_assignments(conn, course_id, user["id"] if user else None)
    return render_template("course_detail.html", course=course, progress=progress, files=files,
                           bundle=bundle, videos=videos, assignments=assignments)


@bp.get("/videos/<int:video_id>/stream")
@course_access_required
def video_stream(video_id: int):
    """在线播放课程视频。send_file 默认支持 Range，浏览器拖动进度条就能跳。"""
    conn = get_db()
    row = conn.execute("SELECT * FROM videos WHERE id = ?", (video_id,)).fetchone()
    if not row:
        abort(404)
    path = os.path.join(db.FILE_DIR, row["stored_name"])
    if not os.path.isfile(path):
        abort(404)
    mimetype = mimetypes.guess_type(row["stored_name"])[0] or "video/mp4"
    return send_file(path, mimetype=mimetype, conditional=True)


@bp.post("/courses/<int:course_id>/assignments/<int:assignment_id>/submit")
@login_required
@course_access_required
def assignment_submit(course_id: int, assignment_id: int):
    """学生提交课程作业。提交件存进 files 表（kind=submission），靠 assignment_id 关联。"""
    conn = get_db()
    user = current_user()
    back = url_for("main.course_detail", course_id=course_id) + "#homework"

    item = conn.execute("SELECT * FROM assignments WHERE id = ? AND course_id = ?",
                        (assignment_id, course_id)).fetchone()
    if not item:
        abort(404)
    if not item["is_open"]:
        flash("这份作业已经停止收交了")
        return redirect(back)

    files = [f for f in request.files.getlist("file") if f and f.filename]
    if not files:
        flash("请先选择要提交的文件")
    else:
        errs = []
        for f in files:
            e = record_submission(conn, user, item, f)
            if e:
                errs.append(e)
        if errs:
            flash(errs[0])
        else:
            flash(f"「{item['title']}」提交成功，共 {len(files)} 个文件")
    return redirect(back)


@bp.route("/courses/<int:course_id>/progress", methods=["POST"])
@login_required
@course_access_required
def course_progress(course_id: int):
    conn = get_db()
    user = current_user()
    try:
        percent = max(0, min(100, int(request.form.get("percent") or 0)))
    except ValueError:
        percent = 0
    status = "done" if percent >= 100 else "learning"
    conn.execute(
        "INSERT INTO course_progress (user_id, course_id, percent, status, updated_at) "
        "VALUES (?, ?, ?, ?, ?) ON CONFLICT(user_id, course_id) DO UPDATE SET "
        "percent = excluded.percent, status = excluded.status, updated_at = excluded.updated_at",
        (user["id"], course_id, percent, status, db.now()))
    conn.commit()
    flash("进度已更新" + ("，这门课标记为已完成 🎉" if status == "done" else ""))
    return redirect(url_for("main.course_detail", course_id=course_id))


@bp.get("/courses/<int:course_id>/site/")
@bp.get("/courses/<int:course_id>/site/<path:subpath>")
@course_access_required
def course_site(course_id: int, subpath: str = ""):
    """上传的课程包（index.html 及其资源）在这里对外提供。"""
    conn = get_db()
    course = conn.execute("SELECT * FROM courses WHERE id = ?", (course_id,)).fetchone()
    if not course or course["source"] != "html":
        abort(404)
    folder = os.path.join(db.COURSE_DIR, str(course_id))
    target = subpath or course["entry_path"] or "index.html"
    if not os.path.isfile(os.path.join(folder, target)):
        abort(404)
    return send_from_directory(folder, target)


# ---------------------------------------------------------------- 挑战

def _parse_elapsed(value) -> int:
    """把前端传的毫秒数字符串安全地转成非负整数。"""
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _gen_invite(conn) -> str:
    """生成 6 位不重复的邀请码（去掉易混淆字符）。"""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    while True:
        code = "".join(secrets.choice(alphabet) for _ in range(6))
        if not conn.execute(
                "SELECT 1 FROM challenge_matches WHERE invite_code = ?", (code,)).fetchone():
            return code


def _record_finish(conn, match_id: int, user_id: int, elapsed_ms: int) -> None:
    """比赛房间里标记某人完成；双方都完成则关闭房间。"""
    m = conn.execute("SELECT * FROM challenge_matches WHERE id = ?", (match_id,)).fetchone()
    if not m:
        return
    if m["host_id"] == user_id:
        conn.execute(
            "UPDATE challenge_matches SET host_elapsed_ms = ?, host_finished_at = ? WHERE id = ?",
            (elapsed_ms, db.now(), match_id))
    elif m["guest_id"] == user_id:
        conn.execute(
            "UPDATE challenge_matches SET guest_elapsed_ms = ?, guest_finished_at = ? WHERE id = ?",
            (elapsed_ms, db.now(), match_id))
    m = conn.execute("SELECT * FROM challenge_matches WHERE id = ?", (match_id,)).fetchone()
    if m["host_finished_at"] and m["guest_finished_at"]:
        conn.execute("UPDATE challenge_matches SET status = 'done' WHERE id = ?", (match_id,))


def _active_match(conn, challenge_id: int, user_id: int):
    return conn.execute(
        "SELECT * FROM challenge_matches WHERE challenge_id = ? AND status != 'done' "
        "AND (host_id = ? OR guest_id = ?) ORDER BY id DESC LIMIT 1",
        (challenge_id, user_id, user_id)).fetchone()


@bp.get("/challenges")
def challenge_list():
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM challenges WHERE is_open = 1 ORDER BY sort_order, id DESC").fetchall()
    records = {}
    user = current_user()
    if user:
        records = {r["challenge_id"]: r for r in conn.execute(
            "SELECT * FROM challenge_records WHERE user_id = ? ORDER BY id DESC",
            (user["id"],)).fetchall()}
    return render_template("challenge_list.html", rows=rows, records=records)


@bp.get("/challenges/<int:challenge_id>")
def challenge_detail(challenge_id: int):
    conn = get_db()
    challenge = conn.execute("SELECT * FROM challenges WHERE id = ?", (challenge_id,)).fetchone()
    if not challenge or not challenge["is_open"]:
        abort(404)
    user = current_user()
    records = []
    match = None
    opponent = None
    if user:
        records = conn.execute(
            "SELECT r.*, f.original_name, f.id AS file_id FROM challenge_records r "
            "LEFT JOIN files f ON f.id = r.file_id "
            "WHERE r.user_id = ? AND r.challenge_id = ? ORDER BY r.id DESC",
            (user["id"], challenge_id)).fetchall()
        match = _active_match(conn, challenge_id, user["id"])
        if match:
            other_id = match["guest_id"] if match["host_id"] == user["id"] else match["host_id"]
            opponent = conn.execute(
                "SELECT id, username, nickname FROM users WHERE id = ?",
                (other_id,)).fetchone() if other_id else None
    all_challenges = conn.execute(
        "SELECT id, title, difficulty FROM challenges WHERE is_open = 1 "
        "ORDER BY sort_order, id DESC").fetchall()
    return render_template("challenge_detail.html", challenge=challenge, records=records,
                           all_challenges=all_challenges, match=match, opponent=opponent,
                           cur_id=challenge_id)


@bp.post("/challenges/<int:challenge_id>/submit")
@login_required
def challenge_submit(challenge_id: int):
    conn = get_db()
    user = current_user()
    challenge = conn.execute("SELECT * FROM challenges WHERE id = ?", (challenge_id,)).fetchone()
    if not challenge:
        abort(404)

    note = (request.form.get("note") or "").strip()
    elapsed_ms = _parse_elapsed(request.form.get("elapsed_ms"))
    file_id = None
    uploads = [f for f in request.files.getlist("file") if f and f.filename]
    for upload in uploads:
        stored, original, size = save_upload(upload, prefix="hw_")
        cur = conn.execute(
            "INSERT INTO files (kind, title, description, stored_name, original_name, size, "
            "challenge_id, owner_id, created_at) VALUES ('submission', ?, ?, ?, ?, ?, ?, ?, ?)",
            (f"{user['username']} 的提交 · {challenge['title']}", note, stored, original, size,
             challenge_id, user["id"], db.now()))
        if file_id is None:
            file_id = cur.lastrowid
    if not note and file_id is None:
        flash("请填写说明或上传文件后再提交")
        return redirect(url_for("main.challenge_detail", challenge_id=challenge_id))

    conn.execute(
        "INSERT INTO challenge_records (user_id, challenge_id, passed, note, file_id, elapsed_ms, "
        "created_at) VALUES (?, ?, 0, ?, ?, ?, ?)",
        (user["id"], challenge_id, note, file_id, elapsed_ms, db.now()))
    conn.commit()
    # 若在比赛房间里，顺带记录完成用时
    m = _active_match(conn, challenge_id, user["id"])
    if m:
        _record_finish(conn, m["id"], user["id"], elapsed_ms)
        conn.commit()
    flash("提交成功，等待管理员批阅")
    return redirect(url_for("main.challenge_detail", challenge_id=challenge_id))


# ---------------------------------------------------------------- 挑战：联机比赛

@bp.post("/challenges/<int:challenge_id>/match/create")
@login_required
def match_create(challenge_id: int):
    conn = get_db()
    user = current_user()
    challenge = conn.execute("SELECT * FROM challenges WHERE id = ?", (challenge_id,)).fetchone()
    if not challenge:
        abort(404)
    existing = conn.execute(
        "SELECT * FROM challenge_matches WHERE challenge_id = ? AND status != 'done' AND host_id = ? "
        "ORDER BY id DESC LIMIT 1", (challenge_id, user["id"])).fetchone()
    if not existing:
        code = _gen_invite(conn)
        conn.execute(
            "INSERT INTO challenge_matches (challenge_id, invite_code, host_id, status, created_at) "
            "VALUES (?, ?, ?, 'waiting', ?)", (challenge_id, code, user["id"], db.now()))
        conn.commit()
        flash("比赛房间已创建，把邀请码发给对手吧！")
    else:
        flash("你已有一个进行中的房间，邀请码：" + existing["invite_code"])
    return redirect(url_for("main.challenge_detail", challenge_id=challenge_id))


@bp.post("/challenges/<int:challenge_id>/match/join")
@login_required
def match_join(challenge_id: int):
    conn = get_db()
    user = current_user()
    code = (request.form.get("invite_code") or "").strip().upper()
    m = conn.execute("SELECT * FROM challenge_matches WHERE invite_code = ? AND status != 'done'",
                     (code,)).fetchone()
    if not m or m["challenge_id"] != challenge_id:
        flash("邀请码无效或房间已结束")
    elif m["host_id"] == user["id"]:
        flash("不能加入自己创建的房间")
    elif m["guest_id"] and m["guest_id"] != user["id"]:
        flash("该房间已有 2 人")
    else:
        conn.execute("UPDATE challenge_matches SET guest_id = ?, status = 'racing' WHERE id = ?",
                     (user["id"], m["id"]))
        conn.commit()
        flash("已加入比赛房间，开始挑战吧！")
    return redirect(url_for("main.challenge_detail", challenge_id=challenge_id))


@bp.post("/challenges/<int:challenge_id>/match/<int:match_id>/finish")
@login_required
def match_finish(challenge_id: int, match_id: int):
    conn = get_db()
    user = current_user()
    elapsed_ms = _parse_elapsed(request.form.get("elapsed_ms"))
    m = conn.execute("SELECT * FROM challenge_matches WHERE id = ?", (match_id,)).fetchone()
    if not m or m["challenge_id"] != challenge_id:
        abort(404)
    if user["id"] not in (m["host_id"], m["guest_id"]):
        abort(403)
    _record_finish(conn, match_id, user["id"], elapsed_ms)
    conn.commit()
    flash("已记录你的完成时间！")
    return redirect(url_for("main.challenge_detail", challenge_id=challenge_id))


@bp.post("/challenges/<int:challenge_id>/match/<int:match_id>/leave")
@login_required
def match_leave(challenge_id: int, match_id: int):
    conn = get_db()
    user = current_user()
    m = conn.execute("SELECT * FROM challenge_matches WHERE id = ?", (match_id,)).fetchone()
    if not m or m["challenge_id"] != challenge_id:
        abort(404)
    if m["host_id"] == user["id"]:
        conn.execute("DELETE FROM challenge_matches WHERE id = ?", (match_id,))
    elif m["guest_id"] == user["id"]:
        conn.execute("UPDATE challenge_matches SET guest_id = NULL, status = 'waiting' WHERE id = ?",
                     (match_id,))
    conn.commit()
    flash("已退出房间")
    return redirect(url_for("main.challenge_detail", challenge_id=challenge_id))


# ---------------------------------------------------------------- 社区

@bp.get("/community")
def community():
    conn = get_db()
    rows = conn.execute(
        "SELECT p.*, u.nickname, u.username, "
        "(SELECT COUNT(*) FROM replies r WHERE r.post_id = p.id) AS reply_count "
        "FROM posts p LEFT JOIN users u ON u.id = p.user_id "
        "ORDER BY p.is_top DESC, p.id DESC").fetchall()
    return render_template("community.html", rows=rows)


@bp.route("/community/new", methods=["GET", "POST"])
@login_required
def post_new():
    if request.method == "POST":
        title = (request.form.get("title") or "").strip()
        content = (request.form.get("content") or "").strip()
        if not title or not content:
            flash("标题和内容都要填")
        else:
            conn = get_db()
            cur = conn.execute(
                "INSERT INTO posts (user_id, title, content, created_at) VALUES (?, ?, ?, ?)",
                (current_user()["id"], title, content, db.now()))
            conn.commit()
            return redirect(url_for("main.post_detail", post_id=cur.lastrowid))
    return render_template("post_new.html")


@bp.route("/community/<int:post_id>", methods=["GET", "POST"])
def post_detail(post_id: int):
    conn = get_db()
    post = conn.execute(
        "SELECT p.*, u.nickname, u.username, u.id AS author_id FROM posts p "
        "LEFT JOIN users u ON u.id = p.user_id WHERE p.id = ?", (post_id,)).fetchone()
    if not post:
        abort(404)

    if request.method == "POST":
        user = current_user()
        if user is None:
            return redirect(url_for("auth.login", next=url_for("main.post_detail", post_id=post_id)))
        content = (request.form.get("content") or "").strip()
        if not content:
            flash("回复内容不能为空")
        else:
            conn.execute(
                "INSERT INTO replies (post_id, user_id, content, created_at) VALUES (?, ?, ?, ?)",
                (post_id, user["id"], content, db.now()))
            conn.execute("UPDATE posts SET views = views + 0 WHERE id = ?", (post_id,))
            conn.commit()
            flash("回复成功")
        return redirect(url_for("main.post_detail", post_id=post_id))

    conn.execute("UPDATE posts SET views = views + 1 WHERE id = ?", (post_id,))
    conn.commit()
    replies = conn.execute(
        "SELECT r.*, u.nickname, u.username FROM replies r LEFT JOIN users u ON u.id = r.user_id "
        "WHERE r.post_id = ? ORDER BY r.id", (post_id,)).fetchall()
    return render_template("post_detail.html", post=post, replies=replies)


# ---------------------------------------------------------------- 文件

@bp.get("/files")
@login_required
def file_hub():
    """文件系统入口页：先选「下载」还是「上传」，再进各自页面。

    顶栏不再直接挂这两个入口，改由首页「实验室内部」的磁贴进入。
    """
    conn = get_db()
    user = current_user()
    resources = conn.execute(
        "SELECT COUNT(*) c FROM files WHERE kind = 'resource'").fetchone()["c"]
    mine = 0
    if user:
        mine = conn.execute(
            "SELECT COUNT(*) c FROM files WHERE kind = 'resource' AND owner_id = ?",
            (user["id"],)).fetchone()["c"]
    hw = conn.execute(
        "SELECT COUNT(*) n FROM assignments a JOIN courses co ON co.id = a.course_id "
        "WHERE co.is_open = 1").fetchone()["n"]
    return render_template("file_hub.html", resources=resources, mine=mine, hw=hw)


@bp.get("/files/download")
@login_required
def file_list():
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
    if course.isdigit():                       # 只看某个课程的资料
        sql += " AND f.course_id = ?"
        params.append(int(course))
    elif course == "none":                     # 不属于任何课程的公共资料
        sql += " AND f.course_id IS NULL"
    sql += " ORDER BY f.id DESC"
    rows = conn.execute(sql, params).fetchall()

    # 顶部标签：一门课一个标签，点开只看这门课的文件
    tabs = conn.execute(
        "SELECT c.id, c.title, c.icon, COUNT(f.id) AS n FROM courses c "
        "JOIN files f ON f.course_id = c.id AND f.kind = 'resource' "
        "WHERE c.is_open = 1 GROUP BY c.id, c.title, c.icon, c.sort_order "
        "ORDER BY c.sort_order, c.id").fetchall()
    none_count = conn.execute(
        "SELECT COUNT(*) c FROM files WHERE kind = 'resource' AND course_id IS NULL"
    ).fetchone()["c"]
    total = conn.execute(
        "SELECT COUNT(*) c FROM files WHERE kind = 'resource'").fetchone()["c"]
    return render_template("file_list.html", rows=rows, keyword=keyword, course=course,
                           tabs=tabs, none_count=none_count, total=total)


@bp.post("/files/<int:file_id>/delete")
@login_required
def file_delete(file_id: int):
    """删除公共资料：**只有上传者本人或管理员**能删，其他人一律 403。"""
    conn = get_db()
    user = current_user()
    row = conn.execute(
        "SELECT * FROM files WHERE id = ? AND kind = 'resource'", (file_id,)).fetchone()
    if not row:
        abort(404)
    if not (user["is_admin"] or row["owner_id"] == user["id"]):
        abort(403)
    path = os.path.join(db.FILE_DIR, row["stored_name"])
    if os.path.isfile(path):
        os.remove(path)                      # 物理文件一起删掉，不然白占磁盘
    conn.execute("DELETE FROM files WHERE id = ?", (file_id,))
    conn.commit()
    flash(f"已删除「{row['title']}」")
    return redirect(request.referrer or url_for("main.file_list"))


# ---------------------------------------------------------------- 作业文件传输

@bp.get("/files/homework")
@login_required
def homework_hub():
    """作业文件传输：集中列出各门课程的作业，在这里提交、查看自己的提交记录。

    与「文件上传」分开：那儿的文件是公开资料，这里的提交件只有本人和管理员能下载。
    """
    conn = get_db()
    user = current_user()
    rows = conn.execute(
        "SELECT a.*, c.title AS course_title, c.icon AS course_icon "
        "FROM assignments a JOIN courses c ON c.id = a.course_id "
        "WHERE c.is_open = 1 "
        "ORDER BY c.sort_order, c.id, a.sort_order, a.id").fetchall()

    groups: list = []
    index: dict = {}
    for a in rows:
        key = a["course_id"]
        if key not in index:
            g = {"course_id": key, "title": a["course_title"],
                 "icon": a["course_icon"] or "📘", "items": []}
            index[key] = g
            groups.append(g)
        item = dict(a)
        item["submit_count"] = conn.execute(
            "SELECT COUNT(DISTINCT owner_id) c FROM files "
            "WHERE kind = 'submission' AND assignment_id = ?", (a["id"],)).fetchone()["c"]
        item["my_files"] = conn.execute(
            "SELECT * FROM files WHERE kind = 'submission' AND assignment_id = ? "
            "AND owner_id = ? ORDER BY id DESC", (a["id"], user["id"])).fetchall()
        item["my_count"] = len(item["my_files"])
        item["mine"] = item["my_files"][0] if item["my_files"] else None
        g["items"].append(item)
    total = sum(len(g["items"]) for g in groups)
    return render_template("homework_hub.html", groups=groups, total=total)


@bp.post("/files/homework/<int:assignment_id>/submit")
@course_access_required
def homework_submit(assignment_id: int):
    """「作业文件传输」页的提交入口（与课程页的提交共用 record_submission）。

    作业提交是**唯一**仍需激活码的非课程页操作 —— 按作业所属课程判权限。
    """
    conn = get_db()
    user = current_user()
    back = url_for("main.homework_hub") + f"#hw{assignment_id}"
    item = conn.execute("SELECT * FROM assignments WHERE id = ?", (assignment_id,)).fetchone()
    if not item:
        abort(404)
    if not item["is_open"]:
        flash("这份作业已经停止收交了")
        return redirect(back)
    files = [f for f in request.files.getlist("file") if f and f.filename]
    if not files:
        flash("请先选择要提交的文件")
    else:
        errs = []
        for f in files:
            e = record_submission(conn, user, item, f)
            if e:
                errs.append(e)
        if errs:
            flash(errs[0])
        else:
            flash(f"「{item['title']}」提交成功，共 {len(files)} 个文件")
    return redirect(back)


@bp.get("/download/<int:file_id>")
def download(file_id: int):
    conn = get_db()
    row = conn.execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone()
    if not row:
        abort(404)
    user = current_user()
    if row["kind"] in ("submission", "drive"):
        # 作业提交件、云盘文件：只有本人和管理员能下载
        if user is None or (user["id"] != row["owner_id"] and not user["is_admin"]):
            abort(403)
    else:
        # 公共资料：登录即可下载。
        # 但**挂在课程下的资料**算课程内容，要按该课程是否在激活范围内判 ——
        # 否则学生从「文件下载」页就能绕过课程门禁把课件拿走。
        if user is None:
            target = request.full_path if request.query_string else request.path
            return redirect(url_for("auth.login", next=target))
        course_id = row["course_id"]
        if course_id and not user["is_admin"]:
            if not db.user_course_access(conn, user["id"], int(course_id)):
                if not db.user_activated(conn, user["id"]):
                    flash("这份资料属于课程内容，需要激活码才能下载。")
                else:
                    flash("这份资料属于你未解锁的课程，请联系管理员补充权限。")
                return redirect(url_for("main.activate"))
    path = os.path.join(db.FILE_DIR, row["stored_name"])
    if not os.path.isfile(path):
        abort(404)
    name = row["original_name"] or row["stored_name"] or ("file-%d" % file_id)
    return attachment_response(path, name, safe_ascii_name(name, "course-file"))


@bp.route("/upload", methods=["GET", "POST"])
@login_required
def upload():
    """成员上传资料：上传后归入「文件下载」列表，所有成员都能看到并下载。

    （课程作业的提交请走「作业文件传输」页 / 课程页的作业区，那里是私有提交件。）
    """
    conn = get_db()
    user = current_user()
    if request.method == "POST":
        title = (request.form.get("title") or "").strip()
        description = (request.form.get("description") or "").strip()
        uploads = [f for f in request.files.getlist("file") if f and f.filename]
        if not uploads:
            flash("请选择要上传的文件")
        else:
            ok = 0
            bad = 0
            for upload_file in uploads:
                t = title or os.path.basename(upload_file.filename)
                ext = os.path.splitext(upload_file.filename)[1].lower()
                if ext and ext not in ALLOWED_UPLOAD_EXT:
                    bad += 1
                    continue
                stored, original, size = save_upload(upload_file, prefix="up_")
                conn.execute(
                    "INSERT INTO files (kind, title, description, stored_name, original_name, "
                    "size, owner_id, created_at) VALUES ('resource', ?, ?, ?, ?, ?, ?, ?)",
                    (t, description, stored, original, size, user["id"], db.now()))
                ok += 1
            conn.commit()
            msg = f"上传成功，已归入「文件下载」，共 {ok} 个文件"
            if bad:
                msg += f"，{bad} 个格式不支持已跳过"
            flash(msg)
        return redirect(url_for("main.upload"))

    mine = conn.execute(
        "SELECT * FROM files WHERE kind = 'resource' AND owner_id = ? ORDER BY id DESC",
        (user["id"],)).fetchall()
    return render_template("upload.html", mine=mine)


# ---------------------------------------------------------------- 个人云盘

@bp.route("/drive", methods=["GET", "POST"])
@login_required
def drive():
    """个人云盘：每个人一块私人空间存文件，只有本人（和管理员）能看。"""
    conn = get_db()
    user = current_user()
    # 注意：0 是合法配额（表示不给空间），不能用 `or 200`，否则 0 会被当成空值
    quota = int(user["quota_mb"]) if user["quota_mb"] is not None else 200

    if request.method == "POST":
        uploads = [f for f in request.files.getlist("file") if f and f.filename]
        if not uploads:
            flash("请选择要上传的文件")
        else:
            # 云盘不限文件类型（私人空间，只有本人和管理员能下载，且一律以附件形式下载）
            used = conn.execute(
                "SELECT COALESCE(SUM(size), 0) s FROM files WHERE kind='drive' AND owner_id=?",
                (user["id"],)).fetchone()["s"]
            ok = 0
            skipped = 0
            for upload_file in uploads:
                stored, original, size = save_upload(upload_file, prefix="dv_")
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
            msg = f"已上传 {ok} 个文件到你的云盘"
            if skipped:
                msg += f"，{skipped} 个因空间不足跳过"
            flash(msg)
        return redirect(url_for("main.drive"))

    files = conn.execute(
        "SELECT * FROM files WHERE kind = 'drive' AND owner_id = ? ORDER BY id DESC",
        (user["id"],)).fetchall()
    usage = db.drive_usage(conn, user["id"])
    return render_template("drive.html", files=files, usage=usage, quota=quota)


@bp.post("/drive/<int:file_id>/delete")
@login_required
def drive_delete(file_id: int):
    conn = get_db()
    user = current_user()
    row = conn.execute(
        "SELECT * FROM files WHERE id = ? AND kind = 'drive' AND owner_id = ?",
        (file_id, user["id"])).fetchone()
    if not row:
        abort(404)
    path = os.path.join(db.FILE_DIR, row["stored_name"])
    if os.path.isfile(path):
        os.remove(path)
    conn.execute("DELETE FROM files WHERE id = ?", (file_id,))
    conn.commit()
    flash("文件已删除")
    return redirect(url_for("main.drive"))


# ---------------------------------------------------------------- 用户中心

@bp.get("/me")
@login_required
def me():
    conn = get_db()
    user = current_user()
    stats = db.study_stats(conn, user["id"])
    progress = conn.execute(
        "SELECT cp.*, c.title, c.icon, c.category FROM course_progress cp "
        "LEFT JOIN courses c ON c.id = cp.course_id WHERE cp.user_id = ? "
        "ORDER BY cp.updated_at DESC", (user["id"],)).fetchall()
    records = conn.execute(
        "SELECT r.*, ch.title, ch.difficulty, ch.id AS cid FROM challenge_records r "
        "LEFT JOIN challenges ch ON ch.id = r.challenge_id WHERE r.user_id = ? "
        "ORDER BY r.id DESC", (user["id"],)).fetchall()
    files = conn.execute(
        "SELECT * FROM files WHERE kind IN ('submission', 'resource') AND owner_id = ? "
        "ORDER BY id DESC LIMIT 20", (user["id"],)).fetchall()
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
    return render_template("me.html", stats=stats, progress=progress, records=records,
                           files=files, posts=posts, achievements=achievements,
                           done=done, passed=passed)


@bp.route("/me/password", methods=["POST"])
@login_required
def change_password():
    conn = get_db()
    user = current_user()
    old = request.form.get("old_password") or ""
    new = request.form.get("new_password") or ""
    confirm = request.form.get("confirm_password") or ""
    if not db.verify_password(old, user["password_hash"]):
        flash("原密码不正确")
    elif len(new) < 6:
        flash("新密码至少 6 位")
    elif new != confirm:
        flash("两次输入的新密码不一致")
    else:
        conn.execute("UPDATE users SET password_hash = ? WHERE id = ?",
                     (db.hash_password(new), user["id"]))
        conn.commit()
        flash("密码已更新")
    return redirect(url_for("main.me"))


@bp.post("/me/cancel")
def cancel_account():
    """自助注销账号（用户中心 → 注销账号）。

    做法：不物理删行，而是把身份信息全部匿名化 + is_active=0。
    - is_active=0 后 current_user()/api_user() 都取不到用户 → 网页 session 和
      App 的 14 天 token 在下一个请求就全部失效，各端立即被登出；
    - username/phone 有 UNIQUE 约束，替换成 deleted-<id>-<日期>，重复注销不冲突；
    - 昵称改成「已注销用户」，社区帖/回复里显示的作者名随之匿名；
    - 学习记录、作业提交等保留（已匿名），管理员后台仍可查数量；
    - 密码换成随机串，谁也登不进这个账号了。
    """
    user = current_user()
    if user is None:
        return redirect(url_for("auth.login"))
    password = request.form.get("password") or ""
    if not request.form.get("confirm"):
        flash("请先勾选「我已知晓注销后果」")
        return redirect(url_for("main.me"))
    if not db.verify_password(password, user["password_hash"]):
        flash("密码不正确，账号未注销")
        return redirect(url_for("main.me"))
    if user["is_admin"]:
        flash("管理员账号不能自助注销，请让其他管理员处理")
        return redirect(url_for("main.me"))

    conn = get_db()
    anon = f"deleted-{user['id']}-{db.now()[:10].replace('-', '')}"
    conn.execute(
        "UPDATE users SET username = ?, phone = ?, student_no = '', nickname = '已注销用户', "
        "password_hash = ?, is_active = 0, quota_mb = 0 WHERE id = ?",
        (anon, anon, db.hash_password(secrets.token_urlsafe(24)), user["id"]))
    conn.commit()
    logout_user()
    flash("账号已注销。个人信息已清除且不可恢复，如需彻底删除全部数据请联系管理员。")
    return redirect(url_for("main.home"))


@bp.get("/api/ping")
def ping():
    return jsonify({"ok": True, "time": db.now()})


# ---------------------------------------------------------------- 报到

# ---------------------------------------------------------------- App 下载页

@bp.get("/download")
def app_download():
    """App 下载页：安卓、Windows 与 macOS 各取「最新 / 上一版」，上一版用于演示自动更新。"""
    conn = get_db()
    ver = db.app_latest(conn, "android")
    prev = db.app_previous(conn, "android")
    win = db.app_latest(conn, "windows")
    win_prev = db.app_previous(conn, "windows")
    win_portable = db.app_latest(conn, "windows-portable")
    mac = db.app_latest(conn, "mac")
    mac_prev = db.app_previous(conn, "mac")
    return render_template(
        "download.html",
        ver=ver, prev=prev,
        win=win, win_prev=win_prev, win_portable=win_portable,
        mac=mac, mac_prev=mac_prev,
    )


# ---------------------------------------------------------------- 安装包下载

def _app_pkg_path(row) -> str:
    """把 app_versions.download_url 换算成磁盘上的真实路径。"""
    rel = (row["download_url"] or "").lstrip("/")
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), rel)


def _app_pkg_name(row, path) -> str:
    """用户看到的落盘文件名（中文正式名）。"""
    name = (row["file_name"] or "").strip()
    return name or os.path.basename(path)


def _app_ascii_name(row, name) -> str:
    """给安装包算一个全英文的 ASCII 回退名。

    直接把中文剥掉会得到「--1.3.6.exe」这种没法看的名字（不认 filename*
    的下载器就存成这个），所以这里按渠道 + 版本号拼：
    teaching-system-Setup-1.3.6.exe / teaching-system-Portable-1.3.6.exe。
    """
    ver = (row["version_name"] or "").strip() or "latest"
    suffix = {"windows": "Setup", "windows-portable": "Portable"}.get(
        (row["platform"] or "").strip().lower(), ""
    )
    base = "teaching-system" + ("-" + suffix if suffix else "")
    return "%s-%s%s" % (base, ver, os.path.splitext(name)[1].lower())


def _zip_cache_path(path) -> str:
    return os.path.splitext(path)[0] + ".zip"


def _build_zip(src_pkg, dst_zip, arcname, note=""):
    """把安装包（src_pkg）压成一个 zip（dst_zip）。

    exe 本身已经压过一遍，再走 deflate 纯属白烧 CPU，所以用 store 模式，
    本质就是「带 CRC 校验的文件复制」，几十 MB 一两秒就好。
    先写临时文件再 os.replace，避免并发请求读到半个包。
    """
    tmp = "%s.tmp-%s" % (dst_zip, secrets.token_hex(6))
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED, allowZip64=True) as zf:
            zf.write(src_pkg, arcname)
            if note:
                zf.writestr("使用说明.txt", note)
        os.replace(tmp, dst_zip)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def _zip_note(row, exe_name) -> str:
    """zip 里附的说明书：把「为什么给 zip、怎么校验」讲清楚。"""
    lines = [
        "教学管理系统 客户端安装包",
        "=" * 40,
        "",
        "解压后直接双击 %s 即可。" % exe_name,
        "",
        "为什么还提供一个 zip？",
        "  浏览器对「可执行文件 + 不常下载」会先扣下来等用户确认，",
        "  下载项可能一直停在「未确认 xxxxxx.crdownload」而不改名，",
        "  看起来就像「下载不了」。zip 不会触发这层拦截。",
        "",
        "版本：v%s   平台：%s" % (row["version_name"] or "", row["platform"] or ""),
    ]
    if row["sha512"]:
        lines += ["", "SHA-512（Base64）：", (row["sha512"] or "").strip()]
    return "\n".join(lines) + "\n"


@bp.get("/app/apk/<int:version_code>")
def app_apk_download(version_code):
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM app_versions WHERE version_code = ? AND platform = 'android'",
        (version_code,),
    ).fetchone()
    if row is None:
        abort(404)
    path = _app_pkg_path(row)
    if not os.path.isfile(path):
        abort(404)
    name = "教学管理系统-v%s.apk" % row["version_name"]
    return attachment_response(path, name, _app_ascii_name(row, name))


@bp.get("/app/download/<int:vid>")
def app_file_download(vid):
    """按版本记录 ID 下载原始安装包，覆盖安卓 / Windows 安装版 / Windows 绿色版。

    用下载名（file_name）命名落盘文件，用户看到的就是「教学管理系统-安装版-1.3.6.exe」。
    文件本身放在 static 目录下，Apache 会直接托管，不必占用 Flask 工作线程。
    """
    conn = get_db()
    row = conn.execute("SELECT * FROM app_versions WHERE id = ?", (vid,)).fetchone()
    if row is None:
        abort(404)
    path = _app_pkg_path(row)
    if not os.path.isfile(path):
        abort(404)
    name = _app_pkg_name(row, path)
    return attachment_response(path, name, _app_ascii_name(row, name))


@bp.get("/app/zip/<int:vid>")
def app_zip_download(vid):
    """下载同一份安装包的 zip 打包版（浏览器安全拦截的兜底通道）。

    Edge / Chrome 对未签名、信誉不足的 exe 会先扣在「未确认 xxx.crdownload」
    里等用户点「保留」，用户没留意就以为下载失败。zip 不在这类拦截范围内，
    所以给每份安装包留一个 zip 入口，解压出来还是同一个 exe。
    首次请求时打包并缓存在安装包旁边，之后直接复用（exe 换了会自动重打）。
    """
    conn = get_db()
    row = conn.execute("SELECT * FROM app_versions WHERE id = ?", (vid,)).fetchone()
    if row is None:
        abort(404)
    path = _app_pkg_path(row)
    if not os.path.isfile(path):
        abort(404)

    exe_name = _app_pkg_name(row, path)
    zpath = _zip_cache_path(path)
    try:
        if not os.path.isfile(zpath) or os.path.getmtime(zpath) < os.path.getmtime(path):
            _build_zip(path, zpath, exe_name, _zip_note(row, exe_name))
    except OSError:
        current_app.logger.exception("打包 zip 失败：%s", path)
        abort(503)          # 磁盘满 / 权限不对：让用户退回 exe 直链
    name = os.path.splitext(exe_name)[0] + ".zip"
    return attachment_response(zpath, name, _app_ascii_name(row, name))


@bp.get("/favicon.ico")
def favicon():
    """站点图标：浏览器默认会来要这个文件（不在 /static 下），之前一直是 404。"""
    static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
    return send_from_directory(static_dir, "favicon.ico",
                              mimetype="image/vnd.microsoft.icon")



# ---------------------------------------------------------------- 工具箱

@bp.get("/tools")
def tools():
    """工具箱：网络工具 + 日常实用工具，全部在前端本地运行。"""
    return render_template("tools.html")




# ---------------------------------------------------------------- 开发指南页

@bp.get("/guide")
@admin_required
def dev_guide():
    return render_template("guide.html")


@bp.get("/guide/windows")
@admin_required
def dev_guide_windows():
    """Windows 桌面端的迭代教程（仅管理员）。"""
    return render_template("guide-windows.html")



# ---------------------------------------------------------------- 源代码下载（仅管理员）

@bp.get("/source")
@admin_required
def source_download():
    src_dir = os.path.join(db.DATA_DIR, "source")
    return send_from_directory(src_dir, "teaching-system-android-source.zip", as_attachment=True)


@bp.get("/source/windows")
@admin_required
def windows_source_download():
    """Windows 桌面端完整源代码（仅管理员）。"""
    src_dir = os.path.join(db.DATA_DIR, "source")
    return send_from_directory(src_dir, "teaching-system-windows-source.zip", as_attachment=True)


@bp.get("/guide/mac")
@admin_required
def dev_guide_mac():
    """macOS 桌面端的迭代教程（仅管理员）。"""
    return render_template("guide-mac.html")


@bp.get("/source/mac")
@admin_required
def mac_source_download():
    """macOS 桌面端完整源代码（仅管理员）。"""
    src_dir = os.path.join(db.DATA_DIR, "source")
    return send_from_directory(src_dir, "teaching-system-mac-source.zip", as_attachment=True)


# ---------------------------------------------------------------- 法律条款
# 登录/注册页的勾选框里链到这两个页面。此前只写了链接、没建路由，
# 点开就是 404（用户报过这个 bug）。这里补上真实页面，并在页脚加入口。

@bp.get("/privacy")
def privacy():
    """隐私政策。无需登录即可查看——注册前就得能读到。"""
    return render_template("privacy.html", updated="2026-10-16")


@bp.get("/agreement")
def agreement():
    """用户协议。同上，公开可读。"""
    return render_template("agreement.html", updated="2026-10-16")


# ---------------------------------------------------------------- 格式转换
CONVERT_DIR = os.path.join(db.DATA_DIR, "convert")

IMAGE_EXTS = {"jpg","jpeg","jpe","jfif","png","gif","bmp","tif","tiff","webp","ico",
              "svg","tga","pcx","psd","exr","dds","xwd","xpm","xbm","pbm","pgm","ppm",
              "pnm","pam","jbg","pct","pict","ras","sun","viff","wbmp","cur","avif",
              "heic","heif","jp2","j2k","jps","sgi","rgb","rgba","rgbo","mtv","map",
              "otb","palm","pcd","pfm","picon","uyvy","xv","yuv","hdr","xcf"}
AUDIO_EXTS = {"mp3","wav","ogg","oga","m4a","m4r","flac","aac","wma","amr","opus",
              "mp2","ac3","dts","aif","aiff","au","snd","caf","voc","wv","tta","spx",
              "gsm","sln","ra","8svx","oma","mka"}
DOC_EXTS = {"pdf","doc","docx","xls","xlsx","txt","odt","csv","html","htm","rtf",
            "docm","dotx","dot","dotm","odp","ods","xps","oxps","djvu","epub","wps",
            "wpd","fodt","fods","abw","dbk","sxw","kwd","ppt","pptx"}

TARGET_IMAGE = ["png","jpg","jpeg","gif","bmp","tiff","webp","ico","tga","pcx",
                "psd","pbm","pgm","ppm","svg","dds","xwd","jp2","jpe","jfif"]
TARGET_AUDIO = ["mp3","wav","ogg","m4a","flac","aac","wma","amr","opus","mp2",
                "ac3","aiff","au","caf","m4r"]
TARGET_DOC = ["pdf","docx","doc","xlsx","xls","csv","txt","odt","html","rtf","pptx"]


@bp.route("/convert", methods=["GET", "POST"])
def convert():
    result = None
    error = None
    if request.method == "POST":
        upload = request.files.get("file")
        target = (request.form.get("target") or "").strip().lower()
        if upload is None or not upload.filename:
            error = "请选择要转换的文件"
        elif not target:
            error = "请选择目标格式"
        else:
            os.makedirs(CONVERT_DIR, exist_ok=True)
            ext = os.path.splitext(upload.filename)[1].lstrip(".").lower()
            token = secrets.token_hex(8)
            in_path = os.path.join(CONVERT_DIR, token + "." + ext)
            upload.save(in_path)
            try:
                out_path = _convert_file(in_path, ext, target, token)
                name = os.path.basename(out_path)
                result = {"url": url_for("main.convert_download", name=name), "name": name}
            except Exception as e:
                error = "转换失败：" + str(e)
            finally:
                try:
                    os.remove(in_path)
                except Exception:
                    pass
    return render_template("convert.html", result=result, error=error)


@bp.get("/convert/download/<name>")
def convert_download(name):
    import re as _re
    if not _re.fullmatch(r"[0-9a-f]{16}\.[a-z0-9]+", name):
        abort(404)
    path = os.path.join(CONVERT_DIR, name)
    if not os.path.exists(path):
        abort(404)
    return send_file(path, as_attachment=True, download_name=name)


def _convert_file(in_path, src_ext, target_ext, token):
    out_path = os.path.join(CONVERT_DIR, token + "." + target_ext)
    if src_ext == target_ext:
        raise RuntimeError("源格式与目标格式相同，无需转换")
    if src_ext in IMAGE_EXTS and target_ext in TARGET_IMAGE:
        p = subprocess.run(["convert", in_path, out_path], capture_output=True, timeout=180)
        if p.returncode != 0 or not os.path.exists(out_path):
            raise RuntimeError("图像转换失败（该格式可能不受支持）")
    elif src_ext in AUDIO_EXTS and target_ext in TARGET_AUDIO:
        p = subprocess.run(["ffmpeg", "-y", "-i", in_path, "-vn", out_path],
                           capture_output=True, timeout=300)
        if p.returncode != 0 or not os.path.exists(out_path):
            raise RuntimeError("音频转换失败（该格式可能不受支持）")
    elif src_ext in DOC_EXTS and target_ext in TARGET_DOC:
        if src_ext == "pdf" and target_ext == "docx":
            code = "from pdf2docx import Converter; c = Converter(r'%s'); c.convert(r'%s'); c.close()" % (in_path, out_path)
            p = subprocess.run([sys.executable, "-c", code], capture_output=True, timeout=300)
            if p.returncode != 0 or not os.path.exists(out_path):
                raise RuntimeError("PDF 转 Word 失败")
        else:
            out_dir = os.path.dirname(out_path)
            p = subprocess.run(
                ["soffice", "--headless", "-env:UserInstallation=file:///tmp/lo_profile",
                 "--convert-to", target_ext, "--outdir", out_dir, in_path],
                capture_output=True, timeout=300,
            )
            if p.returncode != 0 or not os.path.exists(out_path):
                raise RuntimeError("文档转换失败（该格式可能不受支持）")
    else:
        raise RuntimeError("不支持的源格式或转换组合")
    return out_path


# ---------------------------------------------------------------- 分片上传
# 背景：Apache 默认对请求体有 2GB 上限（实测 1GB 通过、2GB 起 413），
# 而且这台机器只有 1.6G 内存，单次请求传 4GB 会把服务器压垮（2026-09-28 实测）。
# 解决：配置层加 LimitRequestBody 0 解除硬限制 + 前端把大文件切成 8MB 小片逐片上传。
# 好处：不受任何大小限制、内存可控、单片失败可重传、支持断点续传。

CHUNK_SIZE = 8 * 1024 * 1024          # 每片 8MB
CHUNK_TTL = 24 * 3600                 # 未完成的临时分片保留 24 小时
CHUNK_DIR = os.path.join(db.DATA_DIR, "chunks")


def _chunk_dir(uid: str) -> str:
    return os.path.join(CHUNK_DIR, uid)


def _chunk_meta(uid: str):
    if not uid:
        return None
    p = os.path.join(_chunk_dir(uid), "meta.json")
    if not os.path.exists(p):
        return None
    try:
        with open(p, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _chunk_write_meta(uid: str, meta: dict) -> None:
    d = _chunk_dir(uid)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "meta.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False)


def _chunk_received(uid: str) -> list:
    d = _chunk_dir(uid)
    if not os.path.isdir(d):
        return []
    out = []
    for n in os.listdir(d):
        if n.startswith("part_"):
            try:
                out.append(int(n[len("part_"):]))
            except ValueError:
                pass
    return sorted(out)


def _chunk_sweep() -> None:
    """清理超过 TTL 的僵尸分片目录，避免磁盘被占满。"""
    try:
        if not os.path.isdir(CHUNK_DIR):
            return
        now = time.time()
        for name in os.listdir(CHUNK_DIR):
            d = os.path.join(CHUNK_DIR, name)
            if not os.path.isdir(d):
                continue
            try:
                if now - os.path.getmtime(d) > CHUNK_TTL:
                    shutil.rmtree(d, ignore_errors=True)
            except OSError:
                pass
    except OSError:
        pass


@bp.post("/upload/chunk/init")
@login_required
def chunk_init():
    """开启一次分片上传：登记文件名/大小，返回 upload_id 和分片大小。"""
    data = request.get_json(silent=True) or request.form or {}
    name = os.path.basename((data.get("filename") or "").strip())
    if not name:
        return jsonify({"ok": False, "error": "缺少文件名"}), 400
    try:
        total = int(data.get("size") or 0)
    except (TypeError, ValueError):
        total = 0
    if total <= 0:
        return jsonify({"ok": False, "error": "文件大小无效"}), 400
    ext = os.path.splitext(name)[1].lower()
    if ext and ext not in ALLOWED_UPLOAD_EXT:
        return jsonify({"ok": False, "error": "不支持的文件格式：%s" % ext}), 400

    _chunk_sweep()
    uid = secrets.token_hex(16)
    _chunk_write_meta(uid, {
        "uid": uid,
        "filename": name,
        "size": total,
        "user_id": current_user()["id"],
        "fields": {k: v for k, v in data.items() if k not in ("filename", "size")},
        "created": time.time(),
    })
    return jsonify({"ok": True, "upload_id": uid, "chunk_size": CHUNK_SIZE,
                    "chunks": max(1, math.ceil(total / CHUNK_SIZE))})


@bp.post("/upload/chunk/part")
@login_required
def chunk_part():
    """接收一个分片，落盘为 part_<index>。"""
    uid = (request.form.get("upload_id") or "").strip()
    meta = _chunk_meta(uid)
    if not meta or meta.get("user_id") != current_user()["id"]:
        return jsonify({"ok": False, "error": "上传会话无效，请重新开始"}), 400
    try:
        idx = int(request.form.get("index"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "分片序号无效"}), 400
    if idx < 0 or idx >= max(1, math.ceil(int(meta["size"]) / CHUNK_SIZE)):
        return jsonify({"ok": False, "error": "分片序号越界"}), 400
    f = request.files.get("chunk")
    if f is None:
        return jsonify({"ok": False, "error": "缺少分片数据"}), 400
    d = _chunk_dir(uid)
    os.makedirs(d, exist_ok=True)
    f.save(os.path.join(d, "part_%d" % idx))
    return jsonify({"ok": True, "index": idx, "received": len(_chunk_received(uid))})


@bp.get("/upload/chunk/status")
@login_required
def chunk_status():
    """查询某个上传会话已收到哪些分片（用于断点续传）。"""
    uid = (request.args.get("upload_id") or "").strip()
    meta = _chunk_meta(uid)
    if not meta or meta.get("user_id") != current_user()["id"]:
        return jsonify({"ok": False, "error": "上传会话无效"}), 400
    return jsonify({"ok": True, "received": _chunk_received(uid),
                    "size": meta.get("size", 0),
                    "chunks": max(1, math.ceil(int(meta["size"]) / CHUNK_SIZE))})


@bp.post("/upload/chunk/finish")
@login_required
def chunk_finish():
    """所有分片到齐后按顺序合并成正式文件并入库。"""
    data = request.get_json(silent=True) or request.form or {}
    uid = (data.get("upload_id") or "").strip()
    meta = _chunk_meta(uid)
    if not meta or meta.get("user_id") != current_user()["id"]:
        return jsonify({"ok": False, "error": "上传会话无效，请重新开始"}), 400

    d = _chunk_dir(uid)
    got = set(_chunk_received(uid))
    total_chunks = max(1, math.ceil(int(meta["size"]) / CHUNK_SIZE))
    missing = [i for i in range(total_chunks) if i not in got]
    if missing:
        return jsonify({"ok": False, "error": "还缺 %d 个分片，请重传" % len(missing),
                        "missing": missing[:50]}), 400

    name = meta["filename"]
    ext = os.path.splitext(name)[1].lower()
    stored = "up_%s%s" % (secrets.token_hex(8), ext)
    dest = os.path.join(db.FILE_DIR, stored)
    try:
        with open(dest, "wb") as out:
            for i in range(total_chunks):
                with open(os.path.join(d, "part_%d" % i), "rb") as fh:
                    shutil.copyfileobj(fh, out, 1024 * 1024)
    except OSError as exc:
        try:
            os.remove(dest)
        except OSError:
            pass
        current_app.logger.error("chunk merge failed: %s", exc)
        return jsonify({"ok": False, "error": "合并文件失败（可能是磁盘空间不足）"}), 500

    size = os.path.getsize(dest)
    shutil.rmtree(d, ignore_errors=True)

    fields = meta.get("fields") or {}
    title = (str(fields.get("title") or "")).strip() or name
    description = (str(fields.get("description") or "")).strip()
    category = (str(fields.get("category") or "")).strip()
    course_id = None
    raw_course = fields.get("course_id")
    try:
        if raw_course not in (None, "", "None"):
            course_id = int(raw_course)
    except (TypeError, ValueError):
        course_id = None

    conn = get_db()
    cur = conn.execute(
        "INSERT INTO files (kind, title, description, stored_name, original_name, size, "
        "category, course_id, owner_id, created_at) "
        "VALUES ('resource', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (title, description, stored, name, size, category, course_id,
         current_user()["id"], db.now()))
    conn.commit()
    return jsonify({"ok": True, "file_id": cur.lastrowid, "size": size,
                    "name": name, "title": title})


# ---------------------------------------------------------------- 视频字幕（网站端）
# 由 patch_subtitle.py 追加
import subtitle as subtitle_mod


@bp.get("/videos/<int:video_id>/subtitle")
@course_access_required
def video_subtitle(video_id: int):
    """课程视频字幕：把后台上传的 srt/vtt 统一转成 WebVTT 给 <track> 用。"""
    conn = get_db()
    row = conn.execute("SELECT subtitle FROM videos WHERE id = ?", (video_id,)).fetchone()
    if not row or not row["subtitle"]:
        abort(404)
    path = os.path.join(db.FILE_DIR, row["subtitle"])
    if not os.path.isfile(path):
        abort(404)
    return subtitle_mod.vtt_response(path)
