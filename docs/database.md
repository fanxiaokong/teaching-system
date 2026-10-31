# 数据库连接 · 改线上数据

**只想直接改线上数据 → 跳到第五节，一条命令：`./tools/db-live.sh`。**

---

## 一、先看结论

线上数据有**两条入口**，都改的是同一份真库：

| 入口 | 工具 | 体验 | 适合 |
|---|---|---|---|
| **⭐ 实时网页编辑器** | 浏览器 | 打开就能改，**改完立即生效**，不用 push | 日常改数据（首推） |
| 镜像 + 行级推送 | Navicat | Navicat 界面，改完要跑一次推送 | 批量改 / 想用 Navicat |

本机另外两个 SQLite 文件（Navicat 也能连）：

| 连接名（建议） | Navicat 类型 | 数据库文件 | 说明 |
|---|---|---|---|
| **本地开发库** | SQLite | `~/teaching-system/server/data/netlab.db` | 本地跑的那个站点用的库，随便改 |
| **线上生产库(镜像)** | SQLite | `~/teaching-system/server/data/netlab-server-mirror.db` | 线上库的镜像。**改完要推上线才生效**，见第六节 |

都是 **SQLite**，29 张表，结构一致。

> **Navicat 改镜像 ≠ 改线上。** 想实时生效用第五节；要保留 Navicat 操作习惯用第六节。

> 另外本机还有一个 **MySQL 9.6.0**（见文末第九节）：`127.0.0.1:3306`，用户 `admin`。
> 它和这些 SQLite 库**没有任何关系**，里面只有系统库，是另一套东西。

---

## 二、为什么 SQLite 不能「像 MySQL 那样填个 IP 连上」

SQLite **没有客户端/服务器结构** —— 没有网络协议、没有端口，它就是一个文件。Navicat 打开 SQLite 的本质是「打开一个本地文件」。

- **Navicat 的 SSH 隧道对 SQLite 无效**：那个标签页只给 MySQL/PostgreSQL 这类有网络协议的库用。
- **SSHFS / macFUSE 挂载远程目录**：能让 Navicat 像连本地文件一样打开，但**不推荐**。网络文件系统上 SQLite 的 `fcntl` 锁不可靠，而网站本身**一直在写**（每次登录写 `last_login_at`、每次练习写 `practice_logs`），
  两个 writer 撞上就可能**写坏生产库**。加上要装内核扩展、重启、手动批准，风险收益完全不划算。

所以「直接连」这件事，**不能用把文件搬到网络上的思路做**，得在服务器本机开一个能写这个文件的进程，再把它的界面转出来给你。第五节就是这么做的。

> 顺带一个坑：线上库是 **WAL 模式**（`journal_mode = wal`）。
> **直接 `scp` 那个 `netlab.db` 会丢数据** —— 最新写入可能还在 `netlab.db-wal` 里。
> 镜像拉取脚本用的是服务器端 `sqlite3 .backup`，会正确处理 WAL，网站正在写入时拉也安全。

---

## 三、在 Navicat 里连这两个本地 SQLite 文件（可选）

### 本地开发库

1. 打开 **Navicat Premium Lite**
2. 菜单栏 **文件 → 新建连接 → SQLite…**
   （或点工具栏左上角的 **「连接」** 按钮，在下拉里选 **SQLite**）
3. 填写：
   - **连接名**：`本地开发库`
   - **数据库文件**：点右侧的 **…** 按钮，选到
     `~/teaching-system/server/data/netlab.db`
4. 点 **测试连接** → 应该提示成功
5. 点 **确定**，左侧列表里双击这个连接 → 展开就能看到 29 张表

### 线上生产库（镜像）

重复上面步骤，只是换成：

- **连接名**：`线上生产库(镜像)`
- **数据库文件**：`~/teaching-system/server/data/netlab-server-mirror.db`

---

## 四、刷新镜像（想用 Navicat 看线上最新快照时）

镜像不是实时同步的，想看线上最新数据，跑一次拉取：

**方式 A** —— VS Code 里 `Cmd+Shift+P` → `Tasks: Run Task` → **③ 拉取线上数据（改前先跑这个）**

**方式 B** —— 终端：

```bash
cd ~/teaching-system
./tools/db-pull.sh
```

跑完在 Navicat 里右键连接 → **刷新**（或 `Cmd+R`）即可。脚本会顺手打印完整性校验和行数，比如：

```
    integrity_check : ok
    表数量          : 29
    用户 / 课程     : 23 / 25
```

---

## 五、⭐ 直接连线上库改数据（实时生效）

### 怎么用

```bash
cd ~/teaching-system
./tools/db-live.sh
```

就这一条。它会自动建好通道并打开浏览器：

```
  地址   ：http://127.0.0.1:8081/
  口令   ：CHANGE_ME_PASSWORD
```

进去就是**正在对外服务的那份数据库**（`/opt/websystem/data/netlab.db`）：
左侧列出 29 张表 → 点进去看数据 → **双击单元格改**、`+` 加行、垃圾桶删行，
还有 **「执行 SQL」** 标签页可以直接跑 `UPDATE ... WHERE ...`。

**改完即生效** —— 网站下次请求就读到新数据，**不用 push、不用重启 Apache**。

关掉通道：`./tools/db-live.sh --stop`

### 为什么这样是安全的

| 设计 | 原因 |
|---|---|
| 服务只绑 **`127.0.0.1:8081`** | 外网**根本访问不到**这个端口，必须先进服务器或者走 SSH 转发 |
| 走 **SSH 端口转发**，不额外开放端口 | 通道复用你已有的部署密钥，用完 `--stop` 一关就没了 |
| 以 **`www-data`** 身份运行 | ⚠️ 这条最关键。SQLite 是 WAL 模式，写的时候会在库旁边生成 `netlab.db-wal` / `-shm`。**如果以 root 运行，这两个文件会变成 root 所有，Apache（www-data）之后就写不进去了 → 网站所有写操作报错。** |
| 同一台机器上直接写文件 | 用的是 SQLite 原生锁，和 Apache 那边是**正确的并发关系**（不是网络文件系统那种假锁） |
| 额外一层网页口令 | 纵深防御。即使有人蹭到隧道也进不去 |
| `systemd` 托管，`Restart=on-failure` | 挂了自动拉起；`systemctl status sqliteweb` 看状态 |

