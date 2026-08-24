"""matplotlib 画布：地图视图与时间序列视图，支持框选。"""
from __future__ import annotations

import matplotlib

matplotlib.use("QtAgg")

import matplotlib.dates as mdates
import numpy as np
import pandas as pd
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from matplotlib.widgets import RectangleSelector
from PySide6.QtCore import Signal

from ..geo import lon_to_pm180
from ..io_utils import UID_COL
from ..qc.basic import (DT_COL, FIX_LAT_COL, FIX_LON_COL, LAT_COL, LON_COL,
                        VALUE_COL)
from ..status import STATUS_LABELS
from . import palette

STATUS_COL = "_STATUS"


class BaseCanvas(FigureCanvasQTAgg):
    """散点 + 框选。子类实现 _coords() 决定坐标映射。"""

    selection_made = Signal(list)  # 框选命中的 UID 列表

    def __init__(self, parent=None):
        fig = Figure(figsize=(8, 5), facecolor=palette.SURFACE)
        super().__init__(fig)
        self.setParent(parent)
        self.ax = fig.add_subplot(111)
        self._style_axes()
        self._xy = np.empty((0, 2))
        self._uids: np.ndarray = np.empty(0, dtype=object)
        self._sel_artist = None
        self._selected: set[str] = set()
        self._selector = RectangleSelector(
            self.ax, self._on_rect, useblit=True, button=[1],
            props=dict(facecolor=palette.SELECT_EDGE, edgecolor=palette.SELECT_EDGE,
                       alpha=0.15, fill=True),
            interactive=False,
        )
        self._selector.set_active(False)

    # ---- 框选 ----
    def set_select_mode(self, on: bool) -> None:
        self._selector.set_active(bool(on))

    def _on_rect(self, eclick, erelease) -> None:
        if len(self._xy) == 0:
            return
        x0, x1 = sorted([eclick.xdata, erelease.xdata])
        y0, y1 = sorted([eclick.ydata, erelease.ydata])
        m = ((self._xy[:, 0] >= x0) & (self._xy[:, 0] <= x1)
             & (self._xy[:, 1] >= y0) & (self._xy[:, 1] <= y1))
        if m.any():
            self.selection_made.emit(list(self._uids[m]))

    def set_selection(self, uids: set[str]) -> None:
        self._selected = set(uids)
        self._draw_selection()
        self.draw_idle()

    def _draw_selection(self) -> None:
        if self._sel_artist is not None:
            self._sel_artist.remove()
            self._sel_artist = None
        if not self._selected or len(self._xy) == 0:
            return
        m = np.isin(self._uids, list(self._selected))
        if not m.any():
            return
        self._sel_artist = self.ax.scatter(
            self._xy[m, 0], self._xy[m, 1], s=90, facecolors="none",
            edgecolors=palette.SELECT_EDGE, linewidths=1.8, zorder=10)

    # ---- 绘制 ----
    def _style_axes(self) -> None:
        self.ax.set_facecolor(palette.SURFACE)
        self.ax.grid(True, color=palette.GRID, linewidth=0.6)
        self.ax.tick_params(colors=palette.INK_MUTED, labelsize=8)
        for s in self.ax.spines.values():
            s.set_color(palette.COAST)

    def plot(self, sub: pd.DataFrame, title: str = "") -> None:
        self.ax.clear()
        self._style_axes()
        self._sel_artist = None
        if len(sub) == 0:
            self._xy = np.empty((0, 2))
            self._uids = np.empty(0, dtype=object)
            self.ax.set_title(title or "无数据", fontsize=10, color=palette.INK_PRIMARY)
            self.draw_idle()
            return
        xs, ys = self._coords(sub)
        self._xy = np.column_stack([xs, ys])
        self._uids = sub[UID_COL].to_numpy(dtype=object)
        self._plot_background(sub)
        handles = []
        for status, (color, marker, size, z) in palette.STATUS_STYLE.items():
            m = (sub[STATUS_COL] == status).to_numpy()
            if not m.any():
                continue
            kw = dict(s=size, marker=marker, zorder=z,
                      label=f"{STATUS_LABELS[status]} ({int(m.sum())})")
            if marker == "x":
                kw.update(c=color, linewidths=1.4)
            elif status == "manual_keep":
                kw.update(facecolors="none", edgecolors=color, linewidths=1.6)
            else:
                kw.update(c=color, edgecolors="none")
            handles.append(self.ax.scatter(xs[m], ys[m], **kw))
        if handles:
            self.ax.legend(loc="best", fontsize=8, framealpha=0.9)
        self.ax.set_title(title, fontsize=10, color=palette.INK_PRIMARY)
        self._finalize_axes(sub)
        self._draw_selection()
        self.figure.tight_layout()
        self.draw_idle()

    # ---- 子类接口 ----
    def _coords(self, sub: pd.DataFrame):
        raise NotImplementedError

    def _plot_background(self, sub: pd.DataFrame) -> None:
        pass

    def _finalize_axes(self, sub: pd.DataFrame) -> None:
        pass


