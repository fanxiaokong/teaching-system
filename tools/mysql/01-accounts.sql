-- ══════════════════════════════════════════════════════════════
--  在服务器 MySQL 上建与「本机 MySQL」完全一致的账号 + netlab 库
--  用法：mysql < 01-accounts.sql        （以 root 身份，走 auth_socket）
--  幂等：重复执行无副作用
-- ══════════════════════════════════════════════════════════════

-- ── 1. 库（utf8mb4，全站中文数据）──────────────────────────────
CREATE DATABASE IF NOT EXISTS netlab
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_0900_ai_ci;

-- ── 2. 账号：admin，本机/socket 两种 host 都建一份 ────────────
-- 为什么两个 host 都要：Navicat 走 TCP 会匹配 '127.0.0.1'，
-- 命令行 mysql -u admin 走 socket 会匹配 'localhost'。
-- 只建一个的话另一种方式会 Access denied。
CREATE USER IF NOT EXISTS 'admin'@'localhost'
  IDENTIFIED WITH caching_sha2_password BY 'CHANGE_ME_PASSWORD';
CREATE USER IF NOT EXISTS 'admin'@'127.0.0.1'
  IDENTIFIED WITH caching_sha2_password BY 'CHANGE_ME_PASSWORD';

-- 已存在则改密码（保证重复执行时口径一致）
ALTER USER 'admin'@'localhost'
  IDENTIFIED WITH caching_sha2_password BY 'CHANGE_ME_PASSWORD';
ALTER USER 'admin'@'127.0.0.1'
  IDENTIFIED WITH caching_sha2_password BY 'CHANGE_ME_PASSWORD';

-- 与本机一致：超级管理员
GRANT ALL PRIVILEGES ON *.* TO 'admin'@'localhost' WITH GRANT OPTION;
GRANT ALL PRIVILEGES ON *.* TO 'admin'@'127.0.0.1' WITH GRANT OPTION;

-- ── 3. root 也设成同样的密码（与本机口径一致）──────────────────
-- ⚠️ 这会把 root@localhost 从 auth_socket 改成密码认证。
--    改完 `mysql`（免密）就不再可用，要用 `mysql -u root -p`。
--    因为 admin 已经建好且是全权限，即使这里出问题也不会锁死。
ALTER USER 'root'@'localhost'
  IDENTIFIED WITH caching_sha2_password BY 'CHANGE_ME_PASSWORD';

FLUSH PRIVILEGES;

-- ── 4. 回显结果 ────────────────────────────────────────────────
SELECT '账号清单' AS section;
SELECT user, host, plugin FROM mysql.user
 WHERE user IN ('root','admin') ORDER BY user, host;
SELECT '权限核对' AS section;
SHOW GRANTS FOR 'admin'@'localhost';
