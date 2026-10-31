#!/bin/bash
# ══════════════════════════════════════════════════════════════
#  安全地改【线上 MySQL】的数据（走 SSH 隧道，改完立即生效）
#
#  为什么不用 Navicat 手点：
#    Navicat 表格里点一下 ✓ 就直接改了线上，**没有备份、没有撤销、不问一句**。
#    这个脚本每次写入前**自动整库备份**，并显示改了哪张表、多少行。
#
#  用法：
#    ./tools/db-mysql-sql.sh "SELECT ..."                    # 只读查询（唯一不用 --write 的）
#    ./tools/db-mysql-sql.sh --write "UPDATE users SET ..."  # 写入：自动备份 + 二次确认
#    ./tools/db-mysql-sql.sh --write -y "DELETE FROM ..."    # 跳过确认
#    ./tools/db-mysql-sql.sh --write --file change.sql       # 从文件执行多条
#    ./tools/db-mysql-sql.sh --self-test                     # 事务写入+回滚，零生产影响
#    ./tools/db-mysql-sql.sh --backup                        # 只备份
#    ./tools/db-mysql-sql.sh --restore <备份文件>            # 从备份还原
#    ./tools/db-mysql-sql.sh --list-backups                  # 列出备份
#
#  安全设计：
#    · 默认只读 —— 非 SELECT 必须显式 --write
#    · 写入前自动整库 dump（139KB，秒级）
#    · UPDATE/DELETE 没有 WHERE 时必须再加 --force
#    · 断言连的是线上 netlab（防连错库）
# ══════════════════════════════════════════════════════════════
set -Eeuo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
LK="$REPO/tools/db-mysql-live.sh"

DB_HOST=127.0.0.1
DB_PORT=13306                 # 隧道端口（服务器 MySQL 只绑 127.0.0.1，必须走隧道）
DB_USER=admin
DB_PASS='CHANGE_ME_PASSWORD'
DB_NAME=netlab
EXPECT_HOST_SUFFIX='your-server-hostname'   # 线上服务器 hostname，防连错库

BK_DIR="$REPO/backups/mysql"

