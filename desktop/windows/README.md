# 教学管理系统 · Windows 客户端

教学管理系统（https://your-server.example.com）的 Windows 桌面客户端。

## 形态

**原生桌面应用外壳 + 站点实时内容**，不是把浏览器塞进一个框：

```
┌───────────────────────────────────────────────────────────┐
│ NL 教学管理系统 │ Windows 客户端        ─   □   ✕        │ ← 自绘标题栏（无系统边框）
├───────────────────────────────────────────────────────────┤
│ ← → ⟳ ⌂ │ ▤ │  首页 / 招新进行中…   已连接  ⬤账户  − +  ☰ │ ← 工具栏
├──────────┬────────────────────────────────────────────────┤
│ 导航      │                                                │
│  首页     │                                                │
│  课程资料 │        站点真实页面（原生 WebContentsView）      │
│  挑战     │                                                │
│  …        │                                                │
│ 工具/内部 │                                                │
├──────────┴────────────────────────────────────────────────┤
│ ⓘ 就绪   https://your-server.example.com/            下载   100% │ ← 状态栏
└───────────────────────────────────────────────────────────┘
```

站点原有的顶部导航条在客户端内被隐藏（避免与侧边导航重复），
其余页面、样式、数据与服务端**完全一致**。

## 为什么能"完美复刻"

内容区直接加载站点真实地址（`https://your-server.example.com`），因此：

- 页面、样式、数据与服务端**实时一致**，站点改版客户端自动同步
- 登录、注册、云盘上传下载、文件中心、社区发帖与附件、挑战、报到、格式转换**全部可用**
- Cookie / 登录态持久化在本机，关闭软件无需重新登录

## 功能一览

| 能力 | 说明 |
| --- | --- |
| 自绘标题栏 | 无系统边框，最小化 / 最大化 / 关闭自绘，支持拖动与双击最大化 |
| 工具栏 | 后退 / 前进 / 刷新 / 首页、侧栏开关、当前页面标题、连接状态、账户、缩放、更新徽标、菜单 |
| 侧边导航 | 按「导航 / 工具 / 实验室内部」分组，当前页高亮，可整体隐藏 |
| 应用菜单 | 系统**原生菜单**：账户（个人中心 / 退出，未登录时为登录 / 注册）、刷新、缩放、全屏、侧栏开关、自动检查更新、检查更新、下载目录、清除登录状态、关于 |
| **OTA 在线升级** | 启动后 8 秒检查一次、运行期间每 6 小时一次；发现新版本时工具栏亮起徽标 + 系统通知，点开是独立的「软件更新」对话框：版本对比 / 更新内容 / 安装包体积 / 下载进度与速度 / SHA-512 校验 / 稍后提醒 / 跳过此版本 |
| 状态栏 | 连接状态、当前地址、更新进度、下载进度、缩放比例 |
| 账户入口 | 工具栏右上角显示头像首字母与昵称，点开即为账户菜单 |
| 登录态保持 | 独立持久化会话（`persist:teaching-system`），Cookie / localStorage 长期保存 |
| 文件上传 | 云盘、社区附件、格式转换等 `<input type=file>` 走系统原生选择框 |
| 下载 | 云盘 / 文件中心 / 社区附件 / APK 下载到系统「下载」目录，任务栏图标显示实时进度，完成后系统通知 |
| 站内子站 | 考试系统、Docker 面板在客户端内新窗口打开，共享登录态 |
| 站外链接 | DeepSeek / CSDN / 豆包 / 备案链接 / 内网选课平台等交给系统默认浏览器 |
| 断网兜底 | 连接失败时显示内置离线页（重试 / 浏览器打开），不出现空白窗口 |
| 崩溃恢复 | 渲染进程异常退出时弹窗询问是否重新加载 |
| 单实例 | 重复启动会聚焦已有窗口，不会开出多个进程 |
| 窗口记忆 | 尺寸、位置、最大化状态、缩放比例、侧栏可见性、自动检查更新开关、已跳过版本全部记忆 |
| 应用图标 | 站点官方 `NL` 图标（多尺寸 .ico + 托盘图标） |

### 快捷键