class MapCanvas(BaseCanvas):
    """经纬度散点图，可叠加 GSHHG 海岸线与单站航迹连线。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._coast_xy: np.ndarray | None = None
        self.track_gap_days = 30.0
        self.draw_track = False

    def set_coastlines(self, lines: list[np.ndarray]) -> None:
        """折线列表合并为 NaN 分隔的单一数组，绘制时只调用一次 plot。"""
        if not lines:
            self._coast_xy = None
            return
        sep = np.full((1, 2), np.nan)
        parts: list[np.ndarray] = []
        for seg in lines:
            parts.append(seg)
            parts.append(sep)
        self._coast_xy = np.vstack(parts)

    def _coords(self, sub: pd.DataFrame):
        return lon_to_pm180(sub[LON_COL].to_numpy(float)), sub[LAT_COL].to_numpy(float)

    def _plot_background(self, sub: pd.DataFrame) -> None:
        if self._coast_xy is not None:
            self.ax.plot(self._coast_xy[:, 0], self._coast_xy[:, 1],
                         color=palette.COAST, linewidth=0.5, zorder=1)
        if self.draw_track:
            self._plot_track(sub)
        self._plot_repair_arrows(sub)

    def _plot_repair_arrows(self, sub: pd.DataFrame) -> None:
        """镜像修复：原位置 → 建议位置的箭头。"""
        if FIX_LAT_COL not in sub.columns:
            return
        rows = sub[sub[STATUS_COL].isin(("repair_suggested", "manual_repair"))
                   & sub[FIX_LAT_COL].notna()]
        for _, r in rows.iterrows():
            x0 = float(lon_to_pm180(r.get("_ORIG_LON", r[LON_COL])))
            y0 = float(r.get("_ORIG_LAT", r[LAT_COL]))
            x1 = float(lon_to_pm180(r[FIX_LON_COL]))
            y1 = float(r[FIX_LAT_COL])
            self.ax.annotate(
                "", xy=(x1, y1), xytext=(x0, y0),
                arrowprops=dict(arrowstyle="->", color=palette.REPAIR_ARROW,
                                linewidth=1.1, alpha=0.8),
                zorder=6)

    def _plot_track(self, sub: pd.DataFrame) -> None:
        alive = sub[sub[STATUS_COL].isin(["kept", "review", "manual_keep"])]
        alive = alive.sort_values(DT_COL, kind="mergesort")
        if len(alive) < 2:
            return
        x = lon_to_pm180(alive[LON_COL].to_numpy(float))
        y = alive[LAT_COL].to_numpy(float)
        t = alive[DT_COL]
        gaps = t.diff().dt.total_seconds().to_numpy() / 86400.0
        # 跨 180° 经线或超过时间间隔阈值处断开
        brk = (np.abs(np.diff(x)) > 180.0) | (gaps[1:] > self.track_gap_days)
        start = 0
        for i in list(np.where(brk)[0] + 1) + [len(x)]:
            if i - start >= 2:
                self.ax.plot(x[start:i], y[start:i], color=palette.TRACK_LINE,
                             linewidth=0.9, zorder=2)
            start = i

    def _finalize_axes(self, sub: pd.DataFrame) -> None:
        self.ax.set_xlabel("经度", fontsize=9, color=palette.INK_MUTED)
        self.ax.set_ylabel("纬度", fontsize=9, color=palette.INK_MUTED)
        # 自动缩放到数据范围（留边距），可用工具栏缩放/平移，Home 恢复
        x, y = self._xy[:, 0], self._xy[:, 1]
        mx = max(3.0, (x.max() - x.min()) * 0.08)
        my = max(3.0, (y.max() - y.min()) * 0.08)
        self.ax.set_xlim(max(-185, x.min() - mx), min(185, x.max() + mx))
        self.ax.set_ylim(max(-92, y.min() - my), min(92, y.max() + my))
        self.ax.set_aspect("auto")


class SeriesCanvas(BaseCanvas):
    """观测值时间序列散点图。"""

    def __init__(self, parent=None, value_label: str = "VIS"):
        super().__init__(parent)
        self.value_label = value_label

    def _coords(self, sub: pd.DataFrame):
        return mdates.date2num(sub[DT_COL]), sub[VALUE_COL].to_numpy(float)

    def _finalize_axes(self, sub: pd.DataFrame) -> None:
        self.ax.set_xlabel("时间", fontsize=9, color=palette.INK_MUTED)
        self.ax.set_ylabel(self.value_label, fontsize=9, color=palette.INK_MUTED)
        locator = mdates.AutoDateLocator()
        self.ax.xaxis.set_major_locator(locator)
        self.ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
