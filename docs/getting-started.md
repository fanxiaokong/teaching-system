# 开始开发 · 三步

> 一页纸入口。详细内容见《本地开发迭代手册.html》。
> 本页 2026-10-16 校订：数据库已切 MySQL、口令改明文存储、安卓工程换了目录。

---

## 第 1 步：用 VS Code 打开工作区

双击这个文件：

```
~/teaching-system/教学管理系统.code-workspace
```

VS Code 会一次打开五个目录：**网页端 / 安卓端 / Windows客户端 / macOS客户端 / 发布工具**。

---

## 第 2 步：按需启动

### 网页端（最常用）

| 操作 | 方式 |
|---|---|
| 启动本地站点 | 按 `F5`，或 `Cmd+Shift+P` → `Tasks: Run Task` → ① 启动本地站点（`http://127.0.0.1:8000`） |
| 调试（断点/变量） | 按 `F5` 选「网页端 · 调试运行」 |
| 上线 | 任务 → ② 部署到线上服务器（rsync + 重启 + 验证） |
| 备份线上库 | 任务 → ④ 归档备份线上数据库（带时间戳） |
| 看数据库全貌 | 见 **`数据库连接.md`** |

### 改线上数据（现在只走 MySQL）

> ⚠️ **`./tools/db-live.sh` 已停用。** 它连的是服务器上的 sqlite-web（127.0.0.1:8081），
> 而那台机器上的 `netlab.db` 是**早已废弃的 SQLite 快照**——线上早在 2026-10-16 就切到 MySQL 了。
> 继续用它，你改的是没人读的文件，还以为改的是线上。脚本现在会直接拦住并提示。

**主路：Navicat 直连生产库（改完即生效，不用 push、不用重启）**

```
主机  db.example.com
端口  13306          ← 注意是 13306，不是 3306
用户  admin
密码  CHANGE_ME_PASSWORD
库    netlab
```

连不上先跑 `./tools/db-cloud-check.sh`，它会告诉你卡在哪一步。
服务器侧 13306 配了**来源 IP 白名单**，换了网络（比如从家里换到学校）需要放行新 IP：

```bash
curl -s https://ifconfig.me; echo                       # 先看你现在的公网 IP
ssh root@YOUR_SERVER_IP "mysql-allow.sh add <上面那个IP>"
```

**备路：SSH 隧道**（白名单没加上你的时候用）

```bash
./tools/db-mysql-live.sh        # 然后 Navicat 连 127.0.0.1:13306
```

### 改密码（现在是明文，直接改就行）

口令**明文存储**，Navicat 里双击 `users.password_hash` 就能改。

终端里改：

```bash
python3 tools/password-plain.py --list            # 看谁的口令是什么
python3 tools/password-plain.py set demo_user '新密码'   # 改一个
python3 tools/password-plain.py convert-all '新密码' -y   # 把所有还是哈希的账号统一改掉
./tools/set-password.sh demo_user '新密码'              # 等价，写法更短
```

> 为什么要保留 `convert-all`：老账号可能还留着历史 PBKDF2 哈希（不可逆，解不出原文），
> 登录校验两种格式都认，所以不转也能用；转过之后就是纯明文了。

### 用户忘密码了怎么办

**用户自助**：登录页点「忘记密码？」（`/forgot`，App 端在登录页同样有入口）。两步式：

1. 填手机号 / 用户名 / 学号 → 系统定位账号
2. 核对「学号或昵称」+ **输入原密码** → 设置新密码

> ⚠️ 第 2 步要求原密码是平台约定（任何改密都必须过原密码这道闸）。
> 所以**真忘了原密码的用户走不通**，此时让他走下面这条路。

**管理员重置**：后台 →「用户与学习数据」→ 对应用户点重置，系统生成随机密码并显示出来，转告用户即可。

防爆破：同一个账号 10 分钟只给 6 次找回尝试（`throttle.forgot_gate`）。

### 安卓端

**权威工程在这里**（用 Android Studio 打开）：

```
~/project/teaching-system/android
```