> 服务端构成：`/opt/sqliteweb/venv`（独立 venv，**不动站点自己的 `/opt/websystem/venv`**）+ `systemd` 单元 `sqliteweb.service`。

### ⚠️ 三个必须知道的坑

1. **这里改的是裸数据，绕过了网站的业务逻辑。**
   最典型的是密码：`users.password_hash` 要填**哈希**不是明文，得用 `python3 tools/pw-hash.py` 先生成（见第七节）。
   改后台管理密码也一样（存在 `settings.admin_password`）。

2. **外键约束是关着的。**
   网站自己连接时开了 `PRAGMA foreign_keys = ON`，而 sqlite-web 默认**不开**。
   所以在这个网页里删一条被引用的父行（比如删课程）时，**不会被拦住，也不会级联**，容易留下孤儿数据。
   建议删数据还是在网站后台删，或者先跑一遍 `PRAGMA foreign_key_check;`。

3. **它是开发用 Web 服务器**（Flask 自带），日志里会有 "development server" 的警告。
   只监听回环、单用户用，完全够；**但它不是给公网用的**，别把 `-H` 改成 `0.0.0.0`。

### 部署细节（万一要重装 / 换服务器）

| 项 | 值 |
|---|---|
| 代码位置 | `/opt/sqliteweb/venv/bin/sqlite_web`（版本 0.8.2） |
| 服务定义 | `/etc/systemd/system/sqliteweb.service`（本地副本：`tools/sqliteweb.service`） |
| 端口 | 服务器 `127.0.0.1:8081` |
| 口令 | 环境变量 `SQLITE_WEB_PASSWORD`（在 unit 文件里） |
| 常用命令 | `systemctl status / restart sqliteweb`、`journalctl -u sqliteweb -n 50` |

---

## 六、用 Navicat 改线下 + 行级推送到线上

**先记住一句话**：在 Navicat 里连的「线上生产库(镜像)」只是**一份本地文件**。你在里面怎么改，**线上网站都不会变**。
必须用下面的方式「推」上去。

适合：**批量改**（改一堆课程名、一批用户昵称）、或者你就是想用 Navicat 的界面/导入导出。

```bash
cd ~/teaching-system

# ① 拉最新镜像（同时自动刷新"基线"）
./tools/db-pull.sh

# ② 在 Navicat 里打开「线上生产库(镜像)」，改数据，⌘S 保存

# ③ 干跑：看差异 + 冲突检测，不动线上
python3 tools/db_push.py

# ④ 确认无误，真正执行
python3 tools/db_push.py --apply
```

`db_push.py` 的安全设计：

| 机制 | 说明 |
|---|---|
| **只推行级差异** | 逐行比对「基线 vs 你改后的镜像」，只生成真正变化的那几行 `UPDATE/INSERT/DELETE`。**不会整库覆盖**，所以不会冲掉你编辑期间线上产生的新数据 |
| **默认干跑** | 不加 `--apply` 就只打印差异和 SQL，绝不碰服务器 |
| **冲突检测** | 动手前重新拉一份**当前线上库**，逐行核对「你要改的那几行，线上是否也被人改过了」。有冲突就整体中止 |
| **自动备份** | 真正执行时先在服务器留一份 `netlab.db.bak-push-<时间戳>` |
| **单事务** | 所有语句包在一个事务里，出错整体回滚；完事自动跑 `integrity_check` |

> 「基线」是 `server/data/netlab-server-baseline.db`，`db-pull.sh` 每次都会自动同步它。
> **别手动改基线**，否则差异就算不准了。

### 另外两条路

**直接敲一句 SQL**（适合改一个字段，无需开界面）：

```bash
# 只读查询 —— 直接跑
./tools/db-sql.sh "SELECT id, username, nickname FROM users LIMIT 10;"

# 写操作 —— 必须显式加 --write，脚本会先自动备份
./tools/db-sql.sh --write "UPDATE users SET nickname='孔' WHERE id=1;"
```

护栏：**默认只读**（不是 `SELECT/PRAGMA/EXPLAIN/WITH/VALUES` 开头的一律拒绝）；写操作要显式 `--write` 且执行前自动备份；SQL 走 base64 传输，避免多层 shell 的引号问题。

**走网站后台**（`https://your-server.example.com/admin`）：自带权限校验和业务逻辑，日常改内容优先用它。

---

## 七、关于「密码怎么都是加密的」

`users.password_hash` 那一长串**不是随便加密的密文，是单向哈希**，**不存在"解密出来"这回事**（谁都不能）。

站点的算法（在 `server/app/db.py` 里，**不是 bcrypt**）：

```
存储格式 = pbkdf2_sha256$<salt>$<digest>
salt   = secrets.token_hex(16)                        → 32 位十六进制
digest = pbkdf2_hmac("sha256", 密码, salt, 120000).hex() → 64 位十六进制
```

所以"改密码"的正确做法是：**生成一个新的哈希写进去**，而不是解出原文。已经做好工具了：

```bash
cd ~/teaching-system

# 只想拿一个哈希
python3 tools/pw-hash.py '你想要的明文密码'

# 直接生成可执行的 UPDATE 语句（用户名 demo_user）
python3 tools/pw-hash.py --sql demo_user 'CHANGE_ME_PASSWORD'
# → UPDATE users SET password_hash = 'pbkdf2_sha256$...$...' WHERE username = 'demo_user';

# 校验某个哈希对应哪个明文
python3 tools/pw-hash.py --verify '明文' 'pbkdf2_sha256$...$...'
```

生成的哈希**已和服务器上站点自己的 `db.verify_password()` 交叉校验通过**（正确口令 → `True`，错误口令 → `False`），可以直接用。

**改线上某个账号的密码，两步：**

```bash
# ① 生成 UPDATE 语句
python3 tools/pw-hash.py --sql demo_user 'CHANGE_ME_PASSWORD'

# ② 把它交给 --write 执行（复制上一步的输出即可）
./tools/db-sql.sh --write "UPDATE users SET password_hash = 'pbkdf2_sha256$...$...' WHERE username = 'demo_user';"
```

