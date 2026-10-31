# 教学管理系统 App（安卓 · Jetpack Compose 原生版）

把 **https://your-server.example.com**（教学管理系统）做成安卓原生 App，界面用 Jetpack Compose 手写，数据对接网站真实接口（`/api/v1/...`），**不是**打开网页的 WebView 壳。

## 实时预览（重点）

在 **Android Studio** 里打开 `android/` 目录后：

1. 左侧打开任意界面代码，例如 `app/src/main/java/com/teachingsystem/web/ui/screens/HomeScreen.kt`
2. 找到文件底部的 `@Preview` 函数，点它左上角的「预览」按钮
3. **右边立即渲染出界面**，改代码（文字/颜色/布局）保存后实时刷新 —— 和小程序开发者工具一个体验

> 注意：Compose 的实时预览需要 **Android Studio**（IntelliJ IDEA 社区版不支持 Compose 预览）。

## 功能页面

| 页面 | 接口 | 说明 |
|---|---|---|
| 首页 | `GET /api/v1/home` | Hero + 磁贴导航 + 招新统计 |
| 课程 | `GET /api/v1/courses` | 课程列表 + 搜索 |
| 课程详情 | `GET /api/v1/courses/{id}` | 简介 + 课件资料 |
| 文件中心 | `GET /api/v1/files` | 文件列表 |
| 登录 | `POST /api/v1/login` | 账号密码登录 |
| 注册 | `POST /api/v1/register` | 新用户注册 |
| 我的 | `GET /api/v1/me` | 个人中心 + 激活码 + 退出 |
| 报名 | `POST /api/v1/join` | 招新报名表 |
| 报到登记 | `GET/POST /api/v1/report` | 新生报到申请 + 状态查询 |
| 在线更新 | `GET /api/v1/app/version` | 启动自动检查新版本 |

登录态用 Bearer token（本地存储），与网站/小程序同一套后端。

## 在线更新（OTA）

App 启动时会自动请求 `/api/v1/app/version`，比对本地 `versionCode`：

- 发现新版本 → 弹窗提示（版本号 + 更新说明）→ 点「立即更新」下载 APK（带进度条）→ 调起系统安装器一键覆盖安装
- 无新版本 → 静默跳过；也可在「我的 → 检查更新」手动触发

管理员在网站后台「版本管理」页上传新 APK + 填版本号/更新说明即可发布新版本。**版本号（versionCode）必须大于上一版**，客户端才会提示更新。

> 首次使用：`versionCode=2`（v1.1）是第一个带更新能力的版本，需手动安装一次；之后发布的 v3、v4… 手机上旧版 App 就会自动检测并一键更新。

## 构建 / 安装

命令行一键构建（需 JDK17，工程已配好国内镜像）：

```bash
cd android && ./build_android.sh
```

产出：`android/app/build/outputs/apk/debug/app-debug.apk`，传到安卓手机安装即可。

## 技术栈

- Kotlin 2.0.21 + Jetpack Compose（Material3）
- Gradle 8.10.2 + AGP 8.7.3 + JDK 17
- 网络：OkHttp；图片：Coil；解析：org.json；导航：navigation-compose
- minSdk 24（Android 7.0+），targetSdk 34
- 包名 `com.teachingsystem.web`，应用名「教学管理系统」

## 目录结构

```
android/app/src/main/java/com/teachingsystem/web/
├── MainActivity.kt          # 入口
├── data/                    # 数据层
│   ├── Api.kt               # OkHttp 封装 + 首页数据模型
│   ├── Session.kt           # 登录态全局状态
│   └── Updater.kt           # 版本检查 / APK 下载 / 安装
└── ui/
    ├── App.kt               # 底部导航 + 路由
    ├── Common.kt            # 通用顶栏 / Toast
    ├── UpdateDialog.kt      # 更新弹窗（发现新版本 / 下载进度）
    ├── theme/Theme.kt       # 主题色（主色 #1F4E79，与网站一致）
    └── screens/             # 各页面
        ├── HomeScreen.kt    # 首页（含 @Preview）
        ├── AuthScreens.kt   # 登录 / 注册
        ├── MeScreen.kt      # 我的
        ├── ReportScreen.kt  # 报到登记
        └── ContentScreens.kt# 课程 / 详情 / 文件 / 报名 / 协议
```
