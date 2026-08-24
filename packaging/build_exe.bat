@echo off
chcp 65001 >nul
rem 在 Windows 上一键打包 IMMA2-QC.exe
rem 用法：双击运行，或在命令行执行 packaging\build_exe.bat
cd /d "%~dp0.."
set "LOG=%CD%\build_log.txt"
echo 工作目录：%CD%
echo 详细日志：%LOG%
echo ==== build started ==== > "%LOG%"

where python >nul 2>nul
if errorlevel 1 (
    echo [错误] 未找到 python 命令。请安装 Python 3.11 或 3.12，并勾选 "Add Python to PATH"。
    goto :error
)
echo --- python info --- >> "%LOG%"
python --version >> "%LOG%" 2>&1
python --version
python -c "import sys; print(sys.executable)" >> "%LOG%" 2>&1

echo.
echo === 第 1 步 / 共 3 步：安装依赖（可能需要几分钟，请耐心等待）===
echo --- pip install --- >> "%LOG%"
python -m pip install -r requirements.txt pyinstaller pillow >> "%LOG%" 2>&1
if errorlevel 1 (
    echo [错误] 依赖安装失败。常见原因：
    echo   1. Python 版本过新或过旧（推荐 3.11 / 3.12）；
    echo   2. 网络问题。可先执行以下命令换国内镜像源后重试：
    echo      python -m pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
    goto :error
)

echo.
echo === 第 2 步 / 共 3 步：打包（同样需要几分钟）===
if exist "packaging\icon_source.png" python packaging\make_icon.py >> "%LOG%" 2>&1
echo --- pyinstaller --- >> "%LOG%"
python -m PyInstaller --clean --noconfirm packaging\IMMA2-QC.spec >> "%LOG%" 2>&1
if errorlevel 1 goto :error

if not exist "dist\IMMA2-QC.exe" (
    echo.
    echo [错误] 打包流程结束，但没有生成 dist\IMMA2-QC.exe。
    echo 最常见原因：杀毒软件/Windows Defender 把刚生成的 exe 当作可疑文件删除了。
    echo 处理方法：打开 Windows 安全中心 → 病毒和威胁防护 → 保护历史记录，
    echo 若看到 IMMA2-QC.exe 被隔离，点“还原”，并把本文件夹加入排除项，然后重新运行本脚本。
    goto :error
)

echo.
echo === 第 3 步 / 共 3 步：自检 ===
"dist\IMMA2-QC.exe" --selfcheck
if errorlevel 1 (
    echo [错误] 自检未通过（资源不完整）。
    goto :error
)

echo.
echo ============================================
echo 打包完成：%CD%\dist\IMMA2-QC.exe
echo ============================================
pause
exit /b 0

:error
echo.
echo -------- 日志最后 30 行 --------
powershell -NoProfile -Command "Get-Content -LiteralPath '%LOG%' -Tail 30" 2>nul
echo --------------------------------
echo 打包失败。请把上面的内容（或整个 build_log.txt 文件）发给开发者。
pause
exit /b 1
