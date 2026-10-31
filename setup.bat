@echo off
REM 教学管理系统 · Windows 一键配置与启动
REM 用法：
REM   setup.bat           启动（装依赖 + 运行）
REM   setup.bat --no-run  只装依赖与生成配置，不启动
python setup.py %*
if errorlevel 1 (
  echo.
  echo [!] 若提示找不到 python，请改用 py setup.py，或安装 Python 3.10+ 并勾选 "Add python.exe to PATH"
  py setup.py %*
)
