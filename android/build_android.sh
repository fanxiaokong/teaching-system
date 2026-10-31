#!/bin/bash
# 一键构建安卓 Debug APK（跨平台：macOS / Linux）
# 优先使用工程自带的 Gradle（android/gradle/gradle-8.10.2，无需联网下载 Gradle）
# 依赖：JDK17 + Android SDK（脚本自动探测常见路径）
set -e
cd "$(dirname "$0")"

echo "==> 1/3 探测 JDK17 ..."
if [ -z "$JAVA_HOME" ] || [ ! -x "$JAVA_HOME/bin/java" ]; then
    for cand in \
        "/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home" \
        "/opt/homebrew/opt/openjdk@17" \
        "/usr/local/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home" \
        "/usr/local/opt/openjdk@17" \
        "/usr/lib/jvm/java-17-openjdk-amd64" \
        "/usr/lib/jvm/java-17-openjdk"; do
        if [ -x "$cand/bin/java" ]; then export JAVA_HOME="$cand"; break; fi
    done
fi
if [ -z "$JAVA_HOME" ] || [ ! -x "$JAVA_HOME/bin/java" ]; then
    echo "❌ 未找到 JDK17。请安装 JDK17（如 Adoptium Temurin）并设置 JAVA_HOME。"
    exit 1
fi
export PATH="$JAVA_HOME/bin:$PATH"
echo "   使用 JDK: $("$JAVA_HOME/bin/java" -version 2>&1 | head -1)"

echo "==> 2/3 探测 Android SDK ..."
if [ -z "$ANDROID_HOME" ] || [ ! -d "$ANDROID_HOME" ]; then
    ANDROID_HOME="$HOME/Library/Android/sdk"
fi
if [ ! -d "$ANDROID_HOME" ]; then
    echo "❌ 未找到 Android SDK。请安装 Android Studio，或设置 ANDROID_HOME。"
    exit 1
fi
export ANDROID_HOME
export ANDROID_SDK_ROOT="$ANDROID_HOME"
echo "sdk.dir=$ANDROID_HOME" > local.properties
echo "   使用 SDK: $ANDROID_HOME"

echo "==> 3/3 构建 assembleDebug ..."
GRADLE="gradle/gradle-8.10.2/bin/gradle"
if [ -x "$GRADLE" ]; then
    "$GRADLE" assembleDebug
else
    echo "   未找到工程自带 Gradle，改用 wrapper（会自动下载 Gradle）..."
    sh ./gradlew assembleDebug
fi

APK=app/build/outputs/apk/debug/app-debug.apk
if [ -f "$APK" ]; then
    echo ""
    echo "✅ 构建成功！APK：$(cd "$(dirname "$APK")" && pwd)/$(basename "$APK")"
    echo "   大小：$(du -h "$APK" | cut -f1)"
else
    echo "❌ 未找到 APK，请检查上方日志。"
    exit 1
fi
