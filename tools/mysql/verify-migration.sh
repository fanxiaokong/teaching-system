#!/bin/bash
# 迁移后核对 MySQL 侧的结构
PW='CHANGE_ME_PASSWORD'
q() { mysql "$@" 2>&1 | grep -v "Using a password"; }

echo "=== 表 / 索引 / 视图 数量 ==="
q -u root -p"$PW" -N -e "
SELECT CONCAT('  表  ', COUNT(*)) FROM information_schema.tables
  WHERE table_schema='netlab' AND table_type='BASE TABLE';
SELECT CONCAT('  索引 ', COUNT(DISTINCT table_name, index_name)) FROM information_schema.statistics
  WHERE table_schema='netlab';"

echo "=== 引擎 / 字符集 / 排序规则（应全为 InnoDB + utf8mb4_0900_ai_ci）==="
q -u root -p"$PW" -N -e "
SELECT CONCAT('  ', engine, ' / ', table_collation, '  ×', COUNT(*)) FROM information_schema.tables
  WHERE table_schema='netlab' GROUP BY engine, table_collation;"

echo "=== 被放宽/改写的列（重点核对）==="
q -u root -p"$PW" -e "
SELECT table_name AS 表, column_name AS 列, column_type AS 类型, is_nullable AS 可空,
       column_default AS 默认值
  FROM information_schema.columns
 WHERE table_schema='netlab'
   AND ((column_name IN ('size','file_size') )
        OR (table_name='settings'      AND column_name='k')
        OR (table_name='scan_logins'   AND column_name='token')
        OR (table_name='users'         AND column_name='username')
        OR (table_name='registrations' AND column_name='contact'))
 ORDER BY table_name, column_name;"

echo "=== 索引清单（18 个，看有没有缺）==="
q -u root -p"$PW" -N -e "
SELECT CONCAT('  ', table_name, '  ', index_name, '  (', GROUP_CONCAT(column_name ORDER BY seq_in_index), ')')
  FROM information_schema.statistics WHERE table_schema='netlab'
 GROUP BY table_name, index_name ORDER BY table_name, index_name;" | grep -v PRIMARY

echo "=== 中文有没有乱码（取几条中文最多的数据）==="
q -u root -p"$PW" netlab -e "
SELECT id, title FROM courses LIMIT 3;
SELECT k, LEFT(v,30) AS v FROM settings WHERE k IN ('site_title','site_subtitle','group_note');
SELECT username FROM users LIMIT 3;"

echo "=== 大整数是否保住了（教学视频字节数）==="
q -u root -p"$PW" netlab -e "
SELECT id, LEFT(title,26) AS 标题, size, FORMAT(size/1024/1024, 0) AS MB FROM videos ORDER BY size DESC LIMIT 3;"
