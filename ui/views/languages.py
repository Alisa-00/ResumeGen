from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QPushButton,
    QLineEdit,
    QLabel,
    QMessageBox,
    QSizePolicy,
    QComboBox,
)

from db.database import Database
from ui.widgets import (
    section_title,
    hline,
    primary_btn,
    flat_link_btn,
    field,
    Card,
    scrollable,
)


# Built-in proficiency levels that users can choose from or type their own
BUILTIN_PROFICIENCIES = [
    "Native",
    "Full Professional Proficiency",
    "Elementary Proficiency",
]


class _LanguageRow(QWidget):
    def __init__(self, data: dict | None = None, parent=None):
        super().__init__(parent)
        self._data = data

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 4, 0, 4)
        root.setSpacing(8)

        # Language name field
        self.f_name = QLineEdit((data or {}).get("name", ""))
        self.f_name.setPlaceholderText("e.g. English")
        self.f_name.setMinimumWidth(150)

        # Proficiency level - editable combo box
        self.f_proficiency = QComboBox()
        self.f_proficiency.setEditable(True)
        self.f_proficiency.addItems(BUILTIN_PROFICIENCIES)
        current_prof = (data or {}).get("proficiency_level", "")
        if current_prof:
            # If current value is not in builtins, it will be added as editable text
            idx = self.f_proficiency.findText(current_prof)
            if idx == -1:
                self.f_proficiency.setCurrentText(current_prof)
            else:
                self.f_proficiency.setCurrentIndex(idx)
        self.f_proficiency.setMinimumWidth(200)

        # Remove button
        self._rm = QPushButton("×")
        self._rm.setFixedSize(28, 28)
        self._rm.setFlat(True)
        self._rm.setStyleSheet(
            "QPushButton { color: #f38ba8; background: transparent; border: none; font-size: 20px; }"
            "QPushButton:hover { color: #f5c2e7; }"
        )

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

    def connect_remove(self, slot):
        self._rm.clicked.connect(slot)


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

        # Help text
        help_lbl = QLabel(
            "Add languages with proficiency levels. Use the built-in levels or type your own."
        )
        help_lbl.setStyleSheet("color: #a6adc8; font-size: 14px;")
        help_lbl.setWordWrap(True)
        layout.addWidget(help_lbl)

        # Container for language rows
        self._rows_container = QWidget()
        self._rows_layout = QVBoxLayout(self._rows_container)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(6)
        layout.addWidget(self._rows_container)

        # Buttons
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
        row.connect_remove(lambda _=None, r=row: self._remove_row(r))
        self._rows.append(row)
        self._rows_layout.addWidget(row)

    def _remove_row(self, row: _LanguageRow):
        if row._data and row._data.get("id"):
            self.db.delete_language(row._data["id"])
        self._rows.remove(row)
        self._rows_layout.removeWidget(row)
        row.deleteLater()

    def _save_all(self):
        for row in self._rows:
            data = row.get_data()
            if data["name"]:
                self.db.upsert_language(
                    name=data["name"],
                    proficiency_level=data["proficiency_level"],
                    id=data["id"],
                )
        QMessageBox.information(self, "Saved", "Languages saved.")
