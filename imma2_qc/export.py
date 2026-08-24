"""导出：应用自动质控 + 人工决定，输出清洗后的 CSV 与审计文件。

输出结构：
  output_dir/
  ├── <与输入同名的月度 CSV>          清洗后数据（仅业务字段）
  └── _qc_audit/
      ├── summary_YYYY.csv           年度统计
      ├── deleted_records_YYYY.csv   删除记录及原因（含人工删除）
      ├── review_records_YYYY.csv    待人工检查记录
      ├── manual_decisions.csv       全部人工决定
      ├── qc_summary_all_years.csv   全年份汇总
      └── settings.json              本次导出实际使用的配置
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from . import flags
from .config import QCConfig
from .decisions import DecisionStore
from .io_utils import SOURCE_FILE_COL, SOURCE_ROW_COL, UID_COL
from .qc.basic import (FIX_LAT_COL, FIX_LON_COL, FIX_TYPE_COL, QC_FLAG_COL,
                       REVIEW_COL, YEAR_COL)
from .qc.engine import INTERNAL_COLS, summarize

MANUAL_COL = "MANUAL"
FINAL_DELETED_COL = "_FINAL_DELETED"


def apply_decisions(df: pd.DataFrame, decisions: DecisionStore) -> pd.DataFrame:
    """计算最终删除状态：人工决定优先于自动 QC_FLAG。"""
    df = df.copy()
    df[MANUAL_COL] = decisions.manual_column(df)
    auto_deleted = df[QC_FLAG_COL] != ""
    df[FINAL_DELETED_COL] = (
        (auto_deleted & (df[MANUAL_COL] != flags.MANUAL_KEEP))
        | (df[MANUAL_COL] == flags.MANUAL_DELETE)
    )
    return df


def _format_coord(value: float) -> str:
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return "0" if text in {"", "-0"} else text


def _apply_repairs(df: pd.DataFrame, cfg: QCConfig) -> pd.DataFrame:
    """已采纳的镜像修复：把业务经纬度列替换为建议坐标。"""
    if FIX_TYPE_COL not in df.columns:
        return df
    repaired = (df[MANUAL_COL] == flags.MANUAL_REPAIR) & df[FIX_LAT_COL].notna()
    if not repaired.any():
        return df
    df = df.copy()
    df.loc[repaired, cfg.lat_col] = df.loc[repaired, FIX_LAT_COL].map(_format_coord)
    df.loc[repaired, cfg.lon_col] = df.loc[repaired, FIX_LON_COL].map(_format_coord)
    return df


def export_results(df: pd.DataFrame, cfg: QCConfig, decisions: DecisionStore,
                   output_dir: str | Path, overwrite: bool = False) -> Path:
    """导出清洗结果与审计文件，返回输出目录。"""
    output_dir = Path(output_dir)
    if output_dir.exists() and any(output_dir.iterdir()) and not overwrite:
        raise FileExistsError(f"输出目录非空: {output_dir}（确认后使用覆盖导出）")
    audit_dir = output_dir / "_qc_audit"
    audit_dir.mkdir(parents=True, exist_ok=True)

    df = apply_decisions(df, decisions)
    df = _apply_repairs(df, cfg)
    business_cols = [c for c in df.columns
                     if c not in INTERNAL_COLS
                     and c not in (QC_FLAG_COL, REVIEW_COL, MANUAL_COL, FINAL_DELETED_COL,
                                   SOURCE_FILE_COL, SOURCE_ROW_COL, UID_COL)]

    # ---- 清洗后的月度文件（按来源文件分组，保留原始字段与顺序）----
    kept = df[~df[FINAL_DELETED_COL]]
    for fname, g in kept.groupby(SOURCE_FILE_COL, sort=True):
        g.sort_values(SOURCE_ROW_COL)[business_cols].to_csv(
            output_dir / fname, index=False, encoding="utf-8")

    # ---- 审计文件 ----
    audit_cols = business_cols + [QC_FLAG_COL, REVIEW_COL, MANUAL_COL,
                                  SOURCE_FILE_COL, SOURCE_ROW_COL, UID_COL]
    deleted = df[df[FINAL_DELETED_COL]]
    review = kept[kept[REVIEW_COL] != ""]
    repaired = kept[kept[MANUAL_COL] == flags.MANUAL_REPAIR] \
        if FIX_TYPE_COL in df.columns else kept.iloc[0:0]
    from .qc.basic import LAT_COL as _LAT, LON_COL as _LON
    repair_cols = audit_cols + [_LAT, _LON, FIX_TYPE_COL, FIX_LAT_COL, FIX_LON_COL]
    for year in sorted(df[YEAR_COL].unique()):
        d = deleted[deleted[YEAR_COL] == year]
        if len(d):
            d[audit_cols].to_csv(audit_dir / f"deleted_records_{year}.csv",
                                 index=False, encoding="utf-8")
        r = review[review[YEAR_COL] == year]
        if len(r):
            r[audit_cols].to_csv(audit_dir / f"review_records_{year}.csv",
                                 index=False, encoding="utf-8")
        rp = repaired[repaired[YEAR_COL] == year]
        if len(rp):
            rp[repair_cols].rename(columns={
                _LAT: "ORIG_LATITUDE", _LON: "ORIG_LONGITUDE",
                FIX_TYPE_COL: "FIX", FIX_LAT_COL: "FIX_LATITUDE",
                FIX_LON_COL: "FIX_LONGITUDE"}).to_csv(
                audit_dir / f"repaired_records_{year}.csv",
                index=False, encoding="utf-8")

    summary = summarize(df)
    manual_del = df[df[MANUAL_COL] == flags.MANUAL_DELETE].groupby(YEAR_COL).size()
    manual_keep = df[df[MANUAL_COL] == flags.MANUAL_KEEP].groupby(YEAR_COL).size()
    manual_repair = df[df[MANUAL_COL] == flags.MANUAL_REPAIR].groupby(YEAR_COL).size()
    final_kept = kept.groupby(YEAR_COL).size()
    summary["MANUAL_DELETE"] = summary["YEAR"].map(manual_del).fillna(0).astype(int)
    summary["MANUAL_KEEP"] = summary["YEAR"].map(manual_keep).fillna(0).astype(int)
    summary["MANUAL_REPAIR"] = summary["YEAR"].map(manual_repair).fillna(0).astype(int)
    summary["FINAL_KEPT"] = summary["YEAR"].map(final_kept).fillna(0).astype(int)
    for year in summary["YEAR"]:
        summary[summary["YEAR"] == year].to_csv(
            audit_dir / f"summary_{year}.csv", index=False, encoding="utf-8")
    summary.to_csv(audit_dir / "qc_summary_all_years.csv", index=False, encoding="utf-8")

    decisions.save(audit_dir / "manual_decisions.csv")
    (audit_dir / "settings.json").write_text(cfg.to_json(), encoding="utf-8")
    return output_dir
