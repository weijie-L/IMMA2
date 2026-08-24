@echo off
chcp 65001 >nul
rem 在 Windows 上一键打包 IMMA2-QC.exe
rem 用法：双击运行，或在命令行执行 packaging\build_exe.bat
cd /d "%~dp0.."
echo 工作目录：%CD%

where python >nul 2>nul
if errorlevel 1 (
    echo [错误] 未找到 python 命令。请安装 Python 3.10+ 并勾选 "Add Python to PATH"。
    goto :error
)
python --version

echo.
echo === 第 1 步 / 共 3 步：安装依赖 ===
python -m pip install -r requirements.txt pyinstaller
if errorlevel 1 (
    echo [错误] 依赖安装失败。若提示找不到 PySide6 的版本，
    echo 多半是 Python 版本过新（如 3.14），请改装 Python 3.11 或 3.12。
    goto :error
)

echo.
echo === 第 2 步 / 共 3 步：打包 ===
python -m PyInstaller --clean --noconfirm packaging\IMMA2-QC.spec
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
echo 打包失败。请把本窗口中的报错信息（截图或复制文字）发给开发者。
pause
exit /b 1
