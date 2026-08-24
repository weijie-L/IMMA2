"""地图底图。

默认使用内置的国界 shapefile（imma2_qc/assets/basemap/country.shp），
也可在“设置”中改用 GSHHG 海岸线（优先粗分辨率 c/l/i，保证交互流畅）。
读取失败时地图仅显示经纬网格。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

_PREFERRED = ("c", "l", "i", "h", "f")  # GSHHG 分辨率，从粗到细

DEFAULT_BASEMAP = Path(__file__).resolve().parent.parent / "assets" / "basemap" / "country.shp"


def _read_polylines(shp_path: str | Path, min_points: int = 2) -> list[np.ndarray]:
    """读取 shapefile 的全部部件轮廓，返回 (N,2) [lon, lat] 折线列表。"""
    try:
        import shapefile  # pyshp
    except ImportError:
        return []
    lines: list[np.ndarray] = []
    try:
        with shapefile.Reader(str(shp_path)) as reader:
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


def load_default_basemap() -> list[np.ndarray]:
    """内置国界底图（经度 -180..180）。"""
    if not DEFAULT_BASEMAP.exists():
        return []
    return _read_polylines(DEFAULT_BASEMAP)


def find_l1_shapefile(gshhg_dir: str | Path) -> Path | None:
    gshhg_dir = Path(gshhg_dir)
    candidates = {p.name: p for p in gshhg_dir.rglob("GSHHS_*_L1.shp")}
    for res in _PREFERRED:
        name = f"GSHHS_{res}_L1.shp"
        if name in candidates:
            return candidates[name]
    return next(iter(candidates.values()), None)


def load_coastlines(gshhg_dir: str | Path, min_points: int = 30) -> list[np.ndarray]:
    """GSHHG L1 海岸线折线列表（跳过点数过少的小岛以保证流畅）。"""
    shp = find_l1_shapefile(gshhg_dir)
    if shp is None:
        return []
    return _read_polylines(shp, min_points=min_points)