| 快捷键 | 作用 |
| --- | --- |
| `F5` / `Ctrl+R` | 刷新 |
| `Ctrl+Shift+R` | 强制刷新（忽略缓存） |
| `Alt+←` / `Alt+→` | 后退 / 前进 |
| `Alt+Home` | 回到首页 |
| `Ctrl+ +` / `Ctrl+ -` / `Ctrl+0` | 放大 / 缩小 / 实际大小（记忆缩放） |
| `F11` | 全屏 |
| `F12` | 开发者工具 |
| `Ctrl+Q` | 退出 |

## 目录结构

```
desktop/
├─ src/
│  ├─ main.js        主进程：窗口外壳、原生内容视图、原生菜单、下载、链接路由、会话、更新窗口
│  ├─ updater.js     OTA：检查版本、下载与 SHA-512 校验、安装（安装版静默原地升级 / 绿色版原地替换）
│  ├─ update-scripts.js 安装脚本生成 + 分离式 PowerShell 启动器（不依赖 Electron，可被测试工具直接引用）
│  ├─ preload.js     外壳与主进程的桥（白名单 IPC）
│  ├─ shell.html     外壳结构：标题栏 / 工具栏 / 侧栏 / 状态栏
│  ├─ shell.css      外壳样式（Windows 11 风格浅色主题）
│  ├─ shell.js       外壳逻辑：导航、标题、账户、更新徽标、快捷键
│  ├─ update.html    「软件更新」对话框（独立无边框模态窗口）
│  ├─ update.css     对话框样式
│  ├─ update.js      对话框渲染：按阶段出图、按钮回传主进程
│  ├─ splash.html    启动画面
│  └─ offline.html   连接失败兜底页
├─ assets/           运行期图标、托盘图标
├─ build/icon.ico    打包用多尺寸图标
├─ server/           服务端改动的本地镜像（上传前先在这里改，便于 diff 与复用）
├─ tools/
│  ├─ ssh_run.py     SSH 执行 / 上传 / 下载（凭据走环境变量）
│  ├─ publish_app.py 发布安装包：上传 + 算 SHA-512 + 写 app_versions + 标记最新版
│  ├─ install-sim.js 绿色版原地替换脚本的「落地演练」：用同一个 update-scripts.js，对真实文件跑一次改名换上
│  ├─ verify.js      端到端界面验证（CDP 驱动，断言写入 shots/verify/report.json）
│  ├─ smoke-test.js  冒烟测试：真实加载各页面并截图
│  ├─ drive.js       通过 CDP 驱动运行中的客户端（开发调试用）
│  └─ shot.py        抓取窗口截图（PrintWindow，不受遮挡影响；可指定窗口标题关键词）
├─ shots/            验证截图
└─ package.json      工程与打包配置
```

## 构建

```bash
# 依赖（国内镜像）
export ELECTRON_MIRROR="https://npmmirror.com/mirrors/electron/"
export ELECTRON_BUILDER_BINARIES_MIRROR="https://npmmirror.com/mirrors/electron-builder-binaries/"
npm install

# 打包（安装版 + 绿色版）
npm run dist
```

产物在 `desktop/dist/`：

- `教学管理系统-安装版-1.3.5.exe` — NSIS 安装包，可选安装目录，创建桌面与开始菜单快捷方式
- `教学管理系统-绿色版-1.3.5.exe` — 免安装单文件

### 发布新版本（让客户端能 OTA 到它）

```bash
# 1) 改 package.json 的 version，重新打包
npm run dist

# 2) 上传并登记版本（会自动算 SHA-512、写 app_versions、把同渠道旧记录降级为「上一版」）
export LC_PASS='...'
python tools/publish_app.py --file "dist/教学管理系统-安装版-1.3.4.exe" \
    --platform windows --version 1.3.4 --notes-file release-notes.txt \
    --name "教学管理系统-安装版-1.3.4.exe"
python tools/publish_app.py --file "dist/教学管理系统-绿色版-1.3.4.exe" \
    --platform windows-portable --version 1.3.4 --notes-file release-notes.txt \
    --name "教学管理系统-绿色版-1.3.4.exe"
```

发布完成后：

- `https://your-server.example.com/download` 立刻显示新版本与两种安装包
- 已装客户端在下次检查时（启动后 8 秒 / 每 6 小时）收到更新提示

