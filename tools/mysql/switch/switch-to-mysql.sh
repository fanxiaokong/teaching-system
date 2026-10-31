#!/usr/bin/env bash
# ============================================================================
#  把线上站点数据库从 SQLite 切到 MySQL（在【服务器】上以 root 运行）
#
#      ./switch-to-mysql.sh --dry-run     # 只体检 + 打印将执行的动作，不改任何东西
#      ./switch-to-mysql.sh               # 真正执行
#
#  设计要点
#     · SQLite 全程不动 —— 它是回滚底牌，切换前后都保持可回退状态
#     · 动手前先备份：SQLite 快照 + 应用目录 tar + Apache 配置
#     · 数据重同步用 --drop-existing 全量重建 netlab（此刻应用还在 SQLite 上跑，无影响）
#     · 后端开关 = 写 /opt/websystem/db-backend.env 一个文件 + 重启 apache
#     · 任一步失败 → 自动回滚（挪走 env 文件 + 重启），站点立刻回到 SQLite
# ============================================================================
set -Eeuo pipefail

TS="$(date +%Y%m%d-%H%M%S)"
APP=/opt/websystem/app
DATA=/opt/websystem/data
VENV=/opt/websystem/venv
TOOLS=/opt/websystem/tools/mysql
ENVFILE=/opt/websystem/db-backend.env
DB="$DATA/netlab.db"
BKROOT=/opt/websystem/backups
BK="$BKROOT/mysql-switch-$TS"
HERE="$(cd "$(dirname "$0")" && pwd)"

MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=admin
MYSQL_PASSWORD='CHANGE_ME_PASSWORD'
MYSQL_DB=netlab

DRY=0
[ "${1:-}" == "--dry-run" ] && DRY=1

log() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
sub() { printf '    %s\n' "$*"; }
ok()  { printf '    \033[32m✔ %s\033[0m\n' "$*"; }
warn(){ printf '    \033[33m! %s\033[0m\n' "$*"; }
die() { printf '\n\033[1;31m❌ %s\033[0m\n' "$*" >&2; exit 1; }

SITE_DOWN=0
rollback() {
    printf '\n\033[1;31m⚠️  出错，正在自动回滚到 SQLite…\033[0m\n'
    rm -f "$ENVFILE"
    systemctl restart apache2 || true
    sleep 1
    printf '\033[32m已回滚：后端=SQLite，站点应已恢复。\033[0m\n'
}
trap 'rollback' ERR

# ---------------------------------------------------------------- 0 体检
log "0/7 体检（--dry-run=${DRY}）"
[ "$(id -u)" -eq 0 ] || die "必须以 root 运行"
command -v mysql  >/dev/null || die "缺 mysql 客户端"
command -v sqlite3 >/dev/null || die "缺 sqlite3"
[ -f "$DB" ] || die "找不到线上 SQLite: $DB"
for f in db.py wsgi_entry.py; do
    [ -f "$APP/$f" ] || die "应用目录缺 $f"
done
# mysqldialect.py / mysqldb.py 是要新装的文件，允许尚不存在
for f in mysqldialect.py mysqldb.py db.py wsgi_entry.py; do
    [ -f "$HERE/$f" ] || die "payload 缺 ${f}（请用 deploy-switch.sh 上传）"
done
systemctl is-active --quiet mysql || die "MySQL 没在跑"
systemctl is-active --quiet apache2 || die "apache2 没在跑"
mysql -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" -N -e 'SELECT 1' "$MYSQL_DB" >/dev/null 2>&1 \
    || die "MySQL 账号 $MYSQL_USER 连不上库 $MYSQL_DB"
"$VENV/bin/python" -c 'import pymysql' 2>/dev/null \
    || die "venv 里没有 pymysql（先 pip install pymysql）"
sub "MySQL $(mysql -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" -N -e 'SELECT VERSION()' 2>/dev/null) / 库 $MYSQL_DB 可达"
sub "线上 SQLite $(stat -c '%s 字节  mtime=%y' "$DB" | cut -c1-40)"
if [ -f "$ENVFILE" ]; then
    warn "$ENVFILE 已存在（当前可能已在 MySQL 上）："
    sed 's/^/      /' "$ENVFILE"
