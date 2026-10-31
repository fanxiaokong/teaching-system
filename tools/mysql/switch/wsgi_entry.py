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
os.environ.setdefault("SECRET_KEY", "netlab-secret-key-change-me")

sys.path.insert(0, "/opt/websystem/app")

from core import create_app  # noqa: E402

application = create_app()