`version_code` 由版本名自动推导（`1.3.4 → 1003004`，见 `db.semver_code`），不用手填整数。

### 常见问题

**打包报 `Cannot create symbolic link`**

`winCodeSign` 压缩包内含 macOS 符号链接，Windows 非管理员账户解压会失败。解决方式是在
`%LOCALAPPDATA%\electron-builder\Cache\winCodeSign\` 下手工提供 `winCodeSign-2.6.0`
目录（含 `rcedit-x64.exe` 与 `windows-10/x64/signtool.exe` 即可），electron-builder 检测到
目录存在便跳过解压。或开启 Windows「开发者模式」后再构建。

**外壳布局塌陷（隐藏侧栏后状态栏上移）**

外壳根容器（`body`）必须显式声明为 flex 列：

```css
body { display: flex; flex-direction: column; }
```

标题栏 / 工具栏 / 主体 / 状态栏都用 `flex: none | 1` 书写，缺少这个根声明时它们会退化为
普通块级流 —— `flex: 1` 失效，`.body` 高度由自身内容（侧栏）撑开，一旦隐藏侧栏就塌陷为 0，
状态栏随即上移到工具栏下方。`tools/verify.js` 里的「根容器为 flex 列」「状态栏贴底」
「折叠侧栏后横向布局正确」三条断言就是防这个回归的。

**外壳 HTML 画的浮层看不见（被内容区挡住）**

内容区是原生 `WebContentsView`，**永远绘制在外壳 HTML 之上**。任何在外壳页面里用
`position: fixed` 覆盖到内容区的浮层（下拉菜单、更新对话框）都会被网页盖住，
DOM 断言还查不出来（元素存在、`hidden=false`、`getBoundingClientRect()` 也正常，就是看不见）。

所以外壳里**不要**再放跨到内容区的浮层：

- 应用菜单 / 账户菜单 → 用系统原生菜单（`Menu.popup({ window, x, y })`）
- 更新对话框 → 用独立的无边框模态窗口（`update.html`）

`tools/verify.js` 里的「弹层改用原生菜单」断言会检查 `#menuPop` 已不存在，防止回退。

**下载卡在 100% 不动（Electron net 流的 end 事件不可靠）**

用 `net.request()` 下载大文件时，偶发 `res.on('end')` 不派发：文件其实已经完整落盘
（78 MB 一个字节不差），界面却永远停在「下载中」。因此完成判定**不能只靠 `end`**：

```js
// 收到数据后：字节数够了就直接收尾
if (total > 0 && received >= total) finalize();
// finalize 里再核对磁盘真实大小 + SHA-512，另有 45s 空闲看门狗与 12s 落盘兜底
```

实测这一条是修掉「下载完成但按钮不出现」的关键。

**调试运行**

```bash
npm start                      # 普通启动
LC_DEBUG_PORT=9222 npm start   # 启动并开放调试端口
```

开放调试端口后可用 `tools/drive.js` 驱动界面：

```bash
node tools/drive.js list
node tools/drive.js eval shell 'document.getElementById("btnMenu").click(); "ok"'
node tools/drive.js shot shell shots/menu.png
```

**抓取界面截图**

```bash
python tools/shot.py shots/ui.png 1200 3
```

用 `PrintWindow` 直接抓窗口内容，不受其它窗口遮挡影响。

> 注意：内容区是独立的原生 `WebContentsView`，`Page.captureScreenshot` 抓不到它
> （只会得到空白占位），所以整窗证据一律用 `tools/shot.py`，不要用 CDP 截图。

## 端到端界面验证

```bash
LC_DEBUG_PORT=9222 npm start        # 一个终端启动客户端
node tools/verify.js shots/verify   # 另一个终端跑验证
```

逐项断言：外壳元素齐全、侧栏 10 项、无整页滚动条、站点自带导航已隐藏、
8 个页面逐个导航 + 外壳标题/高亮/状态栏同步、前进后退、原生菜单接线、更新徽标默认隐藏、
更新检查有回执、缩放、侧栏折叠复原、账户状态与站点一致、内容区无横向溢出。
结果写入 `shots/verify/report.json`。

