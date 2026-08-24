# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：单文件图形界面程序。

用法（在仓库根目录）：
    pyinstaller --clean --noconfirm packaging/IMMA2-QC.spec
产物：dist/IMMA2-QC.exe（Windows）或 dist/IMMA2-QC（Linux/macOS）
"""
import os

ROOT = os.path.abspath(os.path.join(SPECPATH, os.pardir))
# exe 图标：由 packaging/make_icon.py 生成；不存在时不设置
ICON = os.path.join(SPECPATH, "icon.ico")
ICON = ICON if os.path.exists(ICON) else None

a = Analysis(
    [os.path.join(ROOT, "run_app.py")],
    pathex=[ROOT],
    binaries=[],
    # 内置资源（国界底图、窗口图标）随 exe 打包，路径与源码布局一致；
    # 许可与第三方声明随二进制分发（BSD-3 第 2 条要求）
    datas=[(os.path.join(ROOT, "imma2_qc", "assets"),
            os.path.join("imma2_qc", "assets")),
           (os.path.join(ROOT, "LICENSE"), "."),
           (os.path.join(ROOT, "THIRD_PARTY_NOTICES.md"), ".")],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    # 排除用不到的大件，缩小体积、避免冲突
    excludes=["tkinter", "PyQt5", "PyQt6", "IPython", "jupyter",
              "scipy", "pytest", "setuptools"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    name="IMMA2-QC",
    debug=False,
    strip=False,
    upx=False,
    console=False,          # 图形界面程序，不带控制台窗口
    disable_windowed_traceback=False,
    icon=ICON,
)
