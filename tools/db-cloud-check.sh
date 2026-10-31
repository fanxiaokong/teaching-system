#!/usr/bin/env bash
# ============================================================================
#  db-cloud-check.sh —— 检查「从任何地方直连云数据库」这条链路通不通
#
#  用途：你在阿里云控制台放行端口 / 加完 DNS 之后，跑这个确认是否真的通了。
#  顺便会告诉你「卡在哪一步、下一步该点哪里」。
#
#  用法：
#     ./tools/db-cloud-check.sh              # 全量检查
#     ./tools/db-cloud-check.sh --quick      # 只测端口和数据库
# ============================================================================

set -uo pipefail

DOMAIN="db.example.com"
FALLBACK_IP="YOUR_SERVER_IP"
PORT="13306"
DB_USER="admin"
DB_PASS='CHANGE_ME_PASSWORD'

OK="✅"; BAD="❌"; WARN="⚠️ "
EXIT_CODE=0

say()  { printf '%s\n' "$*"; }
head_() { printf '\n\033[1m%s\033[0m\n' "$*"; }
pass() { printf '  %s %s\n' "$OK" "$*"; }
fail() { printf '  %s %s\n' "$BAD" "$*"; EXIT_CODE=1; }
warn() { printf '  %s%s\n' "$WARN" "$*"; }

QUICK=0
[ "${1:-}" = "--quick" ] && QUICK=1

if [ "$QUICK" -eq 0 ]; then
  head_ "① DNS 解析"
  DNS_IP="$(dig +short "$DOMAIN" A 2>/dev/null | head -1)"
  if [ -z "$DNS_IP" ]; then
    fail "$DOMAIN 还没有 A 记录"
    say "     → 去阿里云云解析控制台加一条：类型 A / 主机记录 sql / 值 $FALLBACK_IP"
    say "       https://dns.console.aliyun.com  →  your-server.example.com  →  解析设置  →  添加记录"
  elif [ "$DNS_IP" = "$FALLBACK_IP" ]; then
    pass "$DOMAIN → ${DNS_IP}（正确）"
  else
    warn "$DOMAIN → ${DNS_IP}，但期望是 ${FALLBACK_IP}（改过 IP？）"
  fi
fi

head_ "② 公网端口 $PORT 是否放行"
TARGET="${DNS_IP:-$FALLBACK_IP}"
if [ -z "${TARGET:-}" ]; then TARGET="$FALLBACK_IP"; fi

if nc -z -G 6 "$TARGET" "$PORT" 2>/dev/null; then
  pass "$TARGET:$PORT 可以建立 TCP 连接"
else
  fail "$TARGET:$PORT 连不上"
  say "     → 99% 是阿里云安全组没放行。控制台："
  say "       ECS → 实例 → 这台（${FALLBACK_IP}）→ 安全组 → 访问规则 → 入方向 → 手动添加"
  say "       协议类型=自定义 TCP   端口范围=$PORT/$PORT   授权对象=0.0.0.0/0   策略=允许"
  say "     → 也可以先用 IP 直连试试（绕过 DNS）：$FALLBACK_IP:$PORT"
fi

head_ "③ 数据库握手（真的能登进 netlab）"
MYSQL_BIN=""
for c in /opt/homebrew/bin/mysql /usr/local/mysql/bin/mysql "$(command -v mysql 2>/dev/null)"; do
  if [ -n "$c" ] && [ -x "$c" ]; then MYSQL_BIN="$c"; break; fi
done

if [ -z "$MYSQL_BIN" ]; then
  warn "本机找不到 mysql 客户端，跳过这一步（不影响 Navicat 使用）"
else
  RESULT="$("$MYSQL_BIN" -h "$TARGET" -P "$PORT" -u "$DB_USER" -p"$DB_PASS" \
            --connect-timeout=8 -N -B \
            -e "SELECT CONCAT(VERSION(),' | ',@@hostname,' | users=',(SELECT COUNT(*) FROM netlab.users));" 2>&1 \
            | grep -v "Using a password" | head -2)"
  if printf '%s' "$RESULT" | grep -q 'users='; then
    pass "登录成功：$RESULT"
    say "     → Navicat 就用这组参数：主机 $DOMAIN / 端口 $PORT / 用户 $DB_USER"
  else
    fail "端口通了但数据库登录失败："
    printf '     %s\n' "$RESULT"
    if printf '%s' "$RESULT" | grep -qi "caching_sha2"; then
      say "     → 是密码插件问题，运行下面这条可以切回老插件："
      say "       ssh root@your-server.example.com \"mysql -e \\\"ALTER USER 'admin'@'localhost' IDENTIFIED WITH mysql_native_password BY '$DB_PASS';\\\"\""
    elif printf '%s' "$RESULT" | grep -qi "Access denied"; then
      say "     → 账号密码不对，或这个来源 IP 不在允许范围"
    fi
  fi
fi

head_ "结论"
if [ "$EXIT_CODE" -eq 0 ]; then
  say "  $OK 链路全通，Navicat 直接连 $DOMAIN:$PORT 即可，不需要 SSH 隧道。"
else
  say "  $BAD 还有没通的地方，按上面提示的那一步去做，做完再跑一次这个脚本。"
fi
exit "$EXIT_CODE"
