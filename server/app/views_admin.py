"""管理后台：用户、课程（编辑器/上传 HTML）、挑战、资料、作业提交、社区、学习数据。

入口：/index（或在任意页面右上角进「管理」），实际路径都在 /admin 下。
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import secrets
import shutil
import subprocess

from flask import (Blueprint, abort, after_this_request, flash, jsonify, redirect,
                   render_template, request, send_file, render_template_string, url_for)

import db
from core import admin_required, current_user, get_db
from views_main import (ALLOWED_UPLOAD_EXT, VIDEO_EXT, _find_entry, _safe_extract, _human_size,
                        save_upload, probe_media_duration, format_duration)

bp = Blueprint("admin", __name__, url_prefix="/admin")


def _xlsx(sheet_title: str, headers: list[str], rows) -> io.BytesIO:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font
    from openpyxl.utils import get_column_letter

    book = Workbook()
    sheet = book.active
    sheet.title = sheet_title[:31] or "Sheet1"
    sheet.append(headers)
    for row in rows:
        sheet.append(["" if v is None else v for v in row])
    for cell in sheet[1]:
        cell.font = Font(bold=True)
        cell.alignment = Alignment(vertical="center")
    sheet.freeze_panes = "A2"
    for index, header in enumerate(headers, start=1):
        widest = len(str(header))
        for row in rows:
            if index - 1 < len(row):
                widest = max(widest, min(len(str(row[index - 1] or "")), 50))
        sheet.column_dimensions[get_column_letter(index)].width = min(max(widest + 4, 10), 52)
    buf = io.BytesIO()
    book.save(buf)
    buf.seek(0)
    return buf


XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


# ---------------------------------------------------------------- 概览

@bp.get("")
@bp.get("/")
@admin_required
def dashboard():
    conn = get_db()
    stats = {
        "users": conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"],
        "courses": conn.execute("SELECT COUNT(*) c FROM courses").fetchone()["c"],
        "challenges": conn.execute("SELECT COUNT(*) c FROM challenges").fetchone()["c"],
        "resources": conn.execute("SELECT COUNT(*) c FROM files WHERE kind='resource'").fetchone()["c"],
        "submissions": conn.execute("SELECT COUNT(*) c FROM files WHERE kind='submission'").fetchone()["c"],
        "posts": conn.execute("SELECT COUNT(*) c FROM posts").fetchone()["c"],
        "pending": conn.execute(
            "SELECT COUNT(*) c FROM challenge_records WHERE passed = 0").fetchone()["c"],
    }
    recent_users = conn.execute(
        "SELECT * FROM users ORDER BY id DESC LIMIT 6").fetchall()
    recent_files = conn.execute(
        "SELECT f.*, u.username, u.nickname FROM files f LEFT JOIN users u ON u.id = f.owner_id "
        "WHERE f.kind = 'submission' ORDER BY f.id DESC LIMIT 6").fetchall()
    return render_template("admin_dashboard.html", stats=stats, recent_users=recent_users,
                           recent_files=recent_files, human=_human_size,
                           joins=_join_rows(conn, limit=8), join_stats=db.join_stats(conn),
                           updated_at=db.now())


def _join_rows(conn, limit: int | None = None, keyword: str = "", only_group: str = ""):
    """报名记录查询（后台实时数据用），可按姓名/学院/联系方式搜索、按是否进群筛选。"""
    sql = "SELECT * FROM join_requests"
    where, params = [], []
    if keyword:
        where.append("(name LIKE ? OR college LIKE ? OR contact LIKE ?)")
        params.extend([f"%{keyword}%"] * 3)
    if only_group == "yes":
        where.append("join_group = 1")
    elif only_group == "no":
        where.append("join_group = 0")
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC"
    if limit:
        sql += f" LIMIT {int(limit)}"
    return conn.execute(sql, params).fetchall()


# ---------------------------------------------------------------- 加入我们

@bp.get("/join")
@admin_required
def join_list():
    conn = get_db()
    keyword = (request.args.get("q") or "").strip()
    only_group = (request.args.get("group") or "").strip()
    rows = _join_rows(conn, keyword=keyword, only_group=only_group)
    return render_template("admin_join.html", rows=rows, keyword=keyword, only_group=only_group,
                           join_stats=db.join_stats(conn), updated_at=db.now())


@bp.post("/join/<int:req_id>/delete")
@admin_required
def join_delete(req_id: int):
    conn = get_db()
    conn.execute("DELETE FROM join_requests WHERE id = ?", (req_id,))
    conn.commit()
    flash("已删除该条报名记录")
    return redirect(url_for("admin.join_list", q=request.args.get("q", ""),
                            group=request.args.get("group", "")))


@bp.post("/join/clear")
@admin_required
def join_clear():
    conn = get_db()
    count = conn.execute("SELECT COUNT(*) c FROM join_requests").fetchone()["c"]
    conn.execute("DELETE FROM join_requests")
    conn.commit()
    flash(f"已清空 {count} 条报名记录（建议先导出备份）")
    return redirect(url_for("admin.join_list"))


@bp.get("/join/<fmt>")
@admin_required
def join_export(fmt: str):
    if fmt not in ("csv", "xlsx"):
        abort(404)
    rows = _join_rows(get_db())
    headers = ["编号", "姓名", "学院", "联系方式", "是否加入群聊", "想说的话", "提交时间", "来源 IP"]
    data = [[r["id"], r["name"], r["college"], r["contact"],
             "是" if r["join_group"] else "否", r["note"], r["created_at"], r["ip"]] for r in rows]
    stamp = db.now().replace(":", "").replace(" ", "-")
    if fmt == "xlsx":
        return send_file(_xlsx("报名名单", headers, data), mimetype=XLSX_MIME, as_attachment=True,
                         download_name=f"报名名单-{stamp}.xlsx")
    return send_file(io.BytesIO(db.csv_bytes(headers, data)), mimetype="text/csv",
                     as_attachment=True, download_name=f"报名名单-{stamp}.csv")


@bp.get("/join.json")
@admin_required
def join_json():
    """给后台的自动刷新用：返回统计与列表，页面无需整页重载。"""
    conn = get_db()
    keyword = (request.args.get("q") or "").strip()
    only_group = (request.args.get("group") or "").strip()
    rows = _join_rows(conn, keyword=keyword, only_group=only_group)
    return jsonify({
        "stats": db.join_stats(conn),
        "updated_at": db.now(),
        "rows": [dict(r) for r in rows],
    })


# ---------------------------------------------------------------- 用户

@bp.get("/users")
@admin_required
def users():
    conn = get_db()
    keyword = (request.args.get("q") or "").strip()
    sql = ("SELECT u.*, "
           "(SELECT COUNT(*) FROM study_days s WHERE s.user_id = u.id) AS study_days, "
           "(SELECT COUNT(*) FROM course_progress p WHERE p.user_id = u.id AND p.status='done') "
           "  AS courses_done, "
           "(SELECT COUNT(*) FROM challenge_records r WHERE r.user_id = u.id AND r.passed=1) "
           "  AS challenges_passed, "
           "(SELECT COUNT(*) FROM files f WHERE f.owner_id = u.id AND f.kind='submission') "
           "  AS submissions, "
           "(SELECT COALESCE(SUM(f2.size), 0) FROM files f2 WHERE f2.owner_id = u.id "
           "   AND f2.kind='drive') AS drive_bytes FROM users u")
    params: list = []
    if keyword:
        sql += " WHERE u.username LIKE ? OR u.phone LIKE ? OR u.nickname LIKE ?"
        params = [f"%{keyword}%"] * 3
    sql += " ORDER BY u.id DESC"
    rows = conn.execute(sql, params).fetchall()
    return render_template("admin_users.html", rows=rows, keyword=keyword)


@bp.post("/users/<int:user_id>/<action>")
@admin_required
def user_action(user_id: int, action: str):
    conn = get_db()
    me = current_user()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not row:
        abort(404)
    if action == "toggle":
        conn.execute("UPDATE users SET is_active = ? WHERE id = ?",
                     (0 if row["is_active"] else 1, user_id))
        flash(f"已{'停用' if row['is_active'] else '启用'} {row['username']}")
    elif action == "grant":
        conn.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (user_id,))
        flash(f"已把 {row['username']} 设为管理员")
    elif action == "revoke":
        if row["id"] == me["id"]:
            flash("不能取消自己的管理员权限")
        elif conn.execute("SELECT COUNT(*) c FROM users WHERE is_admin = 1").fetchone()["c"] <= 1:
            flash("系统至少要保留一个管理员，不能再取消了")
        else:
            conn.execute("UPDATE users SET is_admin = 0 WHERE id = ?", (user_id,))
            flash(f"已取消 {row['username']} 的管理员权限")
    elif action == "reset":
        new_password = request.form.get("new_password") or secrets.token_urlsafe(6)
        conn.execute("UPDATE users SET password_hash = ? WHERE id = ?",
                     (db.hash_password(new_password), user_id))
        flash(f"{row['username']} 的密码已重置为：{new_password}（请转告该用户）")
    elif action == "quota":
        try:
            quota = max(0, min(1024 * 1024, int(request.form.get("quota") or 0)))
        except ValueError:
            quota = row["quota_mb"] if row["quota_mb"] is not None else 200
        conn.execute("UPDATE users SET quota_mb = ? WHERE id = ?", (quota, user_id))
        flash(f"{row['username']} 的云盘配额已设为 {quota}MB")
    elif action == "delete":
        if row["id"] == me["id"]:
            flash("不能删除自己的账号")
        else:
            # 先清掉这个人的云盘文件（物理文件 + 记录）
            for d in conn.execute(
                "SELECT stored_name FROM files WHERE kind = 'drive' AND owner_id = ?",
                (user_id,)).fetchall():
                p = os.path.join(db.FILE_DIR, d["stored_name"])
                if os.path.isfile(p):
                    os.remove(p)
            conn.execute("DELETE FROM files WHERE kind = 'drive' AND owner_id = ?", (user_id,))
            conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
            flash(f"账号 {row['username']} 已删除（其云盘文件一并清空，交过的作业记录保留）")
    else:
        abort(404)
    conn.commit()
    return redirect(url_for("admin.users", q=request.args.get("q") or ""))


# ---------------------------------------------------------------- 管理员账号

@bp.route("/admins", methods=["GET", "POST"])
@admin_required
def admins():
    """新建管理员账号 + 管理现有管理员。只有管理员能进（路由本身就有 admin_required）。"""
    conn = get_db()
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        phone = (request.form.get("phone") or "").strip()
        nickname = (request.form.get("nickname") or "").strip()
        password = request.form.get("password") or ""

        errors = []
        if not re.fullmatch(r"[a-zA-Z0-9_]{3,20}", username):
            errors.append("用户名需 3-20 位，只能由字母、数字、下划线组成")
        if not re.fullmatch(r"1\d{10}", phone):
            errors.append("请填写 11 位手机号")
        if len(password) < 6:
            errors.append("密码至少 6 位")
        if conn.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
            errors.append("这个用户名已经被占用")
        if conn.execute("SELECT 1 FROM users WHERE phone = ?", (phone,)).fetchone():
            errors.append("这个手机号已经被注册")

        if errors:
            for e in errors:
                flash(e)
        else:
            conn.execute(
                "INSERT INTO users (username, phone, password_hash, nickname, is_admin, "
                "is_active, created_at) VALUES (?, ?, ?, ?, 1, 1, ?)",
                (username, phone, db.hash_password(password), nickname or "管理员", db.now()))
            conn.commit()
            flash(f"管理员 {username} 已创建，可以登录后台了")
        return redirect(url_for("admin.admins"))

    admins = conn.execute("SELECT * FROM users WHERE is_admin = 1 ORDER BY id").fetchall()
    non_admins = conn.execute(
        "SELECT id, username, nickname, phone FROM users WHERE is_admin = 0 AND is_active = 1 "
        "ORDER BY id DESC").fetchall()
    return render_template("admin_admins.html", admins=admins, non_admins=non_admins)


@bp.get("/users.csv")
@admin_required
def users_csv():
    conn = get_db()
    rows = conn.execute("""
        SELECT u.id, u.username, u.nickname, u.phone, u.is_admin, u.is_active,
               u.created_at, u.last_login_at,
               (SELECT COUNT(*) FROM study_days s WHERE s.user_id = u.id) AS days,
               (SELECT COUNT(*) FROM course_progress p WHERE p.user_id = u.id AND p.status='done') AS done,
               (SELECT COUNT(*) FROM challenge_records r WHERE r.user_id = u.id AND r.passed=1) AS passed
        FROM users u ORDER BY u.id""").fetchall()
    data = db.csv_bytes(
        ["ID", "用户名", "昵称", "手机号", "是否管理员", "是否启用", "注册时间", "最后登录",
         "学习天数", "完成课程", "通过挑战"],
        [(r["id"], r["username"], r["nickname"], r["phone"], "是" if r["is_admin"] else "否",
          "是" if r["is_active"] else "否", r["created_at"], r["last_login_at"] or "",
          r["days"], r["done"], r["passed"]) for r in rows])
    return send_file(io.BytesIO(data), mimetype="text/csv", as_attachment=True,
                     download_name="用户与学习数据.csv")


# ---------------------------------------------------------------- 课程

@bp.get("/courses")
@admin_required
def courses():
    conn = get_db()
    rows = conn.execute(
        "SELECT c.*, (SELECT COUNT(*) FROM assignments a WHERE a.course_id = c.id) AS hw_count "
        "FROM courses c ORDER BY c.sort_order, c.id DESC").fetchall()
    return render_template("admin_courses.html", rows=rows)


@bp.route("/courses/new", methods=["GET", "POST"])
@bp.route("/courses/<int:course_id>", methods=["GET", "POST"])
@admin_required
def course_edit(course_id: int | None = None):
    conn = get_db()
    course = conn.execute("SELECT * FROM courses WHERE id = ?", (course_id,)).fetchone() \
        if course_id else None

    if request.method == "POST":
        title = (request.form.get("title") or "").strip()
        if not title:
            flash("课程标题不能为空")
            return redirect(url_for("admin.course_edit", course_id=course_id) if course_id
                            else url_for("admin.courses"))

        source = request.form.get("source") or "editor"
        payload = (
            title,
            (request.form.get("summary") or "").strip(),
            (request.form.get("category") or "").strip(),
            (request.form.get("icon") or "").strip()[:4],
            source,
            request.form.get("content_html") or "",
            1 if request.form.get("is_open") else 0,
        )
        try:
            order = int(request.form.get("sort_order") or 0)
        except ValueError:
            order = 0

        if course:
            conn.execute(
                "UPDATE courses SET title=?, summary=?, category=?, icon=?, source=?, "
                "content_html=?, is_open=?, sort_order=?, updated_at=? WHERE id=?",
                payload + (order, db.now(), course_id))
            target_id = course_id
        else:
            cur = conn.execute(
                "INSERT INTO courses (title, summary, category, icon, source, content_html, "
                "is_open, sort_order, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                payload + (order, db.now()))
            target_id = cur.lastrowid
        conn.commit()

        # 上传课程包（单个 html 或 zip）
        upload = request.files.get("package")
        if upload and upload.filename:
            folder = os.path.join(db.COURSE_DIR, str(target_id))
            os.makedirs(folder, exist_ok=True)
            for old in os.listdir(folder):
                path = os.path.join(folder, old)
                if os.path.isfile(path):
                    os.remove(path)
            tmp_name = f"pkg_{secrets.token_hex(6)}"
            tmp_path = os.path.join(db.COURSE_DIR, tmp_name)
            upload.save(tmp_path)
            try:
                if upload.filename.lower().endswith(".zip"):
                    _safe_extract(tmp_path, folder)
                else:
                    os.replace(tmp_path, os.path.join(folder, "index.html"))
            except Exception as exc:  # noqa: BLE001
                flash(f"课程包处理失败：{exc}")
            finally:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            entry = _find_entry(folder)
            if entry:
                conn.execute(
                    "UPDATE courses SET source='html', entry_path=?, updated_at=? WHERE id=?",
                    (entry, db.now(), target_id))
                conn.commit()
                flash(f"课程包已导入，入口文件：{entry}")
            else:
                flash("课程包里没有找到 .html 文件")
        flash("课程已保存")
        return redirect(url_for("admin.course_edit", course_id=target_id))

    return render_template("admin_course_edit.html", course=course)


@bp.post("/courses/<int:course_id>/delete")
@admin_required
def course_delete(course_id: int):
    conn = get_db()
    # 1) 先删物理文件：视频与课程资料/作业提交都落在 FILE_DIR（按 stored_name 命名）
    for stored_name in conn.execute(
            "SELECT stored_name FROM videos WHERE course_id = ?", (course_id,)).fetchall():
        p = os.path.join(db.FILE_DIR, stored_name["stored_name"])
        if stored_name["stored_name"] and os.path.isfile(p):
            os.remove(p)
    for stored_name in conn.execute(
            "SELECT stored_name FROM files WHERE course_id = ?", (course_id,)).fetchall():
        p = os.path.join(db.FILE_DIR, stored_name["stored_name"])
        if stored_name["stored_name"] and os.path.isfile(p):
            os.remove(p)
    # 2) 删该课程自定义上传的页面目录（COURSE_DIR/<course_id>）
    course_folder = os.path.join(db.COURSE_DIR, str(course_id))
    if os.path.isdir(course_folder):
        shutil.rmtree(course_folder)
    # 3) 再删子表记录：作业、视频、资料（含学生作业提交）、学习进度
    conn.execute("DELETE FROM videos WHERE course_id = ?", (course_id,))
    conn.execute("DELETE FROM assignments WHERE course_id = ?", (course_id,))
    conn.execute("DELETE FROM files WHERE course_id = ?", (course_id,))
    conn.execute("DELETE FROM course_progress WHERE course_id = ?", (course_id,))
    conn.execute("DELETE FROM courses WHERE id = ?", (course_id,))
    conn.commit()
    flash("课程已删除（相关资料、视频、作业与学习进度已一并清除）")
    return redirect(url_for("admin.courses"))


# ---------------------------------------------------------------- 课程作业

@bp.route("/courses/<int:course_id>/assignments", methods=["GET", "POST"])
@admin_required
def course_assignments(course_id: int):
    """给某门课程布置作业。学生交上来的文件在「作业提交」里看。"""
    conn = get_db()
    course = conn.execute("SELECT * FROM courses WHERE id = ?", (course_id,)).fetchone()
    if not course:
        abort(404)

    if request.method == "POST":
        aid = request.form.get("id")
        title = (request.form.get("title") or "").strip()
        description = (request.form.get("description") or "").strip()
        deadline = (request.form.get("deadline") or "").strip()
        is_open = 1 if request.form.get("is_open") else 0
        try:
            order = int(request.form.get("sort_order") or 0)
        except ValueError:
            order = 0

        if not title:
            flash("作业标题不能为空")
        elif aid:
            conn.execute(
                "UPDATE assignments SET title=?, description=?, deadline=?, is_open=?, "
                "sort_order=? WHERE id=? AND course_id=?",
                (title, description, deadline, is_open, order, aid, course_id))
            conn.commit()
            flash("作业已保存")
        else:
            conn.execute(
                "INSERT INTO assignments (course_id, title, description, deadline, is_open, "
                "sort_order, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (course_id, title, description, deadline, is_open, order, db.now()))
            conn.commit()
            flash("作业已布置，学生那边马上就能看到")
        return redirect(url_for("admin.course_assignments", course_id=course_id))

    rows = db.course_assignments(conn, course_id)
    next_order = conn.execute(
        "SELECT COALESCE(MAX(sort_order), 0) + 1 n FROM assignments WHERE course_id = ?",
        (course_id,)).fetchone()["n"]
    return render_template("admin_assignments.html", course=course, rows=rows,
                           next_order=next_order)


@bp.post("/assignments/<int:assignment_id>/delete")
@admin_required
def assignment_delete(assignment_id: int):
    conn = get_db()
    row = conn.execute("SELECT * FROM assignments WHERE id = ?", (assignment_id,)).fetchone()
    if not row:
        abort(404)
    count = conn.execute(
        "SELECT COUNT(*) c FROM files WHERE kind='submission' AND assignment_id = ?",
        (assignment_id,)).fetchone()["c"]
    conn.execute("DELETE FROM assignments WHERE id = ?", (assignment_id,))
    conn.commit()
    if count:
        flash(f"作业已删除。学生已交的 {count} 个文件没有删，仍可在「作业提交」里下载。")
    else:
        flash("作业已删除")
    return redirect(url_for("admin.course_assignments", course_id=row["course_id"]))


@bp.post("/assignments/<int:assignment_id>/toggle")
@admin_required
def assignment_toggle(assignment_id: int):
    conn = get_db()
    row = conn.execute("SELECT * FROM assignments WHERE id = ?", (assignment_id,)).fetchone()
    if not row:
        abort(404)
    opened = 0 if row["is_open"] else 1
    conn.execute("UPDATE assignments SET is_open = ? WHERE id = ?", (opened, assignment_id))
    conn.commit()
    flash("已开放收交" if opened else "已停止收交")
    return redirect(url_for("admin.course_assignments", course_id=row["course_id"]))


# ---------------------------------------------------------------- 课程视频

@bp.route("/courses/<int:course_id>/videos", methods=["GET", "POST"])
@admin_required
def course_videos(course_id: int):
    """上传/管理课程的教学视频，学生在课程页在线观看。"""
    conn = get_db()
    course = conn.execute("SELECT * FROM courses WHERE id = ?", (course_id,)).fetchone()
    if not course:
        abort(404)

    if request.method == "POST":
        vfs = [f for f in request.files.getlist("file") if f and f.filename]
        if not vfs:
            flash("请选择要上传的视频")
        else:
            desc = (request.form.get("description") or "").strip()
            try:
                order = int(request.form.get("sort_order") or 0)
            except ValueError:
                order = 0
            ok = 0
            bad = 0
            for vf in vfs:
                ext = os.path.splitext(vf.filename)[1].lower()
                if ext not in VIDEO_EXT:
                    bad += 1
                    continue
                title = (request.form.get("title") or "").strip() or os.path.basename(vf.filename)
                stored, original, size = save_upload(vf, prefix="vid_")
                duration = format_duration(probe_media_duration(os.path.join(db.FILE_DIR, stored)))
                conn.execute(
                    "INSERT INTO videos (course_id, title, description, stored_name, "
                    "original_name, size, duration, sort_order, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (course_id, title, desc, stored, original, size, duration, order, db.now()))
                order += 1
                ok += 1
            conn.commit()
            msg = f"已上传 {ok} 个视频"
            if bad:
                msg += f"，{bad} 个格式不支持已跳过"
            flash(msg)
        return redirect(url_for("admin.course_videos", course_id=course_id))

    videos = db.course_videos(conn, course_id)
    next_order = conn.execute(
        "SELECT COALESCE(MAX(sort_order), 0) + 1 n FROM videos WHERE course_id = ?",
        (course_id,)).fetchone()["n"]
    return render_template("admin_videos.html", course=course, videos=videos,
                           next_order=next_order, human=_human_size)


@bp.post("/videos/<int:video_id>/delete")
@admin_required
def video_delete(video_id: int):
    conn = get_db()
    row = conn.execute("SELECT * FROM videos WHERE id = ?", (video_id,)).fetchone()
    if not row:
        abort(404)
    # 字幕跟着视频一起走，不然会剩一堆没人认领的文件
    if row["subtitle"]:
        sub_path = os.path.join(db.FILE_DIR, row["subtitle"])
        if os.path.isfile(sub_path):
            try:
                os.remove(sub_path)
            except OSError:
                pass
    path = os.path.join(db.FILE_DIR, row["stored_name"])
    if os.path.isfile(path):
        os.remove(path)
    conn.execute("DELETE FROM videos WHERE id = ?", (video_id,))
    conn.commit()
    flash("视频已删除")
    return redirect(url_for("admin.course_videos", course_id=row["course_id"]))


# ---------------------------------------------------------------- 挑战

@bp.route("/challenges", methods=["GET", "POST"])
@admin_required
def challenges():
    conn = get_db()
    if request.method == "POST":
        challenge_id = request.form.get("id")
        title = (request.form.get("title") or "").strip()
        try:
            difficulty = int(request.form.get("difficulty") or 1)
        except ValueError:
            difficulty = 1
        try:
            order = int(request.form.get("sort_order") or 0)
        except ValueError:
            order = 0
        payload = (title, (request.form.get("summary") or "").strip(),
                   request.form.get("content_html") or "", difficulty,
                   (request.form.get("deadline") or "").strip(),
                   1 if request.form.get("is_open") else 0, order)
        if not title:
            flash("挑战名称不能为空")
        elif challenge_id:
            conn.execute(
                "UPDATE challenges SET title=?, summary=?, content_html=?, difficulty=?, "
                "deadline=?, is_open=?, sort_order=? WHERE id=?",
                payload + (challenge_id,))
            conn.commit()
            flash("挑战已更新")
        else:
            conn.execute(
                "INSERT INTO challenges (title, summary, content_html, difficulty, deadline, "
                "is_open, sort_order, created_at) VALUES (?,?,?,?,?,?,?,?)",
                payload + (db.now(),))
            conn.commit()
            flash("挑战已创建")
        return redirect(url_for("admin.challenges"))

    rows = conn.execute("""
        SELECT c.*, (SELECT COUNT(*) FROM challenge_records r WHERE r.challenge_id = c.id) AS submits,
               (SELECT COUNT(*) FROM challenge_records r WHERE r.challenge_id = c.id AND r.passed=1)
                 AS passed,
               (SELECT COUNT(*) FROM challenge_matches m WHERE m.challenge_id = c.id) AS matches
        FROM challenges c ORDER BY c.sort_order, c.id DESC""").fetchall()
    return render_template("admin_challenges.html", rows=rows)


@bp.get("/challenges/<int:challenge_id>/matches")
@admin_required
def challenge_matches(challenge_id: int):
    conn = get_db()
    challenge = conn.execute("SELECT * FROM challenges WHERE id = ?", (challenge_id,)).fetchone()
    if not challenge:
        abort(404)
    rows = conn.execute(
        "SELECT m.*, h.username AS host_name, h.nickname AS host_nick, "
        "g.username AS guest_name, g.nickname AS guest_nick "
        "FROM challenge_matches m "
        "LEFT JOIN users h ON h.id = m.host_id "
        "LEFT JOIN users g ON g.id = m.guest_id "
        "WHERE m.challenge_id = ? ORDER BY m.id DESC", (challenge_id,)).fetchall()
    return render_template("admin_challenge_matches.html", challenge=challenge, rows=rows)


@bp.get("/challenges/<int:challenge_id>/records")
@admin_required
def challenge_records(challenge_id: int):
    conn = get_db()
    challenge = conn.execute("SELECT * FROM challenges WHERE id = ?", (challenge_id,)).fetchone()
    if not challenge:
        abort(404)
    rows = conn.execute(
        "SELECT r.*, u.username, u.nickname, f.original_name, f.id AS file_id, f.size "
        "FROM challenge_records r LEFT JOIN users u ON u.id = r.user_id "
        "LEFT JOIN files f ON f.id = r.file_id WHERE r.challenge_id = ? ORDER BY r.id DESC",
        (challenge_id,)).fetchall()
    return render_template("admin_challenge_records.html", challenge=challenge, rows=rows,
                           human=_human_size)


@bp.post("/records/<int:record_id>/<action>")
@admin_required
def record_action(record_id: int, action: str):
    conn = get_db()
    record = conn.execute("SELECT * FROM challenge_records WHERE id = ?", (record_id,)).fetchone()
    if not record:
        abort(404)
    if action == "pass":
        conn.execute("UPDATE challenge_records SET passed = 1 WHERE id = ?", (record_id,))
        flash("已标记为通过")
    elif action == "fail":
        conn.execute("UPDATE challenge_records SET passed = 0 WHERE id = ?", (record_id,))
        flash("已标记为未通过")
    else:
        abort(404)
    conn.commit()
    return redirect(request.referrer or url_for("admin.challenges"))


@bp.post("/challenges/<int:challenge_id>/delete")
@admin_required
def challenge_delete(challenge_id: int):
    conn = get_db()
    conn.execute("DELETE FROM challenges WHERE id = ?", (challenge_id,))
    conn.commit()
    flash("挑战已删除")
    return redirect(url_for("admin.challenges"))


# ---------------------------------------------------------------- 资料与作业

@bp.route("/files", methods=["GET", "POST"])
@admin_required
def files():
    conn = get_db()
    if request.method == "POST":
        uploads = [f for f in request.files.getlist("file") if f and f.filename]
        if not uploads:
            flash("请选择要上传的文件")
        else:
            desc = (request.form.get("description") or "").strip()
            category = (request.form.get("category") or "").strip()
            course_id = request.form.get("course_id") or None
            for upload_file in uploads:
                title = (request.form.get("title") or "").strip() or os.path.basename(upload_file.filename)
                stored, original, size = save_upload(upload_file, prefix="res_")
                conn.execute(
                    "INSERT INTO files (kind, title, description, stored_name, original_name, size, "
                    "category, course_id, owner_id, created_at) "
                    "VALUES ('resource', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (title, desc, stored, original, size, category, course_id,
                     current_user()["id"], db.now()))
            conn.commit()
            flash(f"已上传 {len(uploads)} 个资料")
        return redirect(url_for("admin.files"))

    rows = conn.execute(
        "SELECT f.*, c.title AS course_title FROM files f LEFT JOIN courses c ON c.id = f.course_id "
        "WHERE f.kind = 'resource' ORDER BY f.id DESC").fetchall()
    courses = conn.execute("SELECT id, title FROM courses ORDER BY id DESC").fetchall()
    return render_template("admin_files.html", rows=rows, courses=courses, human=_human_size)


@bp.post("/files/<int:file_id>/delete")
@admin_required
def file_delete(file_id: int):
    conn = get_db()
    row = conn.execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone()
    if row:
        path = os.path.join(db.FILE_DIR, row["stored_name"])
        if os.path.isfile(path):
            os.remove(path)
        conn.execute("DELETE FROM files WHERE id = ?", (file_id,))
        conn.commit()
        flash("文件已删除")
    return redirect(request.referrer or url_for("admin.files"))


@bp.get("/submissions")
@admin_required
def submissions():
    conn = get_db()
    user_id = request.args.get("user_id") or ""
    keyword = (request.args.get("q") or "").strip()
    assignment_id = (request.args.get("assignment_id") or "").strip()
    sql = ("SELECT f.*, u.username, u.nickname, ch.title AS challenge_title, "
           "a.title AS assignment_title, c.title AS course_title "
           "FROM files f LEFT JOIN users u ON u.id = f.owner_id "
           "LEFT JOIN challenges ch ON ch.id = f.challenge_id "
           "LEFT JOIN assignments a ON a.id = f.assignment_id "
           "LEFT JOIN courses c ON c.id = f.course_id WHERE f.kind = 'submission'")
    params: list = []
    if user_id.isdigit():
        sql += " AND f.owner_id = ?"
        params.append(int(user_id))
    if assignment_id.isdigit():          # 从作业管理页点「看提交」跳过来
        sql += " AND f.assignment_id = ?"
        params.append(int(assignment_id))
    if keyword:
        sql += " AND (f.title LIKE ? OR f.original_name LIKE ? OR u.username LIKE ?)"
        params += [f"%{keyword}%"] * 3
    sql += " ORDER BY f.id DESC LIMIT 500"
    rows = conn.execute(sql, params).fetchall()
    focus = None
    if assignment_id.isdigit():
        focus = conn.execute("SELECT * FROM assignments WHERE id = ?",
                             (int(assignment_id),)).fetchone()
    return render_template("admin_submissions.html", rows=rows, human=_human_size,
                           keyword=keyword, user_id=user_id, focus=focus)


@bp.get("/submissions.csv")
@admin_required
def submissions_csv():
    conn = get_db()
    rows = conn.execute(
        "SELECT f.id, u.username, u.nickname, f.title, f.original_name, f.size, f.created_at, "
        "ch.title AS challenge_title, a.title AS assignment_title, c.title AS course_title "
        "FROM files f LEFT JOIN users u ON u.id = f.owner_id "
        "LEFT JOIN challenges ch ON ch.id = f.challenge_id "
        "LEFT JOIN assignments a ON a.id = f.assignment_id "
        "LEFT JOIN courses c ON c.id = f.course_id "
        "WHERE f.kind = 'submission' ORDER BY f.id").fetchall()
    data = db.csv_bytes(
        ["ID", "用户名", "昵称", "标题", "文件名", "大小(字节)", "提交时间",
         "所属课程", "关联作业", "关联挑战"],
        [(r["id"], r["username"], r["nickname"], r["title"], r["original_name"], r["size"],
          r["created_at"], r["course_title"] or "", r["assignment_title"] or "",
          r["challenge_title"] or "") for r in rows])
    return send_file(io.BytesIO(data), mimetype="text/csv", as_attachment=True,
                     download_name="作业提交记录.csv")


# ---------------------------------------------------------------- 学习数据

@bp.get("/progress")
@admin_required
def progress():
    conn = get_db()
    rows = conn.execute("""
        SELECT u.id, u.username, u.nickname, u.phone, u.created_at, u.last_login_at,
               (SELECT COUNT(*) FROM study_days s WHERE s.user_id = u.id) AS days,
               (SELECT COUNT(*) FROM course_progress p WHERE p.user_id = u.id AND p.status='done')
                 AS courses_done,
               (SELECT COUNT(*) FROM challenge_records r WHERE r.user_id = u.id AND r.passed=1)
                 AS passed,
               (SELECT COUNT(*) FROM files f WHERE f.owner_id = u.id AND f.kind='submission')
                 AS submissions
        FROM users u ORDER BY days DESC, u.id""").fetchall()
    return render_template("admin_progress.html", rows=rows)


@bp.get("/progress.xlsx")
@admin_required
def progress_xlsx():
    conn = get_db()
    rows = conn.execute("""
        SELECT u.id, u.username, u.nickname, u.phone, u.created_at, u.last_login_at,
               (SELECT COUNT(*) FROM study_days s WHERE s.user_id = u.id) AS days,
               (SELECT COUNT(*) FROM course_progress p WHERE p.user_id = u.id AND p.status='done')
                 AS courses_done,
               (SELECT COUNT(*) FROM challenge_records r WHERE r.user_id = u.id AND r.passed=1)
                 AS passed,
               (SELECT COUNT(*) FROM files f WHERE f.owner_id = u.id AND f.kind='submission')
                 AS submissions
        FROM users u ORDER BY u.id""").fetchall()
    data = [(r["id"], r["username"], r["nickname"] or "", r["phone"], r["created_at"],
             r["last_login_at"] or "", r["days"], r["courses_done"], r["passed"], r["submissions"])
            for r in rows]
    buf = _xlsx("学习数据", ["ID", "用户名", "昵称", "手机号", "注册时间", "最后登录",
                             "学习天数", "完成课程", "通过挑战", "提交作业"], data)
    return send_file(buf, mimetype=XLSX_MIME, as_attachment=True, download_name="学习数据.xlsx")


# ---------------------------------------------------------------- 社区

@bp.get("/posts")
@admin_required
def posts():
    conn = get_db()
    rows = conn.execute(
        "SELECT p.*, u.username, u.nickname, "
        "(SELECT COUNT(*) FROM replies r WHERE r.post_id = p.id) AS reply_count "
        "FROM posts p LEFT JOIN users u ON u.id = p.user_id "
        "ORDER BY p.id DESC LIMIT 500").fetchall()
    return render_template("admin_posts.html", rows=rows)


@bp.post("/posts/<int:post_id>/<action>")
@admin_required
def post_action(post_id: int, action: str):
    conn = get_db()
    if action == "top":
        conn.execute("UPDATE posts SET is_top = 1 - is_top WHERE id = ?", (post_id,))
        flash("已切换置顶状态")
    elif action == "delete":
        conn.execute("DELETE FROM replies WHERE post_id = ?", (post_id,))
        conn.execute("DELETE FROM posts WHERE id = ?", (post_id,))
        flash("帖子已删除")
    else:
        abort(404)
    conn.commit()
    return redirect(url_for("admin.posts"))


# ---------------------------------------------------------------- 导航链接

@bp.route("/links", methods=["GET", "POST"])
@admin_required
def links():
    conn = get_db()
    if request.method == "POST":
        link_id = request.form.get("id")
        group = (request.form.get("group_name") or "常用链接").strip() or "常用链接"
        title = (request.form.get("title") or "").strip()
        url = (request.form.get("url") or "").strip()
        icon = (request.form.get("icon") or "").strip()[:4]
        description = (request.form.get("description") or "").strip()
        try:
            order = int(request.form.get("sort_order") or 0)
        except ValueError:
            order = 0
        if not title or not url:
            flash("名称和网址都不能为空")
        elif link_id:
            conn.execute(
                "UPDATE nav_links SET group_name=?, title=?, url=?, icon=?, description=?, "
                "sort_order=? WHERE id=?", (group, title, url, icon, description, order, link_id))
            conn.commit()
            flash("已保存修改")
        else:
            conn.execute(
                "INSERT INTO nav_links (group_name, title, url, icon, description, sort_order, "
                "created_at) VALUES (?,?,?,?,?,?,?)",
                (group, title, url, icon, description, order, db.now()))
            conn.commit()
            flash("已添加链接")
        return redirect(url_for("admin.links"))

    rows = conn.execute("SELECT * FROM nav_links ORDER BY sort_order, id").fetchall()
    group_names = [r["group_name"] for r in conn.execute(
        "SELECT DISTINCT group_name FROM nav_links ORDER BY group_name").fetchall()]
    next_order = conn.execute(
        "SELECT COALESCE(MAX(sort_order), 0) + 1 n FROM nav_links").fetchone()["n"]
    return render_template("admin_links.html", rows=rows, group_names=group_names,
                           next_order=next_order)


@bp.post("/links/<int:link_id>/delete")
@admin_required
def link_delete(link_id: int):
    conn = get_db()
    conn.execute("DELETE FROM nav_links WHERE id = ?", (link_id,))
    conn.commit()
    flash("已删除链接")
    return redirect(url_for("admin.links"))


# ---------------------------------------------------------------- 公告

@bp.route("/announcements", methods=["GET", "POST"])
@admin_required
def announcements():
    """公告管理：新建 / 编辑 / 上下架 / 删除。

    公告是「一份内容，三端弹窗」：网站（含桌面客户端内嵌的网页）在登录后的
    任意页面弹，安卓 App 走 /api/v1/announcements/latest 弹。
    所以这里只负责内容与开关，不关心客户端怎么展示。
    """
    conn = get_db()
    if request.method == "POST":
        ann_id = (request.form.get("id") or "").strip()
        title = (request.form.get("title") or "").strip()
        body = (request.form.get("body") or "").strip()
        level = db.normalize_level(request.form.get("level"))
        link_text = (request.form.get("link_text") or "").strip()
        link_url = (request.form.get("link_url") or "").strip()
        starts_at = (request.form.get("starts_at") or "").strip()
        ends_at = (request.form.get("ends_at") or "").strip()
        is_active = 1 if request.form.get("is_active") else 0
        popup = 1 if request.form.get("popup") else 0

        if not title:
            flash("标题不能为空")
        elif not body:
            flash("公告内容不能为空")
        elif starts_at and ends_at and starts_at > ends_at:
            flash("生效时间不能晚于失效时间")
        else:
            author = (current_user() or {}).get("nickname") or \
                     (current_user() or {}).get("username") or ""
            if ann_id:
                conn.execute(
                    "UPDATE announcements SET title=?, body=?, level=?, link_text=?, link_url=?, "
                    "is_active=?, popup=?, starts_at=?, ends_at=?, author=?, updated_at=? "
                    "WHERE id=?",
                    (title, body, level, link_text, link_url, is_active, popup,
                     starts_at, ends_at, author, db.now(), ann_id))
                conn.commit()
                flash("公告已保存（用户下次打开会看到更新后的版本）")
            else:
                conn.execute(
                    "INSERT INTO announcements (title, body, level, link_text, link_url, "
                    "is_active, popup, starts_at, ends_at, author, created_at, updated_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (title, body, level, link_text, link_url, is_active, popup,
                     starts_at, ends_at, author, db.now(), db.now()))
                conn.commit()
                flash("公告已发布" + ("，用户下次打开就会弹窗" if (is_active and popup)
                                      else "（当前未开启弹窗）"))
        return redirect(url_for("admin.announcements"))

    rows = conn.execute(
        "SELECT * FROM announcements ORDER BY is_active DESC, id DESC").fetchall()
    # 编辑态：?edit=<id> 时把那条填进右侧表单
    edit_id = request.args.get("edit", type=int)
    editing = None
    if edit_id:
        editing = conn.execute("SELECT * FROM announcements WHERE id=?",
                               (edit_id,)).fetchone()
    return render_template("admin_announcements.html", rows=rows, editing=editing,
                           stats=db.announcement_stats(conn),
                           levels=db.ANNOUNCE_LEVELS,
                           level_labels=db.ANNOUNCE_LEVEL_LABELS,
                           preview=db.announcement_latest(conn))


@bp.post("/announcements/<int:ann_id>/toggle")
@admin_required
def announcement_toggle(ann_id: int):
    """一键上下架。下架后所有客户端立刻不再弹（已弹过的用户不受影响）。"""
    conn = get_db()
    row = conn.execute("SELECT * FROM announcements WHERE id=?", (ann_id,)).fetchone()
    if row is None:
        abort(404)
    new_state = 0 if row["is_active"] else 1
    conn.execute("UPDATE announcements SET is_active=?, updated_at=? WHERE id=?",
                 (new_state, db.now(), ann_id))
    conn.commit()
    flash("已%s公告「%s」" % ("上架" if new_state else "下架", row["title"]))
    return redirect(url_for("admin.announcements"))


@bp.post("/announcements/<int:ann_id>/toggle-popup")
@admin_required
def announcement_toggle_popup(ann_id: int):
    """切换「是否弹窗」：关掉只留档，用户不会再被打扰。"""
    conn = get_db()
    row = conn.execute("SELECT * FROM announcements WHERE id=?", (ann_id,)).fetchone()
    if row is None:
        abort(404)
    new_state = 0 if row["popup"] else 1
    conn.execute("UPDATE announcements SET popup=?, updated_at=? WHERE id=?",
                 (new_state, db.now(), ann_id))
    conn.commit()
    flash("公告「%s」弹窗已%s" % (row["title"], "开启" if new_state else "关闭"))
    return redirect(url_for("admin.announcements"))


@bp.post("/announcements/<int:ann_id>/delete")
@admin_required
def announcement_delete(ann_id: int):
    conn = get_db()
    row = conn.execute("SELECT title FROM announcements WHERE id=?", (ann_id,)).fetchone()
    conn.execute("DELETE FROM announcements WHERE id=?", (ann_id,))
    conn.commit()
    flash("已删除公告「%s」" % (row["title"] if row else ann_id))
    return redirect(url_for("admin.announcements"))


# ---------------------------------------------------------------- 激活码

@bp.route("/codes", methods=["GET", "POST"])
@admin_required
def codes():
    """生成 / 管理课程激活码：可指定解锁范围（全部课程 / 若干标签 / 指定课程）。

    范围决定成员输码后能看哪些课；没被覆盖的课程在列表里显示为🔒。
    一个成员可以累加多个码（比如「网络基础」标签的码 + 某门单独课的码）。
    """
    conn = get_db()
    new_codes: list[str] = []
    if request.method == "POST":
        try:
            count = int(request.form.get("count") or 1)
        except ValueError:
            count = 1
        note = (request.form.get("note") or "").strip()[:60]
        scope_kind = (request.form.get("scope_kind") or "all").strip()
        categories = request.form.getlist("categories")
        course_ids = request.form.getlist("course_ids")
        try:
            new_codes = db.create_codes(conn, current_user()["id"], count, note,
                                        scope_kind=scope_kind,
                                        categories=categories, course_ids=course_ids)
            scope = ("全部课程" if scope_kind != "limited"
                     else " + ".join(x for x in [
                         "、".join(categories) if categories else "",
                         "指定 %d 门课程" % len(course_ids) if course_ids else ""] if x))
            flash(f"已生成 {len(new_codes)} 个激活码（范围：{scope}）。"
                  f"每个码只能绑定一个账号，复制发给成员即可。")
        except ValueError as exc:
            flash(str(exc))

    rows = conn.execute(
        "SELECT c.*, u.username AS used_by_name, u.nickname AS used_by_nick, "
        "a.username AS created_by_name "
        "FROM activation_codes c "
        "LEFT JOIN users u ON u.id = c.used_by "
        "LEFT JOIN users a ON a.id = c.created_by "
        "ORDER BY c.id DESC").fetchall()
    used = sum(1 for r in rows if r["used_by"])
    # 分组给表单用：标签 → 该标签下的课程
    course_rows = conn.execute(
        "SELECT id, title, category FROM courses WHERE is_open = 1 "
        "ORDER BY category, sort_order, id").fetchall()
    cats = sorted({(r["category"] or "").strip() for r in course_rows if (r["category"] or "").strip()})
    by_cat = {c: [r for r in course_rows if (r["category"] or "").strip() == c] for c in cats}
    no_cat = [r for r in course_rows if not (r["category"] or "").strip()]
    # 列表里显示范围：把 JSON 解析成人话
    scope_labels = {r["id"]: db.code_scope_label(r) for r in rows}
    return render_template("admin_codes.html", rows=rows, new_codes=new_codes,
                           total=len(rows), used=used, unused=len(rows) - used,
                           cats=cats, by_cat=by_cat, no_cat=no_cat,
                           course_rows=course_rows, scope_labels=scope_labels)


@bp.post("/codes/<int:code_id>/delete")
@admin_required
def code_delete(code_id: int):
    """删除激活码。已绑定的码也能删——删掉后该成员立刻失去「课程资料」权限。"""
    conn = get_db()
    row = conn.execute(
        "SELECT c.*, u.nickname AS used_by_nick, u.username AS used_by_name "
        "FROM activation_codes c LEFT JOIN users u ON u.id = c.used_by "
        "WHERE c.id = ?", (code_id,)).fetchone()
    if not row:
        abort(404)
    conn.execute("DELETE FROM activation_codes WHERE id = ?", (code_id,))
    conn.commit()
    if row["used_by"]:
        who = row["used_by_nick"] or row["used_by_name"] or "该成员"
        flash(f"已删除激活码 {row['code']}：{who} 现在无法再进入「课程资料」，"
              f"想恢复的话重新发一个码给他即可。")
    else:
        flash("已删除这个未使用的激活码")
    return redirect(url_for("admin.codes"))


# ---------------------------------------------------------------- 设置与备份

@bp.route("/settings", methods=["GET", "POST"])
@admin_required
def settings():
    conn = get_db()
    if request.method == "POST":
        # 页面上有两张独立的表单，只更新当前提交的那一张，避免互相清空
        if "site_title" in request.form:
            for key in ("site_title", "site_subtitle", "site_intro", "hero_tag", "hero_title",
                        "hero_desc", "contact_info"):
                db.set_setting(conn, key, (request.form.get(key) or "").strip())
            db.set_setting(conn, "register_open",
                           "1" if request.form.get("register_open") else "0")
        if "icp_number" in request.form:
            for key in ("footer_links_title", "icp_number", "police_number"):
                db.set_setting(conn, key, (request.form.get(key) or "").strip())
        if "join_intro" in request.form:
            for key in ("join_intro", "join_points", "group_number"):
                db.set_setting(conn, key, (request.form.get(key) or "").strip())
            db.set_setting(conn, "join_open",
                           "1" if request.form.get("join_open") else "0")
            _save_group_qrcode(conn, request.files.get("qrcode"))
        flash("设置已保存")
        return redirect(url_for("admin.settings"))
    return render_template("admin_settings.html")


QR_ALLOWED_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp"}


def _save_group_qrcode(conn, file_storage) -> None:
    """保存官方群二维码；同名覆盖，并在 URL 后带版本号避免浏览器缓存。"""
    if not file_storage or not file_storage.filename:
        return
    ext = os.path.splitext(file_storage.filename)[1].lower()
    if ext not in QR_ALLOWED_EXT:
        flash("二维码只支持 png / jpg / gif / webp 图片")
        return
    os.makedirs(db.UPLOAD_DIR, exist_ok=True)
    name = f"group_qrcode{ext}"
    for old in os.listdir(db.UPLOAD_DIR):        # 换格式时删掉旧文件
        if old.startswith("group_qrcode.") and old != name:
            try:
                os.remove(os.path.join(db.UPLOAD_DIR, old))
            except OSError:
                pass
    file_storage.save(os.path.join(db.UPLOAD_DIR, name))
    db.set_setting(conn, "group_qrcode", f"/uploads/{name}?v={secrets.token_hex(4)}")
    flash("群二维码已更新")


@bp.get("/backup")
@admin_required
def backup():
    """用 mysqldump 把当前 MySQL 库导出成 .sql 文件下载。"""
    import tempfile

    stamp = db.now().replace(":", "").replace(" ", "-")
    fd, path = tempfile.mkstemp(suffix=".sql", prefix=f"netlab-{stamp}-")
    os.close(fd)

    cmd = [
        "mysqldump",
        "-h", db.MYSQL["host"],
        "-P", str(db.MYSQL["port"]),
        "-u", db.MYSQL["user"],
        "--default-character-set=utf8mb4",
        "--single-transaction",
        "--routines",
        "--no-tablespaces",
        "--skip-lock-tables",
        "--password=%s" % (db.MYSQL["password"] or ""),
        db.MYSQL["database"],
    ]
    try:
        with open(path, "w", encoding="utf-8") as fh:
            subprocess.run(cmd, stdout=fh, stderr=subprocess.PIPE, check=True)
    except Exception as exc:                       # noqa: BLE001
        try:
            os.remove(path)
        except OSError:
            pass
        stderr = getattr(exc, "stderr", None)
        detail = stderr.decode("utf-8", "replace") if stderr else str(exc)
        flash("数据库备份失败：%s" % detail)
        return redirect(url_for("admin.settings"))

    resp = send_file(path, mimetype="application/sql", as_attachment=True,
                     download_name=f"netlab-{stamp}.sql")

    @after_this_request
    def _cleanup(response):
        try:
            os.remove(path)
        except OSError:
            pass
        return response

    return resp


# ================================================================ 服务管理
# 这两个服务是「按需启动」的：默认不跑（容器 restart=no），需要时在后台一键开启，
# 用完关掉，避免常驻把 1.6G 内存吃满导致整站卡死。

SERVICE_DEFS = [
    {
        "key": "surveyking",
        "container": "surveyking",
        "label": "考试系统",
        "sub": "SurveyKing · 在线考试 / 问卷",
        "desc": "Java 应用，启动后约占用 400MB 内存。不用时建议关闭。",
        "url": "https://exam.your-server.example.com",
        "mem_need": 450,
        "heavy": True,
    },
    {
        "key": "portainer",
        "container": "portainer",
        "label": "Docker 管理面板",
        "sub": "Portainer CE · 容器图形化管理",
        "desc": "图形化查看与管理服务器上的容器（英文界面）。占用内存较小。",
        "url": "https://docker.your-server.example.com",
        "mem_need": 150,
        "heavy": False,
    },
]

_SVC_BIN = "/usr/local/bin/netlab-service"

_SVC_LABEL = {
    "running": ("运行中", "badge-ok"),
    "exited": ("已停止", "badge-bad"),
    "created": ("未启动", "badge-bad"),
    "restarting": ("启动中…", "badge-warn"),
    "paused": ("已暂停", "badge-warn"),
    "missing": ("未安装", "badge-bad"),
    "unknown": ("状态未知", "badge-warn"),
}


def _mem_snapshot():
    """读 /proc/meminfo，返回以 MB 为单位的内存概况。"""
    info = {}
    try:
        with open("/proc/meminfo", encoding="utf-8") as fh:
            for line in fh:
                parts = line.split()
                if len(parts) >= 2:
                    try:
                        info[parts[0].rstrip(":")] = int(parts[1])
                    except ValueError:
                        continue
    except OSError:
        return None
    if "MemTotal" not in info:
        return None
    total = info["MemTotal"] // 1024
    avail = info.get("MemAvailable", info.get("MemFree", 0)) // 1024
    swap_total = info.get("SwapTotal", 0) // 1024
    swap_free = info.get("SwapFree", 0) // 1024
    return {
        "total": total,
        "available": avail,
        "used": total - avail,
        "used_pct": round((total - avail) * 100 / total) if total else 0,
        "swap_total": swap_total,
        "swap_used": swap_total - swap_free,
    }


_DATA_DIR_PROBE = "/opt/websystem/data/files"   # 教学视频/资料/云盘/作业等大文件的落盘目录
_DATA_MOUNT = "/opt/websystem"                  # 数据盘真实挂载点（fstab: LABEL=netlab-data）


def _disk_snapshot():
    """读两块盘的使用情况：系统盘（/）与数据盘（放大文件的那块）。

    数据盘用 nofail 挂载，万一开机没挂上，/opt/websystem/data/files 会回落到系统盘上，
    页面就必须把它标出来（否则管理员会以为空间还很足，其实在吃系统盘）。

    判定方式：比较 st_dev 是否与 / 相同 —— 不同即为独立的一块盘。

    为什么不用 os.path.ismount(探测目录)：挂载点是 /opt/websystem，
    而探测目录是它的子目录 /opt/websystem/data/files，ismount 对子目录恒为 False，
    于是盘挂得好好的页面也一直报"未挂载"。（这就是之前那个显示 bug 的根因。）
    """
    def one(path):
        try:
            u = shutil.disk_usage(path)
        except OSError:
            return None
        total = u.total
        return {
            "total": total,
            "used": u.used,
            "free": u.free,
            "used_pct": round(u.used * 100 / total) if total else 0,
        }

    root = one("/")
    if root is None:
        return None

    # 探测目录不存在时，退到它的挂载点再判一次，避免误报
    probe = _DATA_DIR_PROBE
    if not os.path.exists(probe):
        probe = _DATA_MOUNT
    try:
        mounted = os.stat(probe).st_dev != os.stat("/").st_dev
    except OSError:
        mounted = False

    return {
        "root": root,
        "data": one(probe) if mounted else None,
        "data_mounted": mounted,
        "data_path": probe,
    }


def _svc_status(container: str) -> str:
    """查容器状态：running / exited / created / missing / unknown。"""
    try:
        r = subprocess.run(["sudo", "-n", _SVC_BIN, "status", container],
                           capture_output=True, text=True, timeout=15)
        out = (r.stdout or "").strip().splitlines()
        if r.returncode == 0 and out:
            return out[-1].strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return "unknown"


@bp.get("/services")
@admin_required
def services():
    items = []
    for d in SERVICE_DEFS:
        it = dict(d)
        st = _svc_status(d["container"])
        it["status"] = st
        it["status_label"], it["status_cls"] = _SVC_LABEL.get(st, ("状态未知", "badge-warn"))
        items.append(it)
    return render_template("admin_services.html", items=items, mem=_mem_snapshot(),
                           disk=_disk_snapshot())


@bp.post("/services/<key>/<action>")
@admin_required
def service_action(key: str, action: str):
    d = next((x for x in SERVICE_DEFS if x["key"] == key), None)
    if not d or action not in ("start", "stop", "restart"):
        abort(404)

    # 启动 / 重启前先看内存够不够，不够就直接拦下（保护服务器）
    if action in ("start", "restart"):
        mem = _mem_snapshot()
        need = d.get("mem_need", 400)
        if mem and mem["available"] < need:
            flash(f"可用内存只有 {mem['available']}MB，不足以启动「{d['label']}」"
                  f"（建议至少留 {need}MB）。请先关闭其它服务再试。")
            return redirect(url_for("admin.services"))

    try:
        r = subprocess.run(["sudo", "-n", _SVC_BIN, action, d["container"]],
                           capture_output=True, text=True, timeout=180)
    except subprocess.TimeoutExpired:
        flash(f"「{d['label']}」操作超时，请稍后刷新查看状态。")
        return redirect(url_for("admin.services"))
    except OSError as exc:
        flash(f"无法执行服务控制命令：{exc}")
        return redirect(url_for("admin.services"))

    if r.returncode == 0:
        verb = {"start": "启动", "stop": "关闭", "restart": "重启"}[action]
        if action == "start":
            flash(f"已{verb}「{d['label']}」，约需 10-30 秒才能访问（首次启动更久）")
        else:
            flash(f"已{verb}「{d['label']}」")
    else:
        err = (r.stderr or r.stdout or "未知错误").strip().splitlines()
        flash(f"操作失败：{err[-1][:180] if err else '未知错误'}")
    return redirect(url_for("admin.services"))



# ---------------------------------------------------------------- App 版本管理

# 桌面客户端渠道：windows=安装版（NSIS），windows-portable=绿色版（免安装单文件）
WINDOWS_PLATFORMS = ("windows", "windows-portable")
MAC_PLATFORMS = ("mac", "macos")


def _sha512_of(path: str) -> str:
    """计算文件 sha512（hex）。客户端下载完安装包后按这个值校验完整性。"""
    digest = hashlib.sha512()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _app_static_dir() -> str:
    app_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "app")
    os.makedirs(app_dir, exist_ok=True)
    return app_dir


@bp.get("/appversion")
@admin_required
def app_version_list():
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM app_versions ORDER BY platform ASC, version_code DESC, id DESC"
    ).fetchall()
    return render_template(
        "admin_appversion.html",
        rows=rows,
        platform_labels=db.APP_PLATFORM_LABELS,
    )


@bp.post("/appversion")
@admin_required
def app_version_publish():
    conn = get_db()
    platform = db.normalize_platform(request.form.get("platform") or "android")
    version_name = (request.form.get("version_name") or "").strip()
    release_notes = (request.form.get("release_notes") or "").strip()
    upload = request.files.get("package") or request.files.get("apk")
    is_windows = platform in WINDOWS_PLATFORMS
    is_mac = platform in MAC_PLATFORMS

    if is_windows or is_mac:
        # Windows / macOS 的版本号由版本名推导（1.3.0 -> 1003000），不让人工填整数，
        # 从根上避免「填错整数 → 客户端反复提示更新」这类问题。
        vc = db.semver_code(version_name)
        if vc <= 0:
            flash("%s 的版本名必须形如 1.3.0（三段式），如 1.10.2" % ("macOS" if is_mac else "Windows"))
            return redirect(url_for("admin.app_version_list"))
    else:
        version_code = (request.form.get("version_code") or "").strip()
        if not version_code.isdigit() or not version_name:
            flash("请填写正确的版本号（整数）和版本名")
            return redirect(url_for("admin.app_version_list"))
        vc = int(version_code)

    if upload is None or not upload.filename:
        flash("请上传安装包")
        return redirect(url_for("admin.app_version_list"))

    app_dir = _app_static_dir()

    # 磁盘上的文件名统一按「渠道 + 版本名」推导，不用用户上传时的原名。
    #
    # 原因有两个：
    #   1) 安装包原始名字常常含中文（如「教学管理系统-安装版-1.4.8.exe」），
    #      直接当文件名会让 download_url 里出现百分号转义，各客户端处理起来不一致；
    #   2) 以前后台自己拼的是 teaching-system-v19.apk / teaching-system-desktop-setup-v1004008.exe，
    #      而线上实际文件是 teaching-system-android-v1.18.apk / teaching-system-win-setup-v1.4.8.exe，
    #      两套命名并存 → 每次发版都多出一个名字不同的文件，旧包永远不会被覆盖。
    # 现在统一成下面这套（与线上现存文件一致，安卓/Windows 会直接覆盖同名旧文件）。
    ext = os.path.splitext(upload.filename)[1].lower()
    if is_mac:
        if ext != ".dmg":
            flash("macOS 版本请上传 .dmg 安装包")
            return redirect(url_for("admin.app_version_list"))
        safe_name = "teaching-system-mac-v%s.dmg" % version_name
    elif is_windows:
        if ext != ".exe":
            flash("Windows 版本请上传 .exe 安装包")
            return redirect(url_for("admin.app_version_list"))
        flavor = "portable" if platform == "windows-portable" else "setup"
        safe_name = "teaching-system-win-%s-v%s.exe" % (flavor, version_name)
    else:
        if ext != ".apk":
            flash("安卓版本请上传 .apk 安装包")
            return redirect(url_for("admin.app_version_list"))
        safe_name = "teaching-system-android-v%s.apk" % version_name

    # file_name 保留上传时的原始名字，用作展示名（下载页「完整文件名」那一栏）
    display_name = upload.filename
    dest = os.path.join(app_dir, safe_name)
    upload.save(dest)

    if is_mac:
        # dmg 没解析器，只做最基础的体积检查：macOS 客户端不可能小于 1MB
        if os.path.getsize(dest) < 1024 * 1024:
            try:
                os.remove(dest)
            except OSError:
                pass
            flash("这不是有效的 .dmg（文件过小）")
            return redirect(url_for("admin.app_version_list"))
    elif is_windows:
        # 只做最基本的 PE 头与体积检查：确认传的是真正的 Windows 可执行文件
        with open(dest, "rb") as fh:
            head = fh.read(2)
        if head != b"MZ" or os.path.getsize(dest) < 1024 * 1024:
            try:
                os.remove(dest)
            except OSError:
                pass
            flash("这不是有效的 Windows 安装包（缺少 PE 头或文件过小）")
            return redirect(url_for("admin.app_version_list"))
    else:
        # 校验 APK 内部真实版本号，防止误传旧包或版本号填错（否则客户端会陷入反复提示更新的死循环）
        try:
            from pyaxmlparser import APK as _Apk
            _apk = _Apk(dest)
            real_vc = int(_apk.version_code)
            real_vn = str(_apk.version_name)
        except Exception as e:
            try:
                os.remove(dest)
            except OSError:
                pass
            flash("APK 解析失败，请确认上传的是有效安装包（%s）" % e)
            return redirect(url_for("admin.app_version_list"))
        if real_vc != vc or real_vn != version_name:
            try:
                os.remove(dest)
            except OSError:
                pass
            flash("版本不一致：APK 内部实际是 v%s (versionCode=%s)，与填写的 v%s (versionCode=%s) 不符。请先修改 build.gradle.kts 的 versionCode/versionName 并重新构建，再上传。" % (real_vn, real_vc, version_name, vc))
            return redirect(url_for("admin.app_version_list"))

    file_size = os.path.getsize(dest)
    sha512 = _sha512_of(dest)

    # is_latest 只在同一 platform 内互斥，切最新版必须带上平台条件
    conn.execute("UPDATE app_versions SET is_latest = 0 WHERE platform = ?", (platform,))
    conn.execute(
        "INSERT INTO app_versions (version_code, version_name, release_notes, "
        "file_name, file_size, download_url, is_latest, created_at, platform, sha512) "
        "VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?)",
        (vc, version_name, release_notes, display_name, file_size,
         "/static/app/" + safe_name, db.now(), platform, sha512),
    )
    conn.commit()
    label = db.APP_PLATFORM_LABELS.get(platform, platform)
    flash("已发布 %s v%s（%s）" % (label, version_name, _human_size(file_size)))
    return redirect(url_for("admin.app_version_list"))


@bp.post("/appversion/<int:vid>/latest")
@admin_required
def app_version_latest(vid):
    conn = get_db()
    row = conn.execute("SELECT * FROM app_versions WHERE id = ?", (vid,)).fetchone()
    if row is None:
        abort(404)
    platform = db.normalize_platform(row["platform"])
    conn.execute("UPDATE app_versions SET is_latest = 0 WHERE platform = ?", (platform,))
    conn.execute("UPDATE app_versions SET is_latest = 1 WHERE id = ?", (vid,))
    conn.commit()
    flash("已把 %s v%s 设为该渠道最新版本" % (
        db.APP_PLATFORM_LABELS.get(platform, platform), row["version_name"]))
    return redirect(url_for("admin.app_version_list"))


@bp.post("/appversion/<int:vid>/delete")
@admin_required
def app_version_delete(vid):
    conn = get_db()
    row = conn.execute("SELECT * FROM app_versions WHERE id = ?", (vid,)).fetchone()
    if row:
        platform = db.normalize_platform(row["platform"])
        was_latest = bool(row["is_latest"])
        try:
            rel = (row["download_url"] or "").lstrip("/")
            path = os.path.join(os.path.dirname(os.path.abspath(__file__)), rel)
            if os.path.exists(path):
                os.remove(path)
            # 顺手清掉下载页按需生成的 zip 缓存，别在 static/app 里留孤儿
            zpath = os.path.splitext(path)[0] + ".zip"
            if os.path.exists(zpath):
                os.remove(zpath)
        except Exception:
            pass
        conn.execute("DELETE FROM app_versions WHERE id = ?", (vid,))
        # 删掉的是最新版时，把该渠道里版本号最高的那条顶上来，避免下载页空置
        if was_latest:
            heir = conn.execute(
                "SELECT * FROM app_versions WHERE platform = ? "
                "ORDER BY version_code DESC, id DESC LIMIT 1",
                (platform,),
            ).fetchone()
            if heir is not None:
                conn.execute("UPDATE app_versions SET is_latest = 1 WHERE id = ?", (heir["id"],))
        conn.commit()
        flash("已删除该版本")
    return redirect(url_for("admin.app_version_list"))


# ---------------------------------------------------------------- 批量删除
# 通用多选 / 全选删除：前端在列表容器上标 data-batch-entity，勾选后 POST 到这里。
# 删除逻辑与单条删除完全一致（含磁盘文件清理、外键级联、最新版本继承等），
# 只是把循环跑了一遍，避免再写 9 个重复接口。
BATCH_ENTITIES = {
    "course":       ("courses",         "课程"),
    "assignment":    ("assignments",     "作业"),
    "video":        ("videos",          "视频"),
    "file":         ("files",           "资料"),
    "challenge":    ("challenges",      "挑战"),
    "link":         ("nav_links",       "链接"),
    "announcement": ("announcements",   "公告"),
    "code":         ("activation_codes", "激活码"),
    "appversion":   ("app_versions",    "版本"),
}


def _safe_remove(path: str) -> None:
    try:
        if os.path.isfile(path):
            os.remove(path)
    except OSError:
        pass


def _remove_entity(conn, entity: str, eid: int) -> int:
    """删除单个实体（与单条删除等价的清理逻辑）。返回删除条数（0 或 1）。"""
    if entity == "course":
        for sn in conn.execute("SELECT stored_name FROM videos WHERE course_id=?", (eid,)):
            _safe_remove(os.path.join(db.FILE_DIR, sn["stored_name"]))
        for sn in conn.execute("SELECT stored_name FROM files WHERE course_id=?", (eid,)):
            _safe_remove(os.path.join(db.FILE_DIR, sn["stored_name"]))
        folder = os.path.join(db.COURSE_DIR, str(eid))
        if os.path.isdir(folder):
            shutil.rmtree(folder)
        conn.execute("DELETE FROM videos WHERE course_id=?", (eid,))
        conn.execute("DELETE FROM assignments WHERE course_id=?", (eid,))
        conn.execute("DELETE FROM files WHERE course_id=?", (eid,))
        conn.execute("DELETE FROM course_progress WHERE course_id=?", (eid,))
        conn.execute("DELETE FROM courses WHERE id=?", (eid,))
        return 1
    if entity == "assignment":
        conn.execute("DELETE FROM assignments WHERE id=?", (eid,))
        return 1
    if entity == "video":
        row = conn.execute("SELECT * FROM videos WHERE id=?", (eid,)).fetchone()
        if not row:
            return 0
        if row["subtitle"]:
            _safe_remove(os.path.join(db.FILE_DIR, row["subtitle"]))
        _safe_remove(os.path.join(db.FILE_DIR, row["stored_name"]))
        conn.execute("DELETE FROM videos WHERE id=?", (eid,))
        return 1
    if entity == "file":
        row = conn.execute("SELECT * FROM files WHERE id=?", (eid,)).fetchone()
        if not row:
            return 0
        _safe_remove(os.path.join(db.FILE_DIR, row["stored_name"]))
        conn.execute("DELETE FROM files WHERE id=?", (eid,))
        return 1
    if entity == "challenge":
        conn.execute("DELETE FROM challenges WHERE id=?", (eid,))
        return 1
    if entity == "link":
        conn.execute("DELETE FROM nav_links WHERE id=?", (eid,))
        return 1
    if entity == "announcement":
        conn.execute("DELETE FROM announcements WHERE id=?", (eid,))
        return 1
    if entity == "code":
        conn.execute("DELETE FROM activation_codes WHERE id=?", (eid,))
        return 1
    if entity == "appversion":
        row = conn.execute("SELECT * FROM app_versions WHERE id=?", (eid,)).fetchone()
        if not row:
            return 0
        platform = db.normalize_platform(row["platform"])
        was_latest = bool(row["is_latest"])
        rel = (row["download_url"] or "").lstrip("/")
        base = os.path.dirname(os.path.abspath(__file__))
        _safe_remove(os.path.join(base, rel))
        _safe_remove(os.path.splitext(os.path.join(base, rel))[0] + ".zip")
        conn.execute("DELETE FROM app_versions WHERE id=?", (eid,))
        if was_latest:
            heir = conn.execute(
                "SELECT * FROM app_versions WHERE platform=? "
                "ORDER BY version_code DESC, id DESC LIMIT 1", (platform,)).fetchone()
            if heir is not None:
                conn.execute("UPDATE app_versions SET is_latest=1 WHERE id=?", (heir["id"],))
        return 1
    return 0


@bp.post("/batch-delete")
@admin_required
def batch_delete():
    entity = request.form.get("entity")
    if entity not in BATCH_ENTITIES:
        abort(400)
    raw = request.form.get("ids", "")
    try:
        ids = [int(x) for x in raw.split(",") if x.strip()]
    except ValueError:
        abort(400)
    if not ids:
        flash("没有选中任何项")
        return redirect(request.referrer or url_for("admin.dashboard"))
    conn = get_db()
    deleted = 0
    for i in ids:
        deleted += _remove_entity(conn, entity, i)
    conn.commit()
    flash(f"已批量删除 {deleted} 个{BATCH_ENTITIES[entity][1]}")
    return redirect(request.referrer or url_for("admin.dashboard"))


# ---------------------------------------------------------------- 视频字幕管理
# 由 patch_subtitle.py 追加
import subtitle as subtitle_mod


@bp.post("/videos/<int:video_id>/subtitle")
@admin_required
def video_subtitle_upload(video_id: int):
    """给视频挂字幕（.vtt / .srt）。网站播放器和 App 都会显示它。"""
    conn = get_db()
    row = conn.execute("SELECT * FROM videos WHERE id = ?", (video_id,)).fetchone()
    if not row:
        abort(404)
    back = url_for("admin.course_videos", course_id=row["course_id"])

    f = request.files.get("subtitle")
    if not f or not f.filename:
        flash("请选择字幕文件")
        return redirect(back)
    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in subtitle_mod.SUBTITLE_EXT:
        flash("字幕只支持 .vtt 或 .srt 格式")
        return redirect(back)

    # 先落盘再改库里的引用，避免旧字幕还在被播放时就被删了
    stored, original = subtitle_mod.save_subtitle(f, db.FILE_DIR)
    old = row["subtitle"]
    conn.execute("UPDATE videos SET subtitle = ?, subtitle_name = ? WHERE id = ?",
                 (stored, original, video_id))
    conn.commit()
    if old:
        old_path = os.path.join(db.FILE_DIR, old)
        if os.path.isfile(old_path):
            try:
                os.remove(old_path)
            except OSError:
                pass
    flash("字幕已上传：" + original)
    return redirect(back)


@bp.post("/videos/<int:video_id>/subtitle/delete")
@admin_required
def video_subtitle_delete(video_id: int):
    conn = get_db()
    row = conn.execute("SELECT * FROM videos WHERE id = ?", (video_id,)).fetchone()
    if not row:
        abort(404)
    old = row["subtitle"]
    conn.execute("UPDATE videos SET subtitle = '', subtitle_name = '' WHERE id = ?", (video_id,))
    conn.commit()
    if old:
        old_path = os.path.join(db.FILE_DIR, old)
        if os.path.isfile(old_path):
            try:
                os.remove(old_path)
            except OSError:
                pass
    flash("字幕已删除")
    return redirect(url_for("admin.course_videos", course_id=row["course_id"]))
