"""注册 / 登录 / 退出 / 找回密码。

登录支持「用户名」或「手机号」；失败时统一提示，不区分是账号错还是密码错
（避免被用来枚举已注册手机号），并引导用户联系管理员。

找回密码是两步式：先认账号，再核对身份 + 原密码。详见 forgot() 的注释。
"""
from __future__ import annotations

import re

from flask import (Blueprint, flash, jsonify, redirect, render_template, request, send_file,
                   session, url_for)

import db
import throttle
from core import current_user, get_db, login_user, logout_user

bp = Blueprint("auth", __name__)

USERNAME_RE = re.compile(r"^[A-Za-z0-9_\u4e00-\u9fa5]{3,20}$")
PHONE_RE = re.compile(r"^1[3-9]\d{9}$")
STUDENT_RE = re.compile(r"^[A-Za-z0-9]{4,30}$")

LOGIN_FAILED = "用户名 / 手机号或密码不正确。若忘记密码请联系系统管理员。"


@bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user():
        return redirect(url_for("main.home"))
    conn = get_db()
    if db.get_setting(conn, "register_open", "1") != "1":
        return render_template("register.html", closed=True)

    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        phone = (request.form.get("phone") or "").strip()
        student_no = (request.form.get("student_no") or "").strip()
        password = request.form.get("password") or ""
        confirm = request.form.get("confirm") or ""
        nickname = (request.form.get("nickname") or "").strip()[:20]

        errors = []
        if not USERNAME_RE.match(username):
            errors.append("用户名需 3-20 位，可用中文、字母、数字、下划线")
        if not PHONE_RE.match(phone):
            errors.append("请填写 11 位手机号")
        if not STUDENT_RE.match(student_no):
            errors.append("请填写正确的学号（4-30 位字母或数字）")
        if len(password) < 6:
            errors.append("密码至少 6 位")
        if password != confirm:
            errors.append("两次输入的密码不一致")
        if not errors:
            if conn.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
                errors.append("这个用户名已经被注册了")
            elif conn.execute("SELECT 1 FROM users WHERE phone = ?", (phone,)).fetchone():
                errors.append("这个手机号已经被注册了")
            elif conn.execute("SELECT 1 FROM users WHERE student_no = ?", (student_no,)).fetchone():
                errors.append("这个学号已经被注册了")

        if errors:
            return render_template("register.html", errors=errors,
                                   form={"username": username, "phone": phone,
                                         "student_no": student_no, "nickname": nickname})

        cur = conn.execute(
            "INSERT INTO users (username, phone, student_no, password_hash, nickname, is_active, created_at) "
            "VALUES (?, ?, ?, ?, ?, 1, ?)",
            (username, phone, student_no, db.hash_password(password), nickname, db.now()))
        conn.commit()
        user = conn.execute("SELECT * FROM users WHERE id = ?", (cur.lastrowid,)).fetchone()
        login_user(user)
        db.record_study_day(conn, user["id"])
        flash("注册成功，欢迎加入！")
        return redirect(url_for("main.me"))

    return render_template("register.html", form={})


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user():
        return redirect(url_for("main.home"))
    conn = get_db()

    if request.method == "POST":
        identifier = (request.form.get("identifier") or "").strip()
        password = request.form.get("password") or ""

        # 防爆破：同一个 IP 打同一个账号 5 分钟最多 8 次
        wait = throttle.login_gate(identifier or "-")
        if wait:
            return render_template(
                "login.html", identifier=identifier,
                error=f"尝试太频繁了，请等 {wait} 秒后再试。",
            ), 429

        row = conn.execute(
            "SELECT * FROM users WHERE username = ? OR phone = ? OR student_no = ?", (identifier, identifier, identifier)
        ).fetchone()

        if row and row["is_active"] and db.verify_password(password, row["password_hash"]):
            throttle.login_ok(identifier)
            login_user(row)
            conn.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (db.now(), row["id"]))
            conn.commit()
            db.record_study_day(conn, row["id"])
            nxt = request.args.get("next") or url_for("main.me")
            return redirect(nxt if nxt.startswith("/") else url_for("main.me"))

        return render_template("login.html", identifier=identifier, error=LOGIN_FAILED)

    return render_template("login.html")


@bp.get("/logout")
def logout():
    logout_user()
    return redirect(url_for("main.home"))


# ---------------------------------------------------------------- 找回密码

FORGOT_SESSION_KEY = "forgot_uid"


def _find_account(identifier: str):
    """按 用户名 / 手机号 / 学号 找账号。"""
    return get_db().execute(
        "SELECT * FROM users WHERE username = ? OR phone = ? OR student_no = ?",
        (identifier, identifier, identifier),
    ).fetchone()


def _identity_question(row) -> str:
    """该账号要用什么核对身份。

    优先学号（更客观），没填学号就退到昵称。两者都没有的账号只能靠原密码，
    返回空串表示「这题跳过」。
    """
    if str(row["student_no"] or "").strip():
        return "student_no"
    if str(row["nickname"] or "").strip():
        return "nickname"
    return ""


def _identity_matches(row, answer: str) -> bool:
    """核对「学号 或 昵称」，填对任意一个即可。

    两者都没填过的账号直接放行 —— 此时仍有过原密码那道闸，不会因此变松。
    """
    answer = (answer or "").strip()
    candidates = [str(row["student_no"] or "").strip(),
                  str(row["nickname"] or "").strip()]
    candidates = [c for c in candidates if c]
    if not candidates:
        return True
    return any(answer.lower() == c.lower() for c in candidates)


