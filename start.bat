@echo off
rem ==================================================
rem  Deep Agent Search  -  一键启动 (薄封装)
rem  真正的逻辑统一维护在 start.ps1，本文件仅负责转调。
rem  用法: 双击本文件，或在项目根目录执行 start.bat
rem  参数透传给 start.ps1，例如只重建前端：
rem      start.bat -FrontendOnly
rem ==================================================
chcp 65001 >nul
cd /d "%~dp0"

echo ==================================================
echo   Deep Agent Search  -  一键启动 (Docker)
echo ==================================================
echo.
echo 正在调用 start.ps1 ...
echo.

rem %* 把命令行参数原样透传给 PowerShell 脚本（例如 -FrontendOnly）
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" %*
if errorlevel 1 (
    echo.
    echo [错误] 启动脚本执行失败，请查看上方错误信息。
    pause
    exit /b 1
)

exit /b 0
