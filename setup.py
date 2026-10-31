#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""教学管理系统 · 跨平台一键配置与启动脚本（Windows / macOS / Linux）

纯标准库实现，运行本脚本不需要任何第三方依赖。它会自动完成：
  1. 检测操作系统，确认本机 Python >= 3.10；
  2. 在 server/.venv 创建虚拟环境（已存在则复用）；
  3. 安装 server/app/requirements.txt 中的 Python 依赖；
  4. 生成 .env（随机 SECRET_KEY + 随机管理员密码），并写入 DATA_DIR / PORT 等；
  5. 首次启动时由应用自动建库、建管理员账号；
  6. 前台启动 Flask（wsgi.py）并打开浏览器。

用法：
  python3 setup.py              # 安装依赖 + 启动服务（默认 http://127.0.0.1:8000）
  python3 setup.py --no-run     # 只装依赖与生成配置，不启动（适合二次部署）
  python3 setup.py --port 9000  # 指定监听端口
  python3 setup.py --no-browser # 启动后不自动打开浏览器
  python3 setup.py --reinstall  # 强制重建虚拟环境并重装依赖

说明：
  · 服务端运行只需 Python；Node.js（桌面端构建）、JDK/Android SDK（安卓构建）
    与本脚本无关，缺失不影响服务端启动。
  · 数据库默认 SQLite（零配置），切 MySQL 见 .env.example。
