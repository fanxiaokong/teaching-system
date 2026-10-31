"""数据层：建表、连接管理、口令哈希、学习统计、CSV 导出。

**本系统仅支持 MySQL 8 后端**（不再支持 SQLite），由环境变量 NETLAB_DB_BACKEND 决定：
  NETLAB_DB_BACKEND=mysql  → MySQL 8，参数见下面的 MYSQL_* 块（默认即 mysql）

SQLite 与 MySQL 的差异**全部**收在 mysqldialect.py / mysqldb.py 两个模块里，
上层这 390 条 SQL 一行都不用改；建表语句（SCHEMA）里的 SQLite 方言会在运行时
被翻译成 MySQL 方言（PRAGMA 跳过、AUTOINCREMENT→AUTO_INCREMENT、TEXT 索引列→
VARCHAR(255)、PRAGMA table_info→information_schema 等），所以 `init_db()` 直接
就能在 MySQL 上把整库建出来。
"""
from __future__ import annotations

import csv
import datetime
import hashlib
import io
import json
import os
import secrets

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("DATA_DIR") or os.path.join(BASE_DIR, "data")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
FILE_DIR = os.path.join(DATA_DIR, "files")       # 公共资料 + 作业提交
COURSE_DIR = os.path.join(DATA_DIR, "courses")   # 上传的课程 index.html 及其资源
FEEDBACK_DIR = os.path.join(DATA_DIR, "feedback")  # 意见反馈的截图

# ---------------------------------------------------------------- 后端选择
# 本系统仅支持 MySQL 后端；未显式设置时也按 mysql 处理。
BACKEND = (os.environ.get("NETLAB_DB_BACKEND") or "mysql").strip().lower()
MYSQL = {
    "host": os.environ.get("NETLAB_MYSQL_HOST", "127.0.0.1"),
    "port": int(os.environ.get("NETLAB_MYSQL_PORT", "3306")),
    "user": os.environ.get("NETLAB_MYSQL_USER", "admin"),
    "password": os.environ.get("NETLAB_MYSQL_PASSWORD", ""),
    "database": os.environ.get("NETLAB_MYSQL_DATABASE", "netlab"),
}
USE_MYSQL = BACKEND == "mysql"

# ---------------------------------------------------------------- 口令存储模式
# NETLAB_PASSWORD_MODE=plain → 明文存储（管理员要求，方便直接在 Navicat 里看/改）
# NETLAB_PASSWORD_MODE=hash  → PBKDF2 哈希（旧行为）
#
# 注意：verify_password() 两种格式都认——凡是形如 pbkdf2_sha256$盐$摘要 的旧值，
# 继续走 PBKDF2 校验；其余一律按明文比对。所以切换模式不会把任何人锁在门外，
# 老账号在"第一次改密码"那一刻自动落成明文。
PASSWORD_MODE = (os.environ.get("NETLAB_PASSWORD_MODE") or "plain").strip().lower()
PLAINTEXT_PASSWORDS = PASSWORD_MODE != "hash"

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- ==================== 账号体系 ====================
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE,
    phone         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    nickname      TEXT DEFAULT '',
    student_no    TEXT DEFAULT '',
    is_admin      INTEGER DEFAULT 0,
    is_active     INTEGER DEFAULT 1,
    quota_mb      INTEGER DEFAULT 200,   -- 个人云盘配额，单位 MB，只有管理员能改
    created_at    TEXT NOT NULL,
    last_login_at TEXT
);

-- 每天一条记录，学习天数 = 行数；连续天数在 Python 里算
CREATE TABLE IF NOT EXISTS study_days (
    user_id INTEGER NOT NULL,
    day     TEXT NOT NULL,
    seconds INTEGER DEFAULT 0,
    PRIMARY KEY (user_id, day)
);

-- ==================== 课程 ====================
CREATE TABLE IF NOT EXISTS courses (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    title        TEXT NOT NULL,
    summary      TEXT DEFAULT '',
    category     TEXT DEFAULT '',
    icon         TEXT DEFAULT '',
    source       TEXT DEFAULT 'editor',      -- editor（后台写） | html（上传 index 文件）
    content_html TEXT DEFAULT '',
    entry_path   TEXT DEFAULT '',            -- source=html 时的入口文件相对路径
    sort_order   INTEGER DEFAULT 0,
    is_open      INTEGER DEFAULT 1,
    created_at   TEXT NOT NULL,
    updated_at   TEXT
);

CREATE TABLE IF NOT EXISTS course_progress (
    user_id    INTEGER NOT NULL,
    course_id  INTEGER NOT NULL,
    percent    INTEGER DEFAULT 0,
    status     TEXT DEFAULT 'learning',      -- learning | done
    updated_at TEXT,
    PRIMARY KEY (user_id, course_id)
);

