@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
chcp 65001 >nul

echo ==^> 1/3 Detecting JDK 17 ...
if not defined JAVA_HOME (
    for /d %%d in ("C:\Program Files\Eclipse Adoptium\jdk-17*") do if exist "%%d\bin\java.exe" set "JAVA_HOME=%%d"
)
if not defined JAVA_HOME (
    for /d %%d in ("C:\Program Files\Java\jdk-17*") do if exist "%%d\bin\java.exe" set "JAVA_HOME=%%d"
)
if not defined JAVA_HOME (
    echo [ERROR] JDK 17 not found.
    echo         Please install JDK 17 ^(Temurin: https://adoptium.net/^)
    echo         then set JAVA_HOME, e.g.:
    echo         setx JAVA_HOME "C:\Program Files\Eclipse Adoptium\jdk-17.0.13.11-hotspot"
    exit /b 1
)
set "PATH=%JAVA_HOME%\bin;%PATH%"
echo        JDK: %JAVA_HOME%

echo ==^> 2/3 Detecting Android SDK ...
if not defined ANDROID_HOME set "ANDROID_HOME=%LOCALAPPDATA%\Android\Sdk"
if not exist "%ANDROID_HOME%" (
    echo [ERROR] Android SDK not found. Please install Android Studio first.
    exit /b 1
)
set "SDKDIR=%ANDROID_HOME:\=/%"
> local.properties echo sdk.dir=%SDKDIR%
echo        SDK: %ANDROID_HOME%

echo ==^> 3/3 Building assembleDebug ...
if exist "gradle\gradle-8.10.2\bin\gradle.bat" (
    call "gradle\gradle-8.10.2\bin\gradle.bat" assembleDebug
) else (
    echo        Local Gradle not found, falling back to wrapper...
    call gradlew.bat assembleDebug
)

if exist "app\build\outputs\apk\debug\app-debug.apk" (
    echo.
    echo [OK] APK built: app\build\outputs\apk\debug\app-debug.apk
) else (
    echo [ERROR] APK not found. Check the log above.
    exit /b 1
)
endlocal
