#!/usr/bin/env bash
# 站点冒烟测试（在【服务器】上以 root 运行）。
#
#   smoke-test.sh --expect mysql   # 切换后：确认站点真的跑在 MySQL 上、且完好
#   smoke-test.sh --expect sqlite  # 回滚后：确认站点回到 SQLite 且完好
#
# 全程只读，唯一"写"是在**临时表**里插一行再回滚，对生产数据零影响。
#
# 三重证明（都不需要管理员口令）：
#   ① 配置层  —— wsgi daemon 进程的 /proc/<pid>/environ 里有 NETLAB_DB_BACKEND
#   ② 运行层  —— 打站点时 MySQL 的 Connections 计数会涨（=应用真的在连 MySQL）
#   ③ 语义层  —— 用 venv python 走应用自己的 db.connect() 跑 SELECT + 临时表写入
set -Eeuo pipefail

VENV=/opt/websystem/venv
APP=/opt/websystem/app
EXPECT=sqlite
REF=""          # 可选：切换时导出的预期行数 JSON
SITE=https://your-server.example.com

while [ $# -gt 0 ]; do
    case "$1" in
        --expect) EXPECT="$2"; shift 2 ;;
        --ref)    REF="$2"; shift 2 ;;
        --site)   SITE="$2"; shift 2 ;;
        *) echo "未知参数: $1" >&2; exit 2 ;;
    esac
done

PASS=0; FAIL=0
ok()   { printf '  \033[32m✅ %s\033[0m\n' "$*"; PASS=$((PASS+1)); }
bad()  { printf '  \033[31m❌ %s\033[0m\n' "$*"; FAIL=$((FAIL+1)); }
head_() { printf '\n\033[1m%s\033[0m\n' "$*"; }

mysql_q() { mysql -uadmin -p"${MYSQL_PW:-CHANGE_ME_PASSWORD}" -N -B -e "$1" 2>/dev/null || true; }

# ---------------------------------------------------------------- ① 服务在跑
head_ "① 服务状态"
if systemctl is-active --quiet apache2; then ok "apache2 active"; else bad "apache2 没在跑"; fi
if systemctl is-active --quiet mysql; then ok "mysql active"; else
    [ "$EXPECT" = mysql ] && bad "mysql 没在跑" || echo "  · mysql 未运行（当前用 SQLite，可接受）"
fi

# ---------------------------------------------------------------- ② 开关文件
# 注意：**不能**去读 /proc/<pid>/environ 判断后端 —— 那只是进程 exec 时的初始环境，
# 而 NETLAB_DB_BACKEND 是 wsgi_entry.py 在 Python 运行时 os.environ 设进去的（putenv
# 不更新 /proc/environ），永远读不到。所以这里只报「配置文件说了什么」，
# 运行时到底走哪个库，由 ④ 的计数器来证明。
head_ "② 后端开关文件（配置层）"
if [ -f /opt/websystem/db-backend.env ]; then
    be=$(sed -n 's/^NETLAB_DB_BACKEND=//p' /opt/websystem/db-backend.env | head -1)
    be="${be:-sqlite}"
    if [ "$be" = "$EXPECT" ]; then ok "开关文件 NETLAB_DB_BACKEND=$be"; else bad "开关文件=${be}，预期 $EXPECT"; fi
    # 顺带确认运行身份读得到（这是上次整站 500 的根因）
    if sudo -u www-data test -r /opt/websystem/db-backend.env; then
        ok "www-data 可读"
    else
        bad "www-data 读不了开关文件"
    fi
elif [ "$EXPECT" = sqlite ]; then
    ok "无开关文件 → 默认 SQLite（符合预期）"
else
    bad "开关文件不存在，但预期 $EXPECT"
fi

# ---------------------------------------------------------------- ③ HTTP
head_ "③ 站点 HTTP"
check_url() {  # $1=path $2=期望码(逗号分隔) $3=body 需含的关键字(可空)
    local path="$1" want="$2" needle="${3:-}"
    local out code body
    out=$(curl -sS -o /tmp/_smoke.body -w '%{http_code}' -m 20 "$SITE$path" 2>/dev/null || echo 000)
    code="$out"; body=$(head -c 400 /tmp/_smoke.body 2>/dev/null || true)
    if echo ",$want," | grep -q ",$code,"; then
        if [ -z "$needle" ] || printf '%s' "$body" | grep -q "$needle"; then
            ok "GET $path → $code"
        else
            bad "GET $path → $code 但正文不含 '$needle'"
        fi
    else
        bad "GET $path → ${code}（期望 ${want}）"
    fi
}
check_url /api/ping        200 ok
check_url /api/v1/ping     200
check_url /api/v1/home     200
check_url /courses         200,302      # 匿名访问会被重定向到登录页，302 属正常
check_url /api/v1/courses  200,401      # 需要登录，401 属正常
check_url /api/v1/app/version 200
check_url /admin           200,302      # 未登录应跳转或给出登录页

