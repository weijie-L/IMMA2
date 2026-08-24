"""主窗口：数据加载、按年份/站点浏览、框选人工复核、导出。"""
from __future__ import annotations

import json
import traceback
from pathlib import Path

import matplotlib
import pandas as pd
from matplotlib.backends.backend_qtagg import NavigationToolbar2QT
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
    QPlainTextEdit, QPushButton, QSplitter, QTableWidget, QTableWidgetItem,
    QTabWidget, QVBoxLayout, QWidget,
)

from .. import flags
from ..config import QCConfig
from ..decisions import ACTION_DELETE, ACTION_KEEP, DecisionStore
from ..export import export_results
from ..io_utils import UID_COL, find_data_files, load_files
from ..qc.basic import (DT_COL, LAT_COL, LON_COL, QC_FLAG_COL, REVIEW_COL,
                        VALUE_COL, YEAR_COL)
from ..qc.engine import run_qc
from ..status import (DELETED_STATUSES, STATUS_AUTO_DEL, STATUS_LABELS,
                      STATUS_MANUAL_DEL, STATUS_MANUAL_KEEP, STATUS_REVIEW,
                      compute_status)
from .basemap import load_coastlines, load_default_basemap
from .canvas import STATUS_COL, MapCanvas, SeriesCanvas

matplotlib.rcParams["font.sans-serif"] = [
    "Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "WenQuanYi Zen Hei",
    "PingFang SC", "DejaVu Sans", "sans-serif"]
matplotlib.rcParams["axes.unicode_minus"] = False

ALL_STATIONS = "<全部站点>"
TABLE_MAX_ROWS = 5000


class QCWorker(QThread):
    done = Signal(object, object)   # raw_df, qc_df
    failed = Signal(str)

    def __init__(self, input_dir: Path, cfg: QCConfig, raw_df=None):
        super().__init__()
        self.input_dir = input_dir
        self.cfg = cfg
        self.raw_df = raw_df

    def run(self):
        try:
            raw = self.raw_df
            if raw is None:
                files = find_data_files(self.input_dir)
                if not files:
                    raise ValueError(f"目录中没有 CSV 数据文件: {self.input_dir}")
                raw = load_files(files, self.cfg)
            qc = run_qc(raw, self.cfg)
            self.done.emit(raw, qc)
        except Exception:
            self.failed.emit(traceback.format_exc())


