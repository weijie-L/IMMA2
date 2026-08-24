"""单点镜像修复建议。

对与前后点均不可达、而前后点能正常连接的单点 B，依次尝试：
  1. 经度镜像：360 − LON
  2. 纬度镜像：−LAT
  3. 经纬度同时镜像
修复后的坐标必须满足两个条件才给出建议（取第一个满足的镜像类型）：
  a. 与前后点都可达（航速档约束）；
  b. 几乎落在前后点连线上：d(A,B') + d(B',C) − d(A,C) ≤ mirror_fit_max_detour_km。
     条件 b 防止时间间隔大、允许半径大时，真正的坏点碰巧镜像到
     “够得着但不在航线上”的位置被误修。

与原 icoads_qc_v5 不同：本程序**不直接修改坐标**，只写入建议
（_FIX_TYPE / _FIX_LAT / _FIX_LON + 复核标记 MIRROR_FIX_SUGGESTED），
在界面中确认（“采纳所选修复”）后导出时才替换坐标。
带修复建议的点不参与后续的同刻冲突 / 单点漂移 / 海陆检查。
"""
from __future__ import annotations

import numpy as np

from .. import flags
from ..config import QCConfig
from ..geo import haversine_km
from .basic import (DT_COL, FIX_LAT_COL, FIX_LON_COL, FIX_TYPE_COL, LAT_COL,
                    LON_COL, VS_COL, add_review)
from .track import _station_groups, allowed_distance_km


def _mirror_candidates(lat: float, lon: float):
    mirrored_lon = 360.0 - lon
    if mirrored_lon >= 360.0:
        mirrored_lon -= 360.0
    yield flags.FIX_MIRROR_LON, lat, mirrored_lon
    yield flags.FIX_MIRROR_LAT, -lat, lon
    yield flags.FIX_MIRROR_BOTH, -lat, mirrored_lon


def suggest_mirror_fixes(df, cfg: QCConfig) -> None:
    df[FIX_TYPE_COL] = ""
    df[FIX_LAT_COL] = np.nan
    df[FIX_LON_COL] = np.nan
    if not cfg.suggest_mirror_fix:
        return

    for _station, g in _station_groups(df):
        idx = list(g.index)
        for k in range(1, len(idx) - 1):
            ia, ib, ic = idx[k - 1], idx[k], idx[k + 1]
            a, b, c = df.loc[ia], df.loc[ib], df.loc[ic]
            # 零坐标点交给零坐标复核，不做镜像
            if b[LAT_COL] == 0.0 or b[LON_COL] == 0.0:
                continue
            dt_ab = (b[DT_COL] - a[DT_COL]).total_seconds() / 3600.0
            dt_bc = (c[DT_COL] - b[DT_COL]).total_seconds() / 3600.0
            dt_ac = (c[DT_COL] - a[DT_COL]).total_seconds() / 3600.0
            allowed_ab = allowed_distance_km(b[VS_COL], dt_ab, cfg)
            allowed_bc = allowed_distance_km(c[VS_COL], dt_bc, cfg)
            d_ab = float(haversine_km(a[LAT_COL], a[LON_COL], b[LAT_COL], b[LON_COL]))
            d_bc = float(haversine_km(b[LAT_COL], b[LON_COL], c[LAT_COL], c[LON_COL]))
            d_ac = float(haversine_km(a[LAT_COL], a[LON_COL], c[LAT_COL], c[LON_COL]))
            # 条件 1-3：原坐标与前后均不可达，前后点可以正常连接
            if not (d_ab > allowed_ab and d_bc > allowed_bc
                    and d_ac <= allowed_distance_km(c[VS_COL], dt_ac, cfg)):
                continue
            # 条件 4-5：修复后的坐标与前后均可达（依次尝试，取第一个满足的）
            for fix_type, fix_lat, fix_lon in _mirror_candidates(
                    float(b[LAT_COL]), float(b[LON_COL])):
                d1 = float(haversine_km(a[LAT_COL], a[LON_COL], fix_lat, fix_lon))
                d2 = float(haversine_km(fix_lat, fix_lon, c[LAT_COL], c[LON_COL]))
                if (d1 <= allowed_ab and d2 <= allowed_bc
                        and d1 + d2 - d_ac <= cfg.mirror_fit_max_detour_km):
                    df.at[ib, FIX_TYPE_COL] = fix_type
                    df.at[ib, FIX_LAT_COL] = fix_lat
                    df.at[ib, FIX_LON_COL] = fix_lon
                    add_review(df, [ib], flags.MIRROR_FIX_SUGGESTED)
                    break
