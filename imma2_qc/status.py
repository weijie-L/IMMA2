"""记录状态计算：自动质控结果 + 人工决定 → 界面显示状态。"""
from __future__ import annotations

import pandas as pd

from . import flags
from .decisions import DecisionStore
from .qc.basic import QC_FLAG_COL, REVIEW_COL

STATUS_KEPT = "kept"              # 保留
STATUS_AUTO_DEL = "auto_del"      # 程序自动删除（可人工恢复）
STATUS_REVIEW = "review"          # 保留但待人工复核
STATUS_MANUAL_DEL = "manual_del"  # 人工删除
STATUS_MANUAL_KEEP = "manual_keep"  # 人工恢复（推翻自动删除）

STATUS_LABELS = {
    STATUS_KEPT: "保留",
    STATUS_AUTO_DEL: "自动删除",
    STATUS_REVIEW: "待复核",
    STATUS_MANUAL_DEL: "人工删除",
    STATUS_MANUAL_KEEP: "人工恢复",
}

DELETED_STATUSES = (STATUS_AUTO_DEL, STATUS_MANUAL_DEL)


def compute_status(df: pd.DataFrame, decisions: DecisionStore) -> pd.Series:
    manual = decisions.manual_column(df)
    auto_del = df[QC_FLAG_COL] != ""
    review = df[REVIEW_COL] != ""

    status = pd.Series(STATUS_KEPT, index=df.index)
    status[review] = STATUS_REVIEW
    status[auto_del] = STATUS_AUTO_DEL
    status[manual == flags.MANUAL_KEEP] = STATUS_MANUAL_KEEP
    status[manual == flags.MANUAL_DELETE] = STATUS_MANUAL_DEL
    return status
