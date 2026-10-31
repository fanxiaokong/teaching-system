# 安卓端源码恢复 + v1.26 逆向工程差距报告

> 生成时间：2026-10-18 ｜ 操作人：WorkBuddy
> 背景：用户反馈「本地安卓源代码没了」。经核查，源码并未真正丢失，而是以
> `teaching-system-android-source.zip` 的形式躺在 `_archives/` 里。本报告记录恢复过程，
> 并基于对**生产环境最新 APK（v1.26）**的反编译，给出与本地 v1.9 源码的差距分析。

---

## 0. 结论速览

| 项 | 结果 |
|---|---|
| 本地安卓源码 | ✅ 已恢复（来自 `_archives/teaching-system-android-source.zip`，完整 Gradle/Kotlin 工程） |
| 恢复位置 | 仓库根 `android/`（扁平结构，已纳入 git） |
| 生产最新版本 | `v1.26`（versionCode=27） |
| 本地源码版本 | `v1.9`（versionCode=10）→ **落后 17 个版本** |
| 逆向工具 | `jadx 1.5.6`（反编译 v1.26 APK → `/tmp/apk_out`，已归档到 `android/reference-v1.26/`） |
| 安全隐患 | ⚠️ 生产 v1.26 APK `android:debuggable="true"`（发的是 debug 包，建议改 release 构建） |
| 包名 / 域名 | `com.teachingsystem.web` ／ `https://your-server.example.com`（与本地一致） |

---

## 1. 源码恢复

- 来源：`_archives/teaching-system-android-source.zip`（含完整 `android/` 工程：Gradle 8.10.2 wrapper、
  `app/build.gradle.kts`、全部 `ui/screens/*.kt`、资源、`build_android.sh/.bat`、`gradle.properties`）。
- 工程自带 Gradle 发行版（~145MB），但**不进 git**（已在 `.gitignore` 排除 `android/gradle/gradle-*/`），
  构建时 `build_android.sh` 会自动回退到 Gradle wrapper 下载。
- 同时把工程文档（`README.md`、`开发迭代指南.md`、`gen_icon.py`、`icon-1024.png`）一并归入 `android/`。
- 注：zip 内存在一个冗余的嵌套 `android/android/`（146MB 重复副本），已清理，仅保留扁平 `android/`。

## 2. 生产 v1.26 逆向所得（jadx 反编译）

### 2.1 基本事实（来自 `AndroidManifest.xml`）
- `versionCode = 27`，`versionName = "1.26"`，`package = com.teachingsystem.web`
- `compileSdk = 34`，`minSdk = 24`，`targetSdk = 34`
- `android:debuggable = "true"` ⚠️（生产包不应可调试，见 §4）
- 权限：INTERNET / REQUEST_INSTALL_PACKAGES / CAMERA / ACCESS_WIFI_STATE / ACCESS_NETWORK_STATE
- `usesCleartextTraffic = false`（已禁明文，符合预期）

### 2.2 生产 APK 包含、但本地 v1.9 源码**缺失**的组件

| 组件（反编译文件） | 含义 | 对应后端功能 |
|---|---|---|
| `ui/AnnouncementDialogKt.java` + `ui/AnnouncementInfo.java` | **公告弹窗**（字段 id/title/body/level/linkText/linkUrl/updatedAt） | 管理端公告弹窗（已上线） |
| `ui/screens/CancelAccountScreenKt.java` | **注销账号** | 三端注销（已上线） |
| `ui/screens/ChangePasswordScreenKt.java` | **修改密码** | 改密（验原密码） |
| `ui/screens/ForgotPasswordScreenKt.java` | **找回密码** | 找回密码流程 |
| `ui/screens/VideoPlayerScreenKt.java` | **视频播放器**（独立播放页） | 视频解码修复 |
| `ui/screens/WebScreenKt.java` | **WebView 容器页** | 协议/外链/网页登录 |
| `data/CourseApi.java` + `CourseItem/CourseDetail/CourseCache/VideoItem` | **课程/视频数据层（带缓存）** | 课程体系 |
| `ui/screens/CourseScreensKt.java` | 课程列表/详情页 | 课程体系 |
| `ui/UpdateCenter.java` | **更新中心** | 版本管理 |
| `data/Session.java`（含 `logout()`） | 登录态管理（独立 Session 类，v1.9 只有 AuthStore） | — |