@bp.route("/forgot", methods=["GET", "POST"])
def forgot():
    """找回密码（两步式）。

    第 1 步：填手机号 / 用户名 / 学号 → 定位账号
    第 2 步：核对学号或昵称，并**输入原密码** → 设置新密码

    第 2 步为什么还要原密码：站点约定任何改密动作都必须过原密码这道闸，
    所以这里不做「绕过原密码」的通道，而是原样保留。
    真的想不起原密码的用户，第 2 步页面上有明确指引去联系管理员
    （后台 /admin/users 已支持一键重置为随机密码）。

    防滥用：
      · throttle.forgot_gate() 对「同一账号」10 分钟只给 6 次
      · 两步之间用 session 记 uid，不把 uid 放在表单里，避免被改成别人的 id
      · 任何一步失败都计入限流，不给脚本留免费试错
    """
    if current_user():
        # 已登录的人直接去「我的」改密码就够了，那里也是要原密码的
        return redirect(url_for("main.me"))

    conn = get_db()
    step = 1
    account = None
    question = ""
    error = ""

    # ---- 第 2 步：提交新密码 ----
    if request.method == "POST" and (request.form.get("step") or "") == "2":
        uid = session.get(FORGOT_SESSION_KEY)
        row = conn.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone() if uid else None
        if row is None:
            session.pop(FORGOT_SESSION_KEY, None)
            flash("验证已过期，请重新开始")
            return redirect(url_for("auth.forgot"))

        step = 2
        account = row
        question = _identity_question(row)

        # 第 2 步按「用户 ID」计数，而不是按用户填的标识 ——
        # 否则同一个人用手机号 / 用户名 / 学号进来会被算成三个不同的桶，
        # 等于把「防爆破」的额度翻了三倍。第 1 步则必须按输入值计数（那时还不知道是谁）。
        wait = throttle.forgot_gate("uid%d" % row["id"])
        if wait:
            error = f"尝试太频繁了，请等 {wait} 秒后再试"
        else:
            answer = request.form.get("answer") or ""
            old = request.form.get("old_password") or ""
            new = request.form.get("new_password") or ""
            confirm = request.form.get("confirm") or ""
            if not _identity_matches(row, answer):
                error = "学号 / 昵称核对不通过，请再试一次"
            elif not db.verify_password(old, row["password_hash"]):
                error = "原密码不正确"
            elif len(new) < 6:
                error = "新密码至少 6 位"
            elif new != confirm:
                error = "两次输入的新密码不一致"
            elif new == old:
                error = "新密码不能和原密码相同"
            else:
                conn.execute("UPDATE users SET password_hash = ? WHERE id = ?",
                             (db.hash_password(new), row["id"]))
                conn.commit()
                # 回读校验：写进去的必须能验回来，否则宁可报错也别留个登不进的账号
                back = conn.execute("SELECT password_hash FROM users WHERE id = ?",
                                    (row["id"],)).fetchone()["password_hash"]
                if not db.verify_password(new, back):
                    error = "密码写入后校验失败，请重试"
                else:
                    throttle.forgot_ok("uid%d" % row["id"])
                    session.pop(FORGOT_SESSION_KEY, None)
                    flash("密码已重置，请用新密码登录")
                    return redirect(url_for("auth.login"))

    # ---- 第 1 步：提交账号 ----
    elif request.method == "POST":
        identifier = (request.form.get("identifier") or "").strip()
        wait = throttle.forgot_gate(identifier or "-")
        if wait:
            error = f"尝试太频繁了，请等 {wait} 秒后再试"
        elif not identifier:
            error = "请输入手机号、用户名或学号"
        else:
            row = _find_account(identifier)
            if row is None:
                error = "没有找到这个账号，请检查手机号 / 用户名 / 学号是否填对"
            elif not row["is_active"]:
                error = "该账号已被停用，请联系管理员"
            else:
                session[FORGOT_SESSION_KEY] = row["id"]
                step = 2
                account = row
                question = _identity_question(row)

    return render_template("forgot.html", step=step, account=account,
                           question=question, error=error,
                           identifier=request.form.get("identifier") or "")


@bp.post("/forgot/cancel")
def forgot_cancel():
    """放弃本次找回，清掉暂存的 uid。"""
    session.pop(FORGOT_SESSION_KEY, None)
    return redirect(url_for("auth.forgot"))


# ---------------------------------------------------------------- 扫码登录
@bp.get("/scan/qr/<token>")
def scan_qr(token):
    import io
    import qrcode
    url = "https://your-server.example.com/scan-login/" + token
    img = qrcode.make(url)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png")


@bp.get("/scan/poll/<token>")
def scan_poll(token):
    conn = get_db()
    row = conn.execute("SELECT * FROM scan_logins WHERE token = ?", (token,)).fetchone()
    if row is None:
        return jsonify({"ok": False, "status": "notfound"})
    if row["status"] == "confirmed" and row["user_id"]:
        user = conn.execute("SELECT * FROM users WHERE id = ?", (row["user_id"],)).fetchone()
        if user and user["is_active"]:
            login_user(user)
            conn.execute("DELETE FROM scan_logins WHERE token = ?", (token,))
            conn.commit()
            return jsonify({"ok": True, "status": "confirmed"})
    if row["expires_at"] and row["expires_at"] < db.now():
        return jsonify({"ok": False, "status": "expired"})
    return jsonify({"ok": False, "status": row["status"]})