fi
ok "体检通过"

# ---------------------------------------------------------------- 1 备份
log "1/7 备份（SQLite 快照 + 应用目录 + Apache 配置）"
sub "备份目录：$BK"
if [ "$DRY" -eq 0 ]; then
    mkdir -p "$BK" "$TOOLS"
    chown www-data:www-data "$BK"
    # 以 www-data 身份做 .backup，避免 root 打开 WAL 库后 -shm/-wal 属主被改坏
    sudo -u www-data sqlite3 "$DB" ".backup '$BK/netlab.db'"
    chown root:root "$BK/netlab.db"
    sqlite3 "$BK/netlab.db" 'PRAGMA integrity_check;' | grep -q '^ok$' || die "SQLite 备份完整性校验失败"
    ok "SQLite 快照 OK（$(stat -c %s "$BK/netlab.db") 字节，integrity ok）"

    # 逐个复制确实存在的关键源文件（比 tar 整目录更省事、且不受缺文件影响）
    mkdir -p "$BK/pre-switch-code"
    for f in db.py wsgi_entry.py core.py mysqldialect.py mysqldb.py; do
        if [ -f "$APP/$f" ]; then cp -a "$APP/$f" "$BK/pre-switch-code/$f"; fi
    done
    ok "应用源码快照 OK（$BK/pre-switch-code/）"

    cp -a /etc/apache2/sites-available/websystem.conf "$BK/websystem.conf"
    cp -a /etc/apache2/conf-available/netlab-wsgi.conf  "$BK/netlab-wsgi.conf"
    ok "Apache 配置快照 OK"
else
    sub "(dry-run) 跳过实际备份"
fi

# ---------------------------------------------------------------- 2 部署代码
log "2/7 部署 MySQL 兼容层代码"
if [ "$DRY" -eq 0 ]; then
    for f in mysqldialect.py mysqldb.py; do
        install -o www-data -g www-data -m 644 "$HERE/$f" "$APP/$f"
        ok "安装 $f"
    done
    install -o www-data -g www-data -m 644 "$HERE/wsgi_entry.py" "$APP/wsgi_entry.py"
    ok "更新 wsgi_entry.py（启动时读 db-backend.env）"
    install -o www-data -g www-data -m 644 "$HERE/db.py" "$APP/db.py"
    ok "更新 db.py（后端开关）"
    install -o root -g root -m 755 "$HERE/migrate_sqlite_to_mysql.py" "$TOOLS/migrate_sqlite_to_mysql.py"
    ok "安装 migrate_sqlite_to_mysql.py"
    # 语法检查
    "$VENV/bin/python" -m py_compile "$APP/mysqldialect.py" "$APP/mysqldb.py" "$APP/db.py" "$APP/wsgi_entry.py" \
        || die "py_compile 失败"
    ok "py_compile 通过"
    # 冒烟导入（不连库）
    APP_DIR="$APP" "$VENV/bin/python" - <<'PY' || die "兼容层导入失败"
import os, sys
sys.path.insert(0, os.environ.get("APP_DIR", "/opt/websystem/app"))
import mysqldialect, mysqldb
print("    dialect/shim 可导入；translate('SELECT ?','a') =>",
      mysqldialect.to_paramstyle("SELECT ?", "a"))
PY
else
    sub "(dry-run) 将安装：mysqldialect.py / mysqldb.py / wsgi_entry.py / db.py → $APP"
fi

# ---------------------------------------------------------------- 3 重同步数据
log "3/7 把线上 SQLite 最新数据全量重灌进 MySQL（应用此刻仍在 SQLite 上跑）"
tmpdb="/tmp/switch-$TS.db"
if [ "$DRY" -eq 0 ]; then
    sudo -u www-data sqlite3 "$DB" ".backup '$tmpdb'"
    chmod 644 "$tmpdb"
    sub "导出线上快照 $(stat -c %s "$tmpdb") 字节 → $tmpdb"

    # 预期行数**必须**取自这份迁移快照本身 —— 若取自更早的备份，
    # 两次之间的新写入会让行数对不上，冒烟测试会误判并回滚。
    python3 - "$tmpdb" "$BK/expected-counts.json" <<'PY'