MYSQL=(mysql -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" -p"$DB_PASS" --default-character-set=utf8mb4)
Q() { "${MYSQL[@]}" -N -B "$DB_NAME" -e "$1" 2>/dev/null; }

c()  { printf '\033[1;36m%s\033[0m\n' "$*"; }
ok() { printf '\033[32m✔ %s\033[0m\n' "$*"; }
no() { printf '\033[31m✘ %s\033[0m\n' "$*"; }
warn(){ printf '\033[33m! %s\033[0m\n' "$*"; }
die(){ printf '\033[31m✘ %s\033[0m\n' "$*" >&2; exit 1; }

need_tunnel() {
    if ! lsof -nP -iTCP:"$DB_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
        warn "隧道没开，尝试启动…"
        "$LK" >/dev/null 2>&1 || die "隧道起不来，请手动跑：$LK"
    fi
}

assert_target() {
    need_tunnel
    local h; h=$(Q "SELECT @@hostname") || die "连不上 MySQL（隧道断了？）"
    [ "$h" = "$EXPECT_HOST_SUFFIX" ] || die "连到的不是线上机（hostname=${h}），已中止"
    [ "$(Q 'SELECT DATABASE()')" = "$DB_NAME" ] || die "库名不对，已中止"
}

do_backup() {
    mkdir -p "$BK_DIR"
    local f="$BK_DIR/netlab-$(date +%Y%m%d-%H%M%S).sql"
    mysqldump -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" -p"$DB_PASS" \
        --single-transaction --no-tablespaces --skip-comments --default-character-set=utf8mb4 \
        "$DB_NAME" > "$f" 2>/dev/null || die "备份失败"
    [ -s "$f" ] || die "备份文件为空"
    ok "已备份 → ${f}（$(wc -c <"$f" | tr -d ' ') 字节）"
    echo "$f"
}

# 取出语句里第一张被改的表名（用于显示行数变化）
# ⚠️ grep 无匹配会返回 1，而 set -e 下 `tbl=$(...)` 会带着整个脚本一起退出 —— 必须 || true
affected_table() {
    grep -oiE '\b(UPDATE|INSERT[[:space:]]+INTO|DELETE[[:space:]]+FROM|REPLACE[[:space:]]+INTO|TRUNCATE[[:space:]]+TABLE)\s+`?[A-Za-z_][A-Za-z0-9_]*' <<<"$1" \
      | head -1 | sed -E 's/.*[[:space:]]+`?([A-Za-z_][A-Za-z0-9_]*)$/\1/' || true
}

run_sql() {   # $1=SQL  $2=write?  $3=skip-confirm?  $4=force?
    local sql="$1" write="$2" yes="$3" force="$4"
    local head_lc; head_lc=$(printf '%s' "$sql" | grep -viE '^\s*(--|#)' | head -c 400 | tr 'A-Z' 'a-z')

    if [ "$write" != "1" ]; then
        printf '%s' "$head_lc" | grep -qE '^\s*(select|show|desc|describe|explain|with)\b' \
            || die "只读模式：这条不是查询语句。要改数据请加 --write"
    else
        # 无 WHERE 的 UPDATE/DELETE 需要 --force
        if printf '%s' "$head_lc" | grep -qE '^\s*(update|delete)\b' \
           && ! printf '%s' "$head_lc" | grep -qE '\bwhere\b'; then
            [ "$force" = "1" ] || die "UPDATE/DELETE 没有 WHERE —— 会改/删整表！确认要这么做请再加 --force"
        fi
    fi

    local tbl; tbl=$(affected_table "$sql" || true)
    local before=""
    if [ "$write" = "1" ] && [ -n "$tbl" ]; then
        before=$(Q "SELECT COUNT(*) FROM \`$tbl\`" || true)
    fi

    echo; c "──────── SQL ────────"; printf '%s\n' "$sql"; c "─────────────────────"; echo

    if [ "$write" = "1" ]; then
        do_backup >/dev/null
        if [ "$yes" != "1" ]; then
            printf '确认在【线上生产库】执行以上语句？输入 yes 继续：'
            local ans=""; read -r ans < /dev/tty || ans=""
            [ "$ans" = "yes" ] || die "已取消（未执行任何修改）"
        fi
    fi

    # 写入放在单个事务里（DDL 会自动提交，MySQL 语义），并显示改了行数
    local out
    if [ "$write" = "1" ]; then
        out=$("${MYSQL[@]}" "$DB_NAME" -v -e "START TRANSACTION; $sql; COMMIT;" 2>&1) \
            || { printf '%s\n' "$out"; die "执行失败（事务已回滚，数据未变）"; }
        # Rows matched / Changed
        printf '%s\n' "$out" | grep -E 'rows? (affected|matched)|Query OK' | sed 's/^/  /' || true
        ok "执行完成"
        if [ -n "$tbl" ] && [ -n "$before" ]; then
            local after; after=$(Q "SELECT COUNT(*) FROM \`$tbl\`" || true)
            echo "  $tbl 行数：$before → ${after:-?}"
        fi
    else
        "${MYSQL[@]}" --table "$DB_NAME" -e "$sql" || die "查询失败"
    fi
}

# ─────────────────────────── 参数解析
MODE=query; WRITE=0; YES=0; FORCE=0; SQL=""; FILE=""
while [ $# -gt 0 ]; do
    case "$1" in
        --write)  WRITE=1; shift ;;
        -y|--yes) YES=1; shift ;;
        --force)  FORCE=1; shift ;;
        --file)   FILE="$2"; shift 2 ;;
        --backup) MODE=backup; shift ;;
        --list-backups) MODE=list; shift ;;
        --restore) MODE=restore; FILE="$2"; shift 2 ;;
        --self-test) MODE=selftest; shift ;;
        -h|--help) sed -n '2,26p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) SQL="${SQL:+$SQL }$1"; shift ;;
    esac
done
[ -n "$FILE" ] && SQL="$(cat "$FILE")"

assert_target

case "$MODE" in
    list)
        ls -lht "$BK_DIR"/netlab-*.sql 2>/dev/null || echo "（还没有备份）"; exit 0 ;;
    backup)
        p=$(do_backup | tail -1); exit 0 ;;
    restore)
        [ -f "$FILE" ] || die "找不到备份文件：$FILE"
        warn "将用 $FILE **覆盖**线上 netlab 现有数据！"
        printf '输入 yes 确认：'; read -r a < /dev/tty || a=""
        [ "$a" = "yes" ] || die "已取消"
        do_backup >/dev/null
        "${MYSQL[@]}" "$DB_NAME" < "$FILE" || die "还原失败"
        ok "已从备份还原"; exit 0 ;;
    selftest)
        c "自测：在事务里真写一次，然后回滚（生产数据零影响）"
        "${MYSQL[@]}" "$DB_NAME" -e "
            START TRANSACTION;
            CREATE TEMPORARY TABLE _wb_selftest (x INT);
            INSERT INTO _wb_selftest VALUES (1),(2),(3);
            SELECT CONCAT('事务内可见行数 = ', COUNT(*)) AS selftest FROM _wb_selftest;
            ROLLBACK;" --table || die "自测失败"
        ok "写入通道正常，且已回滚"; exit 0 ;;
esac

[ -n "$SQL" ] || die "没给 SQL。用法见 --help"
run_sql "$SQL" "$WRITE" "$YES" "$FORCE"
