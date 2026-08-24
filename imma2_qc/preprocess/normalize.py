"""第2步 规整清洗：提取结果 → 标准列格式。

对应 step.1.1.规整.py：
  - YR/MO/DY/HR 合成 DATE（HR 为 0.01 小时单位，830 → 08:18:00）；
  - LAT/LON 为隐含百分之一单位（5880 → 58.8），已带小数点的视为已转换；
  - 经度统一 0-360°；
  - 站号必须为 1-9 位 ASCII 字母数字；
  - VV_M 为空（含雾未报能见度）或 VV_CODE 非 90-99 的记录删除；
  - 输出标准列：STATION/DATE/SOURCE/LATITUDE/LONGITUDE/ELEVATION/NAME/
    REPORT_TYPE/VIS/Q_VIS/LI/DS/VS_CODE/VS_KMH_RANGE。
"""
from __future__ import annotations

import csv
import math
import os
import re
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

VALID_ID_RE = re.compile(r"^[A-Za-z0-9]+$")

INPUT_COLUMNS = [
    "YR", "MO", "DY", "HR", "LAT", "LON", "ATTC", "TI", "LI",
    "DS", "VS_CODE", "VS_KMH_RANGE", "II", "ID", "VI",
    "VV_CODE", "VV_M", "VV_NOTE",
]

OUTPUT_COLUMNS = [
    "STATION", "DATE", "SOURCE", "LATITUDE", "LONGITUDE", "ELEVATION",
    "NAME", "REPORT_TYPE", "VIS", "Q_VIS", "LI", "DS", "VS_CODE",
    "VS_KMH_RANGE",
]

VALID_VV_CODES = {str(code) for code in range(90, 100)}


def _clean(value) -> str:
    return "" if value is None else str(value).strip()


def _parse_finite(value):
    text = _clean(value)
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def _format_number(value: float, decimals: int = 2) -> str:
    text = f"{value:.{decimals}f}".rstrip("0").rstrip(".")
    return "0" if text in {"", "-0"} else text


def _parse_int(value, minimum, maximum):
    number = _parse_finite(value)
    if number is None or not number.is_integer():
        return None
    integer = int(number)
    return integer if minimum <= integer <= maximum else None


def _parse_hundredths(value, minimum, maximum):
    """IMMA 原始 HR/LAT/LON 使用隐含百分之一单位；已含小数点的视为已转换。"""
    text = _clean(value)
    number = _parse_finite(text)
    if number is None:
        return None
    converted = number if "." in text else number / 100.0
    return converted if minimum <= converted <= maximum else None


def build_date(row: dict):
    year = _parse_int(row.get("YR"), 1600, 2200)
    month = _parse_int(row.get("MO"), 1, 12)
    day = _parse_int(row.get("DY"), 1, 31)
    decimal_hour = _parse_hundredths(row.get("HR"), 0.0, 23.99)

    if year is None or month is None or day is None:
        return None, "invalid_ymd"
    if decimal_hour is None:
        return None, "invalid_hr"
    try:
        base = datetime(year, month, day)
    except ValueError:
        return None, "invalid_calendar_date"
    seconds = round(decimal_hour * 3600)
    return (base + timedelta(seconds=seconds)).strftime("%Y-%m-%d %H:%M:%S"), None


