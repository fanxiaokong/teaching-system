#!/bin/bash
# ══════════════════════════════════════════════════════════════
#  用 Navicat / 命令行 连【线上生产 MySQL】
#
#  为什么不能直接填 your-server.example.com:3306 ？
#    服务器上的 MySQL **只监听 127.0.0.1**（bind-address = 127.0.0.1），
#    而且账号也只有 admin@localhost / admin@127.0.0.1，没有 admin@% 。
#    这是刻意留的安全边界 —— 数据库绝不能对公网开 3306。
#
#  正确姿势：SSH 端口转发
#    本脚本把 本地 13306 → 服务器 127.0.0.1:3306 打通，
#    于是 Navicat 连「127.0.0.1 : 13306」就等于连上了服务器本机的 MySQL。
#
#  用法：
#    ./tools/db-mysql-live.sh          # 开隧道（已在开则复用）+ 打印连接信息 + 自测
#    ./tools/db-mysql-live.sh --test   # 只自测（顺带确认隧道还活着）
#    ./tools/db-mysql-live.sh --stop   # 关隧道
# ══════════════════════════════════════════════════════════════
set -e

HOST="${LC_HOST:-your-server.example.com}"
KEY="${LC_KEY:-$HOME/.ssh/teaching_system_deploy}"
LPORT="${LC_LPORT:-13306}"          # 本地端口（避开本机 MySQL 的 3306）
RPORT="3306"
DB_USER="admin"
DB_PASS='CHANGE_ME_PASSWORD'
DB_NAME="netlab"

SSH_OPTS=(-i "$KEY" -N
          -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null
          -o ConnectTimeout=15 -o ExitOnForwardFailure=yes
          -o ServerAliveInterval=30 -o ServerAliveCountMax=3)

tunnel_pids() { lsof -nP -iTCP:"$LPORT" -sTCP:LISTEN -t 2>/dev/null || true; }

stop_tunnel() {
    local pids; pids=$(tunnel_pids)
    if [ -n "$pids" ]; then
        echo "$pids" | xargs kill 2>/dev/null || true
        sleep 1
        echo "已关闭隧道（本地 ${LPORT}）"
    else
        echo "本地 $LPORT 本来就没在监听"
    fi
}

show_info() {
    cat <<EOF

────────────────────────────────────────────────────────────
 Navicat 里这样填（注意：主机是 **127.0.0.1**，不是 your-server.example.com）
────────────────────────────────────────────────────────────
   连接名   : Web.System（线上 MySQL）
   主机     : 127.0.0.1
   端口     : $LPORT          ← 本机隧道端口，不是 3306
   用户名   : $DB_USER
   密码     : $DB_PASS
   数据库   : $DB_NAME

 命令行验证：
   mysql -h 127.0.0.1 -P $LPORT -u $DB_USER -p'$DB_PASS' $DB_NAME

 ⚠️ 隧道只在本脚本/终端存活期间有效；关掉就断。
    要长期用，建议在 Navicat 里配「SSH 标签」（见文末）。
────────────────────────────────────────────────────────────
EOF
}

run_test() {
    echo "自测：通过隧道连服务器 MySQL …"
    if mysql -h 127.0.0.1 -P "$LPORT" -u "$DB_USER" -p"$DB_PASS" "$DB_NAME" -N -B \
         -e "SELECT CONCAT('OK  MySQL ', VERSION(), ' / 表数 ', (SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='$DB_NAME'), ' / users ', (SELECT COUNT(*) FROM users));" 2>&1 \
         | grep -v "insecure"; then
        echo "隧道可用 ✔"
    else
        echo "❌ 连不上。检查隧道是否还活着：./tools/db-mysql-live.sh --stop 后重开" >&2
        return 1
    fi
}

case "${1:-start}" in
    --stop|stop)
        stop_tunnel; exit 0 ;;
    --test|test)
        run_test; exit $? ;;
esac

# ---- 开隧道（已开则复用）
if [ -n "$(tunnel_pids)" ]; then
    echo "本地 $LPORT 已在监听，复用现有隧道。"
else
    echo "建立隧道：本地 $LPORT → 服务器 127.0.0.1:$RPORT"
    # 用 -f：认证成功且端口绑定完成后 ssh 自己转入后台，
    # 既不继承本脚本的 stdout（否则会挂住调用方），也不阻塞在这里。
    ssh -f "${SSH_OPTS[@]}" -L "127.0.0.1:${LPORT}:127.0.0.1:${RPORT}" "root@${HOST}" \
        || { echo "❌ 隧道建立失败（认证失败 或 本地 $LPORT 被占）" >&2; exit 1; }
    for _ in $(seq 1 20); do
        [ -n "$(tunnel_pids)" ] && break
        sleep 0.5
    done
    if [ -z "$(tunnel_pids)" ]; then
        echo "❌ 隧道没起来。检查 $KEY 是否能免密登录 root@$HOST" >&2
        exit 1
    fi
    echo "隧道已建立 ✔（pid $(tunnel_pids | tr '\n' ' ')）"
fi

show_info
run_test
