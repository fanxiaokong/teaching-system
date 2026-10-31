"""应用核心：Flask 实例、子路径中间件、登录态、模板全局变量。

路由分别放在 views_auth / views_main / views_admin 三个蓝图里，
通过 create_app() 统一注册，避免循环导入。
"""
from __future__ import annotations

import datetime
import functools
import os
import secrets
from urllib.parse import quote, urlparse

from flask import (Flask, flash, g, redirect, render_template, request, send_file,
                   session, url_for)

import db

BASE_PATH = (os.environ.get("BASE_PATH") or "").rstrip("/")

_STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


def asset_version() -> str:
    """静态资源版本号：取 style.css / app.js 的最新修改时间。

    模板里以 ?v=xxx 引用，文件一改版本号就变，避免浏览器继续吃旧缓存
    （否则改完样式访客看到的还是旧页面）。
    """
    latest = 0.0
    for name in ("style.css", "app.js", "transfer_progress.js"):
        try:
            latest = max(latest, os.path.getmtime(os.path.join(_STATIC_DIR, name)))
        except OSError:
            pass
    return str(int(latest))


class PrefixMiddleware:
    """把 /lab 之类的部署前缀从 PATH_INFO 剥到 SCRIPT_NAME，让 url_for 生成带前缀的链接。"""

    def __init__(self, app, prefix: str = ""):
        self.app = app
        self.prefix = prefix

    def __call__(self, environ, start_response):
        prefix = self.prefix
        if prefix:
            path = environ.get("PATH_INFO", "")
            if path == prefix:
                environ["PATH_INFO"] = "/"
                environ["SCRIPT_NAME"] = prefix
            elif path.startswith(prefix + "/"):
                environ["PATH_INFO"] = path[len(prefix):]
                environ["SCRIPT_NAME"] = prefix
            else:
                body = f"404 Not Found (this app is mounted at {prefix})".encode()
                start_response("404 Not Found", [
                    ("Content-Type", "text/plain; charset=utf-8"),
                    ("Content-Length", str(len(body))),
                ])
                return [body]
        return self.app(environ, start_response)


app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
app.config["MAX_CONTENT_LENGTH"] = None                      # 不限制上传大小（要传大视频/安装包）
app.config["PERMANENT_SESSION_LIFETIME"] = 60 * 60 * 24 * 14
app.wsgi_app = PrefixMiddleware(app.wsgi_app, BASE_PATH)


# ---------------------------------------------------------------- 数据库

def get_db():
    if "db" not in g:
        g.db = db.connect()
    return g.db


