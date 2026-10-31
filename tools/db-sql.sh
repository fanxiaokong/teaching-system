#!/bin/bash
# ══════════════════════════════════════════════════════════════
#  在【线上生产库】上执行 SQL —— 带安全护栏
#
#  为什么需要它：
#    Navicat 里连的「线上库」其实是本地镜像（SQLite 没有网络协议，
#    没法真的直连）。在镜像上改数据**不会影响线上**。
#    真要改生产数据，用本脚本 —— 它比「上传整个库覆盖」安全得多。
#
#  安全设计：
#    · 默认只读：非 SELECT/PRAGMA/EXPLAIN/WITH 的语句一律拒绝执行
#    · 写操作必须显式加 --write，且会在服务器上**自动先备份**一份带时间戳的库
#    · SQL 以 base64 传输，避免多层 shell 引号地狱
#
#  用法：
#    ./tools/db-sql.sh "SELECT id,username FROM users LIMIT 5;"
#    ./tools/db-sql.sh --write "UPDATE users SET nickname='x' WHERE id=1;"
# ══════════════════════════════════════════════════════════════
set -e

HOST="${LC_HOST:-YOUR_SERVER_IP}"
KEY="${LC_KEY:-$HOME/.ssh/teaching_system_deploy}"
REMOTE_DB="/opt/websystem/data/netlab.db"
SSH="ssh -i $KEY -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=15 root@$HOST"

WRITE_OK=0
if [ "$1" = "--write" ]; then WRITE_OK=1; shift; fi

SQL="$1"
if [ -z "$SQL" ]; then
  cat <<'USAGE'
用法：
  db-sql.sh "SELECT ..."                  # 只读查询
  db-sql.sh --write "UPDATE/DELETE ..."   # 写操作（会自动先备份）

示例：
  db-sql.sh "SELECT count(*) FROM users;"
  db-sql.sh "SELECT platform,version_code,version_name,is_latest FROM app_versions;"
  db-sql.sh --write "UPDATE users SET nickname='孔' WHERE id=1;"
USAGE
  exit 1
fi

# 判断是否写操作（取第一个关键词）
FIRST=$(printf '%s' "$SQL" | sed 's/^[[:space:]]*//' | cut -d' ' -f1 | tr '[:lower:]' '[:upper:]')
case "$FIRST" in
  SELECT|PRAGMA|EXPLAIN|WITH|VALUES) IS_WRITE=0 ;;
  *) IS_WRITE=1 ;;
esac

if [ "$IS_WRITE" = "1" ] && [ "$WRITE_OK" = "0" ]; then
  echo "❌ 检测到这是写操作（关键字：${FIRST}），已拒绝执行。"
  echo
  echo "   如果确实要改【生产库】，请显式确认："
  echo "     $0 --write \"$SQL\""
  echo
  echo "   脚本会在动手前自动备份一份带时间戳的库到 /opt/websystem/data/。"
  exit 2
fi

B64=$(printf '%s' "$SQL" | base64)

if [ "$IS_WRITE" = "1" ]; then
  TS=$(date +%Y%m%d-%H%M%S)
  echo "⚠️  写操作 · 生产库 · $REMOTE_DB"
  echo "==> 1/2 自动备份到 netlab.db.bak-cli-$TS"
  $SSH "cp '$REMOTE_DB' '$REMOTE_DB.bak-cli-$TS' && ls -la '$REMOTE_DB.bak-cli-$TS'"
  echo "==> 2/2 执行 SQL"
else
  echo "==> 只读查询 · 生产库 · $REMOTE_DB"
fi

# SQL 走 base64 传输，远端解码后交给 sqlite3
$SSH "echo '$B64' | base64 -d > /tmp/.dbsql-$$.sql && sqlite3 -header -column '$REMOTE_DB' < /tmp/.dbsql-$$.sql; RC=\$?; rm -f /tmp/.dbsql-$$.sql; exit \$RC"