> ⚠️ 或者最简单的路：**用网站后台的「重置密码」功能**，它内部就是干这件事，还省得手抖写错 SQL。
> `pw-hash.py` 真正的价值场景是：后台进不去了、要批量重置一堆账号、或者要给新建账号直接塞密码。

**顺带说清 users 表里那几列**（NAVICAT 里看着有用）：

| 列 | 含义 |
|---|---|
| `password_hash` | 上面说的单向哈希，改不了明文 |
| `is_admin` | 1 = 管理员，0 = 普通用户 |
| `is_active` | 1 = 可登录，0 = 已禁用 |
| `quota_mb` | 该用户网盘配额（MB），默认 200 |
| `student_no` | 学号，可为空 |

站点现有关键账号：`admin`(id 1)、`demo_user`(id 3)、`demo_admin2`(id 8)、`demo_admin3`(id 24) 是管理员。

---

## 八、备忘

- 生产库真实位置：`YOUR_SERVER_IP:/opt/websystem/data/netlab.db`（405KB，29 表）
- 服务器上还堆着 **20 多个历史 `.bak-*` 文件**（含 `-wal`/`-shm` 旁文件），是历次改库留下的。不影响运行，但容易看花眼 —— 哪天想清理说一声，我会先列清单再动手。
- 本地这份 `netlab.db` 和镜像的 `users/courses/videos` 都是 `23/25/73`，内容一致。

### 工具清单（`tools/` 目录）

| 脚本 | 作用 |
|---|---|
| **`db-live.sh`** | ⭐ 打开**线上库的实时网页编辑器**（SSH 隧道 + 浏览器），改完立即生效 |
| `sqliteweb.service` | 上面那个编辑器的 systemd 定义（服务器端 `/etc/systemd/system/` 的副本） |
| `db-pull.sh` | 线上库 → 本地镜像（WAL 安全），**并自动同步基线** |
| `db_push.py` | 把镜像的改动**按行**推算到线上（默认干跑 + 冲突检测） |
| `db-sql.sh` | 直接在线上库跑 SQL（默认只读，`--write` 才写） |
| `pw-hash.py` | 生成/校验站点格式的密码哈希 |
| `publish_app.py` | 发版：APK/安装包 + 写 `app_versions` 表 |

三个本地库文件，别搞混：

| 文件 | 是什么 |
|---|---|
| `server/data/netlab.db` | **本地开发库**（本地站点跑的） |
| `server/data/netlab-server-mirror.db` | **线上镜像**（你在这里改，再 push 上去） |
| `server/data/netlab-server-baseline.db` | **基线**（pull 时自动同步，别手动动它） |

### 🔐 顺带发现：`settings` 表里有敏感信息

用编辑器翻表时看到这几行是**明文/可直接用的凭据**，别随手截图外发：

| key | 内容 |
|---|---|
| `ai_text_key` / `ai_vision_key` | DeepSeek API Key（`sk-...`，明文） |
| `admin_password` | 网站后台管理密码的 PBKDF2 哈希 |
| `police_number` / `icp_number` | 备案号 |

---

## 九、本机 MySQL（2026-10-16 已重置账号）

跟上面两个 SQLite 库**无关**，是本机另外装的一套 MySQL。

### 现状

| 项目 | 值 |
|---|---|
| 版本 | MySQL **9.6.0**（Homebrew 安装，`/opt/homebrew`） |
| 地址 | `127.0.0.1` : `3306`（`my.cnf` 里 `bind-address=127.0.0.1`，只允许本机） |
| 账号 | **`admin`** ／ 密码 **`CHANGE_ME_PASSWORD`** |
| 权限 | `ALL PRIVILEGES ON *.* WITH GRANT OPTION`（等同于超级管理员） |
| `root` | 密码同样设为 `CHANGE_ME_PASSWORD`（原来**是空密码**，已补上） |
| 开机自启 | ✅ 已注册 launchd（`~/Library/LaunchAgents/sh.brew.mysql.plist`） |
| 已有数据库 | 只有 `mysql` / `performance_schema` / `sys` 三个**系统库**，没有任何自建库 |

### Navicat 建连接

**文件 → 新建连接 → MySQL…**，填：

| 字段 | 值 |
|---|---|
| 连接名 | `本机 MySQL` |
| 主机 | `127.0.0.1` |
| 端口 | `3306` |
| 用户名 | `admin` |
| 密码 | `CHANGE_ME_PASSWORD` |

### 命令行连接

```bash
mysql -u admin -p -h 127.0.0.1
# 回车后输入密码：CHANGE_ME_PASSWORD
```

### 常用管理命令

```bash
brew services start  mysql     # 启动（并设为开机自启）
brew services stop   mysql     # 停止
brew services restart mysql    # 重启
brew services list             # 看状态
```

### ⚠️ 一个必须记住的坑

**MySQL 的配置文件里 `#` 是注释起始符**，密码含 `#` 时**必须加引号**，否则会被悄悄截断：

```ini
password="CHANGE_ME_PASSWORD"     # ✅ 正确
password=CHANGE_ME_PASSWORD       # ❌ 实际生效的是 "CHANGE_ME"（被 # 截断）
```

（这次就是踩了这个坑：写了个 `~/.my.cnf` 风格的临时配置，连接一直报 `Access denied ... using password: YES`，
排查后才发现密码被 `#` 截断了。命令行直接 `-p` 交互输入则不受影响。）

### 安全提醒

- MySQL 目前**只监听 127.0.0.1**，外网连不上，这点是安全的。
- 密码是明文写在这份文档里的（你要求的）。如果以后把这个文档放进 git 或发给别人，记得先把密码那段删掉。

---

## 十、线上站点数据库已换成 MySQL（2026-10-16 12:21 切换完成）

目标：线上 `your-server.example.com` 的数据库**从 SQLite 换成 MySQL 8**，
账号与口令和本机保持一致 —— **`admin` / `CHANGE_ME_PASSWORD`**。

### 为什么不是重写代码