-- ==================== 挑战（闯关）====================
CREATE TABLE IF NOT EXISTS challenges (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    title        TEXT NOT NULL,
    summary      TEXT DEFAULT '',
    content_html TEXT DEFAULT '',
    difficulty   INTEGER DEFAULT 1,          -- 1 入门 2 进阶 3 高手
    deadline     TEXT DEFAULT '',
    is_open      INTEGER DEFAULT 1,
    sort_order   INTEGER DEFAULT 0,
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS challenge_records (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL,
    challenge_id INTEGER NOT NULL,
    passed       INTEGER DEFAULT 0,
    note         TEXT DEFAULT '',
    file_id      INTEGER,
    elapsed_ms   INTEGER DEFAULT 0,
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS challenge_matches (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    challenge_id     INTEGER NOT NULL,
    invite_code      TEXT NOT NULL UNIQUE,
    host_id          INTEGER NOT NULL,
    guest_id         INTEGER,
    status           TEXT DEFAULT 'waiting',
    host_elapsed_ms  INTEGER DEFAULT 0,
    guest_elapsed_ms INTEGER DEFAULT 0,
    host_finished_at TEXT,
    guest_finished_at TEXT,
    created_at       TEXT NOT NULL
);

-- ==================== 社区 ====================
CREATE TABLE IF NOT EXISTS posts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    title      TEXT NOT NULL,
    content    TEXT NOT NULL,
    views      INTEGER DEFAULT 0,
    is_top     INTEGER DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS replies (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id    INTEGER NOT NULL,
    user_id    INTEGER NOT NULL,
    content    TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- ==================== 文件 ====================
-- kind: resource 管理员发布的公共资料 | submission 学生提交的作业
CREATE TABLE IF NOT EXISTS files (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    kind          TEXT NOT NULL DEFAULT 'resource',
    title         TEXT NOT NULL,
    description   TEXT DEFAULT '',
    stored_name   TEXT NOT NULL,
    original_name TEXT NOT NULL,
    size          INTEGER DEFAULT 0,
    category      TEXT DEFAULT '',
    course_id     INTEGER,
    challenge_id  INTEGER,
    assignment_id INTEGER,                   -- 关联 assignments.id（学生交的作业）
    owner_id      INTEGER,
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_files_kind ON files(kind, id);
CREATE INDEX IF NOT EXISTS idx_files_owner ON files(owner_id);

-- ==================== 首页常用链接（后台可维护）====================
CREATE TABLE IF NOT EXISTS nav_links (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    group_name  TEXT NOT NULL DEFAULT '常用链接',
    title       TEXT NOT NULL,
    url         TEXT NOT NULL,
    icon        TEXT DEFAULT '',
    description TEXT DEFAULT '',
    sort_order  INTEGER DEFAULT 0,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_link_group ON nav_links(group_name, sort_order);

-- ==================== 站点设置 ====================
CREATE TABLE IF NOT EXISTS settings (
    k TEXT PRIMARY KEY,
    v TEXT
);

-- ==================== 课程作业 ====================
-- 管理员给某门课程布置作业；学生提交的文件仍存在 files 表里，
-- 靠 files.assignment_id 关联回具体哪份作业。
CREATE TABLE IF NOT EXISTS assignments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id   INTEGER,
    title       TEXT NOT NULL,
    description TEXT DEFAULT '',
    deadline    TEXT DEFAULT '',
    is_open     INTEGER DEFAULT 1,
    sort_order  INTEGER DEFAULT 0,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_assign_course ON assignments(course_id, sort_order);

-- ==================== 课程视频 ====================
-- 管理员上传教学视频，学生在课程页在线播放（HTML5 video）。
CREATE TABLE IF NOT EXISTS videos (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id     INTEGER,
    title         TEXT NOT NULL,
    description   TEXT DEFAULT '',
    stored_name   TEXT NOT NULL,
    original_name TEXT NOT NULL,
    size          INTEGER DEFAULT 0,
    duration      TEXT DEFAULT '',
    sort_order    INTEGER DEFAULT 0,
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_videos_course ON videos(course_id, sort_order);

-- ==================== 激活码（课程资料门禁）====================
-- 管理员批量生成、发放给成员；成员使用后绑定到其账号（used_by），
-- 之后才能访问「课程资料」（/courses 及资料下载/上传）。管理员不受门禁限制。
CREATE TABLE IF NOT EXISTS activation_codes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    code       TEXT NOT NULL UNIQUE,
    note       TEXT DEFAULT '',
    created_by INTEGER,
    created_at TEXT NOT NULL,
    used_by    INTEGER,
    used_at    TEXT,
    -- 解锁范围。scope_kind='all' = 全部课程（老码的默认语义，行为不变）；
    -- 'limited' 时再看下面两个字段（JSON 数组，任一条命中即算覆盖）。
    scope_kind       TEXT DEFAULT 'all',
    scope_categories TEXT DEFAULT '',   -- 课程标签数组，如 ["网络基础"]
    scope_courses    TEXT DEFAULT ''    -- 课程 id 数组，如 [5,9]
);
CREATE INDEX IF NOT EXISTS idx_activation_used_by ON activation_codes(used_by);

-- ==================== 加入我们（招新报名）====================
CREATE TABLE IF NOT EXISTS join_requests (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    college    TEXT NOT NULL,
    contact    TEXT NOT NULL,
    join_group INTEGER DEFAULT 0,   -- 是否加入官方群聊：1 是 / 0 否
    note       TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    ip         TEXT DEFAULT ''
);

-- ==================== 报到（report）====================
CREATE TABLE IF NOT EXISTS reports (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    name        TEXT NOT NULL,
    college     TEXT NOT NULL,
    major_class TEXT NOT NULL,
    joined_qq   INTEGER DEFAULT 0,
    status      TEXT DEFAULT 'pending',
    review_note TEXT DEFAULT '',
    reviewed_by INTEGER,
    created_at  TEXT NOT NULL,
    reviewed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_reports_user ON reports(user_id);
CREATE INDEX IF NOT EXISTS idx_reports_status ON reports(status, id);

-- ==================== App 版本更新（Android / iOS / Windows 共用一张表）====================
-- platform 区分渠道：android（APK）| ios（安装链接）| windows（桌面客户端 exe）
-- is_latest 只在同一 platform 内互斥，切最新版必须带上 WHERE platform = ?
CREATE TABLE IF NOT EXISTS app_versions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    version_code  INTEGER NOT NULL,
    version_name  TEXT NOT NULL,
    release_notes TEXT DEFAULT '',
    file_name     TEXT NOT NULL DEFAULT '',
    file_size     INTEGER DEFAULT 0,
    download_url  TEXT NOT NULL DEFAULT '',
    is_latest     INTEGER DEFAULT 0,
    created_at    TEXT NOT NULL,
    platform      TEXT NOT NULL DEFAULT 'android',
    sha512        TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS scan_logins (
    token      TEXT PRIMARY KEY,
    user_id    INTEGER,
    status     TEXT DEFAULT 'pending',
    created_at TEXT NOT NULL,
    expires_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_app_versions_latest ON app_versions(platform, is_latest, id);

-- ============ 以下为早期「报名 / 考试 / 刷题」遗留表 ============
-- 功能已下线，表保留以便随时导出旧数据，不再被代码引用。
CREATE TABLE IF NOT EXISTS registrations (
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, college TEXT, class_name TEXT,
    contact TEXT, note TEXT, created_at TEXT, ip TEXT
);
CREATE TABLE IF NOT EXISTS questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, qtype TEXT, stem TEXT, options TEXT, answer TEXT,
    analysis TEXT, tag TEXT, difficulty INTEGER, created_at TEXT
);
CREATE TABLE IF NOT EXISTS exams (
    id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, description TEXT, duration_min INTEGER,
    question_count INTEGER, tag_filter TEXT, pass_score INTEGER, is_open INTEGER, created_at TEXT
);
CREATE TABLE IF NOT EXISTS attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT, exam_id INTEGER, name TEXT, contact TEXT, score REAL,
    total INTEGER, correct INTEGER, passed INTEGER, detail TEXT, status TEXT,
    switch_count INTEGER, started_at TEXT, submitted_at TEXT
);
CREATE TABLE IF NOT EXISTS practice_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, question_id INTEGER, user_answer TEXT,
    is_correct INTEGER, created_at TEXT
);
CREATE TABLE IF NOT EXISTS post_attachments (
    id INTEGER PRIMARY KEY AUTOINCREMENT, post_id INTEGER NOT NULL,
    file_id INTEGER NOT NULL, created_at TEXT
);

-- ---------------------------------------------------------------- 意见反馈
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    title TEXT DEFAULT '',
    category TEXT DEFAULT '',
    content TEXT NOT NULL,
    status TEXT DEFAULT 'open',
    created_at TEXT,
    updated_at TEXT,
    replied_at TEXT,
    replied_by INTEGER
);
CREATE TABLE IF NOT EXISTS feedback_images (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    feedback_id INTEGER NOT NULL,
    stored_name TEXT NOT NULL,
    original_name TEXT DEFAULT '',
    size INTEGER DEFAULT 0,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS feedback_replies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    feedback_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    is_admin INTEGER DEFAULT 0,
    content TEXT NOT NULL,
    created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_feedback_user ON feedback(user_id);
CREATE INDEX IF NOT EXISTS idx_feedback_status ON feedback(status);
CREATE INDEX IF NOT EXISTS idx_fb_reply_fid ON feedback_replies(feedback_id);
CREATE INDEX IF NOT EXISTS idx_fb_img_fid ON feedback_images(feedback_id);

-- ---------------------------------------------------------------- 站点公告
-- 管理员在后台写，用户登录后网站 / App / 桌面客户端弹窗展示。
-- 客户端靠 (id, updated_at) 做「已读」去重：改了公告内容会重新弹一次。
CREATE TABLE IF NOT EXISTS announcements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    level TEXT DEFAULT 'info',          -- info 普通 / warn 重要 / urgent 紧急（决定配色）
    link_text TEXT DEFAULT '',          -- 可选：弹窗底部的按钮文字
    link_url TEXT DEFAULT '',           -- 可选：按钮跳转地址
    is_active INTEGER DEFAULT 1,        -- 0 = 下架，客户端不再收到
    popup INTEGER DEFAULT 1,            -- 1 = 登录后弹窗；0 = 只留档不弹
    starts_at TEXT DEFAULT '',          -- 生效时间（空 = 立即）
    ends_at TEXT DEFAULT '',            -- 失效时间（空 = 长期）
    author TEXT DEFAULT '',
    created_at TEXT,
    updated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_ann_active ON announcements(is_active, id);
"""

DEFAULT_SETTINGS = {
    "site_title": "教学管理系统",
    "site_subtitle": "招新进行中 · 欢迎加入",
    "site_intro": "我们是一群折腾网络与安全的人。零基础也能来，师兄师姐带着上手。",
    "hero_tag": "NETWORK LAB · 招新中",
    "hero_title": "一起把网络玩明白",
    "hero_desc": "不要求基础，只看你愿不愿意动手。真实设备、真实项目，师兄师姐一对一带着做。",
    "contact_info": "",
    "register_open": "1",
    "join_open": "1",
    "group_qrcode": "",
    "group_number": "",
    "join_intro": "我们常年面向全校招新，不限专业、不限年级。不要求你已经会什么，"
                  "肯动手就行。填一份表，我们会尽快联系你。",
    "join_points": "零基础也收｜不要求你提前会什么，肯学就行\n"
                   "真机真环境｜交换机、路由器、防火墙都是真设备，不是模拟器\n"
                   "师兄师姐带｜一对一带着做，卡住了当场解决\n"
                   "有作品可带走｜做过的项目写进简历，面试讲得出来",
    "stat_suffix_1": "门课程",
    "stat_suffix_2": "个挑战",
    # 页脚
    "footer_links_title": "友情链接",
    "icp_number": "",
    "police_number": "",
}

# 分组名等于这个值的导航链接，只显示在页脚右侧，不占用首页版面
FRIENDLY_GROUP = "友情链接"

# 首页「快捷入口」磁贴的初始内容。
# 首页按 group_name 分成若干块，每块的标题就是分组名，块的先后由组内最小排序号决定。
# 图标支持三种写法：① 站内路径（/static/site-icons/xxx.png）② 完整图片网址 ③ 一个 emoji/汉字。
# 前三个图标是从各自官网抓下来、转成 128×128 PNG 后放在站内自托管的，
# 这样不依赖外网请求，也不怕对方改防盗链。
DEFAULT_LINKS = [
    ("实验室内部", "Docker 管理面板", "https://docker.your-server.example.com",
     "🐳", "查看和管理服务器上的容器", 0),
    ("实验室内部", "文件系统", "/files",
     "📁", "下载课件资料 / 提交作业", 1),
    ("常用站点", "DeepSeek", "https://chat.deepseek.com",
     "/static/site-icons/deepseek.png", "AI 问答助手", 10),
    ("常用站点", "CSDN", "https://www.csdn.net",
     "/static/site-icons/csdn.png", "技术博客与问答社区", 11),
    ("常用站点", "豆包", "https://www.doubao.com",
     "/static/site-icons/doubao.png", "字节跳动的 AI 助手", 12),
]


def now() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today() -> str:
    return datetime.date.today().isoformat()


# ---------------------------------------------------------------- 版本号

def semver_code(version_name: str) -> int:
    """把 "1.3.0" 这种语义化版本名换算成可比较的整数 version_code。

    编码：major * 1_000_000 + minor * 1_000 + patch（缺位按 0 补）
        1.3.0 -> 1003000   1.12.5 -> 1012005   2.0.0 -> 2000000

    这样 1.99.99 < 1.100.0 < 2.0.0 始终成立，且同一版本名永远得到同一个整数，
    桌面客户端只要上报同样的算法就不会出现「版本号对不上反复提示更新」。
    minor / patch 超过 999 时编码会串位，实际版本号不会到这个量级。
    解析失败返回 0（视为未知版本，不参与比较）。
    """
    text = str(version_name or "").strip().lstrip("vV")
    if not text:
        return 0
    parts = []
    for chunk in text.split("."):
        digits = ""
        for ch in chunk:
            if ch.isdigit():
                digits += ch
            else:
                break
        if not digits:
            break
        parts.append(int(digits))
    while len(parts) < 3:
        parts.append(0)
    major, minor, patch = parts[0], parts[1], parts[2]
    if minor > 999 or patch > 999:
        return 0
    return major * 1000000 + minor * 1000 + patch


APP_PLATFORMS = ("android", "ios", "windows", "windows-portable", "macos", "mac")

# 渠道中文名，后台下拉框与下载页共用
APP_PLATFORM_LABELS = {
    "android": "安卓 APK",
    "ios": "iOS",
    "windows": "Windows 安装版",
    "windows-portable": "Windows 绿色版",
    "macos": "macOS",
    "mac": "macOS",          # 老库里 mac 渠道存的是 'mac'，两个都认，免得标签显示成英文
}


def normalize_platform(raw) -> str:
    """归一化平台名，缺省与非法值一律落到 android（兼容旧调用）。"""
    value = str(raw or "").strip().lower()
    return value if value in APP_PLATFORMS else "android"


def app_latest(conn, platform: str = "android"):
    """取某平台当前标记为最新的版本行。"""
    return conn.execute(
        "SELECT * FROM app_versions WHERE platform = ? AND is_latest = 1 "
        "ORDER BY version_code DESC, id DESC LIMIT 1",
        (normalize_platform(platform),),
    ).fetchone()


def app_previous(conn, platform: str = "android"):
    """取某平台上一版（非最新里版本号最大的那条），用于下载页「体验自动更新」。"""
    return conn.execute(
        "SELECT * FROM app_versions WHERE platform = ? AND is_latest = 0 "
        "ORDER BY version_code DESC, id DESC LIMIT 1",
        (normalize_platform(platform),),
    ).fetchone()


# ---------------------------------------------------------------- 公告

ANNOUNCE_LEVELS = ("info", "warn", "urgent")
ANNOUNCE_LEVEL_LABELS = {"info": "普通", "warn": "重要", "urgent": "紧急"}


def normalize_level(raw) -> str:
    """把管理员填的等级收敛到三个合法值，非法的一律当普通公告。"""
    text = (raw or "").strip().lower()
    return text if text in ANNOUNCE_LEVELS else "info"


def announcement_latest(conn):
    """取当前应当弹给用户的公告。

    三重过滤，缺一不可：
      · is_active = 1   —— 下架的不弹
      · popup     = 1   —— 只留档不弹的不弹
      · 生效时间已到、失效时间未过（两者留空都表示不限制）
    同一时间只弹一条：按「等级紧急优先 → 更新时间新优先」挑。
    时间用字符串比较即可 —— 全站时间戳都是 'YYYY-MM-DD HH:MM:SS' 定长格式。
    """
    stamp = now()
    rows = conn.execute(
        "SELECT * FROM announcements "
        "WHERE is_active = 1 AND popup = 1 "
        "AND (starts_at IS NULL OR starts_at = '' OR starts_at <= ?) "
        "AND (ends_at IS NULL OR ends_at = '' OR ends_at >= ?) "
        "ORDER BY id DESC",
        (stamp, stamp),
    ).fetchall()
    if not rows:
        return None
    rank = {"urgent": 0, "warn": 1, "info": 2}
    # 先按等级取最优的一组（紧急 > 重要 > 普通），同组里再取最近更新的那条。
    # 分两步做是为了避免「等级升序、时间降序」这种混方向排序写错。
    best = min(rank.get(normalize_level(r["level"]), 2) for r in rows)
    candidates = [r for r in rows if rank.get(normalize_level(r["level"]), 2) == best]
    return max(candidates, key=lambda r: (str(r["updated_at"] or r["created_at"] or ""),
                                          int(r["id"])))


def announcement_stats(conn) -> dict:
    """后台列表页顶部的概览数字。"""
    row = conn.execute(
        "SELECT COUNT(*) AS total, "
        "SUM(CASE WHEN is_active = 1 THEN 1 ELSE 0 END) AS active, "
        "SUM(CASE WHEN is_active = 1 AND popup = 1 THEN 1 ELSE 0 END) AS popping "
        "FROM announcements"
    ).fetchone()
    return {
        "total": int(row["total"] or 0),
        "active": int(row["active"] or 0),
        "popping": int(row["popping"] or 0),
    }


def connect():
    """拿一条 MySQL 连接。本系统仅支持 MySQL 后端。

    需要环境变量 NETLAB_DB_BACKEND=mysql 与 NETLAB_MYSQL_*（HOST / PORT / USER /
    PASSWORD / DATABASE），详见 .env.example。未配置或配置错误会在启动 / 首次访问时
    直接抛 pymysql 的异常，便于快速定位（而不是悄悄退回另一种后端）。
    """
    if not USE_MYSQL:
        raise RuntimeError(
            "本系统仅支持 MySQL 数据库后端。请设置 NETLAB_DB_BACKEND=mysql 并配置 "
            "NETLAB_MYSQL_HOST / NETLAB_MYSQL_PORT / NETLAB_MYSQL_USER / "
            "NETLAB_MYSQL_PASSWORD / NETLAB_MYSQL_DATABASE，详见 .env.example。"
        )
    import mysqldb
    return mysqldb.connect(
        MYSQL["host"], MYSQL["port"], MYSQL["user"], MYSQL["password"],
        MYSQL["database"], debug=os.environ.get("NETLAB_SQL_DEBUG") == "1",
    )


def ensure_column(conn: object, table: str, column: str, ddl: str) -> bool:
    """给已存在的表补一列（SQLite 用 ALTER TABLE ADD COLUMN）。

    `CREATE TABLE IF NOT EXISTS` 对已经建好的表不会做任何事，
    所以后续新增的列必须走这里，否则线上库永远缺这一列。
    返回 True 表示这次真的加了。
    """
    names = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column in names:
        return False
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")
    conn.commit()
    print(f"[netlab] 已为 {table} 补上列 {column}", flush=True)
    return True


def init_db() -> None:
    for folder in (DATA_DIR, UPLOAD_DIR, FILE_DIR, COURSE_DIR, FEEDBACK_DIR):
        os.makedirs(folder, exist_ok=True)
    conn = connect()
    try:
        conn.executescript(SCHEMA)
        ensure_column(conn, "files", "assignment_id", "assignment_id INTEGER")
        # 个人云盘配额：老库 users 表没有这列，必须走 ALTER TABLE 迁移
        ensure_column(conn, "users", "quota_mb", "quota_mb INTEGER DEFAULT 200")
        ensure_column(conn, "users", "student_no", "student_no TEXT DEFAULT ''")
        # 挑战计时：老库 challenge_records 没有这列，走 ALTER TABLE 迁移
        ensure_column(conn, "challenge_records", "elapsed_ms", "elapsed_ms INTEGER DEFAULT 0")
        # 视频时长：老库 videos 没有这列，走 ALTER TABLE 迁移
        ensure_column(conn, "videos", "duration", "duration TEXT DEFAULT ''")
        # 字幕：views_admin.py 会 UPDATE videos SET subtitle/subtitle_name，
        # 但这两列一直没进 SCHEMA、也没走 ensure_column ——
        # 全新装出来的库缺这两列，字幕功能一用就报错。补上。
        ensure_column(conn, "videos", "subtitle", "subtitle TEXT DEFAULT ''")
        ensure_column(conn, "videos", "subtitle_name", "subtitle_name TEXT DEFAULT ''")
        # 版本渠道与校验值：老库 app_versions 没有这两列，必须走 ALTER TABLE 迁移
        ensure_column(conn, "app_versions", "platform", "platform TEXT NOT NULL DEFAULT 'android'")
        ensure_column(conn, "app_versions", "sha512", "sha512 TEXT DEFAULT ''")
        # 激活码解锁范围：老库没有这三列，迁移时默认 scope_kind='all'，
        # 也就是「全部课程」—— 与改动前"激活即全站解锁"的行为完全一致，
        # 已发出的码不会因为这次改动而失效或缩水。
        ensure_column(conn, "activation_codes", "scope_kind",
                      "scope_kind TEXT DEFAULT 'all'")
        ensure_column(conn, "activation_codes", "scope_categories",
                      "scope_categories TEXT DEFAULT ''")
        ensure_column(conn, "activation_codes", "scope_courses",
                      "scope_courses TEXT DEFAULT ''")
        conn.execute(
            "UPDATE activation_codes SET scope_kind = 'all' "
            "WHERE scope_kind IS NULL OR TRIM(scope_kind) = ''"
        )
        conn.execute(
            "UPDATE app_versions SET platform = 'android' "
            "WHERE platform IS NULL OR TRIM(platform) = ''"
        )
        conn.commit()
        for key, value in DEFAULT_SETTINGS.items():
            conn.execute("INSERT OR IGNORE INTO settings (k, v) VALUES (?, ?)", (key, value))
        if conn.execute("SELECT COUNT(*) c FROM nav_links").fetchone()["c"] == 0:
            for group, title, url, icon, desc, order in DEFAULT_LINKS:
                conn.execute(
                    "INSERT INTO nav_links (group_name, title, url, icon, description, "
                    "sort_order, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (group, title, url, icon, desc, order, now()),
                )
        conn.commit()
        _ensure_admin_user(conn)
    finally:
        conn.close()


# ---------------------------------------------------------------- 设置项

def all_settings(conn: object) -> dict:
    return {row["k"]: row["v"] for row in conn.execute("SELECT k, v FROM settings")}


def get_setting(conn: object, key: str, default: str = "") -> str:
    row = conn.execute("SELECT v FROM settings WHERE k = ?", (key,)).fetchone()
    return row["v"] if row else default


def set_setting(conn: object, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO settings (k, v) VALUES (?, ?) ON CONFLICT(k) DO UPDATE SET v = excluded.v",
        (key, value),
    )
    conn.commit()


# ---------------------------------------------------------------- 口令

def hash_password(password: str) -> str:
    """把明文口令变成"库里该存的东西"。

    - 明文模式（默认）：原样返回，库里看到的就是明文，可直接改。
    - 哈希模式：返回 pbkdf2_sha256$盐$摘要。
    """
    if PLAINTEXT_PASSWORDS:
        return password
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000).hex()
    return f"pbkdf2_sha256${salt}${digest}"


def is_hashed(stored) -> bool:
    """这一行的 password_hash 还是旧的 PBKDF2 值吗？"""
    return isinstance(stored, str) and stored.startswith("pbkdf2_sha256$")


def verify_password(password: str, stored) -> bool:
    """校验口令。

    兼容两种存量格式，切换存储模式不会导致任何人登不进来：
      * pbkdf2_sha256$盐$摘要  → 走 PBKDF2
      * 其他                   → 按明文比对
    """
    if stored is None:
        return False
    if not isinstance(stored, str):
        stored = str(stored)

    if stored.startswith("pbkdf2_sha256$"):
        try:
            _, salt, digest = stored.split("$", 2)
        except ValueError:
            return False
        check = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000).hex()
        return secrets.compare_digest(check, digest)

    return secrets.compare_digest(stored, password)


def _ensure_admin_user(conn: object) -> None:
    """首次启动创建一个管理员账号；用户名/手机号/密码可用环境变量指定。"""
    if conn.execute("SELECT COUNT(*) c FROM users WHERE is_admin = 1").fetchone()["c"]:
        return
    username = os.environ.get("ADMIN_USERNAME") or "admin"
    phone = os.environ.get("ADMIN_PHONE") or "13800000000"
    password = os.environ.get("ADMIN_PASSWORD") or secrets.token_urlsafe(9)
    conn.execute(
        "INSERT INTO users (username, phone, password_hash, nickname, is_admin, is_active, "
        "created_at) VALUES (?, ?, ?, ?, 1, 1, ?)",
        (username, phone, hash_password(password), "系统管理员", now()),
    )
    conn.commit()
    print(f"[netlab] 管理员账号已创建：用户名 {username} / 手机号 {phone} / 密码 {password}",
          flush=True)
    if not os.environ.get("ADMIN_PASSWORD"):
        with open(os.path.join(DATA_DIR, "初始管理员密码.txt"), "w", encoding="utf-8") as fh:
            fh.write(f"用户名：{username}\n手机号：{phone}\n密码：{password}\n请登录后立即修改。\n")


# ---------------------------------------------------------------- 学习统计

def record_study_day(conn: object, user_id: int, seconds: int = 0) -> None:
    conn.execute(
        "INSERT INTO study_days (user_id, day, seconds) VALUES (?, ?, ?) "
        "ON CONFLICT(user_id, day) DO UPDATE SET seconds = seconds + excluded.seconds",
        (user_id, today(), seconds),
    )
    conn.commit()


def study_stats(conn: object, user_id: int) -> dict:
    """学习天数、连续天数、今天是否已学习。"""
    days = {row["day"] for row in
            conn.execute("SELECT day FROM study_days WHERE user_id = ?", (user_id,))}
    cursor = datetime.date.today()
    streak = 0
    while cursor.isoformat() in days:
        streak += 1
        cursor -= datetime.timedelta(days=1)
    return {"total": len(days), "streak": streak, "today_done": today() in days}


# ---------------------------------------------------------------- 激活码

CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"  # 去掉易混淆的 0/O/1/I


def _new_code() -> str:
    part = lambda: "".join(secrets.choice(CODE_ALPHABET) for _ in range(4))
    return f"NL-{part()}-{part()}"


def create_codes(conn: object, admin_id: int, count: int, note: str = "",
                 scope_kind: str = "all", categories=None, course_ids=None) -> list[str]:
    """批量生成激活码（保证唯一），返回生成的码列表。一次最多 50 个。

    scope_kind='all'  → 全部课程（默认，与旧行为一致）
    scope_kind='limited' → 只看 categories（课程标签）与 course_ids（指定课程），
                           两者可同时给，命中任意一条即算覆盖。
    """
    kind = "limited" if str(scope_kind or "").strip() == "limited" else "all"
    cats = sorted({str(x).strip() for x in (categories or []) if str(x).strip()})
    ids = []
    for x in (course_ids or []):
        try:
            ids.append(int(x))
        except (TypeError, ValueError):
            continue
    ids = sorted(set(ids))
    # limited 但一个目标都没选 = 这个码谁也开不了，属于误操作，直接拦掉
    if kind == "limited" and not cats and not ids:
        raise ValueError("选择了「指定范围」但没勾任何课程或标签")

    cats_json = json.dumps(cats, ensure_ascii=False) if cats else ""
    ids_json = json.dumps(ids) if ids else ""

    codes: list[str] = []
    for _ in range(max(1, min(count, 50))):
        text = _new_code()
        while conn.execute("SELECT 1 FROM activation_codes WHERE code = ?", (text,)).fetchone():
            text = _new_code()
        conn.execute(
            "INSERT INTO activation_codes (code, note, created_by, created_at, "
            "scope_kind, scope_categories, scope_courses) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (text, note, admin_id, now(), kind, cats_json, ids_json))
        codes.append(text)
    conn.commit()
    return codes


def _row_get(row, key, default=None):
    """从 sqlite3.Row / DictCursor 行里安全取值。

    刚迁到 MySQL 或刚加完列时，行里可能还没有新字段，
    sqlite3.Row 抛 IndexError、DictCursor 抛 KeyError，这里统一兜住。
    """
    try:
        value = row[key]
    except (KeyError, IndexError, TypeError):
        return default
    return default if value is None else value


def parse_code_scope(row) -> dict:
    """把激活码的范围字段解析成 {all, categories:set, courses:set}。

    all=True 表示不限（老码默认值，行为与改动前一致）。
    limited 时 categories / courses 任一条命中即算覆盖该课程。

    这几个字段可以**在数据库里手工改**，所以处处容错：
      · scope_kind 忽略大小写与前后空格：'Limited' / ' LIMITED ' 都按 limited 处理。
        （原来只认全小写，写错大小写会被当成 all —— 也就是"手滑给出全部权限"，
         方向是反的，必须修。）
      · 显式写了 limited 但 JSON 写坏（中文引号、漏引号等）→ 解析成空集合，
        也就是"谁都看不到"。这是 fail-closed：写坏了宁可少给，别误给全部。
      · scope_kind 是没见过的值、但确实填了范围 → 按 limited 处理（尊重填写意图）。
      · 没见过的值且什么都没填 → 退回"全部课程"，兼容改动前的老数据。
    """
    def load_ids(key):
        try:
            data = json.loads(str(_row_get(row, key, "") or "[]"))
        except (ValueError, TypeError):
            return []
        return data if isinstance(data, list) else []

    courses = set()
    for x in load_ids("scope_courses"):
        try:
            courses.add(int(x))
        except (ValueError, TypeError):
            continue
    categories = {str(x).strip() for x in load_ids("scope_categories") if str(x).strip()}

    kind = str(_row_get(row, "scope_kind", "all") or "all").strip().lower()
    if kind == "limited" or (kind != "all" and (categories or courses)):
        return {"all": False, "categories": categories, "courses": courses}
    return {"all": True, "categories": set(), "courses": set()}


def code_scope_label(row) -> str:
    """给界面用的一句话范围描述。"""
    s = parse_code_scope(row)
    if s["all"]:
        return "全部课程"
    parts = []
    if s["categories"]:
        parts.append("、".join(sorted(s["categories"])))
    if s["courses"]:
        parts.append("指定 %d 门课程" % len(s["courses"]))
    return " + ".join(parts) if parts else "未指定（等于没有权限）"


def user_course_scope(conn, user_id: int) -> dict:
    """汇总某用户**全部已用激活码**的解锁范围（多个码累加，这是产品决策）。"""
    rows = conn.execute(
        "SELECT * FROM activation_codes WHERE used_by = ?", (user_id,)).fetchall()
    merged = {"all": False, "categories": set(), "courses": set()}
    for r in rows:
        s = parse_code_scope(r)
        if s["all"]:
            merged["all"] = True
            break
        merged["categories"] |= s["categories"]
        merged["courses"] |= s["courses"]
    return merged


def course_in_scope(scope: dict, course_row) -> bool:
    """某个已汇总的范围是否覆盖这门课。"""
    if scope.get("all"):
        return True
    course_id = _row_get(course_row, "id")
    try:
        if int(course_id) in scope["courses"]:
            return True
    except (TypeError, ValueError):
        pass
    cat = str(_row_get(course_row, "category", "") or "").strip()
    return bool(cat) and cat in scope["categories"]


def user_course_access(conn, user_id: int, course_id: int) -> bool:
    """用户能否访问指定课程（不判管理员，调用方自行短路）。"""
    course = conn.execute("SELECT id, category FROM courses WHERE id = ?",
                          (course_id,)).fetchone()
    if course is None:
        return False
    return course_in_scope(user_course_scope(conn, user_id), course)


def user_accessible_courses(conn, user_id: int) -> set:
    """用户有权访问的课程 id 集合。用于课程列表一次算完，避免逐门查库。"""
    scope = user_course_scope(conn, user_id)
    rows = conn.execute("SELECT id, category FROM courses").fetchall()
    return {int(r["id"]) for r in rows if course_in_scope(scope, r)}


def user_activated(conn: object, user_id: int) -> bool:
    """这个账号有没有用过**任意**一个激活码。

    注意：改动后它**不再**代表"全站课程都解锁"（那是 user_course_scope 的事）。
    它现在只用来判断「要不要给这个用户显示激活入口」这类界面逻辑。
    """
    return conn.execute(
        "SELECT 1 FROM activation_codes WHERE used_by = ? LIMIT 1", (user_id,)
    ).fetchone() is not None


def user_course_count(conn, user_id: int) -> int:
    """用户已解锁的课程数，用于激活成功后给一句明确的反馈。"""
    return len(user_accessible_courses(conn, user_id))


def user_has_all_courses(conn, user_id: int) -> bool:
    """用户是否已解锁**全部开放中的课程**。

    用来判断「还需不需要显示激活入口」——注意不能再用 user_activated
    （那只是"用过任意一个码"），否则只拿到部分课程的人会找不到地方补码。
    """
    scope = user_course_scope(conn, user_id)
    if scope["all"]:
        return True
    total = conn.execute("SELECT COUNT(*) c FROM courses WHERE is_open = 1").fetchone()["c"]
    if total == 0:
        return True
    return len(user_accessible_courses(conn, user_id)) >= total


def redeem_code(conn: object, code_text: str, user_id: int) -> str | None:
    """成员使用激活码：成功绑定到账号，返回 None；失败返回错误提示。"""
    text = (code_text or "").strip().upper()
    if not text:
        return "请输入激活码"
    row = conn.execute("SELECT * FROM activation_codes WHERE code = ?", (text,)).fetchone()
    if row is None:
        return "激活码不存在，请核对后重试（注意短横线和字母，大小写都可以）"
    if row["used_by"] == user_id:
        return "这个激活码你自己已经用过了"          # 累加允许，但同一个码重复输没有意义
    # AND used_by IS NULL 防并发双用：两个请求同时抢同一个码，只有一个能改成功
    cur = conn.execute(
        "UPDATE activation_codes SET used_by = ?, used_at = ? WHERE id = ? AND used_by IS NULL",
        (user_id, now(), row["id"]))
    conn.commit()
    if cur.rowcount == 0:
        return "这个激活码已经被别的账号使用了"
    return None


# ---------------------------------------------------------------- 个人云盘

def drive_usage(conn: object, user_id: int) -> dict:
    """某个用户云盘已用空间与文件数。"""
    row = conn.execute(
        "SELECT COALESCE(SUM(size), 0) AS bytes, COUNT(*) AS count "
        "FROM files WHERE kind = 'drive' AND owner_id = ?",
        (user_id,)).fetchone()
    return {"bytes": row["bytes"], "count": row["count"]}


# ---------------------------------------------------------------- 课程作业

def course_assignments(conn: object, course_id: int,
                       user_id: int | None = None) -> list[dict]:
    """某门课程的作业列表。

    传了 user_id 时顺带查出这个人每份作业的提交情况，
    前台要显示「已提交 / 未提交」，后台要显示「已交 N 人」。
    """
    out: list[dict] = []
    for row in conn.execute(
        "SELECT * FROM assignments WHERE course_id = ? ORDER BY sort_order, id",
        (course_id,),
    ):
        item = dict(row)
        item["submit_count"] = conn.execute(
            "SELECT COUNT(DISTINCT owner_id) c FROM files "
            "WHERE kind = 'submission' AND assignment_id = ?",
            (row["id"],)).fetchone()["c"]
        item["mine"] = None
        item["my_count"] = 0
        if user_id:
            item["mine"] = conn.execute(
                "SELECT * FROM files WHERE kind = 'submission' AND assignment_id = ? "
                "AND owner_id = ? ORDER BY id DESC LIMIT 1",
                (row["id"], user_id)).fetchone()
            item["my_count"] = conn.execute(
                "SELECT COUNT(*) c FROM files WHERE kind = 'submission' AND assignment_id = ? "
                "AND owner_id = ?", (row["id"], user_id)).fetchone()["c"]
        out.append(item)
    return out


def course_videos(conn: object, course_id: int) -> list:
    """某门课程的视频列表，按排序号正序。"""
    return conn.execute(
        "SELECT * FROM videos WHERE course_id = ? ORDER BY sort_order, id",
        (course_id,)).fetchall()


# ---------------------------------------------------------------- 加入我们

def join_stats(conn: object) -> dict:
    """报名实时统计：总数、今日新增、愿进群人数、最近一条的时间。"""
    row = conn.execute(
        "SELECT COUNT(*) AS total, "
        "COALESCE(SUM(CASE WHEN join_group = 1 THEN 1 ELSE 0 END), 0) AS group_yes, "
        "COALESCE(SUM(CASE WHEN substr(created_at, 1, 10) = ? THEN 1 ELSE 0 END), 0) AS today, "
        "MAX(created_at) AS latest "
        "FROM join_requests",
        (today(),),
    ).fetchone()
    stats = dict(row)
    stats["group_no"] = stats["total"] - stats["group_yes"]
    stats["rate"] = round(stats["group_yes"] * 100 / stats["total"]) if stats["total"] else 0
    return stats


def normalize_contact(text: str) -> str:
    """联系方式去掉多余空白，方便查重。"""
    return " ".join((text or "").split())


# ---------------------------------------------------------------- 导出

def csv_bytes(headers: list[str], rows) -> bytes:
    """带 BOM 的 UTF-8 CSV，Excel 双击不乱码。"""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(headers)
    for row in rows:
        writer.writerow(["" if v is None else v for v in row])
    return b"\xef\xbb\xbf" + buf.getvalue().encode("utf-8")
