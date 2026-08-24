"""质控配置：阈值、航速档位表、缺失值标记等。

所有阈值集中在 QCConfig 中，GUI 与命令行共用。
"""
from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field
from pathlib import Path

# VS_CODE 航速档位上限（km/h），来源：ICOADS 航速分类码
VS_SPEED_UPPER_KMH = {
    0: 0.00,
    1: 9.26,
    2: 18.52,
    3: 27.78,
    4: 37.04,
    5: 46.30,
    6: 55.56,
    7: 64.82,
    8: 74.08,
}

# 45 knot 宽松物理上限，仅用于轨迹连续性判断
LOOSE_MAX_SPEED_KMH = 83.34

# 统一视为缺失值的原始字符串（比较前先 strip + 大写）
MISSING_TOKENS = {"", "NA", "NAN", "NULL", "NONE", "N/A", "999999", "-9999", "9999.0", "-9999.0"}


@dataclass
class QCConfig:
    # ---- 字段名 ----
    station_col: str = "STATION"
    date_col: str = "DATE"
    lat_col: str = "LATITUDE"
    lon_col: str = "LONGITUDE"
    value_col: str = "VIS"
    quality_col: str = "Q_VIS"
    vs_col: str = "VS_CODE"
    ds_col: str = "DS"

    # ---- 基础检查 ----
    station_pattern: str = r"^[A-Za-z0-9]+$"  # 站号必须为非空字母数字组合
    value_min: float = 0.0                     # 观测值物理下限
    value_max: float = 1.0e5                   # 观测值物理上限（按需收紧）
    require_quality_col: bool = True
    require_vs_col: bool = True

    # ---- 特殊站号 ----
    drop_ship: bool = True                     # SHIP 为通用占位站号，直接删除
    maskstid_policy: str = "keep"              # keep: 保留但不参与轨迹类检查; drop: 删除

    # ---- 海陆检查 ----
    skip_land: bool = False                    # True 时跳过海陆检查
    land_interior_km: float = 5.0              # 陆地内部判定缓冲（约 5 km）

    # ---- 轨迹 / 漂移 ----
    suggest_mirror_fix: bool = True            # 镜像修复建议（人工确认后生效）
    mirror_fit_max_detour_km: float = 50.0     # 修复点相对 A—C 直线的最大绕行量
    distance_buffer_km: float = 15.0
    spike_min_jump_km: float = 500.0
    spike_bridge_km: float = 100.0
    same_time_cluster_km: float = 30.0
    same_time_conflict_km: float = 100.0
    track_gap_days: float = 30.0               # 超过该间隔视为新航段
    zero_jump_km: float = 500.0                # 突跳到 0 坐标的判定距离

    # ---- 内插位置偏差检查（Met Office MarineQC 思路，只标记复核）----
    interp_check: bool = True
    interp_max_dev_km: float = 200.0           # 偏离时间内插位置的阈值
    interp_max_gap_hours: float = 48.0         # 前后跨度超过此值不做内插检查

    # ---- Met Office MDS 航迹检查（移植自 ET-NCMP/MarineQC，BSD-3）----
    mds_track_check: bool = True
    mds_track_action: str = "review"           # review: 标记复核; delete: 自动删除

    # ---- 观测值时间序列 ----
    series_spike_window: int = 5               # 滑动中位数窗口（奇数）
    series_spike_mad_factor: float = 5.0       # |v-median| > factor*1.4826*MAD 判为尖峰
    series_spike_min_abs: float = 2.0          # 尖峰最小绝对偏差，防止 MAD≈0 时误报
    series_step_threshold: float = 10.0        # 相邻均值台阶突变阈值
    series_step_halfwin: int = 5               # 台阶检测前后窗口

    # ---- 最终整理 ----
    min_records_per_station_year: int = 30

    def to_json(self) -> str:
        return json.dumps(dataclasses.asdict(self), ensure_ascii=False, indent=2)

    @classmethod
    def from_json_file(cls, path: str | Path) -> "QCConfig":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        known = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})
