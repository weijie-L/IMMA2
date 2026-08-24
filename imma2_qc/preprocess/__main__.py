"""预处理命令行模式：

  python -m imma2_qc.preprocess --stages extract,normalize,fill \
      --raw-dir <原始IMMA1目录> --extract-dir <提取输出> --clean-dir <清洗输出>

不带目录参数时使用界面里保存的目录设置（~/.imma2_qc/settings.json）。
"""
from __future__ import annotations

import argparse

from ..paths import load_paths
from .extract import extract_raw
from .fill_speed import fill_fixed_stations, fill_moving_stations
from .normalize import normalize_dir


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="IMMA2 数据预处理（命令行模式）")
    ap.add_argument("--stages", default="extract,normalize,fill",
                    help="逗号分隔：extract,normalize,fill")
    ap.add_argument("--raw-dir")
    ap.add_argument("--extract-dir")
    ap.add_argument("--clean-dir")
    ap.add_argument("--start-year", type=int)
    ap.add_argument("--end-year", type=int)
    ap.add_argument("--overwrite", action="store_true",
                    help="覆盖已存在的提取/规整输出文件")
    args = ap.parse_args(argv)

    saved = load_paths()
    raw_dir = args.raw_dir or saved.raw_dir
    extract_dir = args.extract_dir or saved.extract_dir
    clean_dir = args.clean_dir or saved.clean_dir

    stages = [s.strip() for s in args.stages.split(",") if s.strip()]
    for stage in stages:
        if stage == "extract":
            if not raw_dir or not extract_dir:
                ap.error("extract 需要 --raw-dir 和 --extract-dir（或先在界面中设置）")
            extract_raw(raw_dir, extract_dir, args.start_year, args.end_year,
                        overwrite=args.overwrite)
        elif stage == "normalize":
            if not extract_dir or not clean_dir:
                ap.error("normalize 需要 --extract-dir 和 --clean-dir")
            normalize_dir(extract_dir, clean_dir, overwrite=args.overwrite)
        elif stage == "fill":
            if not clean_dir:
                ap.error("fill 需要 --clean-dir")
            fill_moving_stations(clean_dir)
            fill_fixed_stations(clean_dir)
        else:
            ap.error(f"未知步骤：{stage}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