# ---------------------------------------------------------------- ④ 运行层铁证
if [ "$EXPECT" = mysql ]; then
    head_ "④ 应用真的在查 MySQL 吗（运行层铁证）"
    # 判别力来自"差分"：若应用走 SQLite，打站点**不会**让 MySQL 的
    # 连接数 / SELECT 数增长。两个计数器同时涨，才能证明请求真的查了 MySQL。
    b_conn=$(mysql_q "SHOW GLOBAL STATUS LIKE 'Connections'"  | awk '{print $2}')
    b_sel=$(mysql_q   "SHOW GLOBAL STATUS LIKE 'Com_select'"   | awk '{print $2}')
    for _ in 1 2 3 4 5; do curl -sS -o /dev/null -m 20 "$SITE/api/v1/home" || true; done
    sleep 1
    a_conn=$(mysql_q "SHOW GLOBAL STATUS LIKE 'Connections'"  | awk '{print $2}')
    a_sel=$(mysql_q   "SHOW GLOBAL STATUS LIKE 'Com_select'"   | awk '{print $2}')
    d_conn=$(( ${a_conn:-0} - ${b_conn:-0} ))
    d_sel=$((  ${a_sel:-0}  - ${b_sel:-0}  ))
    if [ "$d_conn" -ge 3 ]; then
        ok "5 次页面请求 → MySQL 连接数 +$d_conn"
    else
        bad "MySQL 连接数只 +${d_conn}，应用可能没走 MySQL"
    fi
    if [ "$d_sel" -ge 5 ]; then
        ok "5 次页面请求 → MySQL SELECT 数 +${d_sel}（确实在查 MySQL）"
    else
        bad "MySQL SELECT 只 +${d_sel}，请求可能没落到 MySQL 上"
    fi
fi

# ---------------------------------------------------------------- ⑤ 语义层
if [ "$EXPECT" = mysql ]; then
    head_ "⑤ 走应用自己的 db 层（语义层）"
    cat > /tmp/_smoke_probe.py <<'PY'
import sys
sys.path.insert(0, "/opt/websystem/app")
import db
print("backend =", db.BACKEND)
conn = db.connect()
cur = conn.cursor()
cur.execute("SELECT COUNT(*) AS n FROM users")
print("users =", cur.fetchone()["n"])
cur.execute("CREATE TEMPORARY TABLE _wb_probe (x INT)")
cur.execute("INSERT INTO _wb_probe (x) VALUES (1), (2)")
cur.execute("SELECT COUNT(*) AS n FROM _wb_probe")
print("temp write ok, rows =", cur.fetchone()["n"])
try:
    cur.execute("SELECT id, group_name, title FROM nav_links LIMIT 1")
    print("nav_links sample =", cur.fetchone())
except Exception as e:
    print("nav_links probe:", e)
conn.rollback()
conn.close()
print("ROLLBACK DONE")
PY
    if NETLAB_DB_BACKEND=mysql NETLAB_MYSQL_HOST=127.0.0.1 NETLAB_MYSQL_USER=admin \
       NETLAB_MYSQL_PASSWORD="${MYSQL_PW:-CHANGE_ME_PASSWORD}" NETLAB_MYSQL_DATABASE=netlab \
       "$VENV/bin/python" /tmp/_smoke_probe.py 2>&1 | tee /tmp/_smoke_probe.out | sed 's/^/    /'; then :; fi
    if grep -q "ROLLBACK DONE" /tmp/_smoke_probe.out; then
        ok "应用 db 层在 MySQL 上连通 + 可写（临时表）+ 可回滚"
    else
        bad "应用 db 层探针失败（见上）"
    fi
    rm -f /tmp/_smoke_probe.py /tmp/_smoke_probe.out
fi

# ---------------------------------------------------------------- ⑥ 行数对账
if [ -n "$REF" ] && [ -f "$REF" ]; then
    head_ "⑥ 28 张表行数对账（vs 切换时的 SQLite）"
    if [ "$EXPECT" = mysql ]; then
        set +e
        python3 - "$REF" <<'PY'
import json, subprocess, sys
ref = json.load(open(sys.argv[1]))
pw = "CHANGE_ME_PASSWORD"
bad = 0
for t in sorted(ref):
    q = "SELECT COUNT(*) FROM `%s`;" % t
    r = subprocess.run(["mysql","-uadmin","-p"+pw,"-N","-B","netlab","-e",q],
                       capture_output=True, text=True)
    got = r.stdout.strip()
    mark = "✅" if got == str(ref[t]) else "❌"
    if mark == "❌": bad += 1
    print("    %s %-22s sqlite=%-6s mysql=%s" % (mark, t, ref[t], got))
print("    不一致 %d 张表" % bad)
sys.exit(1 if bad else 0)
PY
        rc=$?
        set -e
        if [ "$rc" -eq 0 ]; then ok "行数与切换时一致"; else bad "存在行数不一致"; fi
    fi
fi

head_ "结果"
printf '  通过 %d 项，失败 %d 项\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ] || exit 1
echo "  🎉 冒烟测试全通过"
