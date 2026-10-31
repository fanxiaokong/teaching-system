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