### 2.3 生产 APK 实际调用的接口（已从反编译确认）

```
GET  /api/v1/app/version            # 更新检查（version_code 字段）
GET  /api/v1/courses                # 课程列表（?category= 可筛选）
GET  /api/v1/courses/{id}           # 课程详情
GET  /api/v1/videos/{id}/stream?token=    # 视频流
GET  /api/v1/videos/{id}/subtitle?token=  # 字幕
GET  /api/v1/files/{id}/download?token=   # 文件下载
GET  /api/v1/web-login?token=&next=       # WebView 网页登录态桥接
POST /api/v1/scan/confirm           # 扫码确认
```

本地 v1.9 源码的 `Api.kt` 仅有 `/api/v1/home` 与 `/api/v1/app/version`，**以上课程/视频/文件/网页登录/扫码/注销/改密/找回密码/公告接口全部缺失**。

---

## 3. 差距清单（v1.9 源码 → v1.26 需补齐）

1. **数据层**：新增 `CourseApi` + `CourseCache`，`data` 包新增 `CourseItem/CourseDetail/VideoItem/ResourceItem`，
   及独立的 `Session` 类（取代/补充 `AuthStore`）。
2. **路由与页面**：`ui/AppKt` 的 `Routes` 与 `NavHost` 需新增 `announcement`(弹窗宿主)、
   `cancel`(注销)、`changePassword`(改密)、`forgotPassword`(找回密码)、`video`(播放器)、`web`(WebView)、
   `courses`/`courseDetail`(课程) 等路由。
3. **新页面文件**：从 `reference-v1.26/` 反向参考并重写为 Kotlin：
   `ui/AnnouncementDialog.kt`、`ui/screens/CancelAccountScreen.kt`、`ui/screens/ChangePasswordScreen.kt`、
   `ui/screens/ForgotPasswordScreen.kt`、`ui/screens/VideoPlayerScreen.kt`、`ui/screens/WebScreen.kt`、
   `ui/screens/CourseScreens.kt`、`ui/UpdateCenter.kt`。
4. **包名/域名一致**，无需改；`BASE_URL` 仍为 `https://your-server.example.com`。

---

## 4. 安全问题（建议修复）

- ⚠️ **生产 v1.26 是 debug 构建**（`debuggable=true`）。debug 包可被附加调试器、提取数据，且无法上架主流商店。
  修复：`app/build.gradle.kts` 的 `release` 构建开启 `isMinifyEnabled = true` 并去掉 debug 属性，
  改用 `./gradlew assembleRelease` 出包（详见《开发迭代指南》§5）。当前 `build_android.sh` 用的是 `assembleDebug`。
- 其余（禁明文流量、权限最小化、FileProvider 授权）生产已合规。

---

## 5. 下一步（需 Android Studio 环境，本机无 Android SDK，暂未构建验证）

> 本机仅有 JDK 24，缺 Android SDK，**无法在此实际编译/出包**。以下为落地步骤，待有 Android Studio 的机器执行：

1. 用 Android Studio 打开 `android/` 内层目录，首次同步（已配国内镜像）。
2. 参考 `android/reference-v1.26/`（v1.26 反编译源码）把 §3 列出的数据层/页面重写回 Kotlin 工程。
3. 确认 `versionCode/versionName`：本地恢复的是 v1.9（10），生产是 v1.26（27）。
   合并完功能后再把版本号升到 ≥27 发版（**未合并完前不要升到 27**，否则会误导更新网关）。
4. 出 release 包（去掉 debuggable），在「管理 → 版本管理」发布。

---

## 6. 参考 / 复现

- 恢复源：`_archives/teaching-system-android-source.zip`
- 生产 APK：`_archives/teaching-system-android-v1.26.apk`（已从服务器 `static/app/` 下载）
- 反编译命令：`jadx -d /tmp/apk_out _archives/teaching-system-android-v1.26.apk`
- 反编译产物（已归入版本库）：`android/reference-v1.26/`