站点的 390 条 SQL 全是 SQLite 写法（`?` 占位符、`AUTOINCREMENT`、`INSERT OR IGNORE`…）。
逐条改成 MySQL 方言风险极高。改用的办法是**加一层运行时翻译**：

| 模块 | 作用 |
|---|---|
| `server/app/mysqldialect.py` | 唯一的翻译规则源：`?`→`%s`、`AUTOINCREMENT`→`AUTO_INCREMENT`、`TEXT` 索引列→`VARCHAR(255)`、`INTEGER`→`INT/BIGINT`、`ON CONFLICT … DO UPDATE`→`ON DUPLICATE KEY UPDATE`、`PRAGMA table_info`→`information_schema` … |
| `server/app/mysqldb.py` | 运行时连接/游标壳：用 PyMySQL + DictCursor 模拟 `sqlite3.Row`，并把 MySQL `SUM()` 返回的 `DECIMAL` 转回 `int`（否则 JSON 里会变成字符串 `"0"`） |
| `server/app/db.py` | 只多了一段开关：读环境变量 `NETLAB_DB_BACKEND`，`mysql` 走上面两层，其余走原来的 SQLite |

**上层业务代码一行没改。**

### 切换机制（配置文件驱动，不依赖 Apache SetEnv）

`server/app/wsgi_entry.py` 启动时会尝试读 `/opt/websystem/db-backend.env`，把里面的 `KEY=VALUE` 注入环境：

- **文件存在** → 用 MySQL
- **文件不存在** → 用 SQLite（默认）

所以：**切换 = 写这个文件 + 重启 apache2；回滚 = 挪走这个文件 + 重启 apache2。**

### 服务器现状（已核实）

| 项目 | 值 |
|---|---|
| 主机 | `YOUR_SERVER_IP`（阿里云 ECS，Ubuntu 22.04.5，1.6G 内存） |
| MySQL | **8.0.46**，`systemctl status mysql` = active/enabled |
| 监听 | `127.0.0.1:3306`（外网连不上）；`mysqld` 常驻约 **179 MB** |
| 调优 | `innodb_buffer_pool_size=128M`、`performance_schema=OFF`、`max_connections=50`（`/etc/mysql/mysql.conf.d/zz-netlab.cnf`） |
| 账号 | `admin@localhost`、`admin@127.0.0.1`、`root@localhost`，均 `caching_sha2_password` |
| 口令 | 全部 **`CHANGE_ME_PASSWORD`**（与本机一致） |
| 库 | `netlab`（已建好并迁移过一轮：28 表 / 562 行，utf8mb4_0900_ai_ci / InnoDB） |
| 站点 | Apache 2.4 + mod_wsgi **daemon 模式**（`WSGIDaemonProcess netlab`，2 进程 × 10 线程） |
| 应用 | `/opt/websystem/app`，Python venv `/opt/websystem/venv`（3.10.12，已装 **PyMySQL 1.2.3**） |

> 注：服务器 `netlab` 库是从**早先快照**迁的；正式切换时会先把线上 SQLite 的**最新**数据全量重灌一次。

### ✅ 切换记录（2026-10-16 12:21:36）

一次成功，冒烟 **15/15 全通过**。落地的证据链：

| 证据 | 结果 |
|---|---|
| 运行时铁证：打 5 次页面 | MySQL **连接数 +7**、**SELECT 数 +17** |
| 应用自己的 db 层 | `backend=mysql`，SELECT 正常，**临时表写入 + 回滚**正常 |
| 28 张表行数对账 vs 切换时快照 | **不一致 0 张**（562 行全齐） |
| **真实写库实证**：走站点公开表单 `/join` 提交一条 | HTTP 200 → 该行**在 MySQL（命中 1）/ 不在 SQLite（命中 0）**；SQLite 文件 mtime **停在 12:12:37 未动**（应用此后一个字节都没往 SQLite 写）；随后已从 MySQL 删除该自检行 |
| 站点路由 | `/api/ping` 200、`/api/v1/home` 200、`/courses` 302、`/admin` 302、`/api/v1/app/version` 200 |
| Apache 错误日志 | 切换成功后无新错误 |

> ⚠️ 第一次尝试（12:18）**失败并自动回滚**：我把开关文件写成 `root:root 600`，而 WSGI daemon 以 **www-data** 跑，
> 读不到 → `wsgi_entry.py` 导入即 `PermissionError` → 整站 500。回滚把站点完整恢复（全部路由正常）。
> 已改为 `root:www-data 640`，并在脚本里加了一道「**以 www-data 身份实测可读**」的验证。
> 这一次失败反而**实证了回滚链路真的能用**。


### 🔌 用 Navicat 连线上 MySQL（**必须走 SSH 隧道**）

**先说结论：在 Navicat 里填 `your-server.example.com : 3306` 是连不上的，而且不该去改这个。**

| 为什么连不上 | 说明 |
|---|---|
| MySQL 只监听 `127.0.0.1` | `bind-address = 127.0.0.1`（`/etc/mysql/mysql.conf.d/` 下两处），外网根本到不了 3306 |
| 账号没有 `admin@%` | 只有 `admin@localhost`、`admin@127.0.0.1`、`root@localhost` |
| 外网 3306 不通 | 实测 `nc -z your-server.example.com 3306` 失败 |

这是**刻意留的安全边界**：数据库绝不能对公网开 3306。正确做法是走 SSH 隧道。

#### 方式一：Navicat 自带 SSH 标签（一次配好，之后免维护）⭐ 推荐

**「常规」标签**：

| 字段 | 值 |
|---|---|
| 连接名 | `Web.System（线上 MySQL）` |
| 主机 | **`127.0.0.1`** ← 一定是这个，不能填域名 |
| 端口 | `3306` |
| 用户名 | `admin` |
| 密码 | `CHANGE_ME_PASSWORD` |
| 数据库 | `netlab` |

**「SSH」标签**（勾选「使用 SSH 通道」）：

| 字段 | 值 |
|---|---|
| 主机 | `your-server.example.com` |
| 端口 | `22` |
| 用户名 | `root` |
| 验证方法 | **密码**（实测可用；`sshd` 里 `PasswordAuthentication yes`） |
| 密码 | `CHANGE_ME_PASSWORD` |