> ✅ `teaching-system/android/` 那份**落后 10 个版本的旧副本（v1.9）已于 2026-10-16 归档并删除**，
> 归档在 `_archives/android-v1.9-legacy-src.zip`（源码，177&nbsp;KB），原目录已移入废纸篓。
> 从今往后安卓只有下面这一个工程，不会再误构建。

命令行打包（本机已配好 JDK 21 + Android SDK，实测可过）：

```bash
cd ~/project/teaching-system/android
export JAVA_HOME="$HOME/Library/Java/JavaVirtualMachines/jbr-21.0.11/Contents/Home"
export ANDROID_HOME="$HOME/Library/Android/sdk"
./gradlew assembleDebug
# 产出 app/build/outputs/apk/debug/app-debug.apk
```

发版前把 `app/build.gradle.kts` 的 `versionCode` / `versionName` 都加一位。

### Windows / macOS 客户端

在 VS Code 里展开对应目录，`Cmd+Shift+P` → `Tasks: Run Task`：

| 任务 | 作用 |
|---|---|
| ① 安装依赖 | 首次必跑（走国内镜像） |
| ② 调试启动 | `npm start` |
| ③ 打包 | Windows → exe；macOS → dmg |

---

## 第 3 步：发布新版本

两条路都行：

**A. 网站后台**（推荐，有校验）——「管理 → 版本管理」选渠道、填版本名、传安装包。
现在四个渠道齐全：**安卓 APK / macOS（.dmg）/ Windows 安装版 / Windows 绿色版**。

**B. 命令行脚本**（批量或自动化）

```bash
cd ~/teaching-system

# 先干跑（不碰服务器），确认版本号和文件名对
python3 tools/publish_app.py --platform windows --version 1.4.9 \
    --file "desktop/windows/dist/教学管理系统-安装版-1.4.9.exe" --dry-run

# 确认后去掉 --dry-run
```

> 安装包在服务器上的文件名统一按「渠道 + 版本名」生成
> （`teaching-system-android-v1.19.apk` / `teaching-system-mac-v1.0.9.dmg` / `teaching-system-win-setup-v1.4.9.exe`），
> 同名会覆盖，不会再越堆越多。

> **两个须知**：
> 1. `publish_app.py` 现在**写 MySQL**（读 `/opt/websystem/db-backend.env`）。迁移前它写的是已废弃的
>    `netlab.db` 快照 —— 那样会出现「包传上去了、下载页却看不到新版本」的静默失败。若站点回滚到 SQLite，
>    脚本会直接报错退出，不会悄悄写错库。
> 2. 安卓发布时脚本会**读 APK 内部真实的 versionCode/versionName** 跟命令行参数核对，不符直接拒发。
>    这是防「库里写的和包里装的对不上 → 客户端反复提示更新」的唯一有效闸门。

---

## 环境清单（已配好，无需再动）

| 组件 | 状态 |
|---|---|
| VS Code | ✅ `code` 命令已可用 |
| 网页端 venv | ✅ Python 3.13.12，位于 `server/.venv`（**本地默认 SQLite**） |
| JDK 17 / JDK 21 | ✅ `/opt/homebrew/opt/openjdk@17`、`~/Library/Java/JavaVirtualMachines/jbr-21.0.11` |
| Android SDK | ✅ `~/Library/Android/sdk`（许可已接受） |
| 安卓构建验证 | ✅ 已实跑通过 |

> **⚠️ 一个已经替你排掉的坑**：Android Studio 自带的 JBR 是 Java 25，而工程的
> Gradle / AGP 不支持 Java 25（直接报 `What went wrong: 25.0.3`）。
> 已在 `~/.gradle/gradle.properties` 里把 Gradle 的 JDK 钉到 17，**这个文件别删**。

---

## 常用操作

### 发公告（网站 / App / 桌面端三端弹窗）

后台 →「公告」页（`/admin/announcements`）填标题 + 内容即可，**三端自动弹**，不用改代码、不用发版。

- 弹在**登录之后**，同一个人只弹一条（等级：紧急 > 重要 > 普通），点「我知道了」后不再打扰。
- **改了内容会自动重新弹一次**（客户端按 `id + updated_at` 判断有没有读过）。
- 「下架」= 立刻不再弹；「关弹窗」= 只留档不弹。
- 生效/失效时间可留空（= 立即 / 长期）。
- 数据表 `announcements`；App 走 `GET /api/v1/announcements/latest`（需登录）。

