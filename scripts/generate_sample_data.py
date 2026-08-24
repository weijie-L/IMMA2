"""生成演示/测试用的样例数据（含注入的各类异常）。

用法：python scripts/generate_sample_data.py [输出目录，默认 sample_data]
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

rng = np.random.default_rng(42)


def make_ship_track(station: str, year: int, month: int, n: int,
                    lat0: float, lon0: float) -> pd.DataFrame:
    """一条正常移动的船舶轨迹（约 15 km/h 向东北）。"""
    t0 = pd.Timestamp(year=year, month=month, day=1)
    times = [t0 + pd.Timedelta(hours=3 * i) for i in range(n)]
    lats = lat0 + np.cumsum(rng.normal(0.06, 0.02, n))
    lons = lon0 + np.cumsum(rng.normal(0.25, 0.05, n))
    vis = np.clip(rng.normal(20, 4, n), 1, 50)
    return pd.DataFrame({
        "STATION": station,
        "DATE": [t.strftime("%Y-%m-%d %H:%M:%S") for t in times],
        "LATITUDE": np.round(lats, 3),
        "LONGITUDE": np.round(lons % 360.0, 3),
        "VIS": np.round(vis, 1),
        "Q_VIS": 1,
        "VS_CODE": 2,
    })


def main(out_dir: str = "sample_data") -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    frames = []
    for month in (1, 2):
        month_frames = []
        # 三条正常船 + 一个固定站
        for i, (st, lat0, lon0) in enumerate(
                [("SHIPA1", 10.0, 130.0), ("SHIPB2", -20.0, 200.0),
                 ("SHIPC3", 35.0, 320.0)]):
            month_frames.append(make_ship_track(st, 2003, month, 120, lat0, lon0))
        fixed = make_ship_track("FIXED1", 2003, month, 100, 0.0, 0.0)
        fixed["LATITUDE"], fixed["LONGITUDE"] = 25.0, 121.5
        fixed["VS_CODE"] = 0
        month_frames.append(fixed)
        df = pd.concat(month_frames, ignore_index=True).astype(object)

        if month == 1:
            # 注入异常：单点位置尖峰
            df.loc[30, ["LATITUDE", "LONGITUDE"]] = [-60.0, 30.0]
            # VIS 尖峰
            df.loc[45, "VIS"] = 90.0
            # 缺失/非法值
            df.loc[50, "VIS"] = "NA"
            df.loc[51, "LATITUDE"] = 123.0
            # SHIP 占位站号
            ship = df.iloc[[60]].copy()
            ship["STATION"] = "SHIP"
            # 严格重复
            dup = df.iloc[[70]].copy()
            # 同站同刻远距离冲突
            conflict = df.iloc[[80]].copy()
            conflict["LATITUDE"] = df.loc[80, "LATITUDE"] + 15.0
            # 记录数不足的站点
            small = make_ship_track("TINY99", 2003, month, 5, 5.0, 100.0)
            df = pd.concat([df, ship, dup, conflict, small], ignore_index=True)

        df.to_csv(out / f"IMMA1_2003-{month:02d}_VI1.csv", index=False)
        frames.append(df)
    total = sum(len(f) for f in frames)
    print(f"样例数据已写入 {out}（{total} 条记录）")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "sample_data")
