#!/bin/bash
# ══════════════════════════════════════════════════════════════
#  拉取线上生产库到本地（供 Navicat 查看）
#
#  为什么不能直接 scp 那个 .db 文件：
#    线上库是 SQLite **WAL 模式**（PRAGMA journal_mode = wal）。
#    最近的写入可能还在 netlab.db-wal 里，只拷贝 netlab.db
#    会拿到一份「缺最新数据」甚至结构不一致的库。
#
#  正确做法：在服务器上用 sqlite3 的 .backup 指令生成一致性快照
#    —— 它会正确处理 WAL、自动 checkpoint、并保证事务一致，
#       即使此刻网站正在写入也安全。
#
#  用法：
#    ./tools/db-pull.sh              # 拉到默认镜像路径
#    ./tools/db-pull.sh /tmp/x.db    # 拉到指定路径
# ══════════════════════════════════════════════════════════════
set -e

HERE="$(cd "$(dirname "$0")/.." && pwd)"
HOST="${LC_HOST:-YOUR_SERVER_IP}"
KEY="${LC_KEY:-$HOME/.ssh/teaching_system_deploy}"
REMOTE_DB="/opt/websystem/data/netlab.db"
TMP_REMOTE="/tmp/netlab-mirror-$$.db"
DEST="${1:-$HERE/server/data/netlab-server-mirror.db}"

SSH="ssh -i $KEY -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=15 root@$HOST"

echo "==> 1/4 在服务器上生成一致性快照（WAL 安全）"
$SSH "sqlite3 '$REMOTE_DB' \".backup '$TMP_REMOTE'\"" 
echo "    完成"

echo "==> 2/4 下载到本地"
mkdir -p "$(dirname "$DEST")"
# 关键：先清掉旧的 -wal / -shm 旁文件。
# 库是 WAL 模式，SQLite 打开时会生成 netlab.db-wal / -shm。
# 若覆盖 .db 时留下旧的 -wal，SQLite 会把「上一份库的 WAL」套用到新库上 → 可能损坏。
rm -f "$DEST-wal" "$DEST-shm"
scp -q -i "$KEY" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
    "root@$HOST:$TMP_REMOTE" "$DEST"
$SSH "rm -f '$TMP_REMOTE'"

echo "==> 3/4 校验本地副本"
if command -v sqlite3 >/dev/null 2>&1; then
  INTEGRITY=$(sqlite3 "$DEST" "PRAGMA integrity_check;")
  TABLES=$(sqlite3 "$DEST" "SELECT count(*) FROM sqlite_master WHERE type='table';")
  USERS=$(sqlite3 "$DEST" "SELECT count(*) FROM users;" 2>/dev/null || echo "?")
  COURSES=$(sqlite3 "$DEST" "SELECT count(*) FROM courses;" 2>/dev/null || echo "?")
  echo "    integrity_check : $INTEGRITY"
  echo "    表数量          : $TABLES"
  echo "    用户 / 课程     : $USERS / $COURSES"
  [ "$INTEGRITY" = "ok" ] || { echo "❌ 完整性校验未通过"; exit 1; }
else
  echo "    （本机没装 sqlite3 命令行，跳过校验；系统自带的可直接用于 Navicat）"
fi

# 关键：同步刷新「基线」。
# db_push.py 靠「基线 vs 你改过的镜像」来算行级差异。
# 每拉一次就把基线对齐到当前线上状态 —— 这样你后面在 Navicat 里的改动，
# 才能被准确识别为「你改的」，而不是和线上混淆。
BASELINE="$HERE/server/data/netlab-server-baseline.db"
if [ "$DEST" = "$HERE/server/data/netlab-server-mirror.db" ]; then
  rm -f "$BASELINE-wal" "$BASELINE-shm"
  cp "$DEST" "$BASELINE"
  echo "==> 3.5/4 基线已同步：$BASELINE"
fi

echo "==> 4/4 完成"
echo "    本地路径：$DEST"
echo "    体积    ：$(du -h "$DEST" | cut -f1)"
echo "    时间    ：$(date '+%Y-%m-%d %H:%M:%S')"
echo
echo "在 Navicat 里点开这个连接后按 ⌘R 刷新即可看到最新数据。"