> 原生菜单不要放进自动化断言里点开：`Menu.popup()` 弹的是系统菜单，脚本点不掉，
> 会一直悬在窗口上影响后续截图。菜单观感用 `tools/shot.py` 抓整窗后人工核对。

## OTA 在线升级

### 服务端（站点）

| 位置 | 作用 |
| --- | --- |
| `app_versions` 表 | 新增 `platform` 与 `sha512` 两列（老库走 `ensure_column` 自动迁移）。同一 `platform` 只保留一条 `is_latest=1` |
| `GET /api/v1/app/version?platform=windows&version_code=1003003` | 返回最新版本的版本名 / 说明 / 下载地址 / 字节数 / SHA-512 / `need_update`。`platform` 支持 `android` / `ios` / `windows` / `windows-portable` / `macos`，不带参数默认 `android`，老客户端行为不变 |
| `GET /app/download/<vid>` | 按版本记录下载安装包，落盘文件名用中文 `file_name` |
| `GET /download` | 下载页：安卓 + Windows（安装版 / 绿色版）各自的「最新 / 上一版」，并说明 OTA 能力 |
| 后台 `版本管理` | 按平台发布版本：选平台、上传 exe/apk、填版本名与更新说明；Windows 版本号由版本名自动推导 |

渠道区分：安装版走 `windows`，绿色版走 `windows-portable`（`updater.js` 用
`process.env.PORTABLE_EXECUTABLE_FILE` 判断），两者各自维护「最新版」，互不干扰。

### 客户端

```
启动 8 秒后 / 每 6 小时
      ↓
/api/v1/app/version?platform=…&version_code=…
      ↓ 有新版本
工具栏徽标「新版本 v1.3.5」+ 系统通知
      ↓ 用户点开
「软件更新」对话框（独立模态窗口）
   ├─ 版本对比 v1.3.4 → v1.3.5
   ├─ 渠道 / 安装包体积 / 发布时间 / SHA-512 前缀
   ├─ 更新说明（可滚动）
   ├─ 立即更新 → 下载（进度 + 速度，可取消）
   ├─ 下载完成 → 核对磁盘字节数 + SHA-512 → 落地成正式安装包
   ├─ 立即安装并重启
   │    ├─ 安装版：调起 NSIS 安装向导，用户确认后完成升级（向导可选「运行」）
   │    └─ 绿色版：PowerShell 辅助进程等本进程退出 → 原地替换 exe → 重新拉起
   └─ 稍后提醒 / 跳过此版本（记进 window-state.json，可通过菜单「恢复被忽略的版本」撤销）
```

用户操作与状态全程由主进程 `updater.js` 掌握，外壳只负责显示徽标与状态栏进度，
真正的界面是 `update.html`。

> 安装版为什么不做静默安装：本工程用的是「向导式」NSIS（`oneClick: false`），
> 静默 `/S` 不会沿用原安装目录，可能装出第二份。所以升级时调起标准安装向导，
> 由用户确认 —— 这也是常规 Windows 软件的做法，向导结束时可勾选直接运行新版本。

### 设计要点（1.3.6 起，都是踩过坑才有的）

**① 只有「受管副本」才允许自动升级。**

- 绿色版：认 `PORTABLE_EXECUTABLE_FILE`
- 安装版：认「exe 旁边有 `Uninstall*.exe`」

两者都不满足时（比如直接双击打包中间产物 `dist/win-unpacked/教学管理系统.exe`，
或把安装目录拷到别处再启动），客户端**不再假装能升级**，而是在更新窗口里直说原因、
并给出「前往下载页」。

> 为什么必须这么判：这类散装副本如果按安装版渠道升级，安装包只会把新版本装进
> 标准安装目录，**用户一直启动的那个 exe 一个字节都不会变**。
> 表现出来就是最迷惑的那种故障：**「安装向导走完了、看着像更新成功，重启后还是旧版本」**。

**② 安装版改走「静默原地升级」，不再用安装向导。**

`pkg /S /currentuser`。electron-builder 的 NSIS 会从注册表
`HKCU\Software\<APP_GUID>\InstallLocation` 读回上次的安装目录
（见 `multiUser.nsh` 的 `setInstallModePerUser`），所以静默安装天然就是「装回原目录」的原地升级，
既不需要用户点任何东西，也不可能装出第二份。

