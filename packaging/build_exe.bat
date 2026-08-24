@echo off
rem 在 Windows 上一键打包 IMMA2-QC.exe
rem 用法：在仓库根目录双击运行，或在命令行执行 packaging\build_exe.bat
cd /d "%~dp0.."

echo === 安装依赖 ===
pip install -r requirements.txt pyinstaller || goto :error

echo === 打包 ===
pyinstaller --clean --noconfirm packaging\IMMA2-QC.spec || goto :error

echo === 自检 ===
dist\IMMA2-QC.exe --selfcheck
if errorlevel 1 goto :error

echo.
echo 打包完成：dist\IMMA2-QC.exe
pause
exit /b 0

:error
echo.
echo 打包失败，请把上面的报错信息发给开发者。
pause
exit /b 1
