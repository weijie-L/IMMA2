"""GSHHG / 内置国界 海陆检查。

删除距离水陆边界约 land_interior_km 以上的明确陆地内部点（DELETE_DEEP_LAND），
保守保留近岸、港口、岛屿附近与湖泊上的记录：

  - 陆地多边形整体向内收缩 land_interior_km（按 1° ≈ 111.32 km 换算，
    与原 icoads_qc_v5 相同的近似，高纬度东西向实际缓冲会偏小）；
  - 配置了 GSHHG 目录时使用 L1 陆地 + L2 湖泊（湖泊向外扩 buffer 后
    整体保留，落在湖上的记录不删）；
  - 未配置时退回内置国界底图 country.shp。注意内置版没有湖泊层，
    里海/五大湖等大型湖泊上的记录可能被误标——建议配置 GSHHG。

检查只打删除标记，可在界面中框选恢复。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

KM_PER_DEG = 111.32
_PREFERRED = ("c", "l", "i", "h", "f")  # GSHHG 分辨率，从粗到细（粗的收缩计算快）

DEFAULT_BASEMAP = Path(__file__).resolve().parent / "assets" / "basemap" / "country.shp"

_CACHE: dict[tuple, "LandChecker"] = {}


def _find_gshhg_level(gshhg_dir: Path, level: int) -> Path | None:
    candidates = {p.name: p for p in gshhg_dir.rglob(f"GSHHS_*_L{level}.shp")}
    for res in _PREFERRED:
        name = f"GSHHS_{res}_L{level}.shp"
        if name in candidates:
            return candidates[name]
    return next(iter(candidates.values()), None)


def _read_polygons(shp_path: Path, min_points: int = 4) -> list:
    """把 shapefile 的每个部件环读成 shapely Polygon（孔洞按实心处理的近似）。"""
    import shapefile  # pyshp
    from shapely.geometry import Polygon

    polygons = []
    with shapefile.Reader(str(shp_path)) as reader:
        for shape in reader.iterShapes():
            pts = shape.points
            parts = list(shape.parts) + [len(pts)]
            for a, b in zip(parts[:-1], parts[1:]):
                ring = pts[a:b]
                if len(ring) < min_points:
                    continue
                poly = Polygon(ring)
                if not poly.is_valid:
                    poly = poly.buffer(0)
                if not poly.is_empty:
                    polygons.append(poly)
    return polygons


class LandChecker:
    """构造时完成陆地收缩与空间索引；deep_land_mask 批量判断。"""

    def __init__(self, gshhg_dir: str | Path | None = None,
                 interior_km: float = 5.0):
        import shapely

        deg = interior_km / KM_PER_DEG
        land_shp = None
        lake_shp = None
        if gshhg_dir:
            gshhg_dir = Path(gshhg_dir)
            land_shp = _find_gshhg_level(gshhg_dir, 1)
            lake_shp = _find_gshhg_level(gshhg_dir, 2)
        if land_shp is not None:
            self.source = f"GSHHG:{land_shp.name}"
        else:
            land_shp = DEFAULT_BASEMAP
            self.source = "builtin:country.shp"
        if not land_shp.exists():
            raise FileNotFoundError(f"海陆检查底图不存在：{land_shp}")

        eroded = []
        for poly in _read_polygons(land_shp):
            g = poly.buffer(-deg)
            if not g.is_empty:
                eroded.append(g)
        self._land_tree = shapely.STRtree(eroded) if eroded else None

        self._lake_tree = None
        if lake_shp is not None:
            lakes = [p.buffer(deg) for p in _read_polygons(lake_shp)]
            lakes = [p for p in lakes if not p.is_empty]
            if lakes:
                self._lake_tree = shapely.STRtree(lakes)

    def deep_land_mask(self, lons_pm180, lats) -> np.ndarray:
        """lons 为 [-180,180] 经度。返回布尔数组：True = 明确陆地内部。"""
        import shapely

        lons = np.asarray(lons_pm180, dtype=float)
        lats = np.asarray(lats, dtype=float)
        mask = np.zeros(len(lons), dtype=bool)
        if self._land_tree is None or len(lons) == 0:
            return mask
        points = shapely.points(np.column_stack([lons, lats]))
        hits = self._land_tree.query(points, predicate="intersects")
        mask[np.unique(hits[0])] = True
        if self._lake_tree is not None and mask.any():
            idx = np.flatnonzero(mask)
            lake_hits = self._lake_tree.query(points[idx], predicate="intersects")
            mask[idx[np.unique(lake_hits[0])]] = False
        return mask


def get_land_checker(gshhg_dir: str | Path | None,
                     interior_km: float) -> LandChecker:
    """按 (目录, 阈值) 缓存，避免重复读取与收缩计算。"""
    key = (str(gshhg_dir) if gshhg_dir else "", float(interior_km))
    if key not in _CACHE:
        _CACHE[key] = LandChecker(gshhg_dir or None, interior_km)
    return _CACHE[key]