def clean_row(row: dict, counters: Counter):
    date_text, date_error = build_date(row)
    if date_error is not None:
        counters[f"deleted_{date_error}"] += 1
        return None

    latitude = _parse_hundredths(row.get("LAT"), -90.0, 90.0)
    if latitude is None:
        counters["deleted_invalid_lat"] += 1
        return None

    longitude = _parse_hundredths(row.get("LON"), -179.99, 359.99)
    if longitude is None:
        counters["deleted_invalid_lon"] += 1
        return None
    if longitude < 0:
        longitude += 360.0

    station = _clean(row.get("ID"))
    if not 1 <= len(station) <= 9 or VALID_ID_RE.fullmatch(station) is None:
        counters["deleted_invalid_id"] += 1
        return None

    vv_m = _clean(row.get("VV_M"))
    if not vv_m:
        counters["deleted_empty_vv_m"] += 1
        return None
    vv_code = _clean(row.get("VV_CODE"))
    if vv_code not in VALID_VV_CODES:
        counters["deleted_invalid_vv_code"] += 1
        return None

    counters["kept_rows"] += 1
    return {
        "STATION": station,
        "DATE": date_text,
        "SOURCE": _clean(row.get("II")),
        "LATITUDE": _format_number(latitude),
        "LONGITUDE": _format_number(longitude),
        "ELEVATION": "",
        "NAME": station,
        "REPORT_TYPE": _clean(row.get("VI")),
        "VIS": vv_m,
        "Q_VIS": vv_code,
        "LI": _clean(row.get("LI")),
        "DS": _clean(row.get("DS")),
        "VS_CODE": _clean(row.get("VS_CODE")),
        "VS_KMH_RANGE": _clean(row.get("VS_KMH_RANGE")),
    }


def normalize_file(input_path: Path, output_path: Path,
                   overwrite: bool = False) -> Counter:
    counters = Counter()
    temp_path = output_path.with_suffix(output_path.suffix + ".tmp")
    if temp_path.exists():
        raise FileExistsError(f"发现遗留临时文件：{temp_path}")
    if output_path.exists() and not overwrite:
        raise FileExistsError(f"输出已存在：{output_path}")
    if output_path.exists():
        output_path.unlink()

    try:
        with input_path.open("r", encoding="utf-8-sig", newline="") as src, \
                temp_path.open("x", encoding="utf-8-sig", newline="") as dst:
            reader = csv.DictReader(src)
            if reader.fieldnames != INPUT_COLUMNS:
                raise ValueError(
                    f"输入表头不符合预期：{input_path}\n"
                    f"实际：{reader.fieldnames}\n预期：{INPUT_COLUMNS}")
            writer = csv.DictWriter(dst, fieldnames=OUTPUT_COLUMNS,
                                    extrasaction="raise")
            writer.writeheader()
            for row in reader:
                counters["input_rows"] += 1
                cleaned = clean_row(row, counters)
                if cleaned is not None:
                    writer.writerow(cleaned)
            dst.flush()
            os.fsync(dst.fileno())
        os.replace(temp_path, output_path)
        return counters
    except Exception:
        if temp_path.exists():
            temp_path.unlink()
        raise


def normalize_dir(input_dir: str | Path, output_dir: str | Path,
                  pattern: str = "IMMA1_*_VI1.csv", overwrite: bool = False,
                  progress: Callable[[str], None] = print) -> Counter:
    input_dir, output_dir = Path(input_dir), Path(output_dir)
    if not input_dir.is_dir():
        raise FileNotFoundError(f"输入目录不存在：{input_dir}")
    files = sorted(input_dir.glob(pattern))
    if not files:
        raise FileNotFoundError(f"没有找到输入文件：{input_dir / pattern}")
    output_dir.mkdir(parents=True, exist_ok=True)

    overall = Counter()
    for i, path in enumerate(files, start=1):
        out_path = output_dir / path.name
        if out_path.exists() and not overwrite:
            progress(f"[{i}/{len(files)}] {path.name} 输出已存在，跳过")
            overall["skipped_existing"] += 1
            continue
        c = normalize_file(path, out_path, overwrite=overwrite)
        overall.update(c)
        deleted = c["input_rows"] - c["kept_rows"]
        progress(f"[{i}/{len(files)}] {path.name}: 输入={c['input_rows']:,}，"
                 f"保留={c['kept_rows']:,}，删除={deleted:,}")
    progress(f"规整完成：输入 {overall['input_rows']:,} 行，"
             f"保留 {overall['kept_rows']:,} 行")
    return overall
