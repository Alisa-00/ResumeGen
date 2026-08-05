from __future__ import annotations
import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QCheckBox,
    QPushButton,
    QComboBox,
    QLineEdit,
    QMessageBox,
    QFileDialog,
    QSizePolicy,
)

from db.database import Database
from ui.widgets import section_title, hline, primary_btn, field, check_box
from sync.config import SyncConfig
from version import APP_VERSION, version_str

DATE_FORMAT_OPTIONS: list[tuple[str, str]] = [
    ("YYYY", "Year only (2020)"),
    ("MMM YYYY", "Month Year (Mar 2020)"),
    ("MM/YYYY", "Numeric Month/Year (03/2020)"),
]

SECTION_LABELS: dict[str, str] = {
    "contact": "Contact",
    "summary": "Summary",
    "experience": "Experience",
    "education": "Education",
    "languages": "Languages",
    "projects": "Projects",
    "keywords": "Skills / Keywords",
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
        cb = check_box(SECTION_LABELS.get(key, key))
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
    def __init__(self, db: Database, window=None, parent=None):
        super().__init__(parent)
        self.db = db
        self.window_ = window  # AppWindow, for triggering background sync

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

        outer.addWidget(
            QLabel("Filename template  (tokens: {company}  {position}  {date})")
        )
        self._pdf_filename = field("{company}_{position}_{date}")
        self._pdf_filename.setText(
            settings.get("pdf_filename_template") or "{company}_{position}_{date}"
        )
        outer.addWidget(self._pdf_filename)

        # date display format
        outer.addSpacing(4)
        outer.addWidget(hline())
        outer.addWidget(QLabel("Date display format"))
        self._date_fmt_combo = QComboBox()
        self._date_fmt_combo.setFixedWidth(300)
        current_fmt = settings.get("date_format") or "YYYY"
        for fmt_val, fmt_label in DATE_FORMAT_OPTIONS:
            self._date_fmt_combo.addItem(fmt_label, userData=fmt_val)
            if fmt_val == current_fmt:
                self._date_fmt_combo.setCurrentIndex(self._date_fmt_combo.count() - 1)
        outer.addWidget(self._date_fmt_combo)

        # section order
        outer.addSpacing(4)
        outer.addWidget(hline())
        outer.addWidget(QLabel("Default section order & visibility"))

        hint = QLabel("▲▼ to reorder · check to enable · uncheck to disable")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #a6adc8;")
        outer.addWidget(hint)

        order_raw = (
            settings.get("section_order")
            or '["contact","summary","experience","education","languages","projects","keywords"]'
        )
        enabled_raw = (
            settings.get("sections_enabled")
            or '{"contact":1,"summary":1,"experience":1,"education":1,"languages":1,"projects":1,"keywords":1}'
        )

        order = [k for k in json.loads(order_raw) if k != "custom"]
        enabled = {
            k: bool(v) for k, v in json.loads(enabled_raw).items() if k != "custom"
        }

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

        self._build_sync_section(outer)
        outer.addStretch()

    # ── sync ──────────────────────────────────────────────────────────

    def _build_sync_section(self, outer: QVBoxLayout):
        """Sync config is stored OUTSIDE the database (SyncConfig), so it is
        edited here directly rather than through db.save_settings()."""
        # share the engine's live config object when available so changes here
        # are immediately seen by background sync
        engine = getattr(self.window_, "engine", None)
        self._sync_cfg: SyncConfig = engine.cfg if engine else SyncConfig.load()

        outer.addSpacing(4)
        outer.addWidget(hline())
        outer.addWidget(section_title("Sync"))

        info = QLabel(
            "Sync uploads a snapshot of your whole database to a central "
            "SpacetimeDB server and pulls the latest compatible snapshot. It is "
            "optional — the app works fully offline. Latest-write-wins."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #a6adc8;")
        outer.addWidget(info)

        self._sync_enabled = check_box("Enable sync")
        self._sync_enabled.setChecked(self._sync_cfg.sync_enabled)
        outer.addWidget(self._sync_enabled)

        outer.addWidget(QLabel("Sync server URL  (e.g. https://maincloud.spacetimedb.com)"))
        self._sync_url = field("https://…")
        self._sync_url.setText(self._sync_cfg.server_url)
        outer.addWidget(self._sync_url)

        outer.addWidget(QLabel("Module / database name"))
        self._sync_module = field("my-resume-sync")
        self._sync_module.setText(self._sync_cfg.module_name)
        outer.addWidget(self._sync_module)

        outer.addWidget(QLabel("Identity token  (from `spacetime login`)"))
        self._sync_token = field("paste SpacetimeDB identity token")
        self._sync_token.setEchoMode(QLineEdit.EchoMode.Password)
        self._sync_token.setText(self._sync_cfg.identity_token)
        outer.addWidget(self._sync_token)

        btn_row = QHBoxLayout()
        save_sync_btn = primary_btn("Save Sync Settings")
        save_sync_btn.clicked.connect(self._save_sync)
        self._sync_now_btn = QPushButton("Sync now")
        self._sync_now_btn.clicked.connect(self._sync_now)
        btn_row.addWidget(save_sync_btn)
        btn_row.addWidget(self._sync_now_btn)
        btn_row.addStretch()
        outer.addLayout(btn_row)

        self._sync_status = QLabel(self._sync_status_text())
        self._sync_status.setWordWrap(True)
        self._sync_status.setStyleSheet("color: #a6adc8;")
        outer.addWidget(self._sync_status)

    def _sync_status_text(self) -> str:
        ver = version_str(APP_VERSION)
        last = self._sync_cfg.last_synced_at or "never"
        return f"App version {ver} · last synced: {last}"

    def _save_sync(self):
        url = self._sync_url.text().strip().rstrip("/")
        if url and "://" not in url:
            url = "https://" + url  # bare hostname → assume HTTPS
            self._sync_url.setText(url)
        if url and not url.startswith(("http://", "https://")):
            QMessageBox.warning(
                self, "Sync",
                f"Server URL must start with http:// or https:// — got: {url}",
            )
            return False
        self._sync_cfg.sync_enabled = self._sync_enabled.isChecked()
        self._sync_cfg.server_url = url
        self._sync_cfg.module_name = self._sync_module.text().strip()
        self._sync_cfg.identity_token = self._sync_token.text().strip()
        self._sync_cfg.save()

        engine = getattr(self.window_, "engine", None)
        if engine:
            engine.reset_client()  # url/token may have changed
        QMessageBox.information(self, "Saved", "Sync settings saved.")
        if self._sync_cfg.is_ready() and self.window_ is not None:
            # Sync just became usable on this machine — check the server now
            # (first-sync choice / newer snapshot) instead of waiting for the
            # next launch, whose startup pull has already run.
            self.window_.start_initial_sync()
        return True

    def _sync_now(self):
        if not self._save_sync():  # persist any edits first
            return
        if not (self.window_ and getattr(self.window_, "engine", None)):
            QMessageBox.information(self, "Sync", "Sync is unavailable.")
            return
        self._sync_status.setText("Syncing…")
        self._sync_now_btn.setEnabled(False)

        def on_status(msg: str):
            self._sync_now_btn.setEnabled(True)
            self._sync_status.setText(f"{msg}\n{self._sync_status_text()}")

        self.window_.sync_now(on_status=on_status)

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
        order = self._section_order.get_order()
        enabled = self._section_order.get_enabled()
        tmpl_id = self._tmpl_combo.currentData()
        self.db.save_settings(
            section_order=json.dumps(order),
            sections_enabled=json.dumps({k: int(v) for k, v in enabled.items()}),
            default_template_id=tmpl_id,
            pdf_output_folder=self._pdf_folder.text().strip() or None,
            pdf_filename_template=self._pdf_filename.text().strip()
            or "{company}_{position}_{date}",
            date_format=self._date_fmt_combo.currentData() or "YYYY",
        )
        QMessageBox.information(self, "Saved", "Settings saved.")