@app.teardown_appcontext
def close_db(_exc=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


# ---------------------------------------------------------------- 安全响应头
@app.after_request
def _security_headers(resp):
    """统一补上安全响应头。

    放在应用层而不是 Apache 里，是为了「部署即生效」——不用改服务器配置、
    也不会在换 web server 时丢掉。用 setdefault 是为了不覆盖站点自己已设的值。
    """
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    resp.headers.setdefault("Permissions-Policy",
                            "geolocation=(), microphone=(), camera=()")
    # 兜底 HSTS（Apache vhost 里也设了，这里防止哪天换掉 Apache 就裸奔）
    resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
    return resp


# ---------------------------------------------------------------- 登录态

def current_user():
    if "user" not in g:
        uid = session.get("uid")
        g.user = None
        if uid:
            row = get_db().execute(
                "SELECT * FROM users WHERE id = ? AND is_active = 1", (uid,)
            ).fetchone()
            if row:
                g.user = row
            else:
                session.pop("uid", None)
    return g.user


def login_user(user) -> None:
    session["uid"] = user["id"]
    session.permanent = True


def logout_user() -> None:
    session.pop("uid", None)
    session.pop("study_day", None)
    session.pop("_flashes", None)   # 退出时清掉未显示的提示，避免串到下一个登录的人


def login_required(view):
    @functools.wraps(view)
    def wrapper(*args, **kwargs):
        if current_user() is None:
            target = request.full_path if request.query_string else request.path
            return redirect(url_for("auth.login", next=target))
        return view(*args, **kwargs)

    return wrapper


def admin_required(view):
    @functools.wraps(view)
    def wrapper(*args, **kwargs):
        user = current_user()
        if user is None:
            return redirect(url_for("auth.login", next=request.path))
        if not user["is_admin"]:
            return render_template(
                "notice.html", title="无权访问",
                message="这个页面只有管理员可以打开。如果你觉得自己应该能进，请联系系统管理员。",
            ), 403
        return view(*args, **kwargs)

    return wrapper


def course_access_required(view):
    """**课程级**门禁：登录 + 该课程落在用户激活码的解锁范围内。

    与旧的 activation_required 的区别：不再是"有个码就全站通行"，
    而是拿 URL 里的 course_id（或视图参数）去比对该用户已用激活码的范围。

    范围从哪来：`course_id` 视图参数 > `course` 查询参数 > `file_id` 里查出的课程。
    三样都没有说明这门"课"其实不存在，按 403 处理而不是放行 —— 宁可挡住也别漏。
    """
    @functools.wraps(view)
    def wrapper(*args, **kwargs):
        user = current_user()
        if user is None:
            target = request.full_path if request.query_string else request.path
            return redirect(url_for("auth.login", next=target))
        if user["is_admin"]:
            return view(*args, **kwargs)

        conn = get_db()
        course_id = _course_id_for_request(conn, kwargs)
        if course_id is not None and db.user_course_access(conn, user["id"], course_id):
            return view(*args, **kwargs)

        # 访问不了 / 定位不到课程 —— 引导去激活，并说明原因
        if course_id is None:
            flash("这个内容没有关联到具体课程，请联系管理员确认。")
            return redirect(url_for("main.activate"))
        if not db.user_activated(conn, user["id"]):
            flash("这门课程需要激活码才能查看，请输入管理员发放的激活码。")
        else:
            flash("你的激活码不包含这门课程。如需查看，请联系管理员补充权限。")
        return redirect(url_for("main.activate"))

    return wrapper


def _course_id_for_request(conn, view_args: dict) -> int | None:
    """从请求里推断"当前操作的是哪门课"，供 course_access_required 使用。"""
    # 1) 视图参数里直接有 course_id（如 /courses/<course_id>）
    for key in ("course_id", "cid"):
        value = view_args.get(key)
        if value is not None:
            try:
                return int(value)
            except (TypeError, ValueError):
                pass
    # 2) 查询参数 ?course=<id>
    q = (request.args.get("course") or "").strip()
    if q.isdigit():
        return int(q)
    # 3) 视频 id → 查它属于哪门课
    vid = view_args.get("video_id")
    if vid is not None:
        try:
            row = conn.execute("SELECT course_id FROM videos WHERE id = ?", (int(vid),)).fetchone()
            if row is not None:
                return row["course_id"]
        except (TypeError, ValueError):
            pass
    # 4) 作业 id → 查它属于哪门课
    aid = view_args.get("assignment_id")
    if aid is not None:
        try:
            row = conn.execute("SELECT course_id FROM assignments WHERE id = ?",
                               (int(aid),)).fetchone()
            if row is not None:
                return row["course_id"]
        except (TypeError, ValueError):
            pass
    # 5) 文件 id → 查它属于哪门课
    fid = view_args.get("file_id")
    if fid is not None:
        try:
            row = conn.execute("SELECT course_id FROM files WHERE id = ?", (int(fid),)).fetchone()
            if row is not None:
                return row["course_id"]
        except (TypeError, ValueError):
            pass
    return None


def human_size(num) -> str:
    """把字节数转成人类可读的字符串。"""
    value = float(num or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


# ---------------------------------------------------------------- 下载响应

def safe_ascii_name(name: str, default_base: str = "download") -> str:
    """给非 ASCII 文件名算一个「像样」的 ASCII 回退名。

    浏览器只认 Content-Disposition 里的 `filename=`（不认 RFC 5987 的
    `filename*=UTF-8''`）时用的就是这个名字。Flask 的 download_name 会把
    非 ASCII 字符直接剥掉，「教学管理系统-安装版-v1.3.6.exe」就只剩
    「--v1.3.6.exe」，某些下载器会把它当成没有文件名的文件存下来。
    所以这里显式给一个全 ASCII 的名字兜底。
    """
    base, ext = os.path.splitext(name or "")
    keep = "".join(c for c in base if c.isascii() and (c.isalnum() or c in "-_ ."))
    keep = keep.strip(" -_.")
    ext = ext if ext.isascii() else ""
    # 剥完只剩数字/点（中文名被削光的典型结果）也算不上可用名字
    if not keep or not keep[0].isalnum() or not any(c.isalpha() for c in keep):
        return default_base + ext
    return keep + ext


def attachment_response(path: str, name: str, ascii_name: str | None = None):
    """下载响应：中文正式名 + 可用的 ASCII 回退名。

    `filename` 给保守的客户端用，`filename*`（RFC 5987）给现代浏览器用，
    两边都能落到一个正常文件名上。
    """
    resp = send_file(path, as_attachment=True, download_name=name)
    resp.headers["Content-Disposition"] = (
        'attachment; filename="%s"; filename*=UTF-8\'\'%s'
        % (ascii_name or safe_ascii_name(name), quote(name, safe=""))
    )
    return resp


@app.template_filter("host")
def url_host(url: str) -> str:
    """从链接里取出域名，给磁贴当副标题用。"""
    url = (url or "").strip()
    if not url:
        return ""
    if url.startswith("/"):
        return "站内页面"
    try:
        netloc = urlparse(url).netloc
    except ValueError:
        return url
    return netloc[4:] if netloc.startswith("www.") else netloc


@app.template_filter("icon_src")
def icon_src(icon: str) -> str:
    """磁贴图标：返回可用的图片地址，返回空字符串表示用 emoji / 首字。

    支持 `http(s)://…` 的外链、`/static/…` 的站内路径（自动补部署前缀），
    其他内容（emoji、汉字）一律当文字处理。
    """
    icon = (icon or "").strip()
    if icon.startswith(("http://", "https://")):
        return icon
    if icon.startswith("/"):
        return BASE_PATH + icon
    return ""


@app.context_processor
def inject_globals():
    conn = get_db()
    settings = db.all_settings(conn)
    friendly = conn.execute(
        "SELECT * FROM nav_links WHERE group_name = ? ORDER BY sort_order, id",
        (db.FRIENDLY_GROUP,),
    ).fetchall()
    me = current_user()
    # 公告弹窗：只对登录用户注入。管理员后台不弹（免得自己写公告时被打扰）。
    ann = None
    ann_label = ""
    if me and not request.path.startswith("/admin"):
        ann = db.announcement_latest(conn)
        if ann is not None:
            ann_label = db.ANNOUNCE_LEVEL_LABELS.get(
                db.normalize_level(ann["level"]), "公告")
    return {
        "S": settings,
        "BASE": BASE_PATH,
        "site_title": settings.get("site_title", "教学管理系统"),
        "user": me,
        "announcement": ann,
        "announcement_level_label": ann_label,
        "me_activated": bool(me and (me["is_admin"] or db.user_has_all_courses(conn, me["id"]))),
        "human": human_size,
        "footer_links": friendly,
        "friendly_group": db.FRIENDLY_GROUP,
        "year": datetime.date.today().year,
        "asset_ver": asset_version(),
    }


@app.before_request
def touch_study_day():
    """登录用户每天首次访问记一次学习天数（每用户每天只写一次，避免每请求都写库）。"""
    if request.method != "GET" or not request.endpoint:
        return
    if request.endpoint.startswith("static"):
        return
    user = current_user()
    if user and session.get("study_day") != db.today():
        db.record_study_day(get_db(), user["id"])
        session["study_day"] = db.today()


@app.after_request
def no_store_pages(response):
    """HTML 页面禁止缓存。

    否则浏览器会对没有 Cache-Control 的页面做"启发式缓存"，改完版式用户
    打开还是上一版（截图发给开发者时会误判成"没生效"）。
    静态资源走 ?v=mtime，可以放心长缓存。
    """
    if response.mimetype == "text/html":
        response.headers["Cache-Control"] = "no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
    return response


# ---------------------------------------------------------------- 组装

def create_app():
    """注册所有蓝图并确保数据库就绪。

    幂等：mod_wsgi 可能在多进程/重载时重复加载入口脚本，
    导致同一个蓝图对象被二次注册（Flask 3 会抛
    "already registered"）。用模块级标志保证只初始化一次。
    """
    if getattr(app, "_netlab_initialized", False):
        return app

    import views_admin
    import views_api
    import views_auth
    import views_main

    app.register_blueprint(views_auth.bp)
    app.register_blueprint(views_main.bp)
    app.register_blueprint(views_admin.bp)
    app.register_blueprint(views_api.bp)


    # 意见反馈（/feedback + /admin/feedback）
    try:
        import views_feedback
        app.register_blueprint(views_feedback.bp)
    except Exception as exc:                      # noqa: BLE001
        app.logger.warning("feedback blueprint not loaded: %s", exc)

    db.init_db()

    app._netlab_initialized = True
    return app
