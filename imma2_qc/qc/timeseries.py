"""观测值时间序列检查：尖峰（spike）与台阶突变（step）。

均为低置信检查：只标记 REVIEW_FLAGS，不自动删除，由人工在界面中复核。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .. import flags
from ..config import QCConfig
from .basic import DT_COL, QC_FLAG_COL, VALUE_COL, add_review


def check_series_spikes(df: pd.DataFrame, cfg: QCConfig) -> None:
    """滑动中位数 + MAD 尖峰检测（按站点分组，含 MASKSTID）。"""
    win = max(3, cfg.series_spike_window | 1)  # 强制奇数且 >= 3
    active = df[df[QC_FLAG_COL] == ""]
    for _station, g in active.groupby("_STATION", sort=False):
        if len(g) < win:
            continue
        g = g.sort_values(DT_COL, kind="mergesort")
        v = g[VALUE_COL].astype(float)
        med = v.rolling(win, center=True, min_periods=2).median()
        resid = (v - med).abs()
        mad = resid.rolling(win, center=True, min_periods=2).median()
        thresh = np.maximum(cfg.series_spike_mad_factor * 1.4826 * mad,
                            cfg.series_spike_min_abs)
        hit = resid > thresh
        if hit.any():
            add_review(df, list(g.index[hit]), flags.SERIES_SPIKE)


def check_series_steps(df: pd.DataFrame, cfg: QCConfig) -> None:
    """台阶突变：前后窗口均值差超过阈值且残差稳定时，标记突变点。"""
    half = max(2, cfg.series_step_halfwin)
    active = df[df[QC_FLAG_COL] == ""]
    for _station, g in active.groupby("_STATION", sort=False):
        if len(g) < 2 * half + 1:
            continue
        g = g.sort_values(DT_COL, kind="mergesort")
        v = g[VALUE_COL].astype(float).to_numpy()
        hits = []
        for k in range(half, len(v) - half):
            before = v[k - half:k]
            after = v[k:k + half]
            jump = abs(after.mean() - before.mean())
            spread = max(before.std(), after.std())
            if jump >= cfg.series_step_threshold and jump > 3.0 * max(spread, 1e-9):
                hits.append(g.index[k])
        if hits:
            add_review(df, hits, flags.SERIES_STEP)