### 发激活码（可指定解锁哪些课程）

后台 →「激活码」页（`/admin/codes`）。**解锁范围**选一种：

| 选项 | 效果 |
|---|---|
| **全部课程** | 所有课程都能看（默认，老码就是这个） |
| **指定范围** | 只解锁勾选的「课程标签」和/或「具体课程」，可混选，任一条命中即解锁 |

- 勾**标签** = 该标签下**现有及将来新增**的课程都解锁（适合按方向发权限）。
- 一个学生**可以用多个码，权限叠加**：先给「网络基础」标签的码，再单独给某门课的码，两边的课都能看。
- 学生的课程列表里，没解锁的课程**显示但带🔒**，点进去会引导去激活。
- 「指定范围」但一个都没勾 → 会拦下不生成（避免发出去谁也开不了）。
- 收权限：删掉他绑定的那个码即可。

> 哪些操作需要激活码：**只限课程内容**（课程页、视频、字幕、课程包、作业提交、课程下资料的下载）。
> 云盘、上传资料、文件中心、作业汇总页**只要登录就能用**，不需要激活码。

---

### 看服务器内存 / 磁盘（服务管理页）

后台 →「服务管理」（`/admin/services`），除了启停考试系统与 Docker 面板，顶部还有两块实况：

- **内存**：低于阈值会提示；1.6G 内存别常开那两个服务。
- **存储**：系统盘 + 数据盘分别显示已用/剩余，**剩余不足 5G 会变红告警**。

> ⚠️ **数据盘常年偏紧**（39.1G 里教学视频占 32G）。上传新视频前先看一眼这里，
> 满了就去 `/opt/websystem/data/files` 清理旧视频。

---

## 必须记住的规矩

1. **不要同步 `data/` 目录到服务器** —— 会把生产数据覆盖成本地快照。部署任务里已经排除了。
2. **部署任务里的 `--exclude 'static/app/'` 绝对不能去掉** ——
   本地没有这个目录，去掉之后 `rsync --delete` 会把线上约 2.4GB 的 apk/exe/dmg 安装包**全删光**，所有下载链接立刻失效。
3. **安卓只有 WorkBuddy 工作区那一个工程**（`teaching-system/android/` 旧副本已归档删除，见上文）。
4. **本地这份源码是唯一副本** —— 建议尽快 `git init` 或打包备份。
5. **跑 Electron 一定要 `env -u ELECTRON_RUN_AS_NODE`** ——
   本机工具环境里 `ELECTRON_RUN_AS_NODE=1`，Electron 二进制会被当成 Node 执行：
   `--version` 打印 Node 版本号、传 Chromium 开关报 `bad option: ...`，
   打包好的 `.app` 启动会**秒退且无任何日志**，极易被误判成「签名坏了 / 包打崩了」。

### 直接在数据库里给账号授权

权限挂在 `activation_codes` 表的某一行上，`used_by` 填谁的账号 id 就属于谁。

```sql
-- 开全部课程
UPDATE activation_codes SET scope_kind='all', scope_categories='', scope_courses=''
WHERE used_by = <账号id>;

-- 只开某几门课（课程 id）
UPDATE activation_codes SET scope_kind='limited', scope_categories='[]', scope_courses='[5,30]'
WHERE used_by = <账号id>;

-- 开整个标签
UPDATE activation_codes SET scope_kind='limited', scope_categories='["网络基础"]', scope_courses=''
WHERE used_by = <账号id>;
```

- 该账号**一行都没有**时，上面的 UPDATE 影响 0 行 → 得 `INSERT` 一行并把 `used_by` 直接填成他的 id。
- JSON 必须用**英文引号和英文逗号**；写坏了不报错，只会变成"没权限"。
- 改完**不用重启**，学生刷新即生效。
- 核对：后台「激活码」页看「解锁范围」列；或跑
  `cd /opt/websystem/app && /opt/websystem/venv/bin/python /opt/websystem/tools/scope-report.py --user <账号>`

详细版见工程根目录的 `数据库授权操作速查-20261016.html`。