> 原理：Navicat 先 SSH 登进服务器，再**从服务器本机**去连 `127.0.0.1:3306` ——
> 所以「常规」里必须写 `127.0.0.1`，写域名反而连不上。
> 若想用公钥：私钥文件 `~/.ssh/teaching_system_deploy`，但 Navicat 对 ed25519 支持不稳，**优先用密码**。

#### 方式二：用工程里的隧道脚本 + 普通连接（不想在 Navicat 配 SSH 时用）

```bash
cd ~/teaching-system
./tools/db-mysql-live.sh        # 开隧道 + 打印连接信息 + 自测
./tools/db-mysql-live.sh --test # 只自测
./tools/db-mysql-live.sh --stop # 关隧道
```

然后 Navicat 建一条**普通 MySQL 连接**（不勾 SSH）：

| 字段 | 值 |
|---|---|
| 主机 | `127.0.0.1` |
| 端口 | **`13306`** ← 隧道端口，不是 3306 |
| 用户名 / 密码 | `admin` / `CHANGE_ME_PASSWORD` |

⚠️ 隧道只在本机 ssh 进程活着时有效，关机/断网就断；重跑脚本即可（已在开会自动复用）。

### ✏️ 怎么改线上的数据（四条路，按推荐度排）

| 场景 | 用什么 | 说明 |
|---|---|---|
| 改**内容**：用户、课程、课件、导航、作业、激活码、版本、反馈处理 | **网站后台** `https://your-server.example.com/admin` | 最安全。走的是应用自己的校验逻辑，不会碰坏索引和哈希 |
| 零散改几格 | **Navicat 表格视图** | 双击单元格改 → 底部生成 SQL → 点 ✓ **立即在线上生效**。注意下面那四条红线 |
| 批量 / 带条件改（如"把所有 2023 级的手机号补 1"）| **Navicat 查询窗口**，或下面的命令行工具 | 先 `SELECT` 看清楚影响范围，再 `UPDATE` |
| 改密码 | `python3 tools/pw-hash.py --sql <用户名> '新明文'` | **绝不能手打明文到 `password_hash`** |

#### 命令行工具：`tools/db-mysql-sql.sh`（比 Navicat 手点更安全）

每次写入**自动整库备份**（139 KB，秒级），并打印改了哪张表、行数变化。

```bash
cd ~/teaching-system

# 只读查询（默认模式，非查询语句会被拒绝）
./tools/db-mysql-sql.sh "SELECT id, username, phone FROM users LIMIT 5"

# 改数据：加 --write；会先备份、再让你输 yes 确认
./tools/db-mysql-sql.sh --write "UPDATE users SET phone='13900000002' WHERE username='demo_user'"

# 不想交互确认就加 -y
./tools/db-mysql-sql.sh --write -y "DELETE FROM activation_codes WHERE code='XXXX'"

# 多条语句写成文件一次执行
./tools/db-mysql-sql.sh --write --file change.sql

# 备份 / 还原 / 看备份
./tools/db-mysql-sql.sh --backup
./tools/db-mysql-sql.sh --list-backups
./tools/db-mysql-sql.sh --restore backups/mysql/netlab-20261016-124512.sql

# 自检：事务里真写一次再回滚，对生产零影响
./tools/db-mysql-sql.sh --self-test
```

内置三道防线：
1. **默认只读** —— 不是 `SELECT/SHOW/DESC/EXPLAIN` 就必须显式加 `--write`
2. **无 `WHERE` 的 `UPDATE/DELETE` 会被拦住** —— 要整表改得再加 `--force`
3. **断言连的是线上 netlab**（比对服务器 hostname）—— 防连错库

备份在 `backups/mysql/`。**已实测可还原**：把备份灌进临时库后逐表比对，
28 张表的行数与 `CHECKSUM` 全部一致。

#### ⚠️ 用 Navicat 手点改数据时，四条红线

Navicat 里双击单元格改动 → 底部会出现一条**待执行 SQL** → 点 ✓ 就是**直接在线上执行**，
**立刻生效、没有撤销**。执行前请先看两眼：

| 列 | 约束 / 语义 | 手改的后果 |
|---|---|---|
| `username` | **UNIQUE** | 登录凭据之一；改错人就登不进来了 |
| `phone` | **UNIQUE** | **登录凭据之一**（登录接受 username / phone / student_no 任一）|
| `student_no` | **⚠️ 不唯一、无索引**，但**是登录凭据之一** | **最阴的一条**：登录 SQL 是 `WHERE username=? OR phone=? OR student_no=?` 且只取第一条 `fetchone()`。学号没有唯一约束，把 A 的学号改成和 B 一样 → A 用这个学号可能登进 B 的账号（取决于哪条先被查到）。**填学号前必须先 `SELECT` 查占用** |
| `password_hash` | 单向哈希 | **绝不能手打明文**，否则该用户永远登不进去 |

- **UNIQUE 冲突**：改 `username` / `phone` 撞到别人的值会报
  `Duplicate entry 'xxx' for key 'users.phone'`（错误码 1062），整条 UPDATE 失败。
  （实际踩过：`admin` 的号是 `13900000000`，而 `13900000000` 已经属于「小空压 id=17」。）
- **改密码请用工具**，不要手写哈希：
  ```bash
  cd ~/teaching-system
  python3 tools/pw-hash.py --sql <用户名> '新明文密码'   # 生成 UPDATE 语句，再执行
  ```
- 手滑改错了怎么办：用 `./tools/db-mysql-sql.sh --list-backups` 挑一份改之前的备份还原；
  更早的兜底是 SQLite 里**切换前那份**完整数据（`/opt/websystem/data/netlab.db`，自切换起一个字节没被写）。

### 切换怎么做

工具都在 `tools/mysql/switch/`，**在 Mac 上一条命令驱动**（免密 SSH 走 `~/.ssh/teaching_system_deploy`）：

```bash
cd tools/mysql/switch
./deploy-switch.sh check      # ① 上传 + 只体检（dry-run，不动任何东西）
./deploy-switch.sh switch     # ② 真正切换（备份→部署→重灌→开关→重启→冒烟）
./deploy-switch.sh smoke      # ③ 事后抽查
./deploy-switch.sh rollback   # ④ 一键回滚到 SQLite
```

