#!/bin/bash
# 本地开发启动脚本
# 用法：  ./run.sh          → 开发模式（改代码自动重载）
#         PORT=9000 ./run.sh → 换个端口
set -e

HERE="$(cd "$(dirname "$0")" && pwd)"

# 加载项目根目录的 .env（若存在，由 setup.py 生成），让用户自定义配置优先生效
ROOT_ENV="$(cd "$HERE/.." && pwd)/.env"
if [ -f "$ROOT_ENV" ]; then
  set -a
  . "$ROOT_ENV"
  set +a
fi

export DATA_DIR="${DATA_DIR:-$HERE/data}"
export SECRET_KEY="${SECRET_KEY:-dev-secret-key-local-only}"
export BASE_PATH="${BASE_PATH:-}"
export PORT="${PORT:-8000}"
export FLASK_ENV="${FLASK_ENV:-development}"

cd "$HERE/app"
exec "$HERE/.venv/bin/python" wsgi.py
