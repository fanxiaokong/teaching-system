# 教学管理系统 · macOS 客户端

教学管理系统的 macOS 桌面客户端，与 Windows 版（`teaching-system-windows-source`）同源，
都是用 **Electron** 把网站 `https://your-server.example.com` 包成一个原生窗口应用：无边框窗口 +
自绘外壳（标题栏 / 工具栏 / 侧边导航 / 状态栏），网页内容作为原生 `WebContentsView` 嵌入内容区。

本目录是 **macOS 版**，相对 Windows 版的差异：

| 项目 | Windows 版 | macOS 版 |
| --- | --- | --- |
| 打包目标 | NSIS 安装版 + 绿色版（exe） | DMG + ZIP（arm64） |
| OTA platform | `windows` / `windows-portable` | `mac` |
| 升级方式 | 静默原地替换 exe | 下载安装包 → 打开 → 手动拖入「应用程序」 |
| 图标 | `build/icon.ico` | `build/icon.icns` |
| 代码适配 | — | UA 伪装成 Mac；`setAppUserModelId` 加 win32 守卫；`updater.js` 走 mac 分支 |

## 目录结构

```
MacosAPP/
├── package.json          # 构建配置（electron-builder --mac）
├── src/                  # 主进程 + 外壳渲染（与 Windows 版同源）
│   ├── main.js           # 主进程：窗口 / 视图 / 菜单 / 下载 / 托盘
│   ├── updater.js        # OTA 升级（mac 分支：下载 + 打开安装包）
│   ├── preload.js        # 外壳 ↔ 主进程桥（白名单 API）
│   ├── shell.html/.css/.js
│   ├── splash.html / offline.html / update.html / update.css
│   └── update-scripts.js # Windows 安装脚本生成（mac 不调用，保留以便同源）
├── assets/               # icon.png / tray.png
└── build/                # icon.icns（macOS 图标）
```

## 依赖与构建

```bash
npm install            # 安装 electron + electron-builder
npm run dist           # 构建 arm64 的 .dmg 与 .zip → dist/
npm run dist:all       # 同时构建 x64 + arm64（需下载 x64 electron，较慢）
```

> 首次 `npm install` 会从镜像下载 Electron 二进制（约 170MB），请耐心等待。
> 构建需要 macOS 自带工具：`hdiutil`（做 DMG）、`ditto`（做 ZIP），无需额外下载。

## 运行

- **开发调试**：`npm start`（加载未打包代码，此时 OTA 不会下载/安装，仅检查）。
- **用户使用**：打开 `dist/教学管理系统-1.0.0-arm64.dmg` → 把 App 拖进「应用程序」。

### 关于签名（重要）

本工程 `package.json` 里 `mac.identity` 设为 `null`，即 **不签名** 直接打包。
未签名 App 在别人机器上首次打开会被 Gatekeeper 拦截，处理方式：

- 临时放行：右键 App →「打开」→ 在弹窗里确认；或终端执行
  `sudo xattr -cr /Applications/教学管理系统.app`
- 正式分发：用 Apple Developer ID Application 证书签名并公证（Notarize）：
  在 `package.json` 的 `mac` 下填 `"identity": "Developer ID Application: ..."`，
  并配置 `mac.notarize` 或 `electron-builder` 的 `notarize` 配置。

## OTA 在线升级

客户端启动时（延迟 8s）与运行期间每 6 小时自动检查：

```
GET https://your-server.example.com/api/v1/app/version?platform=mac
```

服务端 `app_versions` 表需有 `platform='mac'` 的 `is_latest` 行。发布新版本时：
把新的 `.dmg` 上传到服务器 `static/app/`，并写入 `app_versions`（`platform='mac'`、
`download_url` 指向该 dmg、`is_latest=1`、清掉旧 mac 的 latest）。可参考 `tools/publish_mac.py`。

macOS 端升级动作是「下载安装包 → 自动打开（DMG 挂载 / ZIP 解压）→ 退出客户端」，
之后由用户在 Finder 里把新 App 拖进「应用程序」覆盖旧版。

## 与网站 / 安卓 / iOS 的关系

- 内容、登录、云盘、社区、挑战、工具箱、格式转换等功能 **全部复用网站**，
  客户端只是套壳 + 自绘外壳，不重复实现业务。
- 安卓（Jetpack Compose）、iOS（SwiftUI）、桌面（Electron）三端共用同一套 `/api/v1`。
