#!/usr/bin/env bash
# ============================================================================
#  set-password.sh —— 一条命令改线上用户的登录密码
#
#  站点口令**默认明文存储**（管理员要求：能直接在 Navicat 里看/改）。
#  所以改密码 = 把明文写进 users.password_hash。
#  老账号如果是历史遗留的 PBKDF2 哈希，登录时照样认；改成明文后就是明文了。
#
#  用法：
#     ./tools/set-password.sh --list                    列出所有用户
#     ./tools/set-password.sh demo_user                      给 demo_user 随机一个新密码
#     ./tools/set-password.sh demo_user 'MyNewPass123'       给 demo_user 指定新密码
#     ./tools/set-password.sh --dry-run demo_user 'abc123'   只演一遍，不写库
#     ./tools/set-password.sh --hash demo_user 'abc123'      仍写 PBKDF2 哈希（老口径）
#     ./tools/set-password.sh --local --db netlab_practice stu_lisi 'abc123'
#                                                       改本机沙盒（随便练，不动线上）
#
#  安全设计：
#     · 先查人、给你看是谁，确认了才写
#     · 改之前把**旧值**存成回滚 SQL（backups/passwords/），随时能改回去
#     · 写完后**回读数据库里的值、用新密码验一遍**，确认登录真的能过
#     · 写入走 stdin，明文密码不出现在 ps / 命令行历史里
#
#  批量把老的哈希账号统一改成明文：./tools/password-plain.py convert-all <密码> -y
# ============================================================================

set -uo pipefail

LIVE_HOST="db.example.com"; LIVE_PORT="13306"
LOCAL_HOST="127.0.0.1";        LOCAL_PORT="3306"
DB_USER="admin"
DB_PASS='CHANGE_ME_PASSWORD'
DB_NAME="netlab"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PWHASH="${ROOT}/tools/pw-hash.py"
BACKUP_DIR="${ROOT}/backups/passwords"

OK="✅"; BAD="❌"; WARN="⚠️ "
say()  { printf '%s\n' "$*"; }
pass() { printf '  %s %s\n' "${OK}" "$*"; }
fail() { printf '  %s %s\n' "${BAD}" "$*"; }
warn() { printf '  %s%s\n' "${WARN}" "$*"; }

usage() {
  sed -n '2,26p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
  exit "${1:-0}"
}

# ---------------------------------------------------------------- 参数
MODE="live"; DRY=0; YES=0; LIST=0; STORE="plain"
TARGET=""; NEWPASS=""

while [ $# -gt 0 ]; do
  case "$1" in
    --list)     LIST=1; shift ;;
    --local)    MODE="local"; shift ;;
    --live)     MODE="live"; shift ;;
    --db)       DB_NAME="$2"; shift 2 ;;
    --dry-run)  DRY=1; shift ;;
    --hash)     STORE="hash"; shift ;;
    --plain)    STORE="plain"; shift ;;
    -y|--yes)   YES=1; shift ;;
    -h|--help)  usage 0 ;;
    --)         shift; break ;;
    -*)         fail "未知参数：$1"; usage 1 ;;
    *)          if [ -z "${TARGET}" ]; then TARGET="$1"; elif [ -z "${NEWPASS}" ]; then NEWPASS="$1"; else fail "参数太多了"; usage 1; fi; shift ;;
  esac
done

if [ "${MODE}" = "live" ]; then HOST="${LIVE_HOST}"; PORT="${LIVE_PORT}"; LABEL="线上生产库"; else HOST="${LOCAL_HOST}"; PORT="${LOCAL_PORT}"; LABEL="本机沙盒"; fi

# ---------------------------------------------------------------- 依赖检查
MYSQL_BIN=""
for c in /opt/homebrew/bin/mysql /usr/local/mysql/bin/mysql "$(command -v mysql 2>/dev/null || true)"; do
  if [ -n "${c}" ] && [ -x "${c}" ]; then MYSQL_BIN="${c}"; break; fi
done
[ -z "${MYSQL_BIN}" ] && { fail "找不到 mysql 客户端（brew install mysql-client 或装 MySQL）"; exit 1; }

PYTHON_BIN="$(command -v python3 2>/dev/null || true)"
[ -z "${PYTHON_BIN}" ] && { fail "找不到 python3"; exit 1; }
[ -f "${PWHASH}" ]    || { fail "找不到 ${PWHASH}"; exit 1; }

# ---------------------------------------------------------------- 连库（凭证走临时文件，不进 ps）
CNF="$(mktemp /tmp/netlab-pw-XXXXXX.cnf)"
chmod 600 "${CNF}"
trap 'rm -f "${CNF}"' EXIT
printf '[client]\nhost=%s\nport=%s\nuser=%s\npassword="%s"\nconnect-timeout=10\ndefault-character-set=utf8mb4\n' \
  "${HOST}" "${PORT}" "${DB_USER}" "${DB_PASS}" > "${CNF}"

# ⚠️ -r（--raw）不能省：-B 批处理模式会把制表符**转义成字面量 \t**，那样按列切分全废
sql() { "${MYSQL_BIN}" --defaults-extra-file="${CNF}" -N -B -r "${DB_NAME}" -e "$1" 2>/dev/null; }

