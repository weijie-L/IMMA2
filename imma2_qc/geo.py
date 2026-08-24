"""地理计算：大圆距离、经度归一化。"""
from __future__ import annotations

import numpy as np

EARTH_RADIUS_KM = 6371.0088


def haversine_km(lat1, lon1, lat2, lon2):
    """大圆距离（km）。参数可为标量或 numpy 数组，单位为度。"""
    lat1 = np.radians(np.asarray(lat1, dtype=float))
    lon1 = np.radians(np.asarray(lon1, dtype=float))
    lat2 = np.radians(np.asarray(lat2, dtype=float))
    lon2 = np.radians(np.asarray(lon2, dtype=float))
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat / 2.0) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2.0) ** 2
    a = np.clip(a, 0.0, 1.0)
    return 2.0 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(a))


def normalize_lon_0_360(lon: float) -> float:
    """经度统一到 [0, 360)。输入 [-180, 0) 转换到 [180, 360)。"""
    if lon < 0.0:
        lon += 360.0
    if lon >= 360.0:
        lon -= 360.0
    return lon


def lon_to_pm180(lon):
    """[0,360) 经度转换到 (-180, 180]，用于绘图。"""
    lon = np.asarray(lon, dtype=float)
    return np.where(lon > 180.0, lon - 360.0, lon)


def initial_bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """从点 1 到点 2 的大圆初始方位角（度，0..360，正北为 0）。"""
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dlon = np.radians(lon2 - lon1)
    x = np.sin(dlon) * np.cos(p2)
    y = np.cos(p1) * np.sin(p2) - np.sin(p1) * np.cos(p2) * np.cos(dlon)
    return float(np.degrees(np.arctan2(x, y)) % 360.0)


def destination_point(lat: float, lon: float, bearing_deg: float,
                      distance_km: float) -> tuple[float, float]:
    """从 (lat, lon) 沿方位角 bearing 前进 distance_km 后的位置。lon 输出 [0,360)。"""
    delta = distance_km / EARTH_RADIUS_KM
    theta = np.radians(bearing_deg)
    p1 = np.radians(lat)
    l1 = np.radians(lon)
    p2 = np.arcsin(np.sin(p1) * np.cos(delta)
                   + np.cos(p1) * np.sin(delta) * np.cos(theta))
    l2 = l1 + np.arctan2(np.sin(theta) * np.sin(delta) * np.cos(p1),
                         np.cos(delta) - np.sin(p1) * np.sin(p2))
    return float(np.degrees(p2)), normalize_lon_0_360(float(np.degrees(l2)) % 360.0)


def gc_interpolate(lat1: float, lon1: float, lat2: float, lon2: float,
                   f: float) -> tuple[float, float]:
    """大圆插值：返回从点 1 到点 2 大圆路径上比例 f（0..1）处的 (lat, lon)。

    lon 输出为 [0, 360)。两点重合或对跖时退化返回点 1。
    """
    p1 = np.radians([lat1, lon1])
    p2 = np.radians([lat2, lon2])
    v1 = np.array([np.cos(p1[0]) * np.cos(p1[1]),
                   np.cos(p1[0]) * np.sin(p1[1]), np.sin(p1[0])])
    v2 = np.array([np.cos(p2[0]) * np.cos(p2[1]),
                   np.cos(p2[0]) * np.sin(p2[1]), np.sin(p2[0])])
    dot = float(np.clip(np.dot(v1, v2), -1.0, 1.0))
    omega = np.arccos(dot)
    if omega < 1e-12 or abs(np.pi - omega) < 1e-9:
        return lat1, normalize_lon_0_360(lon1)
    v = (np.sin((1.0 - f) * omega) * v1 + np.sin(f * omega) * v2) / np.sin(omega)
    lat = float(np.degrees(np.arcsin(np.clip(v[2], -1.0, 1.0))))
    lon = float(np.degrees(np.arctan2(v[1], v[0])))
    return lat, normalize_lon_0_360(lon)
