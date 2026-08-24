"""船舶航迹合理性检查。

包含：
  - 同站同刻位置冲突（聚簇 + 前后轨迹可达性判断）
  - 三点单点漂移（高置信孤立尖峰删除）
  - 特殊零坐标复核标记

所有检查按站点分组、按时间排序进行；MASKSTID（keep 策略下）不参与。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .. import flags
from ..config import LOOSE_MAX_SPEED_KMH, VS_SPEED_UPPER_KMH, QCConfig
from ..geo import gc_interpolate, haversine_km
from .basic import (DT_COL, FIX_TYPE_COL, LAT_COL, LON_COL, QC_FLAG_COL,
                    VS_COL, add_review)


def allowed_distance_km(vs_code: int, dt_hours: float, cfg: QCConfig) -> float:
    """最大允许距离 = 目标点航速档上限 × 时间间隔 + 距离缓冲。"""
    speed = VS_SPEED_UPPER_KMH.get(int(vs_code), LOOSE_MAX_SPEED_KMH)
    return speed * dt_hours + cfg.distance_buffer_km


def loose_reachable(dist_km: float, dt_hours: float, cfg: QCConfig) -> bool:
    """45 knot 宽松物理上限，仅用于轨迹连续性/归属判断。"""
    return dist_km <= LOOSE_MAX_SPEED_KMH * dt_hours + cfg.distance_buffer_km


def _station_groups(df: pd.DataFrame):
    """遍历参与轨迹检查的站点分组（排除已删除、MASKSTID 与带修复建议的点）。"""
    active = df[(df[QC_FLAG_COL] == "") & (~df["_IS_MASKSTID"])]
    if FIX_TYPE_COL in df.columns:
        active = active[active[FIX_TYPE_COL] == ""]
    for station, g in active.groupby("_STATION", sort=False):
        yield station, g.sort_values(DT_COL, kind="mergesort")


def check_same_time_conflicts(df: pd.DataFrame, cfg: QCConfig) -> None:
    """同站同刻位置冲突。

    1. 同刻位置按 same_time_cluster_km 聚簇；
    2. 簇间最大距离超过 same_time_conflict_km 视为远距离冲突；
    3. 只有一个簇能与最近前后时刻正常连接时，删除其他簇；
    4. 无法唯一判断时全部保留并标记 SAME_TIME_DISTANT_POSITIONS。
    """
    for _station, g in _station_groups(df):
        times = g[DT_COL]
        dup_times = times[times.duplicated(keep=False)].unique()
        if len(dup_times) == 0:
            continue
        for t in dup_times:
            rows = g[g[DT_COL] == t]
            clusters = _cluster_positions(rows, cfg.same_time_cluster_km)
            if len(clusters) < 2:
                continue
            centers = [(np.mean([df.at[i, LAT_COL] for i in c]),
                        np.mean([df.at[i, LON_COL] for i in c])) for c in clusters]
            max_sep = max(
                haversine_km(centers[a][0], centers[a][1], centers[b][0], centers[b][1])
                for a in range(len(centers)) for b in range(a + 1, len(centers))
            )
            if max_sep <= cfg.same_time_conflict_km:
                continue

            prev_rows = g[g[DT_COL] < t]
            next_rows = g[g[DT_COL] > t]
            prev = prev_rows.iloc[-1] if len(prev_rows) else None
            nxt = next_rows.iloc[0] if len(next_rows) else None
            if prev is None and nxt is None:
                add_review(df, [i for c in clusters for i in c],
                           flags.SAME_TIME_DISTANT_POSITIONS)
                continue

            reachable = []
            for center in centers:
                ok = True
                if prev is not None:
                    dt_h = (t - prev[DT_COL]).total_seconds() / 3600.0
                    d = float(haversine_km(prev[LAT_COL], prev[LON_COL], center[0], center[1]))
                    ok &= loose_reachable(d, dt_h, cfg)
                if nxt is not None:
                    dt_h = (nxt[DT_COL] - t).total_seconds() / 3600.0
                    d = float(haversine_km(center[0], center[1], nxt[LAT_COL], nxt[LON_COL]))
                    ok &= loose_reachable(d, dt_h, cfg)
                reachable.append(ok)

            if sum(reachable) == 1:
                keep_i = reachable.index(True)
                for ci, c in enumerate(clusters):
                    if ci != keep_i:
                        df.loc[list(c), QC_FLAG_COL] = flags.DELETE_SAME_TIME_OFF_TRAJECTORY
            else:
                add_review(df, [i for c in clusters for i in c],
                           flags.SAME_TIME_DISTANT_POSITIONS)


def _cluster_positions(rows: pd.DataFrame, cluster_km: float) -> list[list]:
    """贪心聚簇：与某簇首成员距离 ≤ cluster_km 即归入该簇。返回索引标签列表的列表。"""
    clusters: list[list] = []
    for i, row in rows.iterrows():
        placed = False
        for c in clusters:
            first = rows.loc[c[0]]
            d = float(haversine_km(first[LAT_COL], first[LON_COL], row[LAT_COL], row[LON_COL]))
            if d <= cluster_km:
                c.append(i)
                placed = True
                break
        if not placed:
            clusters.append([i])
    return clusters


def _is_isolated_spike(df: pd.DataFrame, cfg: QCConfig, ia, ib, ic) -> bool:
    a, b, c = df.loc[ia], df.loc[ib], df.loc[ic]
    # 经度或纬度等于 0 的点不自动删除，交由零坐标检查标记复核
    if b[LAT_COL] == 0.0 or b[LON_COL] == 0.0:
        return False
    dt_ab = (b[DT_COL] - a[DT_COL]).total_seconds() / 3600.0
    dt_bc = (c[DT_COL] - b[DT_COL]).total_seconds() / 3600.0
    dt_ac = (c[DT_COL] - a[DT_COL]).total_seconds() / 3600.0
    d_ab = float(haversine_km(a[LAT_COL], a[LON_COL], b[LAT_COL], b[LON_COL]))
    d_bc = float(haversine_km(b[LAT_COL], b[LON_COL], c[LAT_COL], c[LON_COL]))
    d_ac = float(haversine_km(a[LAT_COL], a[LON_COL], c[LAT_COL], c[LON_COL]))
    # A→B 用 B 的航速档，B→C 用 C 的航速档
    return (
        d_ab > allowed_distance_km(b[VS_COL], dt_ab, cfg)
        and d_bc > allowed_distance_km(c[VS_COL], dt_bc, cfg)
        and d_ab >= cfg.spike_min_jump_km
        and d_bc >= cfg.spike_min_jump_km
        and d_ac <= cfg.spike_bridge_km
        and d_ac <= allowed_distance_km(c[VS_COL], dt_ac, cfg)
    )


def _spike_sweep(df: pd.DataFrame, cfg: QCConfig, idx: list, reverse: bool) -> bool:
    """单方向扫描一遍，命中即删并继续。返回本轮是否有删除。"""
    changed = False
    k = len(idx) - 2 if reverse else 1
    while 0 < k <= len(idx) - 2:
        if _is_isolated_spike(df, cfg, idx[k - 1], idx[k], idx[k + 1]):
            df.at[idx[k], QC_FLAG_COL] = flags.DELETE_HIGH_CONFIDENCE_ISOLATED_SPIKE
            idx.pop(k)
            changed = True
            if reverse:
                k -= 1
        else:
            k += -1 if reverse else 1
    return changed


def check_isolated_spikes(df: pd.DataFrame, cfg: QCConfig) -> None:
    """三点单点漂移：A→B、B→C 均不可达且跳距 ≥ spike_min_jump_km，
    A→C 可正常连接且距离 ≤ spike_bridge_km 时，删除 B。

    正向、反向交替扫描直至两个方向都不再有删除（消除贪心顺序依赖）。"""
    for _station, g in _station_groups(df):
        idx = list(g.index)
        while len(idx) >= 3:
            changed = _spike_sweep(df, cfg, idx, reverse=False)
            changed |= _spike_sweep(df, cfg, idx, reverse=True)
            if not changed:
                break


def check_interpolated_positions(df: pd.DataFrame, cfg: QCConfig) -> None:
    """内插位置偏差检查（Met Office MarineQC / Atkinson et al. 2013 思路）。

    对每个中间点 B，用前后点 A、C 按时间比例做大圆内插得到“期望位置”，
    满足任一条件即标记复核（不自动删除）：
      a. B 偏离期望位置超过 interp_max_dev_km——捕捉航行途中、
         航速约束管不住的偏航坏点（大时间间隔下允许半径过大）；
      b. B 与前后均不可达且 A→C 可正常连接，但跳距不足以触发
         高置信三点删除（< spike_min_jump_km）——中等幅度的孤立偏差。
    A→C 总跨度超过 interp_max_gap_hours 时内插无意义，跳过。
    """
    if not cfg.interp_check:
        return
    for _station, g in _station_groups(df):
        idx = list(g.index)
        for k in range(1, len(idx) - 1):
            ia, ib, ic = idx[k - 1], idx[k], idx[k + 1]
            a, b, c = df.loc[ia], df.loc[ib], df.loc[ic]
            if b[LAT_COL] == 0.0 or b[LON_COL] == 0.0:
                continue  # 零坐标点由零坐标检查处理
            dt_ab = (b[DT_COL] - a[DT_COL]).total_seconds() / 3600.0
            dt_ac = (c[DT_COL] - a[DT_COL]).total_seconds() / 3600.0
            if dt_ac <= 0 or dt_ac > cfg.interp_max_gap_hours:
                continue
            dt_bc = dt_ac - dt_ab
            d_ab = float(haversine_km(a[LAT_COL], a[LON_COL], b[LAT_COL], b[LON_COL]))
            d_bc = float(haversine_km(b[LAT_COL], b[LON_COL], c[LAT_COL], c[LON_COL]))
            d_ac = float(haversine_km(a[LAT_COL], a[LON_COL], c[LAT_COL], c[LON_COL]))

            exp_lat, exp_lon = gc_interpolate(
                float(a[LAT_COL]), float(a[LON_COL]),
                float(c[LAT_COL]), float(c[LON_COL]), dt_ab / dt_ac)
            deviation = float(haversine_km(b[LAT_COL], b[LON_COL], exp_lat, exp_lon))

            unreachable_bridged = (
                d_ab > allowed_distance_km(b[VS_COL], dt_ab, cfg)
                and d_bc > allowed_distance_km(c[VS_COL], dt_bc, cfg)
                and d_ac <= allowed_distance_km(c[VS_COL], dt_ac, cfg)
            )
            if deviation > cfg.interp_max_dev_km or unreachable_bridged:
                add_review(df, [ib], flags.INTERP_POSITION_DEVIATION)


def check_zero_coordinates(df: pd.DataFrame, cfg: QCConfig) -> None:
    """特殊零坐标：(0,0) 与突跳到 0 后返回，均只标记复核，不自动删除。"""
    active = df[df[QC_FLAG_COL] == ""]
    both_zero = active[(active[LAT_COL] == 0.0) & (active[LON_COL] == 0.0)]
    if len(both_zero):
        add_review(df, list(both_zero.index), flags.COORDINATE_0_0)

    for _station, g in _station_groups(df):
        idx = list(g.index)
        for k in range(1, len(idx) - 1):
            ia, ib, ic = idx[k - 1], idx[k], idx[k + 1]
            a, b, c = df.loc[ia], df.loc[ib], df.loc[ic]
            zero_lat = b[LAT_COL] == 0.0 and a[LAT_COL] != 0.0 and c[LAT_COL] != 0.0
            zero_lon = b[LON_COL] == 0.0 and a[LON_COL] != 0.0 and c[LON_COL] != 0.0
            if not (zero_lat or zero_lon):
                continue
            d_ab = float(haversine_km(a[LAT_COL], a[LON_COL], b[LAT_COL], b[LON_COL]))
            d_bc = float(haversine_km(b[LAT_COL], b[LON_COL], c[LAT_COL], c[LON_COL]))
            d_ac = float(haversine_km(a[LAT_COL], a[LON_COL], c[LAT_COL], c[LON_COL]))
            if d_ab >= cfg.zero_jump_km and d_bc >= cfg.zero_jump_km and d_ac < cfg.zero_jump_km:
                add_review(df, [ib], flags.SUDDEN_ZERO_AND_RETURN)