# 连通性 + 确认连的是哪台
WHO="$(sql 'SELECT CONCAT(@@hostname, " | ", VERSION());')"
if [ -z "${WHO}" ]; then
  fail "连不上 ${HOST}:${PORT}"
  if [ "${MODE}" = "live" ]; then
    say "     → 跑 ./tools/db-cloud-check.sh 看是哪一环断了"
  else
    say "     → 本机 MySQL 没起？brew services start mysql"
  fi
  exit 1
fi
printf '\n\033[1m目标库\033[0m  %s  (%s:%s)\n' "${LABEL}" "${HOST}" "${PORT}"
say "            ${WHO}"
if [ "${MODE}" = "live" ] && ! printf '%s' "${WHO}" | grep -q 'your-server-hostname'; then
  warn "主机名不是线上那台（your-server-hostname），确认一下你要改的是这台？"
fi

# ---------------------------------------------------------------- --list
if [ "${LIST}" -eq 1 ]; then
  say ""
  printf '\033[1m所有用户\033[0m\n\n'
  {
    printf 'ID\t用户名\t昵称\t管理员\t状态\t最后登录\n'
    # 空字段一律填 '-'：column -t 会把连续制表符当成一个分隔符，导致整行列错位
    sql "SELECT CONCAT_WS(CHAR(9), id, username,
                          IFNULL(NULLIF(nickname,''),'-'),
                          IF(is_admin=1,'是','-'),
                          IF(is_active=1,'启用','已停用'),
                          IFNULL(NULLIF(last_login_at,''),'从未'))
         FROM users ORDER BY id;"
  } | column -t -s "$(printf '\t')"
  say ""
  say "改密码：./tools/set-password.sh <上面某个用户名> '新密码'"
  say "不给新密码就自动生成一个随机的。"
  exit 0
fi

[ -z "${TARGET}" ] && { fail "没给用户名"; say ""; usage 1; }

# 用户名里不能有引号/反斜杠（会破坏 SQL 字面量）
case "${TARGET}" in
  *\'*|*\"*|*\\*|*\ *) fail "用户名里有引号/反斜杠/空格，脚本处理不了，请用 Navicat 手动改"; exit 1 ;;
esac

# ---------------------------------------------------------------- 定位用户
# 登录接受 用户名 / 手机号 / 学号 任一，所以这三个都查
FOUND="$(sql "SELECT CONCAT_WS(CHAR(9), id, username,
                                   IFNULL(NULLIF(nickname,''),'-'),
                                   IF(is_admin=1,'是','-'),
                                   IF(is_active=1,'启用','已停用'),
                                   IFNULL(NULLIF(phone,''),'-'),
                                   IFNULL(NULLIF(student_no,''),'-'),
                                   password_hash,
                                   IFNULL(NULLIF(last_login_at,''),'从未'))
              FROM users
              WHERE username = '${TARGET}' OR phone = '${TARGET}' OR student_no = '${TARGET}';")"

if [ -z "${FOUND}" ]; then
  fail "找不到这个用户：${TARGET}（用户名、手机号、学号都试过了）"
  say "     → 用 ./tools/set-password.sh --list 看看到底有哪些人"
  exit 1
fi
NROWS="$(printf '%s\n' "${FOUND}" | grep -c .)"
if [ "${NROWS}" -gt 1 ]; then
  fail "匹配到 ${NROWS} 个人，不能确定改谁："
  printf '%s\n' "${FOUND}" | awk -F'\t' '{printf "       id=%s  %s\n", $1, $2}'
  say "     → 请用「用户名」精确指定"
  exit 1
fi

U_ID="$(printf '%s' "${FOUND}" | cut -f1)"
U_NAME="$(printf '%s' "${FOUND}" | cut -f2)"
U_NICK="$(printf '%s' "${FOUND}" | cut -f3)"
U_ADMIN="$(printf '%s' "${FOUND}" | cut -f4)"
U_ACTIVE="$(printf '%s' "${FOUND}" | cut -f5)"
U_PHONE="$(printf '%s' "${FOUND}" | cut -f6)"
U_STUNO="$(printf '%s' "${FOUND}" | cut -f7)"
U_OLDVAL="$(printf '%s' "${FOUND}" | cut -f8)"
U_LASTLOGIN="$(printf '%s' "${FOUND}" | cut -f9)"

printf '\n\033[1m要改的人\033[0m\n'
printf '  id=%-4s 用户名=%s  昵称=%s\n' "${U_ID}" "${U_NAME}" "${U_NICK}"
printf '  管理员=%s  状态=%s  手机=%s  学号=%s  最后登录=%s\n' \
  "${U_ADMIN}" "${U_ACTIVE}" "${U_PHONE}" "${U_STUNO}" "${U_LASTLOGIN}"

# ---------------------------------------------------------------- 生成新密码 + 落库值
GENERATED=0
if [ -z "${NEWPASS}" ]; then
  NEWPASS="$("${PYTHON_BIN}" -c 'import secrets; print(secrets.token_urlsafe(9))')"
  GENERATED=1
