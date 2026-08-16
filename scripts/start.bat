@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0\.."

echo ============================================
echo   nnkBiliDown - Bilibili 视频下载器
echo ============================================
echo.

rem 优先使用 py 启动器（python.org 安装包通常自带），其次尝试 python
set "PYCMD="
py -3 -c "import sys" >nul 2>nul
if not errorlevel 1 set "PYCMD=py -3"

if not defined PYCMD (
    python -c "import sys" >nul 2>nul
    if not errorlevel 1 set "PYCMD=python"
)

if not defined PYCMD (
    echo [错误] 没有找到可用的 Python！
    echo.
    echo 请到 https://www.python.org/downloads/ 安装 Python 3.10 或更高版本。
    echo 安装时务必勾选 "Add python.exe to PATH"，安装完成后重新打开本脚本。
    echo.
    echo 如果你已经安装过 Python，可以尝试在项目目录手动运行：
    echo     py -3 start.py
    echo 或
    echo     python start.py
    echo.
    pause
    exit /b 1
)

%PYCMD% -c "import sys; print('[信息] Python ' + sys.version.split()[0] + ' -> ' + sys.executable)"
if errorlevel 1 (
    echo [错误] Python 启动失败，请尝试重新安装 Python 3.10+
    pause
    exit /b 1
)

echo [信息] 正在准备环境并启动服务...
%PYCMD% start.py %*
if errorlevel 1 (
    echo.
    echo [错误] 启动失败，请查看上方错误信息。
    pause
)

endlocal
pause
