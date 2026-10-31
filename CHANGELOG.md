# Changelog

本文件记录项目的版本变更，遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 规范，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

> 说明：本仓库为**多端 monorepo**，各端有独立的版本号。下表为首次开源时的各端版本快照。

## [首次开源] - 2026-10-31

### 各端版本

| 端 | 版本 | 说明 |
|----|------|------|
| 服务端 + Web | — | Flask 应用，无独立版本号 |
| 安卓 App | 1.9（versionCode 10） | `applicationId = com.teachingsystem.web` |
| macOS 客户端 | 1.0.10 | Electron，arm64 |
| Windows 客户端 | 1.4.9 | Electron，x64（NSIS + portable） |

### 本次发布内容

- 将服务端 + Web、安卓 App、macOS/Windows 桌面客户端完整开源。
- 补充 README、LICENSE（MIT）、CONTRIBUTING、CHANGELOG 与 `docs/` 文档。
- 全量脱敏：移除硬编码数据库密码、服务器 IP、生产域名、个人邮箱/手机号，统一替换为占位符。
- 移除旧版快照、反编译代码、内部交付报告等非开源产物。
- 二次去品牌：将代码中残留的 `LinkCoffee` / `LinkCoffee-Lab` 产品品牌名（下载文件名、Gradle 工程名、更新器与发布脚本、文档）统一替换为 `teaching-system`，与各端已设置的 `com.teachingsystem.*` 包名保持一致。

## [一键配置脚本] - 2026-10-31

- 新增跨平台一键配置程序，覆盖 Windows / macOS / Linux：
  - `setup.py`：纯标准库实现，自动建虚拟环境、装依赖、生成 `.env`（随机密钥与管理员密码）、启动 Flask 并打开浏览器；支持 `--no-run` / `--port` / `--reinstall` 等参数。
  - `setup.sh`（macOS/Linux）与 `setup.bat`（Windows）作为各自平台的一键入口。
  - `.env.example`：服务端配置模板（数据库后端、管理员、密钥等）。
  - `server/run.sh` 增加加载项目根目录 `.env` 的逻辑，手动重跑也沿用一键生成的配置。
  - README「快速开始」新增「一键配置」小节。

---

## 迭代记录约定

以后每次发版请在本文件顶部追加，格式如下：

```markdown
## [安卓 1.10] - YYYY-MM-DD

### 新增
- ...

### 修复
- ...

### 变更
- ...
```

并在 README 的「迭代指南」里同步更新对应端的版本信息。