**切换脚本内部 7 步**（`switch-to-mysql.sh`）：

| 步 | 动作 | 安全性 |
|---|---|---|
| 0 | 体检：root / mysql / sqlite3 / 账号可达 / venv 有 pymysql | 只读 |
| 1 | 备份：SQLite `.backup` 快照（校验 integrity）+ 关键源码 + Apache 配置 + 各表行数 JSON | 只读 |
| 2 | 部署 `mysqldialect.py` / `mysqldb.py` / `db.py` / `wsgi_entry.py`，`py_compile` + 导入自检 | 应用此刻仍用 SQLite |
| 3 | 以 `www-data` 身份 `.backup` 线上库 → 全量重灌 `netlab`（`--drop-existing`），逐表哈希校验 | 应用仍用 SQLite，无影响 |
| 4 | 写 `/opt/websystem/db-backend.env`（600，含口令） | 尚未生效 |
| 5 | `systemctl restart apache2` | 开关生效 |
| 6 | 冒烟测试（见下），**失败自动回滚** | — |
| 7 | 打印备份路径与回滚命令 | — |

### 冒烟测试怎么证明"真的在跑 MySQL"（不需要管理员口令）

1. **配置层** —— 读 `(wsgi:netlab)` daemon 进程的 `/proc/<pid>/environ`，确认 `NETLAB_DB_BACKEND=mysql`
2. **运行层** —— 打 5 次站点页面，看 MySQL `Connections` 计数是否相应增长（=应用真的在连 MySQL）
3. **语义层** —— 用 venv python 走应用自己的 `db.connect()` 跑 `SELECT`，再建**临时表**插两行并 `rollback()`（临时表随连接消失，对生产数据零影响）
4. **对账** —— 28 张表行数与切换时的 SQLite 快照逐一对齐
5. **HTTP** —— `/api/ping`、`/api/v1/home`、`/courses`、`/api/v1/app/version`、`/admin` 均正常

### 回滚（`rollback-to-sqlite.sh`）

挪走 `db-backend.env` → 重启 apache → 冒烟验证回到 SQLite。
**SQLite 库自切换起就没被写过**，所以回滚 = 瞬间恢复到切换前那一刻。

> 这条链路**不是纸上谈兵**：12:18 那次失败尝试中自动回滚真跑过一遍，站点被完整恢复（所有路由正常）。
> 手动回滚命令：`cd tools/mysql/switch && ./deploy-switch.sh rollback`

> ⚠️ 唯一代价：切到 MySQL **之后**产生的写入不在 SQLite 里，回滚后会"消失"。
> 切换窗口内（第 3 步重灌 → 第 5 步重启生效，约几秒）的写入会丢。
> 所以**建议挑站点空闲时段执行**（学生不在用的时候）。

### 已做的验证

| 验证 | 结果 |
|---|---|
| 本地 SQLite↔MySQL **全量回归**（同一份数据起两个实例，49 个路由逐一比对） | **0 个真实差异** |
| 其中唯一"差异" `/admin/progress.xlsx` | 已拆包证实：`xl/worksheets/sheet1.xml` **逐字节相同**，只有 `docProps/core.xml` 里的**生成时刻**不同（`04:11:24Z` vs `04:11:25Z`），与后端无关 |
| 服务器 MySQL 表结构覆盖检查 | 28 表 / 227 列，应用所需**全覆盖** |
| 数据迁移完整性 | 28 表 / 562 行，逐表内容哈希一致，中文无乱码 |

> 本地回归跑的其实是**本机 MySQL 9.6.0**，服务器是 **8.0.46** —— 跨大版本都通过了，兼容性更有底。

### 相关代码/工具位置

| 路径 | 说明 |
|---|---|
| `server/app/mysqldialect.py` | SQLite→MySQL 翻译规则（迁移与运行时共用同一份） |
| `server/app/mysqldb.py` | 运行时连接壳（PyMySQL + DictCursor） |
| `tools/mysql/migrate_sqlite_to_mysql.py` | 全量迁移；支持 `NETLAB_APP_DIR` 指定 app 目录 |
| `tools/mysql/regress_compare.py` | 本地双实例全量回归 |
| `tools/mysql/probe_xlsx.py` | xlsx 差异定点拆包探针 |
| `tools/mysql/verify_fresh_schema.py` | 表结构覆盖检查 |
| `tools/mysql/switch/` | 切换工具集（deploy-switch / switch-to-mysql / rollback-to-sqlite / smoke-test） |

---

## 十一、⚠️ 切换后的两个坑（2026-10-16 下午发现）

### 坑 1：`sqlite_web`（8081 网页版编辑器）指向的是**已经废弃的 SQLite**

`sqliteweb` 服务还活着，参数里写死了旧库路径：

```
/opt/sqliteweb/venv/bin/sqlite_web -H 127.0.0.1 -p 8081 -P -x -T -Q 2000 /opt/websystem/data/netlab.db
```

而网站现在读的是 MySQL。**在 8081 上改数据 = 改历史存档，网页毫无变化。**
（日志显示 14:38:50 还有人在 POST `/login/`，文件 mtime 停在 14:25。）

处置：**要么停掉**（`systemctl stop sqliteweb && systemctl disable sqliteweb`），
**要么只当只读历史存档用，绝不在上面做修改**。

### 坑 2：改动是否生效，别拿 8081 当参照

判断"我这条改动生效了没"只看两处：Navicat 重新打开表、网站页面刷新。
想证明应用真的连的是 MySQL，打一次站点再看 `SHOW GLOBAL STATUS LIKE 'Connections'` 有没有涨。

### 切换后两库对账（2026-10-16 下午实测）

用 `netlab.db`（SQLite，死库）与 `netlab`（MySQL，活库）逐表比对：

