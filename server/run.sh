#!/bin/bash
# 本地开发启动脚本
# 用法：  ./run.sh          → 开发模式（改代码自动重载）
#         PORT=9000 ./run.sh → 换个端口
set -e

HERE="$(cd "$(dirname "$0")" && pwd)"

export DATA_DIR="$HERE/data"
export SECRET_KEY="${SECRET_KEY:-dev-secret-key-local-only}"
export BASE_PATH="${BASE_PATH:-}"
export PORT="${PORT:-8000}"
export FLASK_ENV=development

cd "$HERE/app"
exec "$HERE/.venv/bin/python" wsgi.py
