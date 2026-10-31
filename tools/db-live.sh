#!/bin/bash
# ══════════════════════════════════════════════════════════════
#  ⛔ 本脚本已停用 —— 线上库早已不是 SQLite，这个入口会带你去改一个废弃的库
#
#  发生了什么：
#    这个脚本原本是「SSH 隧道 + 服务器上的 sqlite-web（127.0.0.1:8081）」，
#    让你用浏览器直接改线上 SQLite。但 2026-10-16 站点已经切到 **MySQL**，
#    服务器上那份 /opt/websystem/data/netlab.db 变成了**历史快照**，
#    sqlite-web 服务也已经在安全加固时停掉并改名为
#    /opt/sqliteweb.disabled-20261016。
#
#    继续用这条路最危险的地方是：你会以为自己改的是线上数据，
#    其实改的是一个早就没人读的 SQLite 文件 —— 改完毫无效果，还容易误判。
#
#  现在该用哪条路（都对着真正的线上 MySQL）：
#
#    ① Navicat 直连（你想怎么改就怎么改，首选）
#         Navicat 新建连接：主机 db.example.com  端口 13306
#         用户 admin   密码 CHANGE_ME_PASSWORD   库 netlab
#       注意端口是 **13306**，不是 3306。
#       连不上先跑：./tools/db-cloud-check.sh
#       （服务器侧 13306 已加来源 IP 白名单，换网络后要放行新 IP，
#         见服务器上的 mysql-allow.sh）
#
#    ② SSH 隧道（13306 白名单没加上你时的备用路）
#         ./tools/db-mysql-live.sh        然后 Navicat 连 127.0.0.1:13306
#
#    ③ 只在服务器本机改（最稳，不用开放任何端口）
#         ssh root@YOUR_SERVER_IP
#         mysql -uadmin -p netlab        # 密码 CHANGE_ME_PASSWORD
#
#  改密码：./tools/password-plain.py --list / set / convert-all
#  文档：  数据库连接.md（第十三、十四、十五节）
# ══════════════════════════════════════════════════════════════

cat <<'EOF'

⛔  tools/db-live.sh 已停用。

原因：线上库已经是 MySQL，sqlite-web 指向的 netlab.db 是废弃快照，
      继续用会把「改错库」当成「改线上」。

请改用（任选其一）：

  ① Navicat 直连  db.example.com : 13306
       用户 admin / 密码 CHANGE_ME_PASSWORD / 库 netlab
       （端口是 13306，不是 3306；连不上先跑 ./tools/db-cloud-check.sh）

  ② ./tools/db-mysql-live.sh           # SSH 隧道，Navicat 连 127.0.0.1:13306

  ③ ssh root@YOUR_SERVER_IP
     mysql -uadmin -p netlab           # 直接改，最稳

改密码：./tools/password-plain.py set <用户名> <新密码>
详细说明：数据库连接.md 第十三～十五节

EOF

exit 1