import json, sqlite3, sys
c = sqlite3.connect(sys.argv[1])
tabs = [r[0] for r in c.execute(
    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
out = {t: c.execute('SELECT COUNT(*) FROM "%s"' % t).fetchone()[0] for t in tabs}
json.dump(out, open(sys.argv[2], "w"), ensure_ascii=False, indent=1)
print("    导出 %d 张表的预期行数 → %s" % (len(out), sys.argv[2]))
PY

    NETLAB_APP_DIR="$APP" "$VENV/bin/python" "$TOOLS/migrate_sqlite_to_mysql.py" \
        --sqlite "$tmpdb" --host "$MYSQL_HOST" --port "$MYSQL_PORT" \
        --user "$MYSQL_USER" --password "$MYSQL_PASSWORD" --database "$MYSQL_DB" \
        --create-database --drop-existing 2>&1 | sed 's/^/    /'
    rc=${PIPESTATUS[0]}
    [ "$rc" -eq 0 ] || die "迁移返回码 ${rc}（有表不一致）"
    rm -f "$tmpdb"
    ok "数据重灌完成且逐表哈希一致"
else
    sub "(dry-run) 将重灌 netlab（--drop-existing）"
fi

# ---------------------------------------------------------------- 4 写开关
log "4/7 写后端开关 $ENVFILE"
if [ "$DRY" -eq 0 ]; then
    cat > "$ENVFILE" <<EOF
# 站点数据库后端开关 —— 由 tools/mysql/switch/switch-to-mysql.sh 于 $TS 写入
# 删掉本文件（或改 NETLAB_DB_BACKEND=sqlite）并重启 apache2 即回滚到 SQLite
NETLAB_DB_BACKEND=mysql
NETLAB_MYSQL_HOST=$MYSQL_HOST
NETLAB_MYSQL_PORT=$MYSQL_PORT
NETLAB_MYSQL_USER=$MYSQL_USER
NETLAB_MYSQL_PASSWORD=$MYSQL_PASSWORD
NETLAB_MYSQL_DATABASE=$MYSQL_DB
EOF
    # ⚠️ 必须让 www-data 能读！WSGI daemon 就是 www-data 跑的，
    #    写成 root:root 600 会让 wsgi_entry.py 直接 PermissionError → 整站 500。
    chown root:www-data "$ENVFILE"
    chmod 640 "$ENVFILE"
    ok "已写入（root:www-data 640，含口令，仅 www-data 可读）"
    sed 's/^/      /' "$ENVFILE"

    # 以真实的运行身份实测一遍可读性（不靠猜）
    if sudo -u www-data test -r "$ENVFILE"; then
        ok "www-data 可读 ✔"
    else
        die "www-data 读不了 $ENVFILE —— 重启后必然整站 500"
    fi
else
    sub "(dry-run) 将写入 NETLAB_DB_BACKEND=mysql 等 6 行"
fi

# ---------------------------------------------------------------- 5 重启
log "5/7 重启 apache2 使开关生效"
if [ "$DRY" -eq 0 ]; then
    systemctl reload apache2 2>/dev/null || systemctl restart apache2
    # mod_wsgi daemon 需要真正重启才换环境变量，reload 不一定够
    systemctl restart apache2
    sleep 2
    systemctl is-active --quiet apache2 || die "apache2 重启后没起来"
    ok "apache2 已重启"
else
    sub "(dry-run) 将 systemctl restart apache2"
fi

# ---------------------------------------------------------------- 6 冒烟
log "6/7 冒烟测试"
if [ "$DRY" -eq 0 ]; then
    if bash "$HERE/smoke-test.sh" --expect mysql --ref "$BK/expected-counts.json"; then
        ok "冒烟全通过"
    else
        warn "冒烟测试有失败项"
        rollback
        exit 1
    fi
else
    sub "(dry-run) 将执行 smoke-test.sh --expect mysql"
fi

trap - ERR

# ---------------------------------------------------------------- 7 收尾
log "7/7 收尾"
sub "备份留存：$BK"
sub "回滚命令：bash $HERE/rollback-to-sqlite.sh"
printf '\n\033[1;32m🎉 切换完成：站点数据库已是 MySQL\033[0m\n'
printf '   SQLite 快照未动，随时可一键回退。\n'