"""
from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
import secrets
import urllib.request

ROOT = Path(__file__).resolve().parent
SERVER_DIR = ROOT / "server"
APP_DIR = SERVER_DIR / "app"
VENV_DIR = SERVER_DIR / ".venv"
REQ_FILE = APP_DIR / "requirements.txt"
ENV_FILE = ROOT / ".env"
DATA_DIR = SERVER_DIR / "data"  # 与 run.sh / README 保持一致
MIN_PY = (3, 10)


# ---------------------------------------------------------------- 基础工具
def is_windows() -> bool:
    return os.name == "nt" or platform.system().lower().startswith("win")


def venv_python() -> Path:
    if is_windows():
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def banner(msg: str) -> None:
    print("\n" + "=" * 64)
    print(" " + msg)
    print("=" * 64)


def step(msg: str) -> None:
    print("\n▶ " + msg)


def check_python() -> None:
    ver = sys.version_info[:2]
    if ver < MIN_PY:
        sys.exit(
            "✗ 需要 Python >= %d.%d，当前为 %d.%d\n"
            "  请先安装 Python 3.10+：\n"
            "    Windows: winget install Python.Python.3.12\n"
            "    macOS:   brew install python  或 https://www.python.org/downloads/\n"
            "    Linux:   sudo apt install python3.12 python3.12-venv\n"
            % (MIN_PY[0], MIN_PY[1], ver[0], ver[1])
        )
    if ver < (3, 12):
        print("⚠ 当前 Python %d.%d，低于推荐版本 3.12，可正常运行，建议升级。" % ver)


# ---------------------------------------------------------------- 环境配置
def load_env() -> dict:
    env: dict[str, str] = {}
    if not ENV_FILE.exists():
        return env
    for raw in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        env[key.strip()] = val.strip().strip('"').strip("'")
    return env


def create_env_if_missing() -> dict:
    env = load_env()
    generated = False
    if not env.get("SECRET_KEY"):
        env["SECRET_KEY"] = secrets.token_hex(32)
        generated = True
    if not env.get("ADMIN_PASSWORD"):
        env["ADMIN_PASSWORD"] = secrets.token_urlsafe(12)
        generated = True

    env.setdefault("PORT", "8000")
    env.setdefault("BASE_PATH", "")
    env.setdefault("FLASK_ENV", "development")
    env.setdefault("ADMIN_USERNAME", "admin")
    env.setdefault("ADMIN_PHONE", "13800000000")
    env.setdefault("NETLAB_DB_BACKEND", "sqlite")
    env.setdefault("NETLAB_PASSWORD_MODE", "plain")
    env["DATA_DIR"] = str(DATA_DIR)  # 始终显式指向 server/data

    if generated or not ENV_FILE.exists():
        lines = [
            "# 教学管理系统 · 服务端配置（由 setup.py 生成，已加入 .gitignore，请勿提交）",
            "# 修改后重启服务生效。SECRET_KEY / ADMIN_PASSWORD 为随机生成，请妥善保存。",
            "",
            f"PORT={env['PORT']}",
            f"BASE_PATH={env['BASE_PATH']}",
            f"FLASK_ENV={env['FLASK_ENV']}",
            f"SECRET_KEY={env['SECRET_KEY']}",
            f"DATA_DIR={env['DATA_DIR']}",
            f"ADMIN_USERNAME={env['ADMIN_USERNAME']}",
            f"ADMIN_PHONE={env['ADMIN_PHONE']}",
            f"ADMIN_PASSWORD={env['ADMIN_PASSWORD']}",
            f"NETLAB_DB_BACKEND={env['NETLAB_DB_BACKEND']}",
            f"NETLAB_PASSWORD_MODE={env['NETLAB_PASSWORD_MODE']}",
            "",
            "# ---- 切换到 MySQL（取消注释并填写真实值）----",
            "# NETLAB_DB_BACKEND=mysql",
            "# NETLAB_MYSQL_HOST=127.0.0.1",
            "# NETLAB_MYSQL_PORT=3306",
            "# NETLAB_MYSQL_USER=admin",
            "# NETLAB_MYSQL_PASSWORD=CHANGE_ME_PASSWORD",
            "# NETLAB_MYSQL_DATABASE=netlab",
        ]
        ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print("  ✓ 已生成配置：%s" % ENV_FILE)
    else:
        print("  ✓ 沿用已有配置：%s" % ENV_FILE)
    return env


# ---------------------------------------------------------------- 安装
def ensure_venv(reinstall: bool) -> None:
    if reinstall and VENV_DIR.exists():
        shutil.rmtree(VENV_DIR)
        print("  已删除旧虚拟环境，准备重建。")
    if VENV_DIR.exists():
        print("  虚拟环境已存在：%s" % VENV_DIR)
        return
    step("创建虚拟环境 %s" % VENV_DIR)
    try:
        subprocess.run([sys.executable, "-m", "venv", str(VENV_DIR)], check=True)
    except subprocess.CalledProcessError:
        sys.exit(
            "✗ 创建虚拟环境失败。Debian/Ubuntu 请先：\n"
            "    sudo apt install python3-venv python3-pip\n"
            "  然后重新运行本脚本。"
        )
    print("  ✓ 虚拟环境已创建")


def install_deps(reinstall: bool) -> None:
    step("安装 Python 依赖（%s）" % REQ_FILE)
    vpy = str(venv_python())
    # 某些精简 Python 没有 pip，先确保
    subprocess.run([vpy, "-m", "ensurepip", "--upgrade"], check=False)
    # 网络不稳时默认 15s 超时容易在解析阶段断流，拉长超时与重试
    pip_common = ["-m", "pip", "install", "--timeout", "120", "--retries", "15"]
    subprocess.run([vpy, *pip_common, "--upgrade", "pip"], check=True)
    cmd = [vpy, *pip_common, "-r", str(REQ_FILE)]
    if reinstall:
        cmd.append("--force-reinstall")
    subprocess.run(cmd, check=True)
    print("  ✓ 依赖安装完成")


def pre_flight() -> None:
    step("检查依赖是否可正常导入")
    code = "import sys; sys.path.insert(0, %r); import flask, db, core" % str(APP_DIR)
    try:
        subprocess.run([str(venv_python()), "-c", code], cwd=str(APP_DIR), check=True)
        print("  ✓ 依赖导入正常")
    except subprocess.CalledProcessError:
        sys.exit("✗ 依赖导入失败，请查看上方错误。")


# ---------------------------------------------------------------- 运行
def run_server(env: dict, port: str, open_browser: bool) -> None:
    step("启动服务端（http://127.0.0.1:%s）" % port)
    run_env = os.environ.copy()
    run_env.update({k: str(v) for k, v in env.items()})
    run_env["PORT"] = port
    # 把 venv 的 bin/Scripts 放到 PATH 最前，确保子进程用到正确的 Python 环境
    vbin = str(venv_python().parent)
    run_env["PATH"] = vbin + os.pathsep + run_env.get("PATH", "")

    proc = subprocess.Popen([str(venv_python()), "wsgi.py"], cwd=str(APP_DIR), env=run_env)
    print("  服务进程 PID=%d，按 Ctrl+C 停止。" % proc.pid)
    print("  ➜ 站点地址： http://127.0.0.1:%s" % port)
    print("  ➜ 管理员：   用户名 %s / 手机号 %s / 密码 %s"
          % (env.get("ADMIN_USERNAME"), env.get("ADMIN_PHONE"), env.get("ADMIN_PASSWORD")))

    if open_browser:
        for _ in range(30):
            time.sleep(1)
            try:
                with urllib.request.urlopen("http://127.0.0.1:%s" % port, timeout=1) as r:
                    if r.status == 200:
                        break
            except Exception:
                pass
        try:
            webbrowser.open("http://127.0.0.1:%s" % port)
        except Exception:
            pass

    try:
        proc.wait()
    except KeyboardInterrupt:
        print("\n正在停止服务…")
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()


# ---------------------------------------------------------------- 入口
def main() -> None:
    ap = argparse.ArgumentParser(description="教学管理系统 一键配置与启动")
    ap.add_argument("--no-run", action="store_true", help="只安装依赖与生成配置，不启动服务")
    ap.add_argument("--port", default=None, help="指定监听端口（默认用 .env 的 PORT 或 8000）")
    ap.add_argument("--no-browser", action="store_true", help="启动后不自动打开浏览器")
    ap.add_argument("--reinstall", action="store_true", help="强制重建虚拟环境并重装依赖")
    args = ap.parse_args()

    banner("教学管理系统 · 一键配置（%s）" % platform.system())
    check_python()

    if not REQ_FILE.exists():
        sys.exit("✗ 找不到 %s，请确认在仓库根目录运行本脚本。" % REQ_FILE)

    ensure_venv(args.reinstall)
    install_deps(args.reinstall)
    env = create_env_if_missing()
    pre_flight()

    port = args.port or env.get("PORT", "8000")

    if args.no_run:
        banner("配置完成（未启动）")
        print("  数据目录：%s" % env.get("DATA_DIR"))
        print("  管理员：  %s / %s / %s"
              % (env.get("ADMIN_USERNAME"), env.get("ADMIN_PHONE"), env.get("ADMIN_PASSWORD")))
        print("  运行 `python3 setup.py` 即可启动服务。")
        return

    run_server(env, port, open_browser=not args.no_browser)


if __name__ == "__main__":
    main()
