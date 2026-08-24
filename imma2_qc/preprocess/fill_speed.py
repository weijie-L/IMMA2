"""第3步 航速填补：DS / VS_CODE 缺失值填补（直接改写规整清洗目录中的 CSV）。

两个子步骤，均只填空值、不覆盖已有观测：

1. 移动站前后夹逼填补（对应 step.1.1.1_移动站填补）：
   用 SQLite 临时索引跨月寻找同站前后有效记录，前后代码一致时：
     - 前后间隔均 ≤1 小时 → INTERP_1H；
     - 前后跨度 ≤3 小时且三点 VIS 完全相同 → INTERP_3H_VIS；
   同刻代码冲突、边界代码冲突等情况一律不填。

2. 固定站零航速填补（对应 step.1.1.1_固定站填补，按单个文件判断）：
   站点在该文件内出现过 DS=0 且 VS_CODE=0，且所有非空 DS/VS 都为 0，
   才把该站空缺的 DS/VS_CODE/VS_KMH_RANGE 填 0。
"""
from __future__ import annotations

import csv
import os
import sqlite3
from collections import Counter
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Callable

ENCODING = "utf-8-sig"
FILE_PATTERN = "IMMA1_*_VI1.csv"
STATION_COLUMN_CANDIDATES = ("STATION", "ID")
VIS_COLUMN_CANDIDATES = ("VIS", "VV_M")

VS_CODE_TO_KMH_RANGE = {
    "0": "0", "1": "9.26", "2": "18.52", "3": "27.78", "4": "37.04",
    "5": "46.30", "6": "55.56", "7": "64.82", "8": "74.08",
}
VALID_DS_CODES = {str(code) for code in range(10)}

ONE_HOUR = 3600
THREE_HOURS = 3 * 3600
EPOCH = datetime(1970, 1, 1)


def _clean(value) -> str:
    return "" if value is None else str(value).strip()


def _find_column(fieldnames, candidates, label, path):
    for column in candidates:
        if column in fieldnames:
            return column
    raise ValueError(f"找不到{label}列{candidates}：{path}")


def _validate_header(fieldnames, path):
    if fieldnames is None:
        raise ValueError(f"CSV没有表头：{path}")
    station_col = _find_column(fieldnames, STATION_COLUMN_CANDIDATES, "站点", path)
    vis_col = _find_column(fieldnames, VIS_COLUMN_CANDIDATES, "能见度", path)
    missing = {"DS", "VS_CODE", "VS_KMH_RANGE"}.difference(fieldnames)
    if missing:
        raise ValueError(f"缺少必要字段{sorted(missing)}：{path}")
    if "DATE" not in fieldnames and not {"YR", "MO", "DY", "HR"}.issubset(fieldnames):
        raise ValueError(f"缺少DATE或YR/MO/DY/HR日期字段：{path}")
    return station_col, vis_col


def _parse_int(value, minimum, maximum):
    text = _clean(value)
    if not text:
        return None
    try:
        number = Decimal(text)
    except InvalidOperation:
        return None
    if number != number.to_integral_value():
        return None
    result = int(number)
    return result if minimum <= result <= maximum else None


