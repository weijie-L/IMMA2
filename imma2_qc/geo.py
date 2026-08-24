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
