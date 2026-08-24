"""质控引擎单元测试。"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from imma2_qc import flags
from imma2_qc.config import QCConfig
from imma2_qc.decisions import ACTION_DELETE, ACTION_KEEP, DecisionStore
from imma2_qc.export import apply_decisions, export_results
from imma2_qc.io_utils import UID_COL, compute_uids, find_data_files, load_files
from imma2_qc.qc.basic import QC_FLAG_COL, REVIEW_COL, check_basic
from imma2_qc.qc.engine import run_qc, summarize
from imma2_qc.status import compute_status


def cfg_small(**kw) -> QCConfig:
    """测试用配置：不启用站点-年份最少记录数。"""
    kw.setdefault("min_records_per_station_year", 0)
    kw.setdefault("value_max", 100.0)
    return QCConfig(**kw)


def make_df(rows: list[dict]) -> pd.DataFrame:
    base = {"STATION": "TEST1", "Q_VIS": "1", "VS_CODE": "2", "VIS": "10.0"}
    df = pd.DataFrame([{**base, **r} for r in rows]).astype(str)
    df["_SOURCE_FILE"] = "t.csv"
    df["_SOURCE_ROW"] = range(len(df))
    df[UID_COL] = compute_uids(df, QCConfig())
    return df


def track_rows(n: int, start="2003-01-01 00:00", step_h=3,
               lat0=10.0, dlat=0.05, lon0=130.0, dlon=0.2) -> list[dict]:
    t0 = pd.Timestamp(start)
    return [{"DATE": str(t0 + pd.Timedelta(hours=step_h * i)),
             "LATITUDE": f"{lat0 + dlat * i:.3f}",
             "LONGITUDE": f"{lon0 + dlon * i:.3f}"} for i in range(n)]


# ---------- 基础检查 ----------

def test_basic_invalid_fields():
    rows = track_rows(6)
    rows[1]["LATITUDE"] = "123.0"          # 纬度越界
    rows[2]["DATE"] = "not-a-date"         # 日期非法
    rows[3]["VIS"] = "NA"                  # 缺失
    rows[4]["VS_CODE"] = "17"              # 航速档非法
    df = run_qc(make_df(rows), cfg_small())
    assert (df.loc[[1, 2, 3, 4], QC_FLAG_COL]
            == flags.DELETE_INVALID_BASIC_FIELD).all()
    assert (df.loc[[0, 5], QC_FLAG_COL] == "").all()


def test_longitude_normalization():
    rows = track_rows(3)
    rows[0]["LONGITUDE"] = "-170.0"        # 转换到 190
    df = check_basic(make_df(rows), cfg_small())
    assert df.loc[0, "_LON"] == pytest.approx(190.0)
    assert df.loc[0, QC_FLAG_COL] == ""


def test_ship_and_maskstid():
    rows = track_rows(4)
    rows[0]["STATION"] = "SHIP"
    rows[1]["STATION"] = "MASKSTID"
    df = run_qc(make_df(rows), cfg_small())
    assert df.loc[0, QC_FLAG_COL] == flags.DELETE_SHIP
    assert df.loc[1, QC_FLAG_COL] == ""    # keep 策略下保留

    df2 = run_qc(make_df(rows), cfg_small(maskstid_policy="drop"))
    assert df2.loc[1, QC_FLAG_COL] == flags.DELETE_MASKSTID


# ---------- 轨迹检查 ----------

def test_isolated_spike_deleted():
    rows = track_rows(7)
    rows[3]["LATITUDE"], rows[3]["LONGITUDE"] = "-60.0", "30.0"  # 远离轨迹的单点
    df = run_qc(make_df(rows), cfg_small())
    assert df.loc[3, QC_FLAG_COL] == flags.DELETE_HIGH_CONFIDENCE_ISOLATED_SPIKE
    assert (df.drop(3)[QC_FLAG_COL] == "").all()


def test_short_jump_not_deleted():
    """小幅跳动（未达 spike_min_jump_km）不应删除。"""
    rows = track_rows(7)
    rows[3]["LATITUDE"] = f"{10.0 + 0.05 * 3 + 1.0:.3f}"  # 偏离约 100 km
    df = run_qc(make_df(rows), cfg_small())
    assert df.loc[3, QC_FLAG_COL] == ""


def test_same_time_conflict_deleted():
    rows = track_rows(6)
    # 与第 2 条同刻、相距很远的位置
    rows.append({"DATE": rows[2]["DATE"], "LATITUDE": "-50.0", "LONGITUDE": "300.0"})
    df = run_qc(make_df(rows), cfg_small())
    assert df.loc[6, QC_FLAG_COL] == flags.DELETE_SAME_TIME_OFF_TRAJECTORY
    assert df.loc[2, QC_FLAG_COL] == ""


def test_zero_zero_review():
    rows = track_rows(3)
    rows[1]["LATITUDE"], rows[1]["LONGITUDE"] = "0.0", "0.0"
    df = run_qc(make_df(rows), cfg_small())
    assert flags.COORDINATE_0_0 in df.loc[1, REVIEW_COL]
    assert df.loc[1, QC_FLAG_COL] == ""    # 只复核不删除


# ---------- 时间序列 ----------

def test_series_spike_review():
    rows = track_rows(11)
    rows[5]["VIS"] = "90.0"
    df = run_qc(make_df(rows), cfg_small())
    assert flags.SERIES_SPIKE in df.loc[5, REVIEW_COL]
    assert df.loc[5, QC_FLAG_COL] == ""


def test_series_step_review():
    rows = track_rows(20)
    for i in range(10, 20):
        rows[i]["VIS"] = "40.0"
    df = run_qc(make_df(rows), cfg_small())
    assert any(flags.SERIES_STEP in v for v in df[REVIEW_COL])


# ---------- 去重与最少记录数 ----------

def test_strict_duplicate():
    rows = track_rows(4)
    rows.append(dict(rows[2]))
    df = run_qc(make_df(rows), cfg_small())
    assert (df[QC_FLAG_COL] == flags.DELETE_STRICT_DUPLICATE).sum() == 1


def test_station_year_min():
    rows = track_rows(5)
    df = run_qc(make_df(rows), QCConfig(min_records_per_station_year=30,
                                        value_max=100.0))
    assert (df[QC_FLAG_COL] == flags.DELETE_STATION_YEAR_LT_MIN).all()


# ---------- 人工决定与导出 ----------

def test_decisions_override_and_status():
    rows = track_rows(7)
    rows[3]["LATITUDE"], rows[3]["LONGITUDE"] = "-60.0", "30.0"
    df = run_qc(make_df(rows), cfg_small())
    spike_uid = df.loc[3, UID_COL]
    keep_uid = df.loc[1, UID_COL]

    dec = DecisionStore()
    dec.set(spike_uid, ACTION_KEEP)      # 推翻自动删除
    dec.set(keep_uid, ACTION_DELETE)     # 人工删除程序未发现的点

    out = apply_decisions(df, dec)
    assert not out.loc[3, "_FINAL_DELETED"]
    assert out.loc[1, "_FINAL_DELETED"]

    status = compute_status(df, dec)
    assert status.loc[3] == "manual_keep"
    assert status.loc[1] == "manual_del"


def test_decision_store_roundtrip(tmp_path):
    dec = DecisionStore()
    dec.set("abc123", ACTION_DELETE, {"STATION": "T", "DATE": "2003-01-01"})
    p = dec.save(tmp_path / "d.csv")
    dec2 = DecisionStore(p)
    assert dec2.action_of("abc123") == ACTION_DELETE


def test_export_end_to_end(tmp_path):
    import subprocess, sys
    sample = tmp_path / "in"
    subprocess.run([sys.executable, "scripts/generate_sample_data.py", str(sample)],
                   check=True)
    cfg = QCConfig(value_max=100.0)
    files = find_data_files(sample)
    assert len(files) == 2
    df = run_qc(load_files(files, cfg), cfg)

    # 注入的异常都被发现
    assert (df[QC_FLAG_COL] == flags.DELETE_SHIP).sum() == 1
    assert (df[QC_FLAG_COL] == flags.DELETE_STRICT_DUPLICATE).sum() >= 1
    assert (df[QC_FLAG_COL] == flags.DELETE_HIGH_CONFIDENCE_ISOLATED_SPIKE).sum() == 1
    assert (df[QC_FLAG_COL] == flags.DELETE_SAME_TIME_OFF_TRAJECTORY).sum() == 1
    assert (df[QC_FLAG_COL] == flags.DELETE_STATION_YEAR_LT_MIN).sum() == 5
    assert (df[QC_FLAG_COL] == flags.DELETE_INVALID_BASIC_FIELD).sum() == 2
    assert any(flags.SERIES_SPIKE in v for v in df[REVIEW_COL])

    out = tmp_path / "out"
    export_results(df, cfg, DecisionStore(), out)
    assert (out / "IMMA1_2003-01_VI1.csv").exists()
    audit = out / "_qc_audit"
    assert (audit / "qc_summary_all_years.csv").exists()
    assert (audit / "deleted_records_2003.csv").exists()
    assert (audit / "settings.json").exists()

    # 清洗后的文件不含被删除记录，且只保留业务字段
    cleaned = pd.read_csv(out / "IMMA1_2003-01_VI1.csv", dtype=str)
    assert "QC_FLAG" not in cleaned.columns
    assert "SHIP" not in set(cleaned["STATION"])

    s = summarize(df)
    assert s["INPUT"].sum() == len(df)


# ---------- 内置底图 ----------

def test_default_basemap_loads():
    pytest.importorskip("shapefile")
    from imma2_qc.gui.basemap import DEFAULT_BASEMAP, load_default_basemap
    assert DEFAULT_BASEMAP.exists()
    lines = load_default_basemap()
    assert len(lines) > 100
    allpts = np.vstack(lines)
    assert allpts[:, 0].min() >= -180.0 and allpts[:, 0].max() <= 180.0
    assert allpts[:, 1].min() >= -90.0 and allpts[:, 1].max() <= 90.0


# ---------- 海陆检查 ----------

def test_deep_land_check():
    pytest.importorskip("shapely")
    # 一条完全在陆地内部（中亚）的“航迹”应整体标记 DELETE_DEEP_LAND
    rows = track_rows(5, lat0=45.0, lon0=85.0, dlat=0.01, dlon=0.01)
    df = run_qc(make_df(rows), cfg_small())
    assert (df[QC_FLAG_COL] == flags.DELETE_DEEP_LAND).all()

    # 海上航迹不受影响；skip_land 时不检查
    ocean = run_qc(make_df(track_rows(5)), cfg_small())
    assert (ocean[QC_FLAG_COL] == "").all()
    skipped = run_qc(make_df(rows), cfg_small(skip_land=True))
    assert (skipped[QC_FLAG_COL] == "").all()


# ---------- 镜像修复建议 ----------

def test_mirror_lon_suggested():
    """经度符号丢失的点：给出 MIRROR_LON 建议而不是删除。"""
    rows = track_rows(5, lat0=-10.0, dlat=0.0, lon0=85.0, dlon=0.2)
    rows[2]["LONGITUDE"] = f"{360.0 - 85.4:.3f}"     # 真实 85.4 → 274.6
    df = run_qc(make_df(rows), cfg_small())
    assert df.loc[2, "_FIX_TYPE"] == flags.FIX_MIRROR_LON
    assert df.loc[2, "_FIX_LON"] == pytest.approx(85.4)
    assert df.loc[2, QC_FLAG_COL] == ""
    assert flags.MIRROR_FIX_SUGGESTED in df.loc[2, REVIEW_COL]


def test_mirror_lat_suggested():
    rows = track_rows(5, lat0=-10.0, dlat=-0.2, lon0=85.0, dlon=0.05)
    rows[2]["LATITUDE"] = "10.4"                     # 真实 -10.4 → +10.4
    df = run_qc(make_df(rows), cfg_small())
    assert df.loc[2, "_FIX_TYPE"] == flags.FIX_MIRROR_LAT
    assert df.loc[2, "_FIX_LAT"] == pytest.approx(-10.4)
    assert df.loc[2, QC_FLAG_COL] == ""


def test_unrepairable_spike_still_deleted():
    """镜像修不回来的坏点仍走三点漂移删除。"""
    rows = track_rows(7)
    rows[3]["LATITUDE"], rows[3]["LONGITUDE"] = "-60.0", "30.0"
    df = run_qc(make_df(rows), cfg_small())
    assert df.loc[3, "_FIX_TYPE"] == ""
    assert df.loc[3, QC_FLAG_COL] == flags.DELETE_HIGH_CONFIDENCE_ISOLATED_SPIKE


def test_mirror_detour_rejected():
    """修复位置“够得着但偏离航线”时（时间间隔大），不给建议。

    静止站（VS=0 缓冲 15km）间隔 10 天，允许半径只有 15km，
    但把点造在纬度镜像后偏离 A—C 连线较远的位置无法构造……
    改为验证 detour 阈值：把阈值压到 0 时，轻微偏航的镜像点不再被建议。"""
    rows = track_rows(5, lat0=-10.0, dlat=0.0, lon0=85.0, dlon=0.2)
    rows[2]["LATITUDE"] = "-10.3"                    # 镜像修复后仍偏离连线约 33km
    rows[2]["LONGITUDE"] = f"{360.0 - 85.4:.3f}"
    strict = run_qc(make_df(rows), cfg_small(mirror_fit_max_detour_km=0.5))
    assert strict.loc[2, "_FIX_TYPE"] == ""
    loose = run_qc(make_df(rows), cfg_small(mirror_fit_max_detour_km=80.0))
    assert loose.loc[2, "_FIX_TYPE"] == flags.FIX_MIRROR_LON


def test_repair_adopted_and_exported(tmp_path):
    rows = track_rows(5, lat0=-10.0, dlat=0.0, lon0=85.0, dlon=0.2)
    rows[2]["LONGITUDE"] = f"{360.0 - 85.4:.3f}"
    df = run_qc(make_df(rows), cfg_small())
    uid = df.loc[2, UID_COL]

    dec = DecisionStore()
    dec.set(uid, "repair")
    status = compute_status(df, dec)
    assert status.loc[2] == "manual_repair"

    out = tmp_path / "out"
    export_results(df, cfg_small(), dec, out)
    cleaned = pd.read_csv(out / "t.csv", dtype=str)
    assert cleaned.loc[2, "LONGITUDE"] == "85.4"
    repaired = pd.read_csv(out / "_qc_audit" / "repaired_records_2003.csv",
                           dtype=str)
    assert repaired.loc[0, "FIX"] == flags.FIX_MIRROR_LON
    assert float(repaired.loc[0, "ORIG_LONGITUDE"]) == pytest.approx(274.6)
