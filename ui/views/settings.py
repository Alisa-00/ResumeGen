from __future__ import annotations
import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QCheckBox, QPushButton, QComboBox, QLineEdit,
    QMessageBox, QFileDialog, QSizePolicy,
)

from db.database import Database
from ui.widgets import section_title, hline, primary_btn, field

SECTION_LABELS: dict[str, str] = {
    "contact":    "Contact",
    "summary":    "Summary",
    "experience": "Experience",
    "education":  "Education",
    "projects":   "Projects",
    "keywords":   "Skills / Keywords",
}


# ── section order widget ──────────────────────────────────────────────

class SectionOrderWidget(QWidget):
    def __init__(self, order: list[str], enabled: dict[str, bool], parent=None):
        super().__init__(parent)
        self._items: list[tuple[str, QCheckBox]] = []

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 4, 0, 4)
        self._layout.setSpacing(8)

        for key in order:
            if key == "custom":
                continue
            self._append(key, enabled.get(key, True))

    def _append(self, key: str, is_enabled: bool):
        cb = QCheckBox(SECTION_LABELS.get(key, key))
        cb.setChecked(is_enabled)

        up_btn = QPushButton("▲")
        dn_btn = QPushButton("▼")
        for btn in (up_btn, dn_btn):
            btn.setFixedSize(52, 52)
            btn.setStyleSheet(
                "QPushButton {"
                "  font-size: 22px; color: #89b4fa;"
                "  background-color: #313244;"
                "  border-radius: 6px; border: none;"
                "  min-height: 0; min-width: 0;"
                "}"
                "QPushButton:hover { background-color: #45475a; }"
            )

        up_btn.clicked.connect(lambda _=None, k=key: self._move(k, -1))
        dn_btn.clicked.connect(lambda _=None, k=key: self._move(k, +1))

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)
        row.addWidget(up_btn)
        row.addWidget(dn_btn)
        row.addWidget(cb, 1)

        self._items.append((key, cb))
        self._layout.addLayout(row)

    def _move(self, key: str, delta: int):
        idx = next((i for i, (k, _) in enumerate(self._items) if k == key), None)
        if idx is None:
            return
        new_idx = idx + delta
        if new_idx < 0 or new_idx >= len(self._items):
            return

        state = [(k, cb.isChecked()) for k, cb in self._items]
        state[idx], state[new_idx] = state[new_idx], state[idx]

        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.layout():
                while item.layout().count():
                    w = item.layout().takeAt(0).widget()
                    if w:
                        w.deleteLater()

        self._items.clear()
        for k, enabled in state:
            self._append(k, enabled)

    def get_order(self) -> list[str]:
        return [k for k, _ in self._items]

    def get_enabled(self) -> dict[str, bool]:
        return {k: cb.isChecked() for k, cb in self._items}


# ── settings view ─────────────────────────────────────────────────────

class SettingsView(QWidget):
    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db

        settings = self.db.get_settings() or {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 16, 24, 16)
        outer.setSpacing(12)

        outer.addWidget(section_title("Settings"))
        outer.addWidget(hline())

        # default template
        outer.addWidget(QLabel("Default template"))
        self._tmpl_combo = QComboBox()
        self._tmpl_combo.setFixedWidth(300)
        self._load_templates(settings.get("default_template_id"))
        outer.addWidget(self._tmpl_combo)

        # PDF output
        outer.addSpacing(4)
        outer.addWidget(hline())
        outer.addWidget(QLabel("PDF Output"))

        folder_row = QHBoxLayout()
        self._pdf_folder = field("Default save folder for PDFs")
        self._pdf_folder.setText(settings.get("pdf_output_folder") or "")
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._browse_folder)
        folder_row.addWidget(self._pdf_folder)
        folder_row.addWidget(browse_btn)
        outer.addLayout(folder_row)

        outer.addWidget(QLabel("Filename template  (tokens: {company}  {position}  {date})"))
        self._pdf_filename = field("{company}_{position}_{date}")
        self._pdf_filename.setText(
            settings.get("pdf_filename_template") or "{company}_{position}_{date}"
        )
        outer.addWidget(self._pdf_filename)

        # section order
        outer.addSpacing(4)
        outer.addWidget(hline())
        outer.addWidget(QLabel("Default section order & visibility"))

        hint = QLabel("▲▼ to reorder · check to enable · uncheck to disable")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #a6adc8;")
        outer.addWidget(hint)

        order_raw   = settings.get("section_order") or \
            '["contact","summary","experience","education","projects","keywords"]'
        enabled_raw = settings.get("sections_enabled") or \
            '{"contact":1,"summary":1,"experience":1,"education":1,"projects":1,"keywords":1}'

        order   = [k for k in json.loads(order_raw) if k != "custom"]
        enabled = {k: bool(v) for k, v in json.loads(enabled_raw).items() if k != "custom"}

        for key in SECTION_LABELS:
            if key not in order:
                order.append(key)
            if key not in enabled:
                enabled[key] = True

        self._section_order = SectionOrderWidget(order, enabled)
        outer.addWidget(self._section_order)

        outer.addSpacing(8)
        save_btn = primary_btn("Save Settings")
        save_btn.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        save_btn.clicked.connect(self._save)
        outer.addWidget(save_btn)
        outer.addStretch()

    def _load_templates(self, default_id: int | None = None):
        self._tmpl_combo.clear()
        self._tmpl_combo.addItem("— none —", userData=None)
        for tmpl in self.db.get_templates():
            self._tmpl_combo.addItem(tmpl["name"], userData=tmpl["id"])
            if tmpl["id"] == default_id:
                self._tmpl_combo.setCurrentIndex(self._tmpl_combo.count() - 1)

    def _browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select PDF output folder")
        if folder:
            self._pdf_folder.setText(folder)

    def _save(self):
        order   = self._section_order.get_order()
        enabled = self._section_order.get_enabled()
        tmpl_id = self._tmpl_combo.currentData()
        self.db.save_settings(
            section_order         = json.dumps(order),
            sections_enabled      = json.dumps({k: int(v) for k, v in enabled.items()}),
            default_template_id   = tmpl_id,
            pdf_output_folder     = self._pdf_folder.text().strip() or None,
            pdf_filename_template = self._pdf_filename.text().strip()
                                    or "{company}_{position}_{date}",
        )
        QMessageBox.information(self, "Saved", "Settings saved.")