| 表 | SQLite | MySQL | 结论 |
|---|---|---|---|
| `users` | 22 | **23** | MySQL 多 1 条 —— 切换后写进去的测试账号 `stu_test_01` |
| `courses` / `videos` / `files` | 25 / 73 / 80 | 25 / 73 / 80 | 一致 |
| `settings` | 29 | 29 | **逐键比对无差异** |
| `study_days` / `assignments` / `scan_logins` | 141 / 124 / 23 | 141 / 124 / 23 | 一致 |
| 其余各表 | 全部一致 | | 各表 `MAX(created_at)` 也完全相同 |

→ **除 1 条测试数据外零分叉**，SQLite 那份可以当作"切换前快照"的干净兜底存档。

### 线上库现状（实地导出）

28 张表 / 562 行，InnoDB，`utf8mb4_0900_ai_ci`，**没有任何外键**（FK count = 0）。

唯一约束只有这些：`users.username`、`users.phone`、`activation_codes.code`、
`challenge_matches.invite_code`，以及各表主键（`settings.k`、`scan_logins.token`、
`study_days(user_id,day)`、`course_progress(user_id,course_id)`）。
**`users.student_no` 没有唯一约束**——但它参与登录，见第十节红线。

> 📄 面向"我要改数据"的操作指南（含 28 张表清单与场景 SQL 模板）：
> `WorkBuddy/2026-10-15-21-50-20/线上MySQL改数据速查卡.html`

---

## 十二、🧪 练习沙盒 `netlab_practice`（本机，2026-10-16 建）

**别拿生产练手。** 本机有一个结构和线上完全一致的库，专门用来试语句。

| 项 | 值 |
|---|---|
| 连接 | `127.0.0.1:3306` / `admin` / `CHANGE_ME_PASSWORD` |
| 库名 | `netlab_practice` |
| 内容 | 28 张表（结构与线上一致）+ 演示数据：6 用户 / 4 课程 / 4 视频 / 3 作业 / 题库 / 反馈 / 招新报名… |
| 演示账号密码 | 一律 `test1234`（`demo_admin` 是管理员） |

### 怎么建起来的（可复现）

```bash
# ① 从线上库导结构（只导结构，不带数据、不带密码）
ssh root@your-server.example.com "mysqldump -uadmin -p'…' --no-data --single-transaction --skip-comments netlab" \
  > tools/mysql/practice-schema.sql

# ② ⚠️ 关键一步：剥掉自增起始值
#    mysqldump 会把线上的 AUTO_INCREMENT=57 一起带出来，
#    不剥掉的话沙盒里第一个新用户从 id=58 开始，和"预期 6 个用户 / id 从 1 开始"全对不上
sed -i '' -E 's/ AUTO_INCREMENT=[0-9]+//g' tools/mysql/practice-schema.sql   # macOS
sed -i    -E 's/ AUTO_INCREMENT=[0-9]+//g' tools/mysql/practice-schema.sql   # Linux

# ③ 建库 + 灌结构 + 灌演示数据（演示数据脚本见 tools/mysql/practice-seed.sql）
mysql -uadmin -p'CHANGE_ME_PASSWORD' -h127.0.0.1 -e "DROP DATABASE IF EXISTS netlab_practice;
  CREATE DATABASE netlab_practice CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;"
mysql -uadmin -p'CHANGE_ME_PASSWORD' -h127.0.0.1 netlab_practice < tools/mysql/practice-schema.sql
mysql -uadmin -p'CHANGE_ME_PASSWORD' -h127.0.0.1 netlab_practice < tools/mysql/practice-seed.sql
```

仓库里两个文件：`tools/mysql/practice-schema.sql`（28 表结构）、`tools/mysql/practice-seed.sql`（演示数据）。
沙盒玩坏了重跑上面 ③ 即可。

### 演示数据的固定坐标（教学文档里引用了）

| 表 | id | 说明 |
|---|---|---|
| `users` | 1 / 2 | `demo_admin`（管理员）/ `demo_teacher`（管理员，从没登录过） |
| `users` | 3 / 4 / 5 / 6 | `stu_zhangsan`(张三, 学号20250001) / `stu_lisi`(李四) / `stu_wangwu`(王五) / `stu_zhaoliu`(赵六, **已停用**) |
| `courses` | 1 / 2 / 3 / 4 | 网络基础 / 交换路由配置 / 职教高考·汉字录入 / （草稿）综合布线（`is_open=0`） |
| `videos` | 1-2 → 课程1；3-4 → 课程2 | 课程2 的视频 `sort_order` 是 10 / 20 |
| `study_days` | 用户 3 有 2 天、用户 4 有 2 天 | → 张三 2.5 小时、李四 1.3 小时，其余为 0 |
| `settings` | 7 个键 | 含 `join_open` / `register_open` / `registration_open` 三个开关 |
| `activation_codes` | 3 行 | 1 条已被张三用掉（`DEMO-CODE-0001`）、2 条空闲 |

行数总览：users 6 / courses 4 / videos 4 / assignments 3 / files 4 / study_days 4 /
course_progress 3 / settings 7 / nav_links 3 / activation_codes 3 / posts 2 / replies 2 /
questions 2 / challenges 2 / feedback 1。

### 配套教学文档

> 📘 `WorkBuddy/2026-10-15-21-50-20/数据库增删改查教程.html`
> 从"三条铁律"讲到 SELECT / INSERT / UPDATE / DELETE，含 8 个实战场景、8 道练习（带答案）、
> 红线与报错码速查、以及一个 UPDATE 语句生成器。
> **文档里 71 段 SQL 全部在 `netlab_practice` 里实跑验证过**，预期结果也是实测值。


---

## 十三、🌐 直连云数据库：`db.example.com:13306`（2026-10-16 搭好）

**不用 SSH 隧道了。** Navicat 里直接填域名+端口就能连，双击改数据。

```
Navicat → db.example.com:13306 → 阿里云安全组放行 → nginx(stream) → 127.0.0.1:3306 → MySQL netlab
```

### Navicat 填法

| 字段 | 值 |
|---|---|
| 连接类型 | MySQL |
| 主机 | `db.example.com`（或 `YOUR_SERVER_IP`） |
| 端口 | **`13306`** |
| 用户名 / 密码 | `admin` / `CHANGE_ME_PASSWORD` |
| **SSH 标签页** | **留空 / 不勾**（以前走隧道才填，现在直连） |

