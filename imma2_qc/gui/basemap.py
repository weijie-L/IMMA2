"""可选的 GSHHG 海岸线底图。

用户在“设置”中指定 GSHHG shapefile 目录后，从中查找 L1 海岸线
（优先粗分辨率 c/l/i，保证交互流畅），转换为折线段缓存。
未配置或读取失败时地图仅显示经纬网格。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

_PREFERRED = ("c", "l", "i", "h", "f")  # GSHHG 分辨率，从粗到细


def find_l1_shapefile(gshhg_dir: str | Path) -> Path | None:
    gshhg_dir = Path(gshhg_dir)
    candidates = {p.name: p for p in gshhg_dir.rglob("GSHHS_*_L1.shp")}
    for res in _PREFERRED:
        name = f"GSHHS_{res}_L1.shp"
        if name in candidates:
            return candidates[name]
    return next(iter(candidates.values()), None)


def load_coastlines(gshhg_dir: str | Path, min_points: int = 30) -> list[np.ndarray]:
    """返回海岸线折线列表，每条为 (N,2) 数组，列为 [lon(-180..180), lat]。"""
    try:
        import shapefile  # pyshp
    except ImportError:
        return []
    shp = find_l1_shapefile(gshhg_dir)
    if shp is None:
        return []
    lines: list[np.ndarray] = []
    try:
        with shapefile.Reader(str(shp)) as reader:
            for rec in reader.iterShapes():
                pts = np.asarray(rec.points, dtype=float)
                if len(pts) < min_points:
                    continue
                parts = list(rec.parts) + [len(pts)]
                for a, b in zip(parts[:-1], parts[1:]):
                    seg = pts[a:b]
                    if len(seg) >= min_points:
                        lines.append(seg)
    except Exception:
        return []
    return lines
