#!/usr/bin/env bash
# 教学管理系统 · macOS / Linux 一键配置与启动
# 用法：
#   ./setup.sh           启动（装依赖 + 运行）
#   ./setup.sh --no-run  只装依赖与生成配置，不启动
set -e
cd "$(dirname "$0")"
exec python3 setup.py "$@"
