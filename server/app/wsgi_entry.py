"""Apache mod_wsgi 入口：设置数据目录与密钥，然后交给 core.create_app()。

数据库后端（SQLite / MySQL）通过**配置文件**选择，不依赖 Apache 的 SetEnv：

    /opt/websystem/db-backend.env      ← 存在则逐行 KEY=VALUE 注入 os.environ
                                         不存在 → 全默认（SQLite）

切换 = 写入该文件 + 重启 apache2；回滚 = 挪走该文件 + 重启 apache2。
真正的变量名/默认值定义在 app/db.py，这里只负责「把文件读进环境」。
"""
import os
import sys

DB_ENV_FILE = os.environ.get("NETLAB_DB_ENV_FILE", "/opt/websystem/db-backend.env")


def _load_db_env(path):
    """把 KEY=VALUE 文件读进 os.environ。

    两种"读不到"要区别对待：
      · 文件不存在  → 正常情况，说明就该用 SQLite，静默返回
      · 读不了（权限/IO）→ **不能崩**，否则整个站点 500；
        退回 SQLite 并在错误日志里喊一声（冒烟测试会发现后端不对）
    """
    try:
        with open(path, "r", encoding="utf-8") as fh:
            lines = fh.readlines()
    except FileNotFoundError:
        return
    except OSError as exc:
        print("[wsgi_entry] 读不了 %s（%s）—— 退回默认后端（SQLite）" % (path, exc),
              file=sys.stderr, flush=True)
        return
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key:
            os.environ[key] = val


_load_db_env(DB_ENV_FILE)

os.environ.setdefault("DATA_DIR", "/opt/websystem/data")


def _ensure_secret_key():
    """保证 SECRET_KEY 是**本机私有**的强随机值。

    以前这里是写死的 "netlab-secret-key-change-me"。这个常量一旦泄漏，
    任何拿到它的人都能自己签发合法的登录 token / session —— 而站点口令
    现在还是明文存的，等于把后门钥匙挂在门上。所以改成：

        1) 环境/配置文件里有  → 用它（人工轮换的口子）
        2) 否则读 /opt/websystem/secret.key
        3) 再否则生成一份并落盘（chmod 600），保证重启后 session 不失效
    """
    if os.environ.get("SECRET_KEY"):
        return
    import secrets as _secrets
    path = os.environ.get("NETLAB_SECRET_FILE", "/opt/websystem/secret.key")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            key = fh.read().strip()
        if key:
            os.environ["SECRET_KEY"] = key
            return
    except FileNotFoundError:
        pass
    except OSError as exc:
        print("[wsgi_entry] 读不了 %s（%s）" % (path, exc), file=sys.stderr, flush=True)

    key = _secrets.token_hex(32)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(key + "\n")
        print("[wsgi_entry] 已生成新的 SECRET_KEY → %s" % path, file=sys.stderr, flush=True)
    except OSError as exc:
        # 落盘失败也不能崩：宁可本次用随机的（重启后需重新登录）
        print("[wsgi_entry] 写不了 %s（%s）—— 本次使用临时密钥" % (path, exc),
              file=sys.stderr, flush=True)
    os.environ["SECRET_KEY"] = key


_ensure_secret_key()

sys.path.insert(0, "/opt/websystem/app")

from core import create_app  # noqa: E402

application = create_app()