def _parse_timestamp(row):
    date_text = _clean(row.get("DATE"))
    if date_text:
        try:
            value = datetime.strptime(date_text, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None
        return int((value - EPOCH).total_seconds())

    year = _parse_int(row.get("YR"), 1600, 2200)
    month = _parse_int(row.get("MO"), 1, 12)
    day = _parse_int(row.get("DY"), 1, 31)
    hr_text = _clean(row.get("HR"))
    if year is None or month is None or day is None or not hr_text:
        return None
    try:
        raw_hour = Decimal(hr_text)
    except InvalidOperation:
        return None
    decimal_hour = raw_hour if "." in hr_text else raw_hour / Decimal(100)
    if not Decimal("0") <= decimal_hour <= Decimal("23.99"):
        return None
    seconds = int((decimal_hour * Decimal(3600))
                  .to_integral_value(rounding=ROUND_HALF_UP))
    try:
        value = datetime(year, month, day) + timedelta(seconds=seconds)
    except ValueError:
        return None
    return int((value - EPOCH).total_seconds())


def _normalize_vis(value):
    """让 20000 与 20000.0 在 VIS 比较时视为相同。"""
    text = _clean(value)
    if not text:
        return ""
    try:
        number = Decimal(text)
    except InvalidOperation:
        return text
    if not number.is_finite():
        return text
    normalized = format(number.normalize(), "f")
    return "0" if Decimal(normalized) == 0 else normalized


def _valid_ds(value):
    return value in VALID_DS_CODES


def _valid_vs(value):
    return value in VS_CODE_TO_KMH_RANGE


# ============================================================
# 移动站前后夹逼填补
# ============================================================

def _create_database(connection):
    connection.executescript("""
        PRAGMA journal_mode = OFF;
        PRAGMA synchronous = OFF;
        PRAGMA temp_store = MEMORY;
        CREATE TABLE records (
            station TEXT NOT NULL, timestamp INTEGER NOT NULL,
            file_index INTEGER NOT NULL, row_number INTEGER NOT NULL,
            ds TEXT NOT NULL, vs_code TEXT NOT NULL,
            vs_range TEXT NOT NULL, vis TEXT NOT NULL
        );
        CREATE TABLE fills (
            file_index INTEGER NOT NULL, row_number INTEGER NOT NULL,
            candidate_ds TEXT NOT NULL, candidate_vs TEXT NOT NULL,
            candidate_range TEXT NOT NULL, rule TEXT NOT NULL,
            PRIMARY KEY (file_index, row_number)
        );
    """)


def _index_files(connection, input_files, progress):
    counters = Counter()
    insert_sql = "INSERT INTO records VALUES (?, ?, ?, ?, ?, ?, ?, ?)"

    for file_index, path in enumerate(input_files):
        batch = []
        with path.open("r", encoding=ENCODING, newline="") as source:
            reader = csv.DictReader(source)
            station_col, vis_col = _validate_header(reader.fieldnames, path)
            for row_number, row in enumerate(reader, start=2):
                counters["input_rows"] += 1
                station = _clean(row.get(station_col))
                timestamp = _parse_timestamp(row)
                if not station or timestamp is None:
                    continue
                ds = _clean(row.get("DS"))
                vs_code = _clean(row.get("VS_CODE"))
                # 只索引可能作为有效边界或需要填补的记录
                is_reference = _valid_ds(ds) and _valid_vs(vs_code)
                is_target = ds == "" or vs_code == ""
                if not is_reference and not is_target:
                    continue
                batch.append((station, timestamp, file_index, row_number,
                              ds, vs_code, _clean(row.get("VS_KMH_RANGE")),
                              _normalize_vis(row.get(vis_col))))
                if len(batch) >= 50_000:
                    connection.executemany(insert_sql, batch)
                    batch.clear()
        if batch:
            connection.executemany(insert_sql, batch)
        connection.commit()
        progress(f"[建索引 {file_index + 1}/{len(input_files)}] {path.name}")

    connection.execute(
        "CREATE INDEX idx_records_station_time "
        "ON records(station, timestamp, file_index, row_number)")
    connection.commit()
    return counters


def _choose_reference(time_group):
    """返回同一时刻唯一一致的有效代码；存在多组代码时返回冲突标记。"""
    references = [r for r in time_group if _valid_ds(r[4]) and _valid_vs(r[5])]
    code_pairs = {(r[4], r[5]) for r in references}
    if len(code_pairs) > 1:
        return None, True
    if not references:
        return None, False
    ds, vs_code = next(iter(code_pairs))
    vis_values = {r[7] for r in references if r[7] != ""}
    reference_vis = next(iter(vis_values)) if len(vis_values) == 1 else ""
    ranges = {r[6] for r in references if r[6] != ""}
    reference_range = (next(iter(ranges)) if len(ranges) == 1
                       else VS_CODE_TO_KMH_RANGE.get(vs_code, ""))
    return {"timestamp": references[0][1], "ds": ds, "vs_code": vs_code,
            "vs_range": reference_range, "vis": reference_vis}, False


def _resolve_pending(connection, previous_ref, next_ref, pending, counters):
    if previous_ref is None or next_ref is None:
        return
    if (previous_ref["ds"] != next_ref["ds"]
            or previous_ref["vs_code"] != next_ref["vs_code"]):
        counters["rejected_boundary_code_conflict"] += len(pending)
        return

    candidate_ds = previous_ref["ds"]
    candidate_vs = previous_ref["vs_code"]
    if previous_ref["vs_range"] and previous_ref["vs_range"] == next_ref["vs_range"]:
        candidate_range = previous_ref["vs_range"]
    else:
        candidate_range = VS_CODE_TO_KMH_RANGE.get(candidate_vs, "")

    insert_sql = "INSERT OR IGNORE INTO fills VALUES (?, ?, ?, ?, ?, ?)"
    for target in pending:
        target_time, target_ds, target_vs, target_vis = (
            target[1], target[4], target[5], target[7])
        if not previous_ref["timestamp"] < target_time < next_ref["timestamp"]:
            counters["rejected_not_strictly_between"] += 1
            continue
        # 已有一半代码时，它必须和两侧候选代码一致
        if target_ds not in {"", candidate_ds}:
            counters["rejected_existing_ds_conflict"] += 1
            continue
        if target_vs not in {"", candidate_vs}:
            counters["rejected_existing_vs_conflict"] += 1
            continue

        before_gap = target_time - previous_ref["timestamp"]
        after_gap = next_ref["timestamp"] - target_time
        if before_gap <= ONE_HOUR and after_gap <= ONE_HOUR:
            rule = "INTERP_1H"
        elif (next_ref["timestamp"] - previous_ref["timestamp"] <= THREE_HOURS
              and target_vis != ""
              and previous_ref["vis"] == target_vis == next_ref["vis"]):
            rule = "INTERP_3H_VIS"
        else:
            counters["rejected_time_or_vis"] += 1
            continue

        connection.execute(insert_sql, (target[2], target[3], candidate_ds,
                                        candidate_vs, candidate_range, rule))
        counters[f"selected_{rule.lower()}"] += 1


def _build_fill_plan(connection):
    """按站点、时间流式处理，每次只保留一个站点的一小段记录。"""
    counters = Counter()
    cursor = connection.execute(
        "SELECT station, timestamp, file_index, row_number, "
        "ds, vs_code, vs_range, vis FROM records "
        "ORDER BY station, timestamp, file_index, row_number")

    current_station = None
    current_timestamp = None
    time_group: list = []
    previous_ref = None
    pending: list = []

    def process_time_group(group, previous, waiting):
        if not group:
            return previous, waiting
        reference, conflict = _choose_reference(group)
        group_targets = [r for r in group if r[4] == "" or r[5] == ""]
        if conflict:
            counters["conflicting_timestamp_groups"] += 1
            counters["rejected_across_conflict"] += len(waiting)
            return None, []
        if reference is not None:
            _resolve_pending(connection, previous, reference, waiting, counters)
            # 同时刻既有有效代码又有空代码时，不属于前后夹逼，不填
            counters["same_timestamp_targets_not_filled"] += len(group_targets)
            return reference, []
        if previous is not None:
            waiting.extend(group_targets)
        else:
            counters["targets_without_previous_reference"] += len(group_targets)
        return previous, waiting

    for row in cursor:
        station, timestamp = row[0], row[1]
        if current_station is None:
            current_station, current_timestamp = station, timestamp
        if station != current_station:
            previous_ref, pending = process_time_group(time_group, previous_ref, pending)
            counters["targets_without_next_reference"] += len(pending)
            counters["stations_processed"] += 1
            current_station, current_timestamp = station, timestamp
            time_group, previous_ref, pending = [], None, []
        elif timestamp != current_timestamp:
            previous_ref, pending = process_time_group(time_group, previous_ref, pending)
            current_timestamp = timestamp
            time_group = []
        time_group.append(row)

    if time_group:
        previous_ref, pending = process_time_group(time_group, previous_ref, pending)
        counters["targets_without_next_reference"] += len(pending)
        counters["stations_processed"] += 1

    connection.commit()
    counters["planned_fills"] = connection.execute(
        "SELECT COUNT(*) FROM fills").fetchone()[0]
    return counters


def _rewrite_with_fills(connection, file_index, path):
    fill_rows = connection.execute(
        "SELECT row_number, candidate_ds, candidate_vs, candidate_range, rule "
        "FROM fills WHERE file_index = ?", (file_index,)).fetchall()
    if not fill_rows:
        return Counter(skipped_unchanged_file=1)

    fill_map = {rn: (ds, vs, rg, rule) for rn, ds, vs, rg, rule in fill_rows}
    temp_path = path.with_suffix(path.suffix + ".moving_fill.tmp")
    if temp_path.exists():
        raise FileExistsError(f"发现遗留临时文件：{temp_path}")

    counters = Counter()
    try:
        with path.open("r", encoding=ENCODING, newline="") as src, \
                temp_path.open("x", encoding=ENCODING, newline="") as dst:
            reader = csv.DictReader(src)
            _validate_header(reader.fieldnames, path)
            writer = csv.DictWriter(dst, fieldnames=reader.fieldnames,
                                    extrasaction="raise")
            writer.writeheader()
            for row_number, row in enumerate(reader, start=2):
                counters["input_rows"] += 1
                fill = fill_map.get(row_number)
                if fill is not None:
                    candidate_ds, candidate_vs, candidate_range, rule = fill
                    changed = False
                    if _clean(row["DS"]) == "":
                        row["DS"] = candidate_ds
                        counters["filled_ds"] += 1
                        changed = True
                    if _clean(row["VS_CODE"]) == "":
                        row["VS_CODE"] = candidate_vs
                        counters["filled_vs_code"] += 1
                        changed = True
                    if _clean(row["VS_KMH_RANGE"]) == "":
                        row["VS_KMH_RANGE"] = candidate_range
                        counters["filled_vs_kmh_range"] += 1
                        changed = True
                    if changed:
                        counters["changed_rows"] += 1
                        counters[f"changed_{rule.lower()}"] += 1
                writer.writerow(row)
                counters["output_rows"] += 1
            dst.flush()
            os.fsync(dst.fileno())

        if counters["input_rows"] != counters["output_rows"]:
            raise ValueError(f"写出行数不一致：{path.name}")
        os.replace(temp_path, path)
        return counters
    except Exception:
        if temp_path.exists():
            temp_path.unlink()
        raise


def fill_moving_stations(data_dir: str | Path,
                         progress: Callable[[str], None] = print) -> Counter:
    """移动站前后夹逼填补，直接改写目录中的 CSV。"""
    data_dir = Path(data_dir)
    if not data_dir.is_dir():
        raise FileNotFoundError(f"数据目录不存在：{data_dir}")
    index_db = data_dir / "_moving_station_fill_index.sqlite"
    if index_db.exists():
        raise FileExistsError(
            f"发现遗留索引文件：{index_db}。请确认没有其他实例运行后删除再试。")
    input_files = sorted(data_dir.glob(FILE_PATTERN))
    if not input_files:
        raise FileNotFoundError(f"没有找到文件：{data_dir / FILE_PATTERN}")

    connection = None
    overall = Counter()
    try:
        connection = sqlite3.connect(index_db)
        _create_database(connection)
        progress("移动站填补 1/3：建立跨月站点时间索引")
        _index_files(connection, input_files, progress)

        progress("移动站填补 2/3：生成前后夹逼填补计划")
        plan = _build_fill_plan(connection)
        progress(f"处理站点数：{plan['stations_processed']:,}，"
                 f"1小时规则：{plan['selected_interp_1h']:,}，"
                 f"3小时+VIS规则：{plan['selected_interp_3h_vis']:,}，"
                 f"计划填补：{plan['planned_fills']:,}")
        overall.update(plan)

        progress("移动站填补 3/3：改写 CSV")
        for file_index, path in enumerate(input_files):
            stats = _rewrite_with_fills(connection, file_index, path)
            overall.update(stats)
            if not stats["skipped_unchanged_file"]:
                progress(f"[改写 {file_index + 1}/{len(input_files)}] "
                         f"{path.name}: 修改行={stats['changed_rows']:,}")
        progress(f"移动站填补完成：修改 {overall['changed_rows']:,} 行"
                 f"（DS={overall['filled_ds']:,}，VS={overall['filled_vs_code']:,}）")
        return overall
    finally:
        if connection is not None:
            connection.close()
        if index_db.exists():
            index_db.unlink()


# ============================================================
# 固定站零航速填补（按单个文件判断）
# ============================================================

def _collect_file_station_states(path: Path):
    """站点可填补条件：该文件内出现过 DS=0 且 VS=0，且所有非空 DS/VS 均为 0。"""
    states: dict[str, dict] = {}
    with path.open("r", encoding=ENCODING, newline="") as source:
        reader = csv.DictReader(source)
        station_col, _ = _validate_header(reader.fieldnames, path)
        for row in reader:
            station = _clean(row.get(station_col))
            if not station:
                continue
            ds = _clean(row.get("DS"))
            vs_code = _clean(row.get("VS_CODE"))
            state = states.setdefault(station, {
                "seen_zero_pair": False, "has_nonzero_ds": False,
                "has_nonzero_vs": False})
            if ds == "0" and vs_code == "0":
                state["seen_zero_pair"] = True
            if ds not in {"", "0"}:
                state["has_nonzero_ds"] = True
            if vs_code not in {"", "0"}:
                state["has_nonzero_vs"] = True
    return {st for st, s in states.items()
            if s["seen_zero_pair"] and not s["has_nonzero_ds"]
            and not s["has_nonzero_vs"]}


def _rewrite_fixed_fill(path: Path, eligible_stations: set) -> Counter:
    temp_path = path.with_suffix(path.suffix + ".station_fill.tmp")
    if temp_path.exists():
        raise FileExistsError(f"发现遗留临时文件：{temp_path}")
    counters = Counter()
    try:
        with path.open("r", encoding=ENCODING, newline="") as src, \
                temp_path.open("x", encoding=ENCODING, newline="") as dst:
            reader = csv.DictReader(src)
            station_col, _ = _validate_header(reader.fieldnames, path)
            writer = csv.DictWriter(dst, fieldnames=reader.fieldnames,
                                    extrasaction="raise")
            writer.writeheader()
            for row in reader:
                counters["input_rows"] += 1
                if _clean(row.get(station_col)) in eligible_stations:
                    changed = False
                    for column in ("DS", "VS_CODE", "VS_KMH_RANGE"):
                        if _clean(row[column]) == "":
                            row[column] = "0"
                            counters[f"filled_{column.lower()}"] += 1
                            changed = True
                    if changed:
                        counters["changed_rows"] += 1
                writer.writerow(row)
                counters["output_rows"] += 1
            dst.flush()
            os.fsync(dst.fileno())
        if counters["input_rows"] != counters["output_rows"]:
            raise ValueError(f"写出行数不一致：{path.name}")
        os.replace(temp_path, path)
        return counters
    except Exception:
        if temp_path.exists():
            temp_path.unlink()
        raise


def fill_fixed_stations(data_dir: str | Path,
                        progress: Callable[[str], None] = print) -> Counter:
    """固定站零航速填补，按单个文件判断并直接改写。"""
    data_dir = Path(data_dir)
    if not data_dir.is_dir():
        raise FileNotFoundError(f"数据目录不存在：{data_dir}")
    input_files = sorted(data_dir.glob(FILE_PATTERN))
    if not input_files:
        raise FileNotFoundError(f"没有找到文件：{data_dir / FILE_PATTERN}")

    overall = Counter()
    for i, path in enumerate(input_files, start=1):
        eligible = _collect_file_station_states(path)
        counters = _rewrite_fixed_fill(path, eligible)
        overall.update(counters)
        overall["eligible_stations"] += len(eligible)
        progress(f"[固定站填补 {i}/{len(input_files)}] {path.name}: "
                 f"可填站点={len(eligible):,}，修改行={counters['changed_rows']:,}")
    progress(f"固定站填补完成：修改 {overall['changed_rows']:,} 行"
             f"（DS={overall['filled_ds']:,}，VS={overall['filled_vs_code']:,}）")
    return overall
