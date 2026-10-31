#!/usr/bin/env bash
# ============================================================================
#  mysql-allow.sh —— 管理「Navicat 直连口 13306」的来源白名单
#
#  背景：13306 是 nginx 四层代理到 MySQL 的口子。因为库里的口令是明文存的，
#  这个口子绝不能对全网开放，所以用 ufw 做了来源白名单，只放行你明确列出的 IP。
#
#  用法（在服务器上以 root 跑）：
#     mysql-allow.sh show                看当前白名单
#     mysql-allow.sh add 1.2.3.4         放行一个 IP
#     mysql-allow.sh del 1.2.3.4         移除一个 IP
#     mysql-allow.sh me                  打印"帮你加自己当前 IP"的命令（在你本机跑）
#
#  换网络后 Navicat 连不上？先在你自己的电脑上跑：
#       curl -s https://ifconfig.me ; echo
#  把打出来的 IP 加到服务器白名单：
#       ssh root@YOUR_SERVER_IP "mysql-allow.sh add <那个IP>"
#
#  不想加白名单的临时办法（不受本白名单影响，走 SSH 加密隧道）：
#       ssh -L 13306:127.0.0.1:3306 root@YOUR_SERVER_IP
#       Navicat 连 127.0.0.1:13306 即可
#
#  注意：删掉 ufw 里那条 13306 规则 = 口子对全网开放，别手贱。
# ============================================================================

set -uo pipefail

PORT=13306
TAG="Navicat 直连"

OK="✅"; BAD="❌"; WARN="⚠️ "
say()  { printf '%s\n' "$*"; }
pass() { printf '  %s %s\n' "${OK}" "$*"; }
fail() { printf '  %s %s\n' "${BAD}" "$*"; }
warn() { printf '  %s%s\n' "${WARN}" "$*"; }

usage() { sed -n '2,29p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }

[ "$(id -u)" -eq 0 ] || { fail "要 root 才能改防火墙"; exit 1; }
command -v ufw >/dev/null || { fail "这台机器没有 ufw"; exit 1; }

valid_ip() {
  printf '%s' "$1" | grep -qE '^([0-9]{1,3}\.){3}[0-9]{1,3}$' || return 1
  printf '%s' "$1" | awk -F. '{for(i=1;i<=4;i++) if($i<0||$i>255) exit 1}'
}

case "${1:-}" in
  show)
    say ""
    say "13306 当前白名单（ufw）："
    ufw status | grep -E "13306" || warn "没有任何 13306 规则 —— 注意：这可能意味着口子对全网开着"
    say ""
    say "同时也确认一下 ufw 总开关："
    ufw status | head -3 | sed 's/^/    /'
    say ""
    ;;
  add)
    IP="${2:-}"
    [ -z "${IP}" ] && { fail "用法：mysql-allow.sh add <IP>"; exit 1; }
    valid_ip "${IP}" || { fail "'${IP}' 看起来不是合法 IPv4"; exit 1; }
    ufw allow from "${IP}" to any port "${PORT}" proto tcp comment "${TAG}" >/dev/null
    pass "已放行 ${IP} → ${PORT}"
    say "    现在去 Navicat 试连 db.example.com:13306"
    ;;
  del)
    IP="${2:-}"
    [ -z "${IP}" ] && { fail "用法：mysql-allow.sh del <IP>"; exit 1; }
    valid_ip "${IP}" || { fail "'${IP}' 看起来不是合法 IPv4"; exit 1; }
    ufw --force delete allow from "${IP}" to any port "${PORT}" proto tcp >/dev/null
    pass "已移除 ${IP}"
    warn "请再跑 mysql-allow.sh show 确认白名单没被清空"
    ;;
  me)
    say ""
    say "在你自己的电脑上跑这条，把自己的公网 IP 报给服务器："
    say ""
    say "    curl -s https://ifconfig.me; echo"
    say ""
    say "然后："
    say "    ssh root@YOUR_SERVER_IP \"mysql-allow.sh add <上面打出来的IP>\""
    say ""
    ;;
  -h|--help|help|"") usage 0 ;;
  *) fail "未知子命令：$1"; usage 1 ;;
esac
