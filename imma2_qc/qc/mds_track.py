"""Met Office MDS 航迹检查（移植自 ET-NCMP/MarineQC track_check.py，BSD-3）。

对每条船舶轨迹（按站点、按时间）执行多证据组合判定，一个点被标记
需要同时满足三类证据（比单条规则一票否决更稳）：

  1. 中点偏差：由前后点按时间大圆内插的期望位置，偏离 > 150 km；
  2. 速度证据（thisqc_a）：相邻航段计算速度超过由“模态速度”导出的上限
     （模态速度 ≤8.5 节 → 上限 15 节；否则模态 ×1.25）；
  3. 连续性证据（thisqc_b），任一即可：
     - 与“按报告航速/航向外推的位置”前向、反向偏差均超允许值；
     - 报告航向（DS 码）与计算航向差 > 60°（当前点与前一点都不符）；
     - 报告航速（VS 档中值）与计算速度差 > 10 节；
     - 计算速度超过 40 节。

整条轨迹最多迭代 5 轮，每轮剔除已标记的点后重查。

与原实现的适配差异（原代码使用报文中的精确 vsi/dsi）：
  - 报告航速取 VS 档位区间中值（档 k → (k−0.5)×9.26 km/h，0 档为 0）；
  - 报告航向取 DS 码 ×45°（1=NE…8=N；0=静止、9=不定，均视为缺失）；
  - 少于 3 条的轨迹交由“站点-年份最少记录数”规则处理，此处跳过。

结果按 mds_track_action 配置写复核标记（默认）或自动删除标记。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .. import flags
from ..config import QCConfig
from ..geo import destination_point, gc_interpolate, haversine_km, initial_bearing_deg
from .basic import DS_COL, DT_COL, LAT_COL, LON_COL, QC_FLAG_COL, VS_COL, add_review
from .track import _station_groups

KM_PER_KNOT = 1.852

# 阈值（与 MarineQC 一致，换算为 km/h、km）
MODE_BIN_KMH = 3.0 * KM_PER_KNOT          # 模态速度分箱宽 3 节
MODE_MIN_KMH = 8.5 * KM_PER_KNOT          # 模态速度下限 8.5 节
SLOW_MODE_KMH = 8.51 * KM_PER_KNOT
AMAX_SLOW_KMH = 15.0 * KM_PER_KNOT        # 慢速船速度上限 15 节
DIRECTION_MAX_DIFF_DEG = 60.0
SPEED_MAX_DIFF_KMH = 10.0 * KM_PER_KNOT   # 报告航速与计算速度差上限 10 节
ULTRA_FAST_KMH = 40.0 * KM_PER_KNOT       # 超高速 40 节
MIDPOINT_MAX_DIFF_KM = 150.0
ESTIMATE_TOLERANCE = 1.25                 # 外推位置允许偏差系数
MAX_ITERATIONS = 5

DS_TO_DEG = {1: 45.0, 2: 90.0, 3: 135.0, 4: 180.0,
             5: 225.0, 6: 270.0, 7: 315.0, 8: 360.0}


def _vs_mid_kmh(vs_code: int) -> float | None:
    """VS 档位 → 区间中值（km/h）。缺失/非法返回 None。"""
    if vs_code is None or vs_code < 0:
        return None
    if vs_code == 0:
        return 0.0
    return (vs_code - 0.5) * 9.26


def _ds_deg(ds_code: int) -> float | None:
    return DS_TO_DEG.get(int(ds_code)) if ds_code is not None else None


def _angle_diff(a: float, b: float) -> float:
    d = abs(a - b) % 360.0
    return min(d, 360.0 - d)


def _modal_speed_kmh(speeds: list[float]) -> float:
    """3 节分箱的模态速度（箱中心），不低于 8.5 节。"""
    valid = [s for s in speeds if s is not None and 0.0 <= s < 33.0 * KM_PER_KNOT]
    if not valid:
        return MODE_MIN_KMH
    bins = np.floor(np.asarray(valid) / MODE_BIN_KMH).astype(int)
    counts = np.bincount(bins)
    center = (int(np.argmax(counts)) + 0.5) * MODE_BIN_KMH
    return max(center, MODE_MIN_KMH)


def _speed_limits(mode_kmh: float) -> tuple[float, float]:
    """返回 (amax, amin)。慢速船 amax=15 节，否则模态 ×1.25 / ×0.75。"""
    if mode_kmh <= SLOW_MODE_KMH:
        return AMAX_SLOW_KMH, 0.0
    return mode_kmh * 1.25, mode_kmh * 0.75


def _row_values(df: pd.DataFrame, idx: list) -> dict:
    """一次性取出轨迹用到的列，避免逐单元访问。"""
    sub = df.loc[idx]
    return {
        "lat": sub[LAT_COL].to_numpy(float),
        "lon": sub[LON_COL].to_numpy(float),
        "t": sub[DT_COL].to_numpy(),
        "vs": sub[VS_COL].to_numpy(int),
        "ds": sub[DS_COL].to_numpy(int),
    }


def _check_round(df: pd.DataFrame, cfg: QCConfig, idx: list) -> list:
    """单轮检查，返回本轮标记失败的索引标签列表。"""
    n = len(idx)
    if n < 3:
        return []
    v = _row_values(df, idx)
    lat, lon, t, vs, ds = v["lat"], v["lon"], v["t"], v["vs"], v["ds"]

    dt_h = np.empty(n)          # dt_h[i]: i-1 → i 的小时数
    dist = np.empty(n)          # dist[i]: i-1 → i 的距离
    course = np.empty(n)        # course[i]: i-1 → i 的方位角
    speed = np.empty(n)         # speed[i]: i-1 → i 的计算速度
    dt_h[0] = dist[0] = course[0] = speed[0] = np.nan
    for i in range(1, n):
        dt_h[i] = (t[i] - t[i - 1]) / np.timedelta64(1, "h")
        dist[i] = float(haversine_km(lat[i - 1], lon[i - 1], lat[i], lon[i]))
        course[i] = initial_bearing_deg(lat[i - 1], lon[i - 1], lat[i], lon[i])
        speed[i] = dist[i] / dt_h[i] if dt_h[i] > 0 else np.nan

    amax, _amin = _speed_limits(_modal_speed_kmh(
        [s for s in speed[1:] if np.isfinite(s)]))

    failed = []
    for i in range(1, n - 1):
        if not (np.isfinite(speed[i]) and np.isfinite(speed[i + 1])):
            continue

        # ---- 证据 1：中点偏差 > 150 km ----
        span_h = (t[i + 1] - t[i - 1]) / np.timedelta64(1, "h")
        if span_h <= 0:
            continue
        f = dt_h[i] / span_h
        mid_lat, mid_lon = gc_interpolate(lat[i - 1], lon[i - 1],
                                          lat[i + 1], lon[i + 1], f)
        midpoint_diff = float(haversine_km(lat[i], lon[i], mid_lat, mid_lon))
        if midpoint_diff <= MIDPOINT_MAX_DIFF_KM:
            continue

        # ---- 证据 2（thisqc_a）：相邻航段计算速度超限 ----
        thisqc_a = 0
        alt_dist = float(haversine_km(lat[i - 1], lon[i - 1], lat[i + 1], lon[i + 1]))
        alt_speed = alt_dist / span_h
        if speed[i] > amax:
            thisqc_a += 1
        if speed[i + 1] > amax:
            thisqc_a += 1
        if alt_speed > amax:
            thisqc_a += 1
        if thisqc_a == 0:
            continue

        # ---- 证据 3（thisqc_b）：连续性检查 ----
        thisqc_b = 0.0
        vsi = _vs_mid_kmh(vs[i])
        vsi_next = _vs_mid_kmh(vs[i + 1])
        dsi = _ds_deg(ds[i])
        dsi_next = _ds_deg(ds[i + 1])

        # 3a. 报告航速/航向外推位置：前向、反向偏差均超允许值
        if vsi is not None and dsi is not None and vsi > 0:
            fwd_lat, fwd_lon = destination_point(lat[i - 1], lon[i - 1],
                                                 dsi, vsi * dt_h[i])
            fwd_diff = float(haversine_km(lat[i], lon[i], fwd_lat, fwd_lon))
            rev_diff = None
            if vsi_next is not None and dsi_next is not None and vsi_next > 0:
                rev_lat, rev_lon = destination_point(
                    lat[i + 1], lon[i + 1], (dsi_next + 180.0) % 360.0,
                    vsi_next * dt_h[i + 1])
                rev_diff = float(haversine_km(lat[i], lon[i], rev_lat, rev_lon))
            allowance = ESTIMATE_TOLERANCE * max(vsi * dt_h[i], 1.0)
            if fwd_diff > allowance and (rev_diff is None or rev_diff > allowance):
                thisqc_b += 10.0

        # 3b. 报告航向与计算航向差 > 60°（当前段与下一段都不符）
        if dsi is not None and dsi_next is not None:
            if (_angle_diff(dsi, course[i]) > DIRECTION_MAX_DIFF_DEG
                    and _angle_diff(dsi_next, course[i + 1]) > DIRECTION_MAX_DIFF_DEG):
                thisqc_b += 10.0

        # 3c. 报告航速与计算速度差 > 10 节
        if vsi is not None and abs(speed[i] - vsi) > SPEED_MAX_DIFF_KMH:
            thisqc_b += 10.0

        # 3d. 计算速度超过 40 节
        if speed[i] > ULTRA_FAST_KMH:
            thisqc_b += 10.0

        if thisqc_b > 0:
            failed.append(idx[i])
    return failed


def check_mds_track(df: pd.DataFrame, cfg: QCConfig) -> None:
    """MDS 航迹检查：按站点迭代（最多 5 轮），结果按配置写复核或删除标记。"""
    if not cfg.mds_track_check:
        return
    delete_mode = cfg.mds_track_action == "delete"
    for _station, g in _station_groups(df):
        idx = list(g.index)
        all_failed: list = []
        for _round in range(MAX_ITERATIONS):
            failed = _check_round(df, cfg, idx)
            if not failed:
                break
            all_failed.extend(failed)
            idx = [i for i in idx if i not in set(failed)]
        if not all_failed:
            continue
        if delete_mode:
            df.loc[all_failed, QC_FLAG_COL] = flags.DELETE_MDS_TRACK_CHECK
        else:
            add_review(df, all_failed, flags.MDS_TRACK_CHECK)