class ConfigDialog(QDialog):
    """以 JSON 形式编辑质控参数。"""

    def __init__(self, cfg: QCConfig, parent=None):
        super().__init__(parent)
        self.setWindowTitle("质控参数")
        self.resize(520, 620)
        lay = QVBoxLayout(self)
        self.edit = QPlainTextEdit(cfg.to_json())
        lay.addWidget(self.edit)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)
        self.result_cfg: QCConfig | None = None

    def accept(self):
        try:
            data = json.loads(self.edit.toPlainText())
            self.result_cfg = QCConfig(**{k: v for k, v in data.items()
                                          if k in QCConfig.__dataclass_fields__})
        except Exception as e:
            QMessageBox.warning(self, "参数错误", str(e))
            return
        super().accept()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("IMMA2 质控")
        self.resize(1360, 860)

        self.cfg = QCConfig()
        self.raw_df: pd.DataFrame | None = None
        self.df: pd.DataFrame | None = None
        self.status: pd.Series | None = None
        self.decisions = DecisionStore()
        self.input_dir: Path | None = None
        self.selection: set[str] = set()
        self.worker: QCWorker | None = None

        self._build_ui()
        self._update_enabled()

    # ---------- UI 搭建 ----------
    def _build_ui(self):
        tb = self.addToolBar("main")
        tb.setMovable(False)
        self.act_open = tb.addAction("打开数据目录", self.open_dir)
        self.act_rerun = tb.addAction("重新运行质控", self.rerun_qc)
        self.act_export = tb.addAction("导出结果", self.export_results)
        tb.addSeparator()
        self.act_select = tb.addAction("框选模式")
        self.act_select.setCheckable(True)
        self.act_select.toggled.connect(self._toggle_select_mode)
        self.act_delete = tb.addAction("删除所选", self.delete_selected)
        self.act_restore = tb.addAction("恢复所选", self.restore_selected)
        self.act_undo = tb.addAction("清除所选人工决定", self.clear_decisions_selected)
        self.act_clear_sel = tb.addAction("清空选择", self.clear_selection)

        menu = self.menuBar().addMenu("设置")
        menu.addAction("质控参数…", self.edit_config)
        menu.addAction("选择 GSHHG 海岸线目录…", self.choose_gshhg)
        menu.addAction("恢复内置国界底图", self.use_default_basemap)

        # 左侧：年份 + 站点
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(6, 6, 6, 6)
        ll.addWidget(QLabel("年份"))
        self.year_combo = QComboBox()
        self.year_combo.currentIndexChanged.connect(self._year_changed)
        ll.addWidget(self.year_combo)
        ll.addWidget(QLabel("站点（删除+复核数降序）"))
        self.station_list = QListWidget()
        self.station_list.currentItemChanged.connect(lambda *_: self.refresh_views())
        ll.addWidget(self.station_list, stretch=1)

        ll.addWidget(QLabel("显示"))
        self.filter_boxes: dict[str, QCheckBox] = {}
        for st, label in STATUS_LABELS.items():
            cb = QCheckBox(label)
            cb.setChecked(True)
            cb.stateChanged.connect(lambda *_: self.refresh_views())
            self.filter_boxes[st] = cb
            ll.addWidget(cb)
        self.stats_label = QLabel("")
        self.stats_label.setWordWrap(True)
        ll.addWidget(self.stats_label)

        # 中间：地图 / 时间序列（地图默认加载内置国界底图）
        self.map_canvas = MapCanvas()
        self.map_canvas.set_coastlines(load_default_basemap())
        self.series_canvas = SeriesCanvas(value_label=self.cfg.value_col)
        for c in (self.map_canvas, self.series_canvas):
            c.selection_made.connect(self._add_selection)

        tabs = QTabWidget()
        for canvas, name in ((self.map_canvas, "地图视图"),
                             (self.series_canvas, "时间序列")):
            w = QWidget()
            v = QVBoxLayout(w)
            v.setContentsMargins(0, 0, 0, 0)
            v.addWidget(NavigationToolbar2QT(canvas, w))
            v.addWidget(canvas)
            tabs.addTab(w, name)
        self.tabs = tabs

        # 底部：异常记录表
        self.table = QTableWidget()
        self.table.setColumnCount(9)
        self.table.setHorizontalHeaderLabels(
            ["站号", "时间", "纬度", "经度", "观测值", "状态", "QC_FLAG", "REVIEW", "人工"])
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.itemSelectionChanged.connect(self._table_selection_changed)

        right = QSplitter(Qt.Vertical)
        right.addWidget(tabs)
        right.addWidget(self.table)
        right.setSizes([600, 220])

        split = QSplitter(Qt.Horizontal)
        split.addWidget(left)
        split.addWidget(right)
        split.setSizes([280, 1080])
        self.setCentralWidget(split)
        self.statusBar().showMessage("请打开数据目录")

    def _update_enabled(self):
        has_data = self.df is not None
        for a in (self.act_rerun, self.act_export, self.act_select):
            a.setEnabled(has_data)
        has_sel = bool(self.selection)
        for a in (self.act_delete, self.act_restore, self.act_undo, self.act_clear_sel):
            a.setEnabled(has_data and has_sel)

    # ---------- 数据加载 / 质控 ----------
    def open_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择输入数据目录")
        if not d:
            return
        self.input_dir = Path(d)
        self.decisions = DecisionStore(self.input_dir / "_qc_workspace" / "manual_decisions.csv")
        self._start_worker(raw_df=None)

    def rerun_qc(self):
        if self.raw_df is None:
            return
        self._start_worker(raw_df=self.raw_df)

    def _start_worker(self, raw_df):
        if self.worker is not None and self.worker.isRunning():
            QMessageBox.information(self, "请稍候", "质控正在运行中")
            return
        self.statusBar().showMessage("正在读取数据并运行自动质控…")
        QApplication.setOverrideCursor(Qt.WaitCursor)
        self.worker = QCWorker(self.input_dir, self.cfg, raw_df)
        self.worker.done.connect(self._qc_done)
        self.worker.failed.connect(self._qc_failed)
        self.worker.start()

    def _qc_done(self, raw, qc):
        QApplication.restoreOverrideCursor()
        self.raw_df, self.df = raw, qc
        self.status = compute_status(self.df, self.decisions)
        self.selection.clear()
        self._populate_years()
        self._update_enabled()
        n_del = int((self.df[QC_FLAG_COL] != "").sum())
        n_rev = int(((self.df[REVIEW_COL] != "") & (self.df[QC_FLAG_COL] == "")).sum())
        self.statusBar().showMessage(
            f"共 {len(self.df)} 条记录；自动删除 {n_del}，待复核 {n_rev}；"
            f"人工决定 {len(self.decisions)} 条")

    def _qc_failed(self, msg: str):
        QApplication.restoreOverrideCursor()
        self.statusBar().showMessage("质控失败")
        QMessageBox.critical(self, "质控失败", msg[-2000:])

    # ---------- 年份 / 站点导航 ----------
    def _populate_years(self):
        self.year_combo.blockSignals(True)
        self.year_combo.clear()
        years = sorted(int(y) for y in self.df[YEAR_COL].unique() if y > 0)
        for y in years:
            self.year_combo.addItem(str(y), y)
        self.year_combo.blockSignals(False)
        if years:
            self.year_combo.setCurrentIndex(0)
        self._year_changed()

    def _year_changed(self):
        if self.df is None or self.year_combo.count() == 0:
            return
        year = self.year_combo.currentData()
        ydf = self.df[self.df[YEAR_COL] == year]
        ystatus = self.status.loc[ydf.index]
        problem = ystatus.isin([STATUS_AUTO_DEL, STATUS_MANUAL_DEL,
                                STATUS_REVIEW, STATUS_MANUAL_KEEP])
        counts = (ydf.assign(_p=problem).groupby("_STATION")
                  .agg(total=("_STATION", "size"), prob=("_p", "sum")))
        counts = counts.sort_values(["prob", "total"], ascending=False)

        self.station_list.blockSignals(True)
        self.station_list.clear()
        item = QListWidgetItem(ALL_STATIONS)
        item.setData(Qt.UserRole, None)
        self.station_list.addItem(item)
        for st, row in counts.iterrows():
            it = QListWidgetItem(f"{st}  ({int(row['prob'])}/{int(row['total'])})")
            it.setData(Qt.UserRole, st)
            self.station_list.addItem(it)
        self.station_list.blockSignals(False)
        self.station_list.setCurrentRow(0)

    def _current_subset(self) -> pd.DataFrame:
        year = self.year_combo.currentData()
        sub = self.df[self.df[YEAR_COL] == year].copy()
        item = self.station_list.currentItem()
        station = item.data(Qt.UserRole) if item else None
        if station is not None:
            sub = sub[sub["_STATION"] == station]
        sub[STATUS_COL] = self.status.loc[sub.index]
        visible = [st for st, cb in self.filter_boxes.items() if cb.isChecked()]
        return sub[sub[STATUS_COL].isin(visible)]

    # ---------- 视图刷新 ----------
    def refresh_views(self):
        if self.df is None or self.year_combo.count() == 0:
            return
        sub = self._current_subset()
        item = self.station_list.currentItem()
        station = item.data(Qt.UserRole) if item else None
        year = self.year_combo.currentData()
        title = f"{year}  {station or ALL_STATIONS}  ({len(sub)} 条)"
        self.map_canvas.draw_track = station is not None
        self.map_canvas.track_gap_days = self.cfg.track_gap_days
        self.map_canvas.plot(sub, title)
        self.series_canvas.plot(sub, title)
        self.map_canvas.set_selection(self.selection)
        self.series_canvas.set_selection(self.selection)
        self._fill_table(sub)
        self._update_stats(sub)

    def _fill_table(self, sub: pd.DataFrame):
        flagged = sub[(sub[STATUS_COL] != "kept")]
        flagged = flagged.head(TABLE_MAX_ROWS)
        self.table.blockSignals(True)
        self.table.setRowCount(len(flagged))
        for r, (_, row) in enumerate(flagged.iterrows()):
            vals = [row["_STATION"],
                    str(row[DT_COL]),
                    f"{row[LAT_COL]:.3f}" if pd.notna(row[LAT_COL]) else "",
                    f"{row[LON_COL]:.3f}" if pd.notna(row[LON_COL]) else "",
                    f"{row[VALUE_COL]:g}" if pd.notna(row[VALUE_COL]) else "",
                    STATUS_LABELS.get(row[STATUS_COL], row[STATUS_COL]),
                    row[QC_FLAG_COL], row[REVIEW_COL],
                    self.decisions.action_of(row[UID_COL]) or ""]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(str(v))
                if c == 0:
                    it.setData(Qt.UserRole, row[UID_COL])
                self.table.setItem(r, c, it)
        self.table.blockSignals(False)

    def _update_stats(self, sub: pd.DataFrame):
        parts = [f"{STATUS_LABELS[st]}: {int((sub[STATUS_COL] == st).sum())}"
                 for st in STATUS_LABELS]
        self.stats_label.setText("当前视图  " + "，".join(parts)
                                 + f"\n已选择 {len(self.selection)} 个点")

    # ---------- 选择与人工决定 ----------
    def _toggle_select_mode(self, on: bool):
        self.map_canvas.set_select_mode(on)
        self.series_canvas.set_select_mode(on)
        self.statusBar().showMessage(
            "框选模式：在图上拖拽矩形选择点（可多次框选累加）" if on else "")

    def _add_selection(self, uids: list):
        self.selection.update(uids)
        self.map_canvas.set_selection(self.selection)
        self.series_canvas.set_selection(self.selection)
        self._update_enabled()
        self._update_stats(self._current_subset())

    def _table_selection_changed(self):
        uids = {self.table.item(it.row(), 0).data(Qt.UserRole)
                for it in self.table.selectedItems() if self.table.item(it.row(), 0)}
        uids.discard(None)
        if uids:
            self.selection = uids
            self.map_canvas.set_selection(self.selection)
            self.series_canvas.set_selection(self.selection)
            self._update_enabled()

    def clear_selection(self):
        self.selection.clear()
        self.map_canvas.set_selection(self.selection)
        self.series_canvas.set_selection(self.selection)
        self._update_enabled()
        self.refresh_views()

    def _meta_of(self, uid: str) -> dict:
        row = self.df[self.df[UID_COL] == uid].iloc[0]
        return {"STATION": row["_STATION"], "DATE": str(row[DT_COL]),
                "LAT": row[LAT_COL], "LON": row[LON_COL], "VALUE": row[VALUE_COL]}

    def delete_selected(self):
        """人工删除：包含程序未发现的离群点。"""
        for uid in self.selection:
            self.decisions.set(uid, ACTION_DELETE, self._meta_of(uid))
        self._decisions_changed()

    def restore_selected(self):
        """恢复：清除人工删除；对自动删除的点写入人工保留（推翻程序）。"""
        auto_del = set(self.df.loc[(self.df[QC_FLAG_COL] != ""), UID_COL])
        for uid in self.selection:
            if self.decisions.action_of(uid) == ACTION_DELETE:
                self.decisions.clear(uid)
            if uid in auto_del:
                self.decisions.set(uid, ACTION_KEEP, self._meta_of(uid))
        self._decisions_changed()

    def clear_decisions_selected(self):
        for uid in self.selection:
            self.decisions.clear(uid)
        self._decisions_changed()

    def _decisions_changed(self):
        try:
            self.decisions.save()
        except Exception as e:
            QMessageBox.warning(self, "保存人工决定失败", str(e))
        self.status = compute_status(self.df, self.decisions)
        self.refresh_views()
        self.statusBar().showMessage(f"人工决定共 {len(self.decisions)} 条（已自动保存）")

    # ---------- 设置 / 导出 ----------
    def edit_config(self):
        dlg = ConfigDialog(self.cfg, self)
        if dlg.exec() == QDialog.Accepted and dlg.result_cfg is not None:
            self.cfg = dlg.result_cfg
            self.series_canvas.value_label = self.cfg.value_col
            if self.df is not None:
                QMessageBox.information(self, "参数已更新",
                                        "点击“重新运行质控”使新参数生效")

    def choose_gshhg(self):
        d = QFileDialog.getExistingDirectory(self, "选择 GSHHG shapefile 目录")
        if not d:
            return
        lines = load_coastlines(d)
        if not lines:
            QMessageBox.warning(self, "海岸线", "未在该目录找到可用的 GSHHS L1 shapefile")
            return
        self.map_canvas.set_coastlines(lines)
        self.refresh_views()

    def use_default_basemap(self):
        self.map_canvas.set_coastlines(load_default_basemap())
        self.refresh_views()

    def export_results(self):
        d = QFileDialog.getExistingDirectory(self, "选择输出目录")
        if not d:
            return
        out = Path(d)
        overwrite = False
        if out.exists() and any(out.iterdir()):
            ret = QMessageBox.question(
                self, "输出目录非空",
                f"{out}\n目录非空，确认覆盖导出？（将写入同名文件）")
            if ret != QMessageBox.Yes:
                return
            overwrite = True
        try:
            export_results(self.df, self.cfg, self.decisions, out, overwrite=overwrite)
        except Exception as e:
            QMessageBox.critical(self, "导出失败", str(e))
            return
        QMessageBox.information(self, "导出完成", f"结果已写入\n{out}")


def main():
    import sys
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())
