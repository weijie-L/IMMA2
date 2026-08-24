"""设置数据目录对话框：各处理阶段的输入/输出目录，保存后持久化。"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFileDialog, QGridLayout, QLabel, QLineEdit,
    QPushButton, QVBoxLayout,
)

from ..paths import PathsConfig, save_paths


class PathsDialog(QDialog):
    def __init__(self, paths: PathsConfig, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置数据目录")
        self.setMinimumWidth(620)
        self.result_paths: PathsConfig | None = None
        self._edits: dict[str, QLineEdit] = {}

        lay = QVBoxLayout(self)
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        for row, (field, label) in enumerate(PathsConfig.FIELDS_CN.items()):
            grid.addWidget(QLabel(label + "："), row, 0)
            edit = QLineEdit(getattr(paths, field))
            self._edits[field] = edit
            grid.addWidget(edit, row, 1)
            btn = QPushButton("浏览…")
            btn.clicked.connect(lambda _=False, f=field: self._browse(f))
            grid.addWidget(btn, row, 2)
        lay.addLayout(grid)

        tip = QLabel("目录保存在用户主目录 .imma2_qc/settings.json，下次启动自动加载。")
        tip.setWordWrap(True)
        lay.addWidget(tip)

        btns = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        btns.button(QDialogButtonBox.Save).setText("保存")
        btns.button(QDialogButtonBox.Cancel).setText("取消")
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def _browse(self, field: str):
        current = self._edits[field].text().strip()
        d = QFileDialog.getExistingDirectory(
            self, PathsConfig.FIELDS_CN[field], current or "")
        if d:
            self._edits[field].setText(d)

    def accept(self):
        self.result_paths = PathsConfig(
            **{f: e.text().strip() for f, e in self._edits.items()})
        save_paths(self.result_paths)
        super().accept()
