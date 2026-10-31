#!/usr/bin/env bash
# ============================================================================
#  一键回滚：把线上站点从 MySQL 退回 SQLite（在【服务器】上以 root 运行）
#
#      ./rollback-to-sqlite.sh
#
#  做的事：挪走后端开关文件 → 重启 apache → 冒烟验证回到 SQLite。
#  SQLite 库自切换起就没被写过，所以回滚 = 瞬间恢复到切换前那一刻的状态。
#
#  ⚠️ 注意：切到 MySQL 之后产生的写入（新用户/新课件/last_login_at 等）
#           **不在** SQLite 里，回滚后这些改动会"消失"。若需要保留，
#           请先跑 migrate 的**反向导出**（见文末提示）再回滚。
# ============================================================================
set -Eeuo pipefail

TS="$(date +%Y%m%d-%H%M%S)"
ENVFILE=/opt/websystem/db-backend.env
APP=/opt/websystem/app
BKROOT=/opt/websystem/backups
HERE="$(cd "$(dirname "$0")" && pwd)"

log() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
ok()  { printf '    \033[32m✔ %s\033[0m\n' "$*"; }
die() { printf '\n\033[1;31m❌ %s\033[0m\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "必须以 root 运行"

log "1/4 检查当前开关"
if [ ! -f "$ENVFILE" ]; then
    ok "没有 $ENVFILE —— 站点本来就在 SQLite 上，无需回滚"
    exit 0
fi
grep -q 'NETLAB_DB_BACKEND=mysql' "$ENVFILE" && ok "当前后端 = mysql" || ok "当前后端非 mysql（仍按回滚处理）"

log "2/4 挪走开关文件"
mkdir -p "$BKROOT"
mv "$ENVFILE" "$BKROOT/db-backend.env.disabled-$TS"
ok "已移到 $BKROOT/db-backend.env.disabled-$TS"

log "3/4 重启 apache2"
systemctl restart apache2
sleep 2
systemctl is-active --quiet apache2 || die "apache2 没起来！"
ok "apache2 已重启"

log "4/4 冒烟验证已回到 SQLite"
bash "$HERE/smoke-test.sh" --expect sqlite

printf '\n\033[1;32m🎉 已回滚到 SQLite\033[0m\n'
cat <<'TIP'

  若想把 MySQL 期间的改动也带回 SQLite，可先在 MySQL 上导一份全量数据：
      mysql -uadmin -p'CHANGE_ME_PASSWORD' netlab -e "SHOW TABLES"   # 自查
  然后联系我生成一份「MySQL → SQLite」的反向脚本（当前未提供）。
TIP
