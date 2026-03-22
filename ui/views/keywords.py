from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit,
    QPushButton, QLabel,
)

from db.database import Database
from ui.widgets import section_title, hline, field, small_danger_btn, flat_link_btn, scrollable

ROWS_PER_COL = 15
MAX_COLS     = 4


class KeywordsView(QWidget):
    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self._rows: list[tuple[QWidget, dict | None]] = []

        inner = QWidget()
        self._main = QVBoxLayout(inner)
        self._main.setContentsMargins(24, 16, 24, 16)
        self._main.setSpacing(12)
        self._main.addWidget(section_title("Keywords / Skills"))
        self._main.addWidget(hline())

        # add new keyword row — at the top
        add_row = QHBoxLayout()
        self._new_kw = field("New keyword…")
        self._new_kw.setFixedWidth(320)
        self._new_kw.returnPressed.connect(self._add_new)
        self._new_kw.textChanged.connect(self._clear_warning)
        add_btn = flat_link_btn("+ Add")
        add_btn.clicked.connect(self._add_new)
        add_row.addWidget(self._new_kw)
        add_row.addWidget(add_btn)
        add_row.addStretch()
        self._main.addLayout(add_row)

        self._warning_lbl = QLabel("")
        self._warning_lbl.setStyleSheet("color: #f38ba8; font-size: 16px;")
        self._warning_lbl.setVisible(False)
        self._main.addWidget(self._warning_lbl)

        # grid container
        self._grid_widget = QWidget()
        self._grid_layout = QHBoxLayout(self._grid_widget)
        self._grid_layout.setContentsMargins(0, 0, 0, 0)
        self._grid_layout.setSpacing(24)
        self._grid_layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self._grid_layout.addStretch()
        self._main.addWidget(self._grid_widget)
        self._main.addStretch()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scrollable(inner))

        self._load()

    # ------------------------------------------------------------------

    def _load(self):
        for kw in self.db.get_keywords():
            self._add_row(kw)

    def _col_and_row_for(self, idx: int) -> tuple[int, int]:
        col   = (idx // ROWS_PER_COL) % MAX_COLS
        group = idx // (ROWS_PER_COL * MAX_COLS)
        actual_col = col + group * MAX_COLS
        row = idx % ROWS_PER_COL
        return actual_col, row

    def _ensure_col(self, col_idx: int) -> QVBoxLayout:
        needed  = col_idx + 1
        current = self._grid_layout.count() - 1
        while current < needed:
            col_w = QWidget()
            col_l = QVBoxLayout(col_w)
            col_l.setContentsMargins(0, 0, 0, 0)
            col_l.setSpacing(6)
            col_l.addStretch()
            self._grid_layout.insertWidget(current, col_w)
            current += 1
        item = self._grid_layout.itemAt(col_idx)
        return item.widget().layout()

    def _add_row(self, data: dict | None = None):
        idx    = len(self._rows)
        col_i, _ = self._col_and_row_for(idx)
        col_l  = self._ensure_col(col_i)

        row_w = QWidget()
        hl = QHBoxLayout(row_w)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(8)

        name_edit = field("Keyword", (data or {}).get("name", ""))
        name_edit.setFixedWidth(260)
        rm_btn = small_danger_btn()

        def _delete(checked=False, w=row_w, d=data):
            kw_id = (d or {}).get("id")
            if kw_id:
                self.db.delete_keyword(kw_id)
            self._rows = [(rw, rd) for rw, rd in self._rows if rw is not w]
            for i in range(self._grid_layout.count() - 1):
                col_widget = self._grid_layout.itemAt(i).widget()
                if col_widget is None:
                    continue
                cl = col_widget.layout()
                for j in range(cl.count() - 1):
                    if cl.itemAt(j) and cl.itemAt(j).widget() is w:
                        cl.removeWidget(w)
                        w.deleteLater()
                        return

        def _inline_save(d=data, e=name_edit):
            name = e.text().strip()
            if name and d:
                self.db.execute(
                    "UPDATE keyword SET name=? WHERE id=?", (name, d["id"])
                )

        rm_btn.clicked.connect(_delete)
        name_edit.editingFinished.connect(_inline_save)

        hl.addWidget(name_edit)
        hl.addWidget(rm_btn)

        col_l.insertWidget(col_l.count() - 1, row_w)
        self._rows.append((row_w, data))

    def _existing_names(self) -> set[str]:
        result = set()
        for _, data in self._rows:
            name = (data or {}).get("name", "")
            if name:
                result.add(name.lower())
        return result

    def _clear_warning(self):
        self._warning_lbl.setVisible(False)

    def _add_new(self):
        name = self._new_kw.text().strip()
        if not name:
            return
        if name.lower() in self._existing_names():
            self._warning_lbl.setText(f'"{name}" already exists.')
            self._warning_lbl.setVisible(True)
            return
        self._clear_warning()
        new_id = self.db.add_keyword(name)
        self._add_row({"id": new_id, "name": name})
        self._new_kw.clear()