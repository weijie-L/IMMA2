"""命令行批处理模式：不打开界面，直接运行自动质控并导出。

示例：
  python -m imma2_qc.cli --input-dir data/stage3 --output-dir data/stage4 \
      --decisions data/stage3/_qc_workspace/manual_decisions.csv
"""
from __future__ import annotations

import argparse
from pathlib import Path

from .config import QCConfig
from .decisions import DecisionStore
from .export import export_results
from .io_utils import find_data_files, load_files
from .qc.engine import run_qc, summarize


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="IMMA2 自动质控（命令行模式）")
    ap.add_argument("--input-dir", required=True)
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--config", help="QCConfig JSON 文件路径")
    ap.add_argument("--decisions", help="人工决定 CSV（界面中保存的 manual_decisions.csv）")
    ap.add_argument("--gshhg-dir", help="GSHHG 目录（缺省用界面保存的设置，"
                                        "都没有时海陆检查用内置国界底图）")
    ap.add_argument("--overwrite", action="store_true", help="允许写入非空输出目录")
    args = ap.parse_args(argv)

    cfg = QCConfig.from_json_file(args.config) if args.config else QCConfig()
    from .paths import load_paths
    gshhg_dir = args.gshhg_dir or load_paths().gshhg_dir or None
    files = find_data_files(args.input_dir)
    if not files:
        ap.error(f"目录中没有 CSV 数据文件: {args.input_dir}")
    print(f"读取 {len(files)} 个文件…")
    df = load_files(files, cfg)
    print(f"共 {len(df)} 条记录，运行自动质控…")
    df = run_qc(df, cfg, gshhg_dir=gshhg_dir)
    print(summarize(df).to_string(index=False))

    decisions = DecisionStore(args.decisions) if args.decisions else DecisionStore()
    out = export_results(df, cfg, decisions, Path(args.output_dir),
                         overwrite=args.overwrite)
    print(f"结果已写入 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