> 向导方案之所以危险：它把「装到哪」交给用户点选，一旦改了目录或中途取消，
> 就会出现「向导走完、但你在用的那份从没被换过」。

**③ 启动握手：确认不到升级组件，就绝不退出自己。**

替换/安装必须由独立 PowerShell 完成（运行中的 exe 无法被覆盖）。主进程先等它写出的
「已启动」凭据文件，**等到才退出自己**；等不到就退回非分离方式重试，仍失败则留在原样并提示原因。

> 实测 `detached` 方式启动 `powershell.exe` 会出现「进程被创建、但脚本压根没执行」。
> 早期版本在这种情况下照样退出 —— 用户看到的就是「客户端自己关了，可升级根本没做」。

**④ 全程可追溯**：安装脚本把关键节点写进 `%APPDATA%\教学管理系统\updates\update.log`。

### 怎么验证 OTA（含踩过的坑）

正式流程里，替换 exe 必须由「主程序退出之后」的独立进程完成，所以全程难以在
自动化环境里复现。为此把安装脚本生成拆到 `src/update-scripts.js`（不依赖 Electron），
再用 `tools/install-sim.js` 引用**同一份代码**对真实文件跑一次落地演练：

```bash
# 准备：一个「当前绿色版」+ 一个「新安装包」
node tools/install-sim.js \
  dist/installsim/教学管理系统-绿色版-1.3.4.exe \
  dist/installsim/LinkCoffee-portable-v1.3.5.exe
# 期望：当前 exe 被换成新包（字节数一致）、新包被移走、.old 已清理、新版被拉起
```

脚本里把「等待的 PID」换成一个不存在的 PID，让等待步骤立即返回，
于是整段脚本可以在前台同步跑完 —— 这样验证到的就是发版代码本身。

三个已修的坑（都加了防回归）：

1. **下载明明 100% 却卡在「下载中」**：Electron 的 `net` 流对大文件有时不派发
   `end` 事件。完成判定改为「已收字节数 ≥ Content-Length」+ 磁盘实际大小核对，
   另配 45 秒空闲看门狗与 12 秒落盘兜底。
2. **SHA-512 校验总是不通过**：后台与 `publish_app.py` 以 **hex** 存库，而客户端早期
   代码把值统一 `toLowerCase()` 后才比较；base64 是大小写敏感的，一旦小写化必然对不上。
   现在客户端同时接受 hex 与 base64，且 base64 原样比较；服务端统一存 hex。
3. **安装程序起不来却「自己关掉」**：`spawn` 的失败是异步 `'error'` 事件，`try/catch`
   抓不到，不挂监听还会把主进程打挂。现在挂了 `onError`，失败时保持原位并提示原因，
   不再退出。

> 补充：`detached: true` 的分离式进程在某些受限/沙箱环境会被直接拦掉（脚本完全不执行），
> 真实 Windows 上不受影响；本地若发现「点了安装没反应」，先确认不在受限环境里跑。

### 关于登录态检测（易踩坑）

站点有**两套互不相通的鉴权**：

| 用途 | 凭据 | 校验函数 |
| --- | --- | --- |
| 页面路由（`/report`、`/drive`、`/courses`…） | Flask session cookie（`session["uid"]`） | `core.current_user()` |
| `/api/v1/*` 接口 | `Authorization: Bearer <token>` 或 `?token=` | `views_api.api_user()` |

网页表单登录**只写 session cookie，不产生 token**，所以仅靠 `/api/v1/me`
判断登录态会把已登录误判为未登录。客户端的做法是：
优先读页面渲染出的账户区（`base.html` 的 `.nav-right`，已登录时含 `/me` 与
`/logout` 链接），读不到再退回 token 探测。

## 冒烟测试

```bash
npx electron tools/smoke-test.js
```

依次加载首页、挑战、社区、格式转换、加入我们、App 下载、登录、注册八个页面，
截图写入 `shots/`，并把标题、导航项、样式加载状态、控制台报错汇总到 `shots/report.json`。

## 会话与隐私

- 客户端仅在你本机保存登录 Cookie，不上传任何数据到第三方
- 清空登录态：工具栏「菜单 → 清除缓存与登录状态…」
- 所有内容请求直接发往 `your-server.example.com`，与浏览器访问一致
