"""数据读入：扫描月度 CSV、拼接、生成稳定记录标识 UID。

输入文件始终只读，程序不修改原始 CSV。
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd

from .config import QCConfig

SOURCE_FILE_COL = "_SOURCE_FILE"
SOURCE_ROW_COL = "_SOURCE_ROW"
UID_COL = "_UID"


def find_data_files(input_dir: str | Path) -> list[Path]:
    """扫描目录下的 CSV 数据文件（跳过 _ 开头的审计/输出目录与文件）。"""
    input_dir = Path(input_dir)
    files = []
    for p in sorted(input_dir.rglob("*.csv")):
        if any(part.startswith("_") for part in p.relative_to(input_dir).parts):
            continue
        files.append(p)
    return files


def load_files(paths: list[Path], cfg: QCConfig) -> pd.DataFrame:
    """读取并拼接 CSV。所有列按字符串读入，保留原始值用于导出。"""
    frames = []
    for p in paths:
        df = pd.read_csv(p, dtype=str, keep_default_na=False, low_memory=False)
        df[SOURCE_FILE_COL] = p.name
        df[SOURCE_ROW_COL] = df.index.astype(int)
        frames.append(df)
    if not frames:
        raise ValueError("未找到任何 CSV 数据文件")
    out = pd.concat(frames, ignore_index=True)
    out[UID_COL] = compute_uids(out, cfg)
    return out


def compute_uids(df: pd.DataFrame, cfg: QCConfig) -> pd.Series:
    """UID = sha1(站号|日期|纬度|经度|观测值|来源文件|行号) 前 16 位。

    只要输入文件内容不变，UID 稳定，可用于持久化人工决定。
    """
    def col(name: str) -> pd.Series:
        if name in df.columns:
            return df[name].astype(str)
        return pd.Series([""] * len(df), index=df.index)

    joined = (
        col(cfg.station_col) + "|" + col(cfg.date_col) + "|" + col(cfg.lat_col)
        + "|" + col(cfg.lon_col) + "|" + col(cfg.value_col)
        + "|" + col(SOURCE_FILE_COL) + "|" + col(SOURCE_ROW_COL)
    )
    return joined.map(lambda s: hashlib.sha1(s.encode("utf-8")).hexdigest()[:16])