### ⚠️ 为什么必须用 nginx `stream`，不能用普通网站反代

**MySQL 不是 HTTP。** Apache/nginx 的 `http{}`（`ProxyPass` 到 URL）载不动 MySQL 的二进制协议，
只能在四层把 TCP 原样转发 —— 这就是 nginx `stream` 模块的用途。它跟 Apache 那套站点完全独立，
**不碰 80/443**（实测 `your-server.example.com` 仍 200）。

### 服务器侧配置

| 项 | 值 |
|---|---|
| 软件 | `nginx` + **`libnginx-mod-stream`**（Ubuntu 把 stream 拆成独立包了！光装 `nginx` 没有） |
| 配置 | `/etc/nginx/stream.d/mysql.conf`，由 `nginx.conf` 末尾的 `include /etc/nginx/stream.d/*.conf;` 引入 |
| 备份 | `/etc/nginx/nginx.conf.bak-20261016` |
| 监听 | `0.0.0.0:13306` → `proxy_pass 127.0.0.1:3306` |
| 关键参数 | `proxy_timeout 30m`（数据库长连接，默认 10 分钟太短）；`limit_conn` 单 IP 20 并发 |
| 日志 | `/var/log/nginx/mysql-access.log` |
| 自启 | `systemctl enable nginx` 已开 |

**踩的坑**：`apt install nginx` 后默认站点 `/etc/nginx/sites-enabled/default` 会去抢 80/443，
和 Apache 撞车 —— 必须 `rm -f /etc/nginx/sites-enabled/default`。
Ubuntu 的 `nginx -V` 里**没有 `--with-stream`**，模块在独立的 `libnginx-mod-stream` 包里。

### 两件必须人工做的事

1. **阿里云安全组**放行入方向 `自定义TCP 13306/13306`、授权对象 `0.0.0.0/0`。
   服务器上 ufw/iptables 全是空的，**唯一的闸门就是安全组**（实测 13306 在放行前外网完全不通）。
2. **DNS**：`db.example.com` → A 记录 → `YOUR_SERVER_IP`（已生效）。

### 自检 / 回退

```bash
./tools/db-cloud-check.sh     # 查 DNS + 端口 + 数据库握手，通不了会告诉你该点哪儿

# 想关掉对外直连（二选一，推荐后者，随时能开回来）
#   a) 安全组里禁用/删掉那条 13306 规则
#   b) ssh root@your-server.example.com "systemctl stop nginx && systemctl disable nginx"
```

SSH 隧道那套（`tools/db-mysql-live.sh` 与 Navicat 的 SSH 标签）**留着没删**，直连万一出问题可随时退回。

> 📋 面向操作的单页说明：`WorkBuddy/2026-10-15-21-50-20/云数据库直连-操作单.html`

---

## 十四、🔑 改用户密码（三种方式，按场景选）

先记住一件事：**密码不是明文存的，也不能"解出来"**。库里 `users.password_hash` 存的是
`pbkdf2_sha256$32位盐$64位摘要`（PBKDF2-HMAC-SHA256，12 万次迭代，站点自己实现的，
**不是** werkzeug/bcrypt 格式）。所以"改密码"永远是"算一个新哈希写进去"，
**往那一列手打明文 = 这个号从此登不上，而且没有任何提示。**

### 方式 1 · 用户自己改（首选，最省事）

网站 →「我的」页面 →「修改密码」，需要填原密码。
路由 `POST /me/password`（`views_main.py:1057`），校验老密码 → 新密码 ≥6 位 → 两次一致。

### 方式 2 · 管理员后台重置（随机密码）

`https://your-server.example.com/admin/users` → 找到那个人 → 点「重置密码」→
系统生成一个随机密码并在页面提示里显示出来，**当场抄给用户**。
后端是 `secrets.token_urlsafe(6)`（8 位），走的是应用自己的 `hash_password()`，绝对安全。

> 后台这个按钮**不给你指定密码**（模板里没有输入框）。想指定就走方式 3。

### 方式 3 · 一条命令指定新密码（本项目新增工具）

```bash
cd ~/teaching-system

./tools/set-password.sh --list                      # 先看看有哪些人
./tools/set-password.sh demo_user                        # 给 demo_user 随机一个新密码
./tools/set-password.sh demo_user 'MyNewPass123'         # 给 demo_user 指定新密码
./tools/set-password.sh --dry-run demo_user 'abc123'     # 只演一遍，不写库
./tools/set-password.sh --local --db netlab_practice stu_lisi 'abc123'   # 在沙盒练
```

它做的四件事，每件都是防你手滑的：

1. **先查人给你看**（用户名/手机号/学号都能查，因为登录这三列都认），确认了才写
2. **改之前把旧哈希存成回滚 SQL** → `backups/passwords/<时间>-<用户名>.sql`，随时能改回去
3. 用 `tools/pw-hash.py` 的同一套算法算哈希，**生成后先自校验**（验不回的哈希宁可报错也不写库）
4. ⭐ **写完回读数据库里的哈希，再用新密码验一遍** —— 只有这一步过了才告诉你"成了"，
   这样不会出现"以为改好了其实登不上"

**明文密码不会被写进任何文件**，只在屏幕上出现一次。

---

### ⚠️ 写这类脚本时踩的坑（很隐蔽）

**`mysql -N -B` 会把制表符转义成字面量 `\t`。** 批处理模式（`-B`）为了输出可被脚本安全解析，
会把 `\t`、`\n`、`\\` 转义。所以 `SELECT CONCAT_WS(CHAR(9), a, b)` 拿到的是字面 `\t` 而不是制表符，
按列 `cut -f` / `awk -F'\t'` 全部错位。
**必须加 `-r`（`--raw`）**：`mysql -N -B -r -e "..."`。

另外两点：
- **空字段会让 `column -t` 错位**（它把连续制表符当一个），取值时统一用 `IFNULL(NULLIF(col,''),'-')` 占位。
- 凭证走 `mktemp` 生成的临时配置文件 + `--defaults-extra-file`，**密码不进 `ps`**。
  配置文件里 `password="..."` **必须加引号**，否则 `#` 会被当注释截断（本项目密码就带 `#`）。
