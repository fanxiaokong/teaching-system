#!/usr/bin/env bash
# ============================================================================
#  本地驱动：把切换用到的文件上传到服务器，然后在服务器上执行切换/回滚/冒烟
#
#      ./deploy-switch.sh check          # 上传 + 只体检（--dry-run）
#      ./deploy-switch.sh switch         # 上传 + 真正切到 MySQL
#      ./deploy-switch.sh smoke          # 上传 + 只跑冒烟（mysql）
#      ./deploy-switch.sh rollback       # 上传 + 回滚到 SQLite
#
#  前提：~/.ssh/teaching_system_deploy 能免密登录 root@your-server.example.com
# ============================================================================
set -Eeuo pipefail

HOST=root@your-server.example.com
KEY="$HOME/.ssh/teaching_system_deploy"
REMOTE_DIR=/opt/websystem/tools/mysql/switch
REPO="$(cd "$(dirname "$0")/../../.." && pwd)"

SSH=(ssh -i "$KEY" -o BatchMode=yes -o ConnectTimeout=10 "$HOST")
SCP=(scp -i "$KEY" -o BatchMode=yes -o ConnectTimeout=10)

ACTION="${1:-check}"

log() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
ok()  { printf '    \033[32m✔ %s\033[0m\n' "$*"; }
die() { printf '\n\033[1;31m❌ %s\033[0m\n' "$*" >&2; exit 1; }

log "0/2 上传 payload → $HOST:$REMOTE_DIR"
"${SSH[@]}" "mkdir -p $REMOTE_DIR"
FILES=(
    "$REPO/server/app/mysqldialect.py"
    "$REPO/server/app/mysqldb.py"
    "$REPO/server/app/db.py"
    "$REPO/tools/mysql/migrate_sqlite_to_mysql.py"
    "$REPO/tools/mysql/switch/wsgi_entry.py"
    "$REPO/tools/mysql/switch/switch-to-mysql.sh"
    "$REPO/tools/mysql/switch/rollback-to-sqlite.sh"
    "$REPO/tools/mysql/switch/smoke-test.sh"
)
for f in "${FILES[@]}"; do [ -f "$f" ] || die "本地缺文件：$f"; done
"${SCP[@]}" "${FILES[@]}" "$HOST:$REMOTE_DIR/"
"${SSH[@]}" "chmod 755 $REMOTE_DIR/*.sh; sed -i 's/\r$//' $REMOTE_DIR/*.sh; chmod 644 $REMOTE_DIR/*.py; ls -la $REMOTE_DIR"
ok "上传完成"

log "1/2 执行动作：$ACTION"
case "$ACTION" in
    check)    "${SSH[@]}" "bash $REMOTE_DIR/switch-to-mysql.sh --dry-run" ;;
    switch)   "${SSH[@]}" "bash $REMOTE_DIR/switch-to-mysql.sh" ;;
    smoke)    "${SSH[@]}" "bash $REMOTE_DIR/smoke-test.sh --expect mysql" ;;
    rollback) "${SSH[@]}" "bash $REMOTE_DIR/rollback-to-sqlite.sh" ;;
    *) die "未知动作：${ACTION}（可用：check|switch|smoke|rollback）" ;;
esac
