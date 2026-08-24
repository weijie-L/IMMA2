"""质控流水线编排。

处理顺序（对应文档流程的子集，连续异常段整段修复暂未纳入）：
  1. 基础字段检查
  2. 特殊站号处理（SHIP / MASKSTID）
  3. 单点镜像修复建议（只标记，人工采纳后导出时生效；
     带建议的点不参与后续海陆/轨迹检查）
  4. 海陆检查（GSHHG 或内置国界，明确陆地内部点删除）
  5. 同站同刻位置冲突
  6. 三点单点漂移（正反双向扫描收敛）
  7. 特殊零坐标复核标记
  8. 观测值时间序列尖峰 / 台阶（复核标记）
  9. 严格去重
 10. 删除少于 min_records_per_station_year 的“站点—年份”组合

自动删除只写 QC_FLAG，不物理删除记录；人工可在界面中恢复。
"""
from __future__ import annotations

import pandas as pd

from .. import flags
from ..config import QCConfig
from ..io_utils import SOURCE_FILE_COL, SOURCE_ROW_COL, UID_COL
from . import basic, mirror, timeseries, track
from .basic import QC_FLAG_COL, REVIEW_COL, YEAR_COL

INTERNAL_COLS = (
    basic.DT_COL, basic.LAT_COL, basic.LON_COL, basic.VALUE_COL,
    basic.VS_COL, basic.YEAR_COL, "_STATION", "_IS_MASKSTID",
    basic.FIX_TYPE_COL, basic.FIX_LAT_COL, basic.FIX_LON_COL,
)


def run_qc(df: pd.DataFrame, cfg: QCConfig,
           gshhg_dir: str | None = None) -> pd.DataFrame:
    """执行全部自动质控，返回带 QC_FLAG / REVIEW_FLAGS 的 DataFrame。

    gshhg_dir 为 GSHHG shapefile 目录；为空时海陆检查退回内置国界底图。
    """
    df = basic.check_basic(df, cfg)
    mirror.suggest_mirror_fixes(df, cfg)
    _check_deep_land(df, cfg, gshhg_dir)
    track.check_same_time_conflicts(df, cfg)
    track.check_isolated_spikes(df, cfg)
    track.check_zero_coordinates(df, cfg)
    timeseries.check_series_spikes(df, cfg)
    timeseries.check_series_steps(df, cfg)
    _check_strict_duplicates(df, cfg)
    _check_station_year_min(df, cfg)
    return df


def _check_deep_land(df: pd.DataFrame, cfg: QCConfig,
                     gshhg_dir: str | None) -> None:
    """明确陆地内部点标记 DELETE_DEEP_LAND（可在界面中恢复）。"""
    if cfg.skip_land:
        return
    try:
        from ..geo import lon_to_pm180
        from ..landcheck import get_land_checker
        checker = get_land_checker(gshhg_dir, cfg.land_interior_km)
    except ImportError:
        return  # shapely 未安装时静默跳过
    # 带镜像修复建议的点不在原（错误）坐标上做海陆判断
    active = df[(df[QC_FLAG_COL] == "") & (df[basic.FIX_TYPE_COL] == "")]
    if len(active) == 0:
        return
    mask = checker.deep_land_mask(
        lon_to_pm180(active[basic.LON_COL].to_numpy(float)),
        active[basic.LAT_COL].to_numpy(float))
    df.loc[active.index[mask], QC_FLAG_COL] = flags.DELETE_DEEP_LAND


def _check_strict_duplicates(df: pd.DataFrame, cfg: QCConfig) -> None:
    """按输入全部业务字段严格去重（保留首条）。"""
    business_cols = [c for c in df.columns
                     if c not in INTERNAL_COLS
                     and c not in (QC_FLAG_COL, REVIEW_COL,
                                   SOURCE_FILE_COL, SOURCE_ROW_COL, UID_COL)]
    active = df[df[QC_FLAG_COL] == ""]
    dup = active.duplicated(subset=business_cols, keep="first")
    df.loc[active.index[dup], QC_FLAG_COL] = flags.DELETE_STRICT_DUPLICATE


def _check_station_year_min(df: pd.DataFrame, cfg: QCConfig) -> None:
    active = df[df[QC_FLAG_COL] == ""]
    counts = active.groupby(["_STATION", YEAR_COL]).size()
    small = counts[counts < cfg.min_records_per_station_year].index
    if len(small) == 0:
        return
    key = pd.MultiIndex.from_frame(active[["_STATION", YEAR_COL]])
    mask = key.isin(small)
    df.loc[active.index[mask], QC_FLAG_COL] = flags.DELETE_STATION_YEAR_LT_MIN


def summarize(df: pd.DataFrame) -> pd.DataFrame:
    """按年份统计输入 / 保留 / 各类删除 / 复核数量。"""
    rows = []
    for year, g in df.groupby(YEAR_COL):
        row = {"YEAR": int(year), "INPUT": len(g),
               "KEPT": int((g[QC_FLAG_COL] == "").sum()),
               "REVIEW": int((g[REVIEW_COL] != "").sum())}
        for f in flags.AUTO_DELETE_FLAGS:
            row[f] = int((g[QC_FLAG_COL] == f).sum())
        rows.append(row)
    return pd.DataFrame(rows).sort_values("YEAR").reset_index(drop=True)
