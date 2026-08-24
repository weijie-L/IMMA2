"""基础字段检查与特殊站号处理。

在原 DataFrame 上添加解析列：
  _DT      解析后的时间
  _LAT     纬度 float
  _LON     经度 float，统一 [0, 360)
  _VALUE   观测值 float
  _VS      航速档 int（无效为 -1）
  _YEAR    年份 int
并将无效记录写入 QC_FLAG。
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

from .. import flags
from ..config import MISSING_TOKENS, VS_SPEED_UPPER_KMH, QCConfig

DT_COL = "_DT"
LAT_COL = "_LAT"
LON_COL = "_LON"
VALUE_COL = "_VALUE"
VS_COL = "_VS"
YEAR_COL = "_YEAR"
QC_FLAG_COL = "QC_FLAG"
REVIEW_COL = "REVIEW_FLAGS"


def _clean_series(s: pd.Series) -> pd.Series:
    """strip 后把缺失标记统一替换为空字符串。"""
    s = s.fillna("").astype(str).str.strip()
    upper = s.str.upper()
    return s.mask(upper.isin(MISSING_TOKENS), "")


def _to_numeric(s: pd.Series) -> pd.Series:
    return pd.to_numeric(_clean_series(s).replace("", np.nan), errors="coerce")


def check_basic(df: pd.DataFrame, cfg: QCConfig) -> pd.DataFrame:
    """执行基础字段检查，返回添加了解析列与 QC_FLAG 的 DataFrame（副本）。"""
    df = df.copy()
    df[QC_FLAG_COL] = ""
    df[REVIEW_COL] = ""

    required = [cfg.station_col, cfg.date_col, cfg.lat_col, cfg.lon_col, cfg.value_col]
    if cfg.require_quality_col:
        required.append(cfg.quality_col)
    if cfg.require_vs_col:
        required.append(cfg.vs_col)
    missing_cols = [c for c in required if c not in df.columns]
    if missing_cols:
        raise ValueError(f"输入数据缺少必要字段: {missing_cols}")

    station = _clean_series(df[cfg.station_col])
    pat = re.compile(cfg.station_pattern)
    station_ok = station.map(lambda s: bool(s) and bool(pat.match(s)))

    dt = pd.to_datetime(_clean_series(df[cfg.date_col]).replace("", np.nan),
                        errors="coerce", format="mixed")

    lat = _to_numeric(df[cfg.lat_col])
    lon = _to_numeric(df[cfg.lon_col])
    # 经度 [-180, 0) 自动转换到 [180, 360)
    lon = lon.where(lon >= 0.0, lon + 360.0)
    lat_ok = lat.notna() & (lat >= -90.0) & (lat <= 90.0)
    lon_ok = lon.notna() & (lon >= 0.0) & (lon < 360.0)

    value = _to_numeric(df[cfg.value_col])
    value_ok = value.notna() & np.isfinite(value) \
        & (value >= cfg.value_min) & (value <= cfg.value_max)

    ok = station_ok & dt.notna() & lat_ok & lon_ok & value_ok

    if cfg.require_quality_col:
        q = _to_numeric(df[cfg.quality_col])
        ok &= q.notna()
    if cfg.require_vs_col:
        vs = _to_numeric(df[cfg.vs_col])
        vs_ok = vs.notna() & vs.isin(list(VS_SPEED_UPPER_KMH.keys()))
        ok &= vs_ok
        df[VS_COL] = vs.where(vs_ok, -1).astype(int)
    else:
        df[VS_COL] = -1

    df[DT_COL] = dt
    df[LAT_COL] = lat
    df[LON_COL] = lon
    df[VALUE_COL] = value
    df[YEAR_COL] = dt.dt.year.fillna(-1).astype(int)
    df["_STATION"] = station

    df.loc[~ok, QC_FLAG_COL] = flags.DELETE_INVALID_BASIC_FIELD

    # ---- 特殊站号 ----
    is_ship = station.str.upper() == "SHIP"
    if cfg.drop_ship:
        df.loc[is_ship & (df[QC_FLAG_COL] == ""), QC_FLAG_COL] = flags.DELETE_SHIP
    is_mask = station.str.upper() == "MASKSTID"
    if cfg.maskstid_policy == "drop":
        df.loc[is_mask & (df[QC_FLAG_COL] == ""), QC_FLAG_COL] = flags.DELETE_MASKSTID
    df["_IS_MASKSTID"] = is_mask

    return df


def add_review(df: pd.DataFrame, idx, flag: str) -> None:
    """把 review 标记追加到 REVIEW_FLAGS 列（分号分隔，去重）。idx 为索引标签的可迭代对象。"""
    for i in idx:
        cur = df.at[i, REVIEW_COL]
        parts = [p for p in str(cur).split(";") if p]
        if flag not in parts:
            parts.append(flag)
        df.at[i, REVIEW_COL] = ";".join(parts)
