"""第1步 数据提取：原始 IMMA1 定宽报文 → 月度 CSV。

对应 step.1.数据提取_航速修订.py：
  - 扫描 IMMA1_R*_YYYY-MM 文件，同月多个 R 版本取版本号最高者；
  - 跳过 Uida 附加记录（9815 开头）与过短行；
  - WMO Code 4377：VV 编码 90-99 转换为能见度（m），90→25、99→50000；
  - VI=2 且 VV=93 的历史特殊组合表示有雾未报能见度，VV_M 置空；
  - DS/VS_CODE 零值互补（只填缺失，不覆盖已有观测）；
  - VS_CODE=9（>40 节，无有限上限）整行剔除；
  - 输出 IMMA1_YYYY-MM_VI1.csv。
"""
from __future__ import annotations

import csv
import os
import re
from collections import Counter
from pathlib import Path
from typing import Callable

VV_CODE_TO_M = {
    "90": "25", "91": "50", "92": "200", "93": "500", "94": "1000",
    "95": "2000", "96": "4000", "97": "10000", "98": "20000", "99": "50000",
}

VS_CODE_TO_KMH_MAX = {
    "0": "0", "1": "9.26", "2": "18.52", "3": "27.78", "4": "37.04",
    "5": "46.30", "6": "55.56", "7": "64.82", "8": "74.08",
}

SOURCE_PATTERN = re.compile(r"^IMMA1_R(?P<version>[^_]+)_(?P<year>\d{4})-(?P<month>\d{2})$")

OUTPUT_COLUMNS = [
    "YR", "MO", "DY", "HR", "LAT", "LON", "ATTC", "TI", "LI",
    "DS", "VS_CODE", "VS_KMH_RANGE", "II", "ID", "VI",
    "VV_CODE", "VV_M", "VV_NOTE",
]


def _version_key(version: str):
    """3.1.0、3.0.3T 等版本号转成可自然排序的键。"""
    return tuple(int(p) if p.isdigit() else p.upper()
                 for p in re.split(r"(\d+)", version) if p)


def scan_raw_files(raw_dir: str | Path) -> dict[tuple[int, int], list[tuple[str, str]]]:
    """(年, 月) -> [(版本, 路径)]。"""
    index: dict[tuple[int, int], list[tuple[str, str]]] = {}
    for entry in os.scandir(raw_dir):
        if not entry.is_file():
            continue
        m = SOURCE_PATTERN.fullmatch(entry.name)
        if not m:
            continue
        key = (int(m.group("year")), int(m.group("month")))
        index.setdefault(key, []).append((m.group("version"), entry.path))
    return index


def extract_month(file_path: str | Path, save_path: str | Path) -> Counter:
    """提取单个月度报文文件，返回统计。"""
    c = Counter()
    records: list[dict] = []

    # IMMA1 是固定宽度 ASCII；strict 避免忽略坏字节后字段错位
    with open(file_path, encoding="ascii", errors="strict") as f:
        for line in f:
            c["total_lines"] += 1
            record = line.rstrip("\r\n")

            # Subsidiary record 以 Uida attm 的“9815”开头，不含 Core
            if record.startswith("9815") or len(record) < 56:
                continue

            vi = record[53].strip()
            vv_code = record[54:56].strip()
            ds = record[28].strip()
            vs_code = record[29].strip()

            # 零值互补：只填缺失值，不覆盖已有观测
            if ds == "0" and vs_code == "":
                vs_code = "0"
                c["complemented_vs"] += 1
            elif vs_code == "0" and ds == "":
                ds = "0"
                c["complemented_ds"] += 1

            if vs_code == "9":
                c["dropped_vs9"] += 1
                continue

            if vv_code not in VV_CODE_TO_M:
                continue

            vv_m = VV_CODE_TO_M[vv_code]
            vv_note = ""
            # 历史特殊组合：有雾但未报告实际能见度，不能当作 0.5 km
            if vi == "2" and vv_code == "93":
                vv_m = ""
                vv_note = "fog_present_visibility_not_reported"

            records.append({
                "YR": record[0:4], "MO": record[4:6], "DY": record[6:8],
                "HR": record[8:12], "LAT": record[12:17], "LON": record[17:23],
                "ATTC": record[25] if len(record) > 25 else "",
                "TI": record[26] if len(record) > 26 else "",
                "LI": record[27] if len(record) > 27 else "",
                "DS": ds, "VS_CODE": vs_code,
                "VS_KMH_RANGE": VS_CODE_TO_KMH_MAX.get(vs_code, ""),
                "II": record[32:34], "ID": record[34:43].strip(),
                "VI": vi, "VV_CODE": vv_code, "VV_M": vv_m, "VV_NOTE": vv_note,
            })
            c["kept_lines"] += 1

    with open(save_path, "w", encoding="utf-8", newline="") as out:
        writer = csv.DictWriter(out, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(records)
    return c


def extract_raw(raw_dir: str | Path, out_dir: str | Path,
                start_year: int | None = None, end_year: int | None = None,
                overwrite: bool = False,
                progress: Callable[[str], None] = print) -> Counter:
    """提取整个目录。年份范围缺省时处理扫描到的全部年月。"""
    raw_dir, out_dir = Path(raw_dir), Path(out_dir)
    if not raw_dir.is_dir():
        raise FileNotFoundError(f"原始数据目录不存在：{raw_dir}")
    index = scan_raw_files(raw_dir)
    if not index:
        raise FileNotFoundError(f"目录中没有 IMMA1_R*_YYYY-MM 报文文件：{raw_dir}")
    out_dir.mkdir(parents=True, exist_ok=True)

    keys = sorted(k for k in index
                  if (start_year is None or k[0] >= start_year)
                  and (end_year is None or k[0] <= end_year))
    overall = Counter()
    for i, (year, month) in enumerate(keys, start=1):
        candidates = index[(year, month)]
        version, file_path = max(candidates, key=lambda it: _version_key(it[0]))
        if len(candidates) > 1:
            versions = ", ".join(v for v, _ in sorted(candidates, key=lambda it: _version_key(it[0])))
            progress(f"{year}-{month:02d} 检测到多个版本（{versions}），使用 R{version}")

        save_path = out_dir / f"IMMA1_{year}-{month:02d}_VI1.csv"
        if save_path.exists() and not overwrite:
            progress(f"[{i}/{len(keys)}] {save_path.name} 已存在，跳过")
            overall["skipped_existing"] += 1
            continue
        try:
            c = extract_month(file_path, save_path)
        except Exception as e:
            progress(f"[{i}/{len(keys)}] {year}-{month:02d} 处理失败：{e}")
            overall["failed_months"] += 1
            continue
        overall.update(c)
        overall["months"] += 1
        progress(f"[{i}/{len(keys)}] {year}-{month:02d}：总行数={c['total_lines']}，"
                 f"删VS9={c['dropped_vs9']}，DS补0={c['complemented_ds']}，"
                 f"VS补0={c['complemented_vs']}，保留={c['kept_lines']}")
    progress(f"提取完成：{overall['months']} 个月，保留 {overall['kept_lines']} 条")
    return overall
