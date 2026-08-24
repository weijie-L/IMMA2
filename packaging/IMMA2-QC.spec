# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：单文件图形界面程序。

用法（在仓库根目录）：
    pyinstaller --clean --noconfirm packaging/IMMA2-QC.spec
产物：dist/IMMA2-QC.exe（Windows）或 dist/IMMA2-QC（Linux/macOS）
"""
import os

ROOT = os.path.abspath(os.path.join(SPECPATH, os.pardir))

a = Analysis(
    [os.path.join(ROOT, "run_app.py")],
    pathex=[ROOT],
    binaries=[],
    # 内置国界底图随 exe 打包，路径与源码布局一致，basemap.py 无需改动
    datas=[(os.path.join(ROOT, "imma2_qc", "assets", "basemap"),
            os.path.join("imma2_qc", "assets", "basemap"))],
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
)
