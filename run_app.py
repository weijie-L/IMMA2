"""打包入口：python run_app.py 启动界面。

`--selfcheck` 用于验证打包产物：检查内置底图等资源是否正确打入，
打印结果后退出（0 = 正常）。
"""
import sys


def selfcheck() -> int:
    import imma2_qc
    from imma2_qc.gui.basemap import DEFAULT_BASEMAP, load_default_basemap
    lines = load_default_basemap()
    print(f"imma2_qc {imma2_qc.__version__}")
    print(f"basemap: {DEFAULT_BASEMAP}")
    print(f"  exists={DEFAULT_BASEMAP.exists()}  lines={len(lines)}")
    import matplotlib
    import pandas
    import PySide6
    print(f"pandas {pandas.__version__}, matplotlib {matplotlib.__version__}, "
          f"PySide6 {PySide6.__version__}")
    return 0 if lines else 1


if __name__ == "__main__":
    if "--selfcheck" in sys.argv:
        raise SystemExit(selfcheck())
    from imma2_qc.gui.main_window import main
    main()