fi
if [ "${#NEWPASS}" -lt 6 ]; then
  fail "新密码至少要 6 位（站点登录就是这个下限）"
  exit 1
fi

if ! NEWVALUE="$("${PYTHON_BIN}" "${PWHASH}" --mode "${STORE}" "${NEWPASS}")"; then
  fail "生成落库值失败（mode=${STORE}）"
  exit 1
fi
# 自校验：拿生成的值反验一次明文
if ! "${PYTHON_BIN}" "${PWHASH}" --verify "${NEWPASS}" "${NEWVALUE}" >/dev/null 2>&1; then
  fail "自校验没通过，中止（这不该发生）"
  exit 1
fi
if [ "${STORE}" = "plain" ]; then
  pass "新密码将以**明文**写入（可直接在 Navicat 里看/改）"
else
  pass "新密码的 PBKDF2 哈希已生成并自校验通过（--hash 老口径）"
fi

# SQL 字面量转义：明文密码可能出现单引号和反斜杠
SQL_ESCAPED="$(printf '%s' "${NEWVALUE}" | sed "s/\\\\/\\\\\\\\/g; s/'/\\\\'/g")"

# ---------------------------------------------------------------- 备份旧值（回滚用）
mkdir -p "${BACKUP_DIR}"
STAMP="$(date +%Y%m%d-%H%M%S)"
SAFE_NAME="$(printf '%s' "${U_NAME}" | tr -c 'A-Za-z0-9._-' '_')"
ROLLBACK="${BACKUP_DIR}/${STAMP}-${SAFE_NAME}.sql"

if [ "${DRY}" -eq 0 ]; then
  {
    printf -- '-- 回滚 %s 的密码（改于 %s）\n' "${U_NAME}" "${STAMP}"
    printf -- '-- 用法：mysql --defaults-extra-file=<凭证文件> %s < 本文件\n' "${DB_NAME}"
    printf "UPDATE users SET password_hash = '%s' WHERE id = %s;\n" "${U_OLDVAL}" "${U_ID}"
  } > "${ROLLBACK}"
  chmod 600 "${ROLLBACK}"
  pass "旧口令已备份 → backups/passwords/${STAMP}-${SAFE_NAME}.sql（要改回去就跑它）"
fi

# ---------------------------------------------------------------- 确认
say ''
if [ "${DRY}" -eq 1 ]; then
  warn "--dry-run：不写库，只演到这里"
  say "  将要执行： UPDATE users SET password_hash = '<${STORE} 值>' WHERE id = ${U_ID};"
  exit 0
fi
if [ "${YES}" -eq 0 ]; then
  printf '确认把 %s（id=%s）的密码改掉？[y/N] ' "${U_NAME}" "${U_ID}"
  read -r ANS
  case "${ANS}" in y|Y|yes|YES) ;; *) say "已取消，什么都没改。"; exit 0 ;; esac
fi

# ---------------------------------------------------------------- 写库
printf "UPDATE users SET password_hash = '%s' WHERE id = %s;\n" "${SQL_ESCAPED}" "${U_ID}" \
  | "${MYSQL_BIN}" --defaults-extra-file="${CNF}" "${DB_NAME}" 2>/dev/null
RC=$?
if [ "${RC}" -ne 0 ]; then
  fail "写入失败（退出码 ${RC}）"
  say "     → 旧口令还在 backups/passwords/ 里，没丢东西"
  exit 1
fi

# ---------------------------------------------------------------- 回读校验（关键）
STORED="$(sql "SELECT password_hash FROM users WHERE id = ${U_ID};")"
if [ "${STORED}" != "${NEWVALUE}" ]; then
  fail "回读的值和写入的不一致！"
  say "     期望：${NEWVALUE}"
  say "     实际：${STORED}"
  say "     → 用 backups/passwords/ 里的回滚 SQL 恢复，然后告诉我"
  exit 1
fi
if ! "${PYTHON_BIN}" "${PWHASH}" --verify "${NEWPASS}" "${STORED}" >/dev/null 2>&1; then
  fail "回读的值用新密码验不过，登录会失败！"
  say "     → 立刻回滚：mysql ... < backups/passwords/${STAMP}-${SAFE_NAME}.sql"
  exit 1
fi

say ''
pass "已写入并回读校验通过 —— 这个密码现在就能登录了"
say ''
printf '\033[1m  %s 的新密码：\033[0m \033[1;33m%s\033[0m\n' "${U_NAME}" "${NEWPASS}"
if [ "${GENERATED}" -eq 1 ]; then
  say '  （这是自动生成的随机密码，只在屏幕上出现这一次，脚本没有存明文）'
else
  say '  （你指定的密码；明文没写进任何文件）'
fi
say ''
say "  登录入口：https://your-server.example.com/login  （用户名 / 手机号 / 学号 任一都能登）"
say "  要改回原密码：mysql --defaults-extra-file=<凭证> ${DB_NAME} < backups/passwords/${STAMP}-${SAFE_NAME}.sql"
say ''
