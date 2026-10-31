#!/bin/bash
# 建账号后逐项验证（在服务器上以 root 执行）
PW='CHANGE_ME_PASSWORD'
q() { mysql "$@" 2>&1 | grep -v "Using a password"; }

echo "=== 账号清单 ==="
q -u root -p"$PW" -e "SELECT user, host, plugin FROM mysql.user WHERE user IN ('root','admin') ORDER BY user, host;"

echo "=== ① admin 走 socket（localhost）==="
q -u admin -p"$PW" -N -e "SELECT CONCAT('  OK  current_user=', CURRENT_USER(), '  ver=', VERSION());"

echo "=== ② admin 走 TCP（127.0.0.1:3306）==="
q -u admin -p"$PW" -h 127.0.0.1 -P 3306 -N -e "SELECT CONCAT('  OK  current_user=', CURRENT_USER());"

echo "=== ③ root 带密码 ==="
q -u root -p"$PW" -N -e "SELECT CONCAT('  OK  current_user=', CURRENT_USER());"

echo "=== ④ admin 权限核对 ==="
q -u root -p"$PW" -e "SHOW GRANTS FOR 'admin'@'127.0.0.1';"

echo "=== ⑤ 空密码应被拒 ==="
if mysql -u root -e "SELECT 1" >/dev/null 2>&1; then
  echo "  ‼️  免密仍可用 —— 密码没真正生效"
else
  echo "  OK  免密已被拒（密码确实生效）"
fi

echo "=== ⑥ 错误密码应被拒 ==="
if mysql -u admin -pwrongpass -e "SELECT 1" >/dev/null 2>&1; then
  echo "  ‼️  错误密码竟然通过了"
else
  echo "  OK  错误密码被拒"
fi

echo "=== ⑦ TEXT/LONGTEXT 能否用表达式默认值（MySQL 8 迁移关键点）==="
q -u root -p"$PW" netlab <<'SQL'
CREATE TABLE IF NOT EXISTS _t (
  k   VARCHAR(255) PRIMARY KEY,
  v   TEXT     NOT NULL DEFAULT (''),
  big LONGTEXT          DEFAULT ('')
);
INSERT INTO _t (k) VALUES ('x');
SELECT k, CONCAT('[',v,']') AS v_val, CONCAT('[',IFNULL(big,'<NULL>'),']') AS big_val FROM _t;
SELECT COUNT(*) AS 行数 FROM _t;
DROP TABLE _t;
SQL

echo "=== ⑧ netlab 库现状 ==="
q -u root -p"$PW" -N -e "SELECT CONCAT('  表数=', COUNT(*)) FROM information_schema.tables WHERE table_schema='netlab';"
