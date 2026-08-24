"""预处理流水线测试：数据提取、规整清洗、航速填补。"""
from __future__ import annotations

import csv
from pathlib import Path

import pytest

from imma2_qc.paths import PathsConfig
from imma2_qc.preprocess.extract import extract_raw
from imma2_qc.preprocess.fill_speed import (fill_fixed_stations,
                                            fill_moving_stations)
from imma2_qc.preprocess.normalize import OUTPUT_COLUMNS, normalize_dir


def imma_line(yr="2003", mo="01", dy="05", hr="1200", lat="01050",
              lon="013000", attc="0", ti="1", li="1", ds="3", vs="2",
              ii="25", station="SHIPA1", vi="1", vv="97") -> str:
    """构造一条 IMMA1 定宽记录（字段位置与提取程序一致）。"""
    line = [" "] * 60
    def put(start, text):
        for i, ch in enumerate(text):
            line[start + i] = ch
    put(0, yr); put(4, mo); put(6, dy); put(8, hr)
    put(12, lat); put(17, lon)
    put(25, attc); put(26, ti); put(27, li); put(28, ds); put(29, vs)
    put(32, ii); put(34, station.ljust(9))
    put(53, vi); put(54, vv)
    return "".join(line)


@pytest.fixture
def raw_dir(tmp_path):
    d = tmp_path / "raw"
    d.mkdir()
    lines = [
        imma_line(),                                   # 正常记录
        "9815SUBSIDIARY",                              # Uida 附加记录，跳过
        imma_line(hr="1500", vs="9"),                  # VS=9 剔除
        imma_line(hr="1800", ds="0", vs=" "),          # DS=0 → VS 补 0
        imma_line(hr="2100", vi="2", vv="93"),         # 雾未报能见度 → VV_M 空
        imma_line(dy="06", vv="88"),                   # 非法 VV 码，跳过
        imma_line(dy="07", station="BAD ID"),          # 站号带空格 → 规整删除
    ]
    (d / "IMMA1_R3.0.0_2003-01").write_text("\n".join(lines) + "\n",
                                            encoding="ascii")
    # 同月更高版本：只含一条不同小时的记录，应被选中
    (d / "IMMA1_R3.1.0_2003-01").write_text(
        "\n".join(lines) + "\n" + imma_line(dy="08") + "\n", encoding="ascii")
    return d


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def test_extract(raw_dir, tmp_path, capsys):
    out = tmp_path / "extract"
    stats = extract_raw(raw_dir, out, progress=lambda s: None)
    rows = read_csv(out / "IMMA1_2003-01_VI1.csv")
    # 选择了 R3.1.0（多一条 dy=08 记录）；VS=9 与非法 VV 被剔除
    assert stats["dropped_vs9"] == 1
    assert stats["complemented_vs"] == 1
    days = {r["DY"] for r in rows}
    assert "08" in days
    assert all(r["VS_CODE"] != "9" for r in rows)
    vs_filled = [r for r in rows if r["HR"] == "1800"]
    assert vs_filled[0]["DS"] == "0" and vs_filled[0]["VS_CODE"] == "0"
    fog = [r for r in rows if r["VV_CODE"] == "93"]
    assert fog[0]["VV_M"] == "" and fog[0]["VV_NOTE"]


def test_normalize(raw_dir, tmp_path):
    extract_dir = tmp_path / "extract"
    clean_dir = tmp_path / "clean"
    extract_raw(raw_dir, extract_dir, progress=lambda s: None)
    stats = normalize_dir(extract_dir, clean_dir, progress=lambda s: None)
    rows = read_csv(clean_dir / "IMMA1_2003-01_VI1.csv")

    assert stats["deleted_empty_vv_m"] == 1      # 雾未报能见度
    assert stats["deleted_invalid_id"] == 1      # 站号带空格
    assert [list(r.keys()) for r in rows][0] == OUTPUT_COLUMNS
    first = rows[0]
    assert first["DATE"] == "2003-01-05 12:00:00"   # HR=1200 → 12.00h
    assert first["LATITUDE"] == "10.5"              # 01050 → 10.50
    assert first["LONGITUDE"] == "130"              # 013000 → 130.00
    assert first["VIS"] == "10000" and first["Q_VIS"] == "97"


def _write_clean_csv(path: Path, rows: list[dict]):
    cols = OUTPUT_COLUMNS
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in cols})


def base_row(**kw) -> dict:
    row = {"STATION": "MOVE1", "DATE": "2003-01-01 00:00:00", "SOURCE": "25",
           "LATITUDE": "10", "LONGITUDE": "130", "NAME": "MOVE1",
           "REPORT_TYPE": "1", "VIS": "10000", "Q_VIS": "97",
           "LI": "1", "DS": "3", "VS_CODE": "2", "VS_KMH_RANGE": "18.52"}
    row.update(kw)
    return row


def test_fill_moving(tmp_path):
    d = tmp_path / "clean"
    d.mkdir()
    rows = [
        base_row(),                                                    # 参考
        base_row(DATE="2003-01-01 00:30:00", DS="", VS_CODE="",
                 VS_KMH_RANGE=""),                                     # 1小时规则目标
        base_row(DATE="2003-01-01 01:00:00"),                          # 参考
        base_row(DATE="2003-01-01 06:00:00", DS="", VS_CODE="",
                 VS_KMH_RANGE=""),                                     # 无夹逼，不填
    ]
    _write_clean_csv(d / "IMMA1_2003-01_VI1.csv", rows)
    stats = fill_moving_stations(d, progress=lambda s: None)
    assert stats["selected_interp_1h"] == 1
    out = read_csv(d / "IMMA1_2003-01_VI1.csv")
    assert out[1]["DS"] == "3" and out[1]["VS_CODE"] == "2"
    assert out[1]["VS_KMH_RANGE"] == "18.52"
    assert out[3]["DS"] == ""    # 边界外目标保持空


def test_fill_fixed(tmp_path):
    d = tmp_path / "clean"
    d.mkdir()
    rows = [
        base_row(STATION="FIX1", DS="0", VS_CODE="0", VS_KMH_RANGE="0"),
        base_row(STATION="FIX1", DATE="2003-01-01 06:00:00",
                 DS="", VS_CODE="", VS_KMH_RANGE=""),     # 应填 0
        base_row(STATION="MOVE1"),                        # 非零航速站不动
        base_row(STATION="MOVE1", DATE="2003-01-01 06:00:00",
                 DS="", VS_CODE="", VS_KMH_RANGE=""),     # 不满足条件，不填
    ]
    _write_clean_csv(d / "IMMA1_2003-01_VI1.csv", rows)
    stats = fill_fixed_stations(d, progress=lambda s: None)
    assert stats["changed_rows"] == 1
    out = read_csv(d / "IMMA1_2003-01_VI1.csv")
    assert out[1]["DS"] == "0" and out[1]["VS_CODE"] == "0"
    assert out[3]["DS"] == ""


def test_paths_roundtrip(tmp_path, monkeypatch):
    import imma2_qc.paths as paths_mod
    monkeypatch.setattr(paths_mod, "SETTINGS_FILE", tmp_path / "settings.json")
    cfg = PathsConfig(raw_dir="/a", extract_dir="/b", clean_dir="/c")
    paths_mod.save_paths(cfg)
    loaded = paths_mod.load_paths()
    assert loaded == cfg
