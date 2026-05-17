from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLineEdit,
    QLabel,
    QMessageBox,
    QComboBox,
)

from db.database import Database
from ui.widgets import (
    section_title,
    hline,
    primary_btn,
    flat_link_btn,
    small_danger_btn,
    scrollable,
)


BUILTIN_PROFICIENCIES = [
    "Native",
    "Full Professional Proficiency",
    "Elementary Proficiency",
]


def _reorder_layout(layout, items: list) -> None:
    for item in items:
        layout.removeWidget(item)
    for item in items:
        layout.addWidget(item)


class _LanguageRow(QWidget):
    removed = Signal(object)
    moved_up = Signal(object)
    moved_down = Signal(object)

    def __init__(self, data: dict | None = None, parent=None):
        super().__init__(parent)
        self._data = data

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 4, 0, 4)
        root.setSpacing(8)

        _arrow_style = (
            "QPushButton { font-size: 22px; color: #89b4fa;"
            " background-color: #313244; border-radius: 6px; border: none;"
            " min-height: 0; min-width: 0; }"
            "QPushButton:hover { background-color: #45475a; }"
        )

        self._up_btn = QPushButton("▲")
        self._up_btn.setFixedSize(48, 48)
        self._up_btn.setStyleSheet(_arrow_style)
        self._up_btn.clicked.connect(lambda: self.moved_up.emit(self))

        self._down_btn = QPushButton("▼")
        self._down_btn.setFixedSize(48, 48)
        self._down_btn.setStyleSheet(_arrow_style)
        self._down_btn.clicked.connect(lambda: self.moved_down.emit(self))

        # Language name field
        self.f_name = QLineEdit((data or {}).get("name", ""))
        self.f_name.setPlaceholderText("e.g. English")
        self.f_name.setMinimumWidth(150)

        # Proficiency level — editable combo box
        self.f_proficiency = QComboBox()
        self.f_proficiency.setEditable(True)
        self.f_proficiency.addItems(BUILTIN_PROFICIENCIES)
        current_prof = (data or {}).get("proficiency_level", "")
        if current_prof:
            idx = self.f_proficiency.findText(current_prof)
            if idx == -1:
                self.f_proficiency.setCurrentText(current_prof)
            else:
                self.f_proficiency.setCurrentIndex(idx)
        self.f_proficiency.setMinimumWidth(200)

        # Remove button
        self._rm = small_danger_btn()
        self._rm.clicked.connect(lambda: self.removed.emit(self))

        root.addWidget(self._up_btn)
        root.addWidget(self._down_btn)
        root.addWidget(QLabel("Language:"))
        root.addWidget(self.f_name, 1)
        root.addWidget(QLabel("Proficiency:"))
        root.addWidget(self.f_proficiency, 2)
        root.addWidget(self._rm)

    def get_data(self) -> dict:
        return {
            "id": (self._data or {}).get("id"),
            "name": self.f_name.text().strip(),
            "proficiency_level": self.f_proficiency.currentText().strip(),
        }


class LanguagesView(QWidget):
    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self._rows: list[_LanguageRow] = []

        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(24, 16, 24, 16)
        layout.setSpacing(12)
        layout.addWidget(section_title("Languages"))
        layout.addWidget(hline())

        help_lbl = QLabel(
            "Add languages with proficiency levels. Use ▲/▼ to set the default order. "
            "This order is used when creating new applications."
        )
        help_lbl.setStyleSheet("color: #a6adc8; font-size: 14px;")
        help_lbl.setWordWrap(True)
        layout.addWidget(help_lbl)

        self._rows_container = QWidget()
        self._rows_layout = QVBoxLayout(self._rows_container)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(6)
        layout.addWidget(self._rows_container)

        btn_row = QHBoxLayout()
        add_btn = flat_link_btn("+ Add Language")
        add_btn.clicked.connect(lambda: self._add_row())
        save_btn = primary_btn("Save All")
        save_btn.clicked.connect(self._save_all)
        btn_row.addWidget(add_btn)
        btn_row.addStretch()
        btn_row.addWidget(save_btn)
        layout.addLayout(btn_row)
        layout.addStretch()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scrollable(inner))

        self._load()

    def _load(self):
        for lang in self.db.get_languages():
            self._add_row(lang)

    def _add_row(self, data: dict | None = None):
        row = _LanguageRow(data)
        row.removed.connect(self._remove_row)
        row.moved_up.connect(self._move_up)
        row.moved_down.connect(self._move_down)
        self._rows.append(row)
        self._rows_layout.addWidget(row)

    def _remove_row(self, row: _LanguageRow):
        name = row.f_name.text().strip() or "this language"
        reply = QMessageBox.question(
            self,
            "Remove Language",
            f'Remove "{name}" from your profile?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        if row._data and row._data.get("id"):
            self.db.delete_language(row._data["id"])
        self._rows.remove(row)
        self._rows_layout.removeWidget(row)
        row.deleteLater()

    def _move_up(self, row: _LanguageRow):
        idx = self._rows.index(row)
        if idx > 0:
            self._rows[idx], self._rows[idx - 1] = self._rows[idx - 1], self._rows[idx]
            _reorder_layout(self._rows_layout, self._rows)

    def _move_down(self, row: _LanguageRow):
        idx = self._rows.index(row)
        if idx < len(self._rows) - 1:
            self._rows[idx], self._rows[idx + 1] = self._rows[idx + 1], self._rows[idx]
            _reorder_layout(self._rows_layout, self._rows)

    def _save_all(self):
        for i, row in enumerate(self._rows):
            data = row.get_data()
            if data["name"]:
                self.db.upsert_language(
                    name=data["name"],
                    proficiency_level=data["proficiency_level"],
                    id=data["id"],
                    sort_order=i,
                )
        QMessageBox.information(self, "Saved", "Languages saved.")
