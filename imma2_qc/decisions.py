"""人工决定持久化。

界面中的框选删除 / 恢复操作以 UID 为键保存到 CSV，
重新打开数据或重新运行自动质控后仍然生效。
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from . import flags
from .io_utils import UID_COL

ACTION_DELETE = "delete"   # 人工删除（含删除程序未发现的离群点）
ACTION_KEEP = "keep"       # 人工恢复（推翻程序的自动删除）
ACTION_REPAIR = "repair"   # 采纳镜像修复建议（导出时替换坐标）


class DecisionStore:
    """uid -> (action, meta) 的内存表，支持加载/保存 CSV。"""

    COLUMNS = ["UID", "ACTION", "STATION", "DATE", "LAT", "LON", "VALUE", "DECIDED_AT"]

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else None
        self._rows: dict[str, dict] = {}
        if self.path and self.path.exists():
            self.load(self.path)

    def __len__(self) -> int:
        return len(self._rows)

    def action_of(self, uid: str) -> str | None:
        row = self._rows.get(uid)
        return row["ACTION"] if row else None

    def set(self, uid: str, action: str, meta: dict | None = None) -> None:
        if action not in (ACTION_DELETE, ACTION_KEEP, ACTION_REPAIR):
            raise ValueError(f"未知的人工决定: {action}")
        row = {"UID": uid, "ACTION": action,
               "DECIDED_AT": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        for k in ("STATION", "DATE", "LAT", "LON", "VALUE"):
            row[k] = (meta or {}).get(k, "")
        self._rows[uid] = row

    def clear(self, uid: str) -> None:
        self._rows.pop(uid, None)

    def load(self, path: str | Path) -> None:
        df = pd.read_csv(path, dtype=str, keep_default_na=False)
        for _, r in df.iterrows():
            if r.get("ACTION") in (ACTION_DELETE, ACTION_KEEP, ACTION_REPAIR):
                self._rows[r["UID"]] = dict(r)

    def save(self, path: str | Path | None = None) -> Path:
        if path is None and self.path is None:
            raise ValueError("未指定人工决定文件路径")
        path = Path(path or self.path)
        path.parent.mkdir(parents=True, exist_ok=True)
        df = pd.DataFrame(list(self._rows.values()), columns=self.COLUMNS)
        df.to_csv(path, index=False, encoding="utf-8")
        self.path = path
        return path

    def manual_column(self, df: pd.DataFrame) -> pd.Series:
        """返回与 df 对齐的人工决定列：MANUAL_DELETE / MANUAL_KEEP / 空字符串。"""
        action_to_flag = {ACTION_DELETE: flags.MANUAL_DELETE,
                          ACTION_KEEP: flags.MANUAL_KEEP,
                          ACTION_REPAIR: flags.MANUAL_REPAIR}
        mapping = {uid: action_to_flag[r["ACTION"]]
                   for uid, r in self._rows.items()}
        return df[UID_COL].map(mapping).fillna("")
