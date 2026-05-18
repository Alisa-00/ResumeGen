"""
ui/wizard/step_preview.py
Wizard step 2: live resume editor + PDF preview.

The editor binds to a snapshot dict ({"version", "live", "original"}).
All edits mutate `live`; pickers and reset affordances read from `original`.
The renderer is a pure function of the snapshot — no DB access at edit time.
"""

from __future__ import annotations
import json
import copy
from pathlib import Path
from datetime import date

from PySide6.QtCore import Qt, Signal, QTimer, QThreadPool, QRunnable, QObject
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QSplitter,
    QLabel,
    QLineEdit,
    QPushButton,
    QCheckBox,
    QButtonGroup,
    QRadioButton,
    QScrollArea,
    QFrame,
    QDialog,
    QListWidget,
    QListWidgetItem,
    QDialogButtonBox,
    QMessageBox,
    QSizePolicy,
    QTextEdit,
    QComboBox,
)

from db.database import Database
from pdf.display import PdfPreviewWidget
from ui.widgets import primary_btn, flat_link_btn, small_danger_btn

SECTION_LABELS = {
    "contact": "Contact",
    "summary": "Summary",
    "experience": "Experience",
    "education": "Education",
    "languages": "Languages",
    "projects": "Projects",
    "keywords": "Skills / Keywords",
}
SECTION_KEYS = ["contact", "summary", "experience", "education",
                "languages", "projects", "keywords"]
DEBOUNCE_MS = 500


# ── shared helpers ────────────────────────────────────────────────────


def _reorder_layout(layout, items: list) -> None:
    for item in items:
        layout.removeWidget(item)
    for i, item in enumerate(items):
        layout.insertWidget(i, item)


def _toggle_expand(btn: QPushButton, body: QWidget, expanded: str, collapsed: str) -> None:
    v = not body.isVisible()
    body.setVisible(v)
    btn.setText(expanded if v else collapsed)


def _arrow_btn(arrow: str) -> QPushButton:
    btn = QPushButton(arrow)
    btn.setFixedSize(48, 48)
    btn.setFlat(True)
    btn.setStyleSheet(
        "QPushButton { font-size: 22px; color: #89b4fa;"
        " background-color: #313244; border-radius: 6px; border: none;"
        " min-height: 0; min-width: 0; }"
        "QPushButton:hover { background-color: #45475a; }"
    )
    return btn


# ── worker ────────────────────────────────────────────────────────────


class _Sig(QObject):
    done = Signal(bytes)
    error = Signal(str)


class _Task(QRunnable):
    def __init__(self, fn, *args):
        super().__init__()
        self.fn = fn
        self.args = args
        self.sigs = _Sig()

    def run(self):
        try:
            self.sigs.done.emit(self.fn(*self.args))
        except Exception as e:  # noqa: BLE001
            self.sigs.error.emit(str(e))


# ── picker dialog ─────────────────────────────────────────────────────


class _PickerDialog(QDialog):
    def __init__(self, title: str, items: list[tuple[object, str]], parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(400)
        layout = QVBoxLayout(self)
        self._list = QListWidget()
        for key, label in items:
            it = QListWidgetItem(label)
            it.setData(Qt.ItemDataRole.UserRole, key)
            self._list.addItem(it)
        layout.addWidget(self._list)
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def selected(self):
        item = self._list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None


# ── _SubItem (collapsible row for experience / education / projects) ──


class _SubItem(QWidget):
    removed = Signal(object)
    moved_up = Signal(object)
    moved_down = Signal(object)
    changed = Signal()

    def __init__(self, header_text: str, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 2)
        root.setSpacing(0)

        hdr = QWidget()
        hdr.setStyleSheet(
            "QWidget { background: #252535; border: 1px solid #313244; border-radius: 3px; }"
        )
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(8, 4, 8, 4)
        hl.setSpacing(6)

        for arrow, sig in [("▲", self.moved_up), ("▼", self.moved_down)]:
            btn = _arrow_btn(arrow)
            btn.clicked.connect(lambda _=None, s=sig: s.emit(self))
            hl.addWidget(btn)

        self._header_label = QLabel(header_text)
        self._header_label.setStyleSheet("color: #cdd6f4; font-size: 18px;")
        hl.addWidget(self._header_label, 1)

        self._expand_btn = QPushButton("▶ Edit")
        self._expand_btn.setFixedHeight(48)
        self._expand_btn.setFlat(True)
        self._expand_btn.setStyleSheet(
            "QPushButton { color: #89b4fa; font-size: 20px; padding: 0 8px;"
            " background: transparent; border: none; min-height: 0; }"
            "QPushButton:hover { color: #74c7ec; }"
        )
        self._expand_btn.clicked.connect(self._toggle)
        hl.addWidget(self._expand_btn)

        rm = small_danger_btn()
        rm.clicked.connect(lambda: self.removed.emit(self))
        hl.addWidget(rm)

        self._body = QWidget()
        self._body.setStyleSheet(
            "QWidget { background: #181825; border: 1px solid #313244; border-top: none;"
            " border-radius: 0 0 3px 3px; }"
        )
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(12, 8, 12, 8)
        self._body_layout.setSpacing(6)
        self._body.setVisible(False)

        root.addWidget(hdr)
        root.addWidget(self._body)

    def _toggle(self):
        _toggle_expand(self._expand_btn, self._body, "▼ Edit", "▶ Edit")

    def _add_body_row(self, label: str, widget: QWidget) -> QHBoxLayout:
        row = QHBoxLayout()
        lbl = QLabel(label)
        lbl.setFixedWidth(110)
        lbl.setStyleSheet("color: #a6adc8; font-size: 16px;")
        row.addWidget(lbl)
        row.addWidget(widget, 1)
        self._body_layout.addLayout(row)
        return row


class _SubList(QWidget):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: list[_SubItem] = []
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(3)

    def add(self, item: _SubItem):
        item.removed.connect(self._remove)
        item.moved_up.connect(lambda i: self._move(i, -1))
        item.moved_down.connect(lambda i: self._move(i, +1))
        item.changed.connect(self.changed)
        self._items.append(item)
        self._layout.addWidget(item)

    def _remove(self, item: _SubItem):
        self._items.remove(item)
        self._layout.removeWidget(item)
        item.deleteLater()
        self.changed.emit()

    def _move(self, item: _SubItem, delta: int):
        idx = self._items.index(item)
        new = idx + delta
        if 0 <= new < len(self._items):
            self._items[idx], self._items[new] = self._items[new], self._items[idx]
            _reorder_layout(self._layout, self._items)
            self.changed.emit()

    def items(self) -> list[_SubItem]:
        return list(self._items)


# ── contact ───────────────────────────────────────────────────────────


class _ContactWidget(QWidget):
    changed = Signal()

    def __init__(self, live: dict, original_websites: list[dict], parent=None):
        super().__init__(parent)
        self._original_websites = original_websites
        self._site_rows: list[tuple[dict, QWidget, QLineEdit]] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        self._fields: dict[str, QLineEdit] = {}
        for key, label, placeholder in [
            ("name", "Name", "Full name"),
            ("email", "Email", "email@example.com"),
            ("phone", "Phone", "+1 555 000 0000"),
            ("location", "Location", "City, Country"),
        ]:
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(12)
            lbl = QLabel(label)
            lbl.setFixedWidth(100)
            lbl.setStyleSheet(
                "color: #a6adc8; font-size: 18px; border: 1px solid #313244;"
                " border-radius: 3px; padding: 4px 6px;"
            )
            f = QLineEdit(live.get(key) or "")
            f.setPlaceholderText(placeholder)
            f.textChanged.connect(self.changed)
            self._fields[key] = f
            row.addWidget(lbl)
            row.addWidget(f, 1)
            root.addLayout(row)

        lbl_sites = QLabel("Websites")
        lbl_sites.setStyleSheet(
            "color: #a6adc8; font-size: 18px; font-weight: bold; margin-top: 4px; border: none;"
        )
        root.addWidget(lbl_sites)

        self._sites_layout = QVBoxLayout()
        self._sites_layout.setContentsMargins(0, 0, 0, 0)
        self._sites_layout.setSpacing(4)
        root.addLayout(self._sites_layout)

        for ws in (live.get("websites") or []):
            self._add_site_row(ws)

        add_btn = flat_link_btn("+ Add website")
        add_btn.clicked.connect(self._pick_site)
        root.addWidget(add_btn)

    def _add_site_row(self, site: dict):
        row_w = QWidget()
        hl = QHBoxLayout(row_w)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(8)

        lbl = QLabel(f"{site.get('label', '')}:")
        lbl.setFixedWidth(100)
        lbl.setStyleSheet(
            "color: #a6adc8; font-size: 18px; border: 1px solid #313244;"
            " border-radius: 3px; padding: 4px 6px;"
        )
        url_edit = QLineEdit(site.get("url", ""))
        url_edit.textChanged.connect(self.changed)

        rm = small_danger_btn()
        rm.clicked.connect(lambda _=None, s=site, w=row_w: self._remove_site(s, w))

        hl.addWidget(lbl)
        hl.addWidget(url_edit, 1)
        hl.addWidget(rm)

        self._site_rows.append((dict(site), row_w, url_edit))
        self._sites_layout.addWidget(row_w)
        self.changed.emit()

    def _remove_site(self, site: dict, row_w: QWidget):
        self._site_rows = [(s, w, e) for s, w, e in self._site_rows if w is not row_w]
        self._sites_layout.removeWidget(row_w)
        row_w.deleteLater()
        self.changed.emit()

    def _pick_site(self):
        active_labels = {s.get("label") for s, _, _ in self._site_rows}
        available = [
            (i, f"{s.get('label', '')} — {s.get('url', '')}")
            for i, s in enumerate(self._original_websites)
            if s.get("label") not in active_labels
        ]
        if not available:
            QMessageBox.information(
                self.window(), "No more websites",
                "All saved websites are already included. Add more in the Contact section.",
            )
            return
        dlg = _PickerDialog("Add Website", available, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            idx = dlg.selected()
            if idx is not None:
                src = self._original_websites[idx]
                self._add_site_row({
                    "source_id": src.get("id") or src.get("source_id"),
                    "label": src.get("label", ""),
                    "url":   src.get("url", ""),
                })

    def to_live(self) -> dict:
        out = {k: f.text().strip() for k, f in self._fields.items()}
        out["websites"] = [
            {
                "source_id": site.get("source_id") or site.get("id"),
                "label":     site.get("label", ""),
                "url":       url_edit.text().strip(),
            }
            for site, _, url_edit in self._site_rows
        ]
        return out


# ── summary ───────────────────────────────────────────────────────────


class _SummaryWidget(QWidget):
    changed = Signal()

    def __init__(self, live: dict, profile_summaries: list[dict], parent=None):
        super().__init__(parent)
        self._group = QButtonGroup(self)
        self._source_profile_id = live.get("source_profile_id")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        if not profile_summaries:
            root.addWidget(QLabel("No summaries saved. Edit text below."))
            self._edit = QTextEdit(live.get("text") or "")
            self._edit.setFixedHeight(120)
            self._edit.setStyleSheet(
                "QTextEdit { background: #141618; border: 2px solid #89b4fa;"
                " border-radius: 4px; padding: 4px 8px; }"
            )
            self._edit.textChanged.connect(self.changed)
            root.addWidget(self._edit)
            return

        radio_container = QWidget()
        radio_container.setStyleSheet(
            "QWidget#radioContainer { border: 1px solid #6c7086;"
            " border-radius: 4px; background: transparent; }"
        )
        radio_container.setObjectName("radioContainer")
        radio_layout = QVBoxLayout(radio_container)
        radio_layout.setContentsMargins(6, 4, 6, 4)
        radio_layout.setSpacing(2)

        for p in profile_summaries:
            summary = (p.get("summary") or "").strip()
            if not summary:
                continue
            rb_row = QWidget()
            rb_row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
            rbl = QHBoxLayout(rb_row)
            rbl.setContentsMargins(4, 2, 4, 2)
            rbl.setSpacing(8)
            rb = QRadioButton()
            rb.setStyleSheet("""
                QRadioButton { border: none; background: transparent; }
                QRadioButton::indicator { width: 16px; height: 16px;
                    border: 2px solid #89b4fa; border-radius: 8px; background: transparent; }
                QRadioButton::indicator:checked { background: #89b4fa; }
                QRadioButton::indicator:hover { border-color: #cdd6f4; }
            """)
            rb.setProperty("profile_id", p["id"])
            rb.setProperty("summary_text", summary)
            self._group.addButton(rb)
            lbl = QLabel(f"<b>{p['name']}</b>  —  {summary}")
            lbl.setStyleSheet(
                "QLabel { font-size: 15px; color: #a6adc8; border: none;"
                " background: transparent; }"
            )
            lbl.setWordWrap(True)
            lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
            lbl.mousePressEvent = lambda _e, r=rb: r.setChecked(True)
            rbl.addWidget(rb)
            rbl.addWidget(lbl, 1)
            radio_layout.addWidget(rb_row)

        root.addWidget(radio_container)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #313244;")
        root.addWidget(sep)

        self._edit = QTextEdit()
        self._edit.setFixedHeight(120)
        self._edit.setStyleSheet(
            "QTextEdit { background: #141618; border: 2px solid #89b4fa;"
            " border-radius: 4px; padding: 4px 8px; }"
        )
        self._edit.textChanged.connect(self.changed)
        root.addWidget(self._edit)

        self._group.buttonToggled.connect(self._on_radio_toggled)

        chosen_btn = None
        for btn in self._group.buttons():
            if btn.property("profile_id") == self._source_profile_id:
                chosen_btn = btn
                break
        if chosen_btn is None and self._group.buttons():
            chosen_btn = self._group.buttons()[0]

        if chosen_btn:
            chosen_btn.setChecked(True)
        # Always honour the saved live.text (radio toggle would have overwritten it).
        saved_text = live.get("text") or ""
        self._edit.blockSignals(True)
        self._edit.setPlainText(saved_text)
        self._edit.blockSignals(False)

    def _on_radio_toggled(self, btn, checked: bool):
        if not checked:
            return
        actual = self._group.checkedButton()
        if actual is None:
            return
        self._source_profile_id = actual.property("profile_id")
        self._edit.blockSignals(True)
        self._edit.setPlainText(actual.property("summary_text"))
        self._edit.blockSignals(False)
        self.changed.emit()

    def to_live(self) -> dict:
        return {
            "text": self._edit.toPlainText().strip(),
            "source_profile_id": self._source_profile_id,
        }


# ── experience ────────────────────────────────────────────────────────


class _BulletRow(QWidget):
    removed = Signal(object)
    moved_up = Signal(object)
    moved_down = Signal(object)
    changed = Signal()

    def __init__(self, bullet: dict, original_text: str | None, parent=None):
        super().__init__(parent)
        self.source_id = bullet.get("source_id")
        self._original_text = original_text

        hl = QHBoxLayout(self)
        hl.setContentsMargins(0, 1, 0, 1)
        hl.setSpacing(4)

        for arrow, sig in [("▲", self.moved_up), ("▼", self.moved_down)]:
            btn = _arrow_btn(arrow)
            btn.clicked.connect(lambda _=None, s=sig: s.emit(self))
            hl.addWidget(btn)

        self.edit = QTextEdit(bullet.get("text") or "")
        self.edit.setFixedHeight(72)
        self.edit.setStyleSheet(
            "QTextEdit { font-size: 16px; border: 1px solid #313244; border-radius: 4px; }"
        )
        self.edit.textChanged.connect(self.changed)
        hl.addWidget(self.edit, 1)

        if self._original_text is not None:
            rst = QPushButton("↺")
            rst.setFixedSize(28, 28)
            rst.setFlat(True)
            rst.setStyleSheet(
                "QPushButton { color: #a6adc8; background: transparent; border: none;"
                " min-height:0; min-width:0; }"
            )
            rst.setToolTip("Reset to original (snapshot creation time)")
            rst.clicked.connect(lambda: self.edit.setText(self._original_text or ""))
            hl.addWidget(rst)

        rm = small_danger_btn()
        rm.clicked.connect(lambda: self.removed.emit(self))
        hl.addWidget(rm)

    def to_live(self) -> dict:
        return {"source_id": self.source_id, "text": self.edit.toPlainText()}


class _BulletList(QWidget):
    changed = Signal()

    def __init__(self, live_bullets: list[dict], original_bullets: list[dict], parent=None):
        super().__init__(parent)
        self._original_by_id = {b["id"]: b for b in original_bullets if b.get("id")}
        self._items: list[_BulletRow] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(2)

        self._list_layout = QVBoxLayout()
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(2)
        root.addLayout(self._list_layout)

        for b in live_bullets:
            self._add(b)

        add_btn = flat_link_btn("+ Add bullet from snapshot")
        add_btn.clicked.connect(self._pick)
        root.addWidget(add_btn)

    def _add(self, bullet: dict):
        original = self._original_by_id.get(bullet.get("source_id"))
        original_text = original.get("text") if original else None
        row = _BulletRow(bullet, original_text)
        row.removed.connect(self._remove)
        row.moved_up.connect(lambda r: self._move(r, -1))
        row.moved_down.connect(lambda r: self._move(r, +1))
        row.changed.connect(self.changed)
        self._items.append(row)
        self._list_layout.addWidget(row)
        self.changed.emit()

    def _remove(self, row: _BulletRow):
        self._items.remove(row)
        self._list_layout.removeWidget(row)
        row.deleteLater()
        self.changed.emit()

    def _move(self, row: _BulletRow, delta: int):
        idx = self._items.index(row)
        new = idx + delta
        if 0 <= new < len(self._items):
            self._items[idx], self._items[new] = self._items[new], self._items[idx]
            _reorder_layout(self._list_layout, self._items)
            self.changed.emit()

    def _pick(self):
        active = {row.source_id for row in self._items if row.source_id is not None}
        available = [
            (b["id"], b["text"][:80]) for b in self._original_by_id.values()
            if b["id"] not in active
        ]
        if not available:
            QMessageBox.information(
                self.window(), "Nothing to add",
                "All bullets from the snapshot are already included.",
            )
            return
        dlg = _PickerDialog("Add Bullet", available, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            bid = dlg.selected()
            if bid is not None and bid in self._original_by_id:
                b = self._original_by_id[bid]
                self._add({"source_id": bid, "text": b["text"]})

    def to_live(self) -> list[dict]:
        return [row.to_live() for row in self._items]


class _ExperienceItem(_SubItem):
    def __init__(self, live_exp: dict, original_exp: dict | None, parent=None):
        header = f"{live_exp.get('position_name', '')} — {live_exp.get('organization_name', '')}"
        super().__init__(header, parent)
        self._live = dict(live_exp)
        self.source_id = live_exp.get("source_id")

        meta_lbl = QLabel("Per-application company info")
        meta_lbl.setStyleSheet("color: #a6adc8; font-size: 16px; font-weight: bold;")
        self._body_layout.addWidget(meta_lbl)

        self._f_desc = QLineEdit(live_exp.get("organization_description") or "")
        self._f_desc.setPlaceholderText("e.g. startup working on X")
        self._f_desc.setStyleSheet(
            "QLineEdit { background: #141618; border: 1px solid #89b4fa;"
            " border-radius: 4px; padding: 4px 8px; }"
        )
        self._f_desc.textChanged.connect(self.changed)
        self._add_body_row("Description", self._f_desc)

        self._f_url = QLineEdit(live_exp.get("organization_website") or "")
        self._f_url.setPlaceholderText("https://company.com")
        self._f_url.setStyleSheet(
            "QLineEdit { background: #141618; border: 1px solid #89b4fa;"
            " border-radius: 4px; padding: 4px 8px; }"
        )
        self._f_url.textChanged.connect(self.changed)
        self._add_body_row("Website", self._f_url)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #313244; margin-top: 8px;")
        self._body_layout.addWidget(sep)

        original_bullets = (original_exp or {}).get("bullet_points") or []
        self._bullets = _BulletList(
            live_exp.get("bullets") or [], original_bullets
        )
        self._bullets.changed.connect(self.changed)
        self._body_layout.addWidget(self._bullets)

    def to_live(self) -> dict:
        return {
            **self._live,  # carries pass-through fields (location, dates, etc.)
            "source_id": self.source_id,
            "organization_description": self._f_desc.text().strip(),
            "organization_website": self._f_url.text().strip(),
            "bullets": self._bullets.to_live(),
        }


class _ExperienceWidget(QWidget):
    changed = Signal()

    def __init__(self, live_exp: list[dict], original_exp: list[dict], parent=None):
        super().__init__(parent)
        self._original_by_id = {e["id"]: e for e in original_exp if e.get("id")}
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)
        self._sublist = _SubList()
        self._sublist.changed.connect(self.changed)
        root.addWidget(self._sublist)
        add_btn = flat_link_btn("+ Add experience from snapshot")
        add_btn.clicked.connect(self._pick)
        root.addWidget(add_btn)

        for exp in live_exp:
            self._add(exp)

    def _add(self, live_exp: dict):
        original = self._original_by_id.get(live_exp.get("source_id"))
        item = _ExperienceItem(live_exp, original)
        self._sublist.add(item)

    def _pick(self):
        active = {i.source_id for i in self._sublist.items() if i.source_id is not None}
        avail = [
            (e["id"], f"{e.get('position_name', '')} — {e.get('organization_name', '')}")
            for e in self._original_by_id.values() if e["id"] not in active
        ]
        if not avail:
            QMessageBox.information(
                self.window(), "Nothing to add",
                "All experiences from the snapshot are already included.",
            )
            return
        dlg = _PickerDialog("Add Experience", avail, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            eid = dlg.selected()
            if eid in self._original_by_id:
                exp = self._original_by_id[eid]
                bullets = [
                    {"source_id": b["id"], "text": b["text"]}
                    for b in (exp.get("bullet_points") or [])
                ]
                live_exp = {
                    "source_id":                exp["id"],
                    "organization_name":        exp.get("organization_name") or "",
                    "position_name":            exp.get("position_name") or "",
                    "organization_description": exp.get("organization_description") or "",
                    "organization_website":     exp.get("organization_website") or "",
                    "location":                 exp.get("location") or "",
                    "is_ongoing":               bool(exp.get("is_ongoing")),
                    "start_date":               exp.get("start_date") or "",
                    "end_date":                 exp.get("end_date") or "",
                    "bullets":                  bullets,
                }
                self._add(live_exp)
                self.changed.emit()

    def to_live(self) -> list[dict]:
        return [it.to_live() for it in self._sublist.items() if isinstance(it, _ExperienceItem)]


# ── education ─────────────────────────────────────────────────────────


_EDU_FIELDS = [
    ("degree", "Degree", "e.g. B.Sc."),
    ("school", "School", "e.g. MIT"),
    ("school_url", "School URL", "https://university.edu"),
    ("location", "Location", "e.g. Boston, MA"),
    ("field", "Field", "e.g. Computer Science"),
    ("start_date", "Start", "YYYY-MM"),
    ("end_date", "End", "YYYY-MM"),
]


class _EducationItem(_SubItem):
    def __init__(self, live_edu: dict, parent=None):
        header = f"{live_edu.get('degree', '')} — {live_edu.get('school', '')}"
        super().__init__(header, parent)
        self._live = dict(live_edu)
        self.source_id = live_edu.get("source_id")

        self._inputs: dict[str, QLineEdit] = {}
        for key, lbl, ph in _EDU_FIELDS:
            w = QLineEdit(live_edu.get(key) or "")
            w.setPlaceholderText(ph)
            w.setStyleSheet(
                "QLineEdit { background: #141618; border: 1px solid #89b4fa;"
                " border-radius: 4px; padding: 2px 6px; }"
            )
            w.textChanged.connect(self.changed)
            self._inputs[key] = w
            self._add_body_row(lbl, w)

    def to_live(self) -> dict:
        out = dict(self._live)
        for key, _, _ in _EDU_FIELDS:
            out[key] = self._inputs[key].text().strip()
        out["source_id"] = self.source_id
        return out


class _EducationWidget(QWidget):
    changed = Signal()

    def __init__(self, live_edu: list[dict], original_edu: list[dict], parent=None):
        super().__init__(parent)
        self._original_by_id = {e["id"]: e for e in original_edu if e.get("id")}
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)
        self._sublist = _SubList()
        self._sublist.changed.connect(self.changed)
        root.addWidget(self._sublist)
        add_btn = flat_link_btn("+ Add education from snapshot")
        add_btn.clicked.connect(self._pick)
        root.addWidget(add_btn)
        for edu in live_edu:
            self._sublist.add(_EducationItem(edu))

    def _pick(self):
        active = {it.source_id for it in self._sublist.items() if it.source_id is not None}
        avail = [
            (e["id"], f"{e.get('degree', '')} — {e.get('school', '')}")
            for e in self._original_by_id.values() if e["id"] not in active
        ]
        if not avail:
            QMessageBox.information(
                self.window(), "Nothing to add",
                "All education entries from the snapshot are already included.",
            )
            return
        dlg = _PickerDialog("Add Education", avail, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            eid = dlg.selected()
            if eid in self._original_by_id:
                src = self._original_by_id[eid]
                live = {
                    "source_id":  src["id"],
                    "degree":     src.get("degree") or "",
                    "school":     src.get("school") or "",
                    "school_url": src.get("school_url") or "",
                    "location":   src.get("location") or "",
                    "field":      src.get("field") or "",
                    "gpa":        src.get("gpa") or "",
                    "is_ongoing": bool(src.get("is_ongoing")),
                    "start_date": src.get("start_date") or "",
                    "end_date":   src.get("end_date") or "",
                }
                self._sublist.add(_EducationItem(live))
                self.changed.emit()

    def to_live(self) -> list[dict]:
        return [it.to_live() for it in self._sublist.items() if isinstance(it, _EducationItem)]


# ── languages ─────────────────────────────────────────────────────────


class _LanguageRow(QWidget):
    removed = Signal(object)
    moved_up = Signal(object)
    moved_down = Signal(object)
    changed = Signal()

    def __init__(self, lang: dict, parent=None):
        super().__init__(parent)
        self.source_id = lang.get("source_id")
        self._name = lang.get("name") or ""

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        for arrow, sig in [("▲", self.moved_up), ("▼", self.moved_down)]:
            btn = _arrow_btn(arrow)
            btn.clicked.connect(lambda _=None, s=sig: s.emit(self))
            root.addWidget(btn)

        name_lbl = QLabel(f"{self._name}:")
        name_lbl.setFixedWidth(120)
        name_lbl.setStyleSheet(
            "color: #a6adc8; font-size: 18px; border: 1px solid #313244;"
            " border-radius: 3px; padding: 4px 6px;"
        )
        root.addWidget(name_lbl)

        self._proficiency = QLineEdit(lang.get("proficiency_level") or "")
        self._proficiency.setPlaceholderText("e.g. Native, Full Professional Proficiency")
        self._proficiency.setStyleSheet(
            "QLineEdit { background: #141618; border: 1px solid #89b4fa;"
            " border-radius: 4px; padding: 4px 8px; color: #cdd6f4; }"
        )
        self._proficiency.textChanged.connect(self.changed)
        root.addWidget(self._proficiency, 1)

        rm = small_danger_btn()
        rm.clicked.connect(lambda: self.removed.emit(self))
        root.addWidget(rm)

    def to_live(self) -> dict:
        return {
            "source_id":         self.source_id,
            "name":              self._name,
            "proficiency_level": self._proficiency.text().strip(),
        }


class _LanguagesWidget(QWidget):
    changed = Signal()

    def __init__(self, live_lang: list[dict], original_lang: list[dict], parent=None):
        super().__init__(parent)
        self._original_by_id = {l["id"]: l for l in original_lang if l.get("id")}
        self._rows: list[_LanguageRow] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)
        self._rows_layout = QVBoxLayout()
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(4)
        root.addLayout(self._rows_layout)
        add_btn = flat_link_btn("+ Add language from snapshot")
        add_btn.clicked.connect(self._pick)
        root.addWidget(add_btn)

        for lang in live_lang:
            self._add(lang)

    def _add(self, lang: dict):
        row = _LanguageRow(lang)
        row.removed.connect(self._remove)
        row.moved_up.connect(lambda r: self._move(r, -1))
        row.moved_down.connect(lambda r: self._move(r, +1))
        row.changed.connect(self.changed)
        self._rows.append(row)
        self._rows_layout.addWidget(row)
        self.changed.emit()

    def _remove(self, row: _LanguageRow):
        self._rows.remove(row)
        self._rows_layout.removeWidget(row)
        row.deleteLater()
        self.changed.emit()

    def _move(self, row: _LanguageRow, delta: int):
        idx = self._rows.index(row)
        new = idx + delta
        if 0 <= new < len(self._rows):
            self._rows[idx], self._rows[new] = self._rows[new], self._rows[idx]
            _reorder_layout(self._rows_layout, self._rows)
            self.changed.emit()

    def _pick(self):
        active = {r.source_id for r in self._rows if r.source_id is not None}
        avail = [(l["id"], l["name"]) for l in self._original_by_id.values()
                 if l["id"] not in active]
        if not avail:
            QMessageBox.information(
                self.window(), "Nothing to add",
                "All languages from the snapshot are already included.",
            )
            return
        dlg = _PickerDialog("Add Language", avail, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            lid = dlg.selected()
            if lid in self._original_by_id:
                src = self._original_by_id[lid]
                self._add({
                    "source_id": src["id"],
                    "name": src.get("name") or "",
                    "proficiency_level": src.get("proficiency_level") or "",
                })

    def to_live(self) -> list[dict]:
        return [r.to_live() for r in self._rows]


# ── projects ──────────────────────────────────────────────────────────


class _ProjectItem(_SubItem):
    def __init__(self, live_proj: dict, parent=None):
        super().__init__(live_proj.get("name", ""), parent)
        self._live = dict(live_proj)
        self.source_id = live_proj.get("source_id")

        # Replace the header label with an editable QLineEdit for the name.
        hdr_layout = self.layout().itemAt(0).widget().layout()
        for i in range(hdr_layout.count()):
            w = hdr_layout.itemAt(i).widget()
            if w is self._header_label:
                self._name_edit = QLineEdit(self._live.get("name") or "")
                self._name_edit.setStyleSheet(
                    "QLineEdit { color: #cdd6f4; font-size: 18px;"
                    " background: #141618; border: 1px solid #89b4fa;"
                    " border-radius: 4px; padding: 2px 6px; }"
                )
                self._name_edit.textChanged.connect(self.changed)
                hdr_layout.replaceWidget(w, self._name_edit)
                w.deleteLater()
                break

        for label, key in [("Link", "link"), ("Start", "start_date")]:
            val = live_proj.get(key) or ""
            if val:
                lbl = QLabel(val)
                lbl.setStyleSheet("color: #a6adc8; font-size: 16px;")
                lbl.setWordWrap(True)
                self._add_body_row(label, lbl)

        self._text_edit = QTextEdit()
        self._text_edit.setPlainText(live_proj.get("text") or "")
        self._text_edit.setFixedHeight(120)
        self._text_edit.setStyleSheet(
            "QTextEdit { background: #141618; border: 2px solid #89b4fa;"
            " border-radius: 4px; padding: 4px 8px; }"
        )
        self._text_edit.textChanged.connect(self.changed)
        self._body_layout.addWidget(self._text_edit)

    def to_live(self) -> dict:
        return {
            **self._live,
            "source_id": self.source_id,
            "name": self._name_edit.text().strip(),
            "text": self._text_edit.toPlainText(),
        }


class _ProjectsWidget(QWidget):
    changed = Signal()

    def __init__(self, live_prj: list[dict], original_prj: list[dict], parent=None):
        super().__init__(parent)
        self._original_by_id = {p["id"]: p for p in original_prj if p.get("id")}
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)
        self._sublist = _SubList()
        self._sublist.changed.connect(self.changed)
        root.addWidget(self._sublist)
        add_btn = flat_link_btn("+ Add project from snapshot")
        add_btn.clicked.connect(self._pick)
        root.addWidget(add_btn)
        for prj in live_prj:
            self._sublist.add(_ProjectItem(prj))

    def _pick(self):
        active = {it.source_id for it in self._sublist.items() if it.source_id is not None}
        avail = [(p["id"], p.get("name", ""))
                 for p in self._original_by_id.values() if p["id"] not in active]
        if not avail:
            QMessageBox.information(
                self.window(), "Nothing to add",
                "All projects from the snapshot are already included.",
            )
            return
        dlg = _PickerDialog("Add Project", avail, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            pid = dlg.selected()
            if pid in self._original_by_id:
                src = self._original_by_id[pid]
                live = {
                    "source_id":  src["id"],
                    "name":       src.get("name") or "",
                    "link":       src.get("link") or "",
                    "start_date": src.get("start_date") or "",
                    "end_date":   src.get("end_date") or "",
                    "is_ongoing": bool(src.get("is_ongoing")),
                    "text":       src.get("text") or "",
                }
                self._sublist.add(_ProjectItem(live))
                self.changed.emit()

    def to_live(self) -> list[dict]:
        return [it.to_live() for it in self._sublist.items() if isinstance(it, _ProjectItem)]


# ── keywords ──────────────────────────────────────────────────────────


class _KeywordsWidget(QWidget):
    changed = Signal()

    def __init__(self, live_kw: list[dict], original_kw: list[dict], parent=None):
        super().__init__(parent)
        self._pool = original_kw  # full master keywords for picker
        self._active: list[dict] = [dict(k) for k in live_kw]

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 4, 0, 0)
        root.setSpacing(4)

        pick_row = QHBoxLayout()
        self._combo = QComboBox()
        self._combo.setFixedWidth(220)
        self._combo.currentIndexChanged.connect(self._on_pick)
        pick_row.addWidget(self._combo)
        pick_row.addStretch()
        root.addLayout(pick_row)

        self._list = QListWidget()
        self._list.setFlow(QListWidget.Flow.LeftToRight)
        self._list.setWrapping(True)
        self._list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.setSpacing(4)
        self._list.setStyleSheet("""
            QListWidget { background: transparent; border: none; }
            QListWidget::item { background: #313244; color: #cdd6f4;
                border-radius: 10px; padding: 4px 12px; }
            QListWidget::item:hover { background: #f38ba8; color: #1e1e2e; }
        """)
        self._list.itemClicked.connect(self._on_chip_clicked)
        root.addWidget(self._list)

        for kw in self._active:
            self._add_chip(kw)
        self._refresh_combo()
        self._relax_height()

    def _active_ids(self) -> set:
        return {kw.get("source_id") for kw in self._active if kw.get("source_id") is not None}

    def _refresh_combo(self):
        self._combo.blockSignals(True)
        self._combo.clear()
        self._combo.addItem("— add keyword —", userData=None)
        active = self._active_ids()
        for kw in sorted(self._pool, key=lambda k: k.get("name", "")):
            if kw["id"] not in active:
                self._combo.addItem(kw["name"], userData=kw["id"])
        self._combo.blockSignals(False)

    def _on_pick(self, index: int):
        kid = self._combo.itemData(index)
        if kid is None:
            return
        kw = next((k for k in self._pool if k["id"] == kid), None)
        if not kw:
            return
        entry = {"source_id": kid, "name": kw["name"]}
        self._active.append(entry)
        self._add_chip(entry)
        self._refresh_combo()
        self._combo.setCurrentIndex(0)
        self.changed.emit()

    def _add_chip(self, kw: dict):
        item = QListWidgetItem(f"{kw['name']}  ×")
        item.setData(Qt.ItemDataRole.UserRole, kw.get("source_id"))
        self._list.addItem(item)
        self._relax_height()

    def _on_chip_clicked(self, item: QListWidgetItem):
        kw_id = item.data(Qt.ItemDataRole.UserRole)
        self._active = [k for k in self._active if k.get("source_id") != kw_id]
        self._list.takeItem(self._list.row(item))
        self._refresh_combo()
        self._relax_height()
        self.changed.emit()

    def _relax_height(self):
        count = self._list.count()
        row_h = self._list.sizeHintForRow(0) if count > 0 else 36
        self._list.setFixedHeight(
            row_h + 4 if count == 0 else self._list.sizeHint().height()
        )

    def to_live(self) -> list[dict]:
        return [dict(k) for k in self._active]


# ── section row ───────────────────────────────────────────────────────


class _SectionRow(QWidget):
    toggled = Signal()
    move_up = Signal()
    move_down = Signal()

    def __init__(self, key: str, enabled: bool, content: QWidget, parent=None):
        super().__init__(parent)
        self.key = key
        self.content = content

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 2)
        root.setSpacing(0)

        hdr = QWidget()
        hdr.setStyleSheet(
            "QWidget { background: #1e1e2e; border: 1px solid #313244; border-radius: 4px; }"
        )
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(8, 6, 10, 6)
        hl.setSpacing(6)

        for arrow, sig in [("▲", self.move_up), ("▼", self.move_down)]:
            btn = _arrow_btn(arrow)
            btn.clicked.connect(sig)
            hl.addWidget(btn)

        lbl = QLabel(SECTION_LABELS.get(key, key))
        lbl.setStyleSheet("font-size: 20px; color: #cdd6f4;")
        hl.addWidget(lbl, 1)

        self.checkbox = QCheckBox()
        self.checkbox.setChecked(enabled)
        self.checkbox.setStyleSheet("QCheckBox { border: none; }")
        hl.addWidget(self.checkbox)

        self._expand_btn = QPushButton("▶ Edit")
        self._expand_btn.setFlat(True)
        self._expand_btn.clicked.connect(self._toggle)
        hl.addWidget(self._expand_btn)

        self._body = QFrame()
        self._body.setStyleSheet(
            "QFrame { background: #181825; border: 1px solid #313244;"
            " border-top: none; border-radius: 0 0 4px 4px; }"
        )
        bl = QVBoxLayout(self._body)
        bl.setContentsMargins(12, 10, 12, 10)
        bl.setSpacing(6)
        bl.addWidget(content)
        self._body.setVisible(False)

        root.addWidget(hdr)
        root.addWidget(self._body)

        self.checkbox.stateChanged.connect(self.toggled)
        self.checkbox.stateChanged.connect(self._on_check_changed)
        self._on_check_changed()

    def _toggle(self):
        if not self.checkbox.isChecked():
            return
        _toggle_expand(self._expand_btn, self._body, "▼ Edit", "▶ Edit")

    def _on_check_changed(self):
        enabled = self.checkbox.isChecked()
        if not enabled and self._body.isVisible():
            self._body.setVisible(False)
            self._expand_btn.setText("▶ Edit")
        color = "#89b4fa" if enabled else "#45475a"
        hover = "#74c7ec" if enabled else "#45475a"
        self._expand_btn.setStyleSheet(
            f"QPushButton {{ color: {color}; font-size: 20px; padding: 0 6px;"
            f" background: transparent; border: none; min-height: 0; }}"
            f"QPushButton:hover {{ color: {hover}; }}"
        )

    def is_enabled(self) -> bool:
        return self.checkbox.isChecked()


class _SectionList(QWidget):
    order_changed = Signal()
    toggle_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[_SectionRow] = []
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(4)
        self._layout.addStretch()

    def add(self, row: _SectionRow):
        row.toggled.connect(self.toggle_changed)
        row.move_up.connect(lambda r=row: self._move(r, -1))
        row.move_down.connect(lambda r=row: self._move(r, +1))
        self._rows.append(row)
        self._layout.insertWidget(self._layout.count() - 1, row)

    def _move(self, row: _SectionRow, delta: int):
        idx = self._rows.index(row)
        new = idx + delta
        if 0 <= new < len(self._rows):
            self._rows[idx], self._rows[new] = self._rows[new], self._rows[idx]
            _reorder_layout(self._layout, self._rows)
            self.order_changed.emit()

    def order(self) -> list[str]:
        return [r.key for r in self._rows]

    def enabled_map(self) -> dict[str, bool]:
        return {r.key: r.is_enabled() for r in self._rows}

    def content(self, key: str) -> QWidget | None:
        for r in self._rows:
            if r.key == key:
                return r.content
        return None


# ── step 2 ────────────────────────────────────────────────────────────


class StepPreview(QWidget):
    back_requested = Signal()
    saved = Signal(int)

    def __init__(
        self,
        db: Database,
        db_path: Path,
        job_data: dict,
        snapshot: dict,
        application_id: int | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.db = db
        self.db_path = db_path
        self.job_data = job_data
        self.application_id = application_id
        self._snapshot = snapshot
        self._pdf_bytes: bytes | None = None

        self._regen_token = 0
        self._active_tasks: set = set()
        self._is_processing = False
        self._pending_regen = False

        self._debounce = QTimer()
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(DEBOUNCE_MS)
        self._debounce.timeout.connect(self._regenerate)

        self._build_ui()
        self._on_change()

    # ── UI ──────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        top = QWidget()
        top.setStyleSheet("background: #1e1e2e; border-bottom: 1px solid #313244;")
        top.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        tl = QHBoxLayout(top)
        tl.setContentsMargins(12, 8, 12, 8)
        tl.setSpacing(10)

        back = QPushButton("← Back")
        back.setFlat(True)
        back.setStyleSheet("color: #89b4fa;")
        back.clicked.connect(self.back_requested)

        title = QLabel(
            f"<b>{self.job_data['position_name']}</b> @ {self.job_data['company_name']}"
        )
        title.setStyleSheet("font-size: 20px; color: #cdd6f4;")

        self._status_lbl = QLabel("Ready")
        self._status_lbl.setStyleSheet("color: #a6adc8; font-size: 16px;")

        save_btn = primary_btn("Save Application")
        dl_btn = primary_btn("↓ Download PDF")
        save_btn.clicked.connect(self._save)
        dl_btn.clicked.connect(self._download)

        tl.addWidget(back)
        tl.addSpacing(8)
        tl.addWidget(title)
        tl.addStretch()
        tl.addWidget(self._status_lbl)
        tl.addSpacing(4)
        tl.addWidget(save_btn)
        tl.addWidget(dl_btn)
        root.addWidget(top)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        left_inner = QWidget()
        ll = QVBoxLayout(left_inner)
        ll.setContentsMargins(12, 12, 12, 12)
        ll.setSpacing(8)
        hint = QLabel("▲▼ reorder  ·  ✓ enable section  ·  ▶ Edit to expand")
        hint.setStyleSheet("color: #585b70; font-size: 16px;")
        ll.addWidget(hint)

        self._section_list = _SectionList()
        self._section_list.order_changed.connect(self._on_change)
        self._section_list.toggle_changed.connect(self._on_change)
        self._populate_sections()
        ll.addWidget(self._section_list, 1)

        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setWidget(left_inner)
        left_scroll.setFrameShape(QFrame.Shape.NoFrame)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._preview = PdfPreviewWidget()
        splitter.addWidget(left_scroll)
        splitter.addWidget(self._preview)
        splitter.setSizes([600, 400])
        root.addWidget(splitter, 1)

    def _populate_sections(self):
        live = self._snapshot["live"]
        original = self._snapshot["original"]

        order = list(live.get("section_order") or SECTION_KEYS)
        enabled = dict(live.get("sections_enabled") or {k: True for k in SECTION_KEYS})
        # ensure all known section keys are present
        for k in SECTION_KEYS:
            if k not in order:
                order.append(k)
                enabled.setdefault(k, True)

        for key in order:
            content = self._make_content(key, live, original)
            if content is None:
                continue
            row = _SectionRow(key, enabled.get(key, True), content)
            self._section_list.add(row)

    def _make_content(self, key: str, live: dict, original: dict) -> QWidget | None:
        if key == "contact":
            w = _ContactWidget(live.get("contact") or {}, original.get("websites") or [])
        elif key == "summary":
            w = _SummaryWidget(live.get("summary") or {}, original.get("profile_summaries") or [])
        elif key == "experience":
            w = _ExperienceWidget(live.get("experience") or [], original.get("experiences") or [])
        elif key == "education":
            w = _EducationWidget(live.get("education") or [], original.get("education") or [])
        elif key == "languages":
            w = _LanguagesWidget(live.get("languages") or [], original.get("languages") or [])
        elif key == "projects":
            w = _ProjectsWidget(live.get("projects") or [], original.get("projects") or [])
        elif key == "keywords":
            w = _KeywordsWidget(live.get("keywords") or [], original.get("keywords") or [])
        else:
            return None
        w.changed.connect(self._on_change)
        return w

    # ── state ───────────────────────────────────────────────────────

    def _current_snapshot(self) -> dict:
        live = self._snapshot["live"]
        return {
            "version":  self._snapshot.get("version", 1),
            "original": self._snapshot["original"],
            "live": {
                "section_order":    self._section_list.order(),
                "sections_enabled": self._section_list.enabled_map(),
                "contact":   self._section_list.content("contact").to_live()
                              if self._section_list.content("contact") else (live.get("contact") or {}),
                "summary":   self._section_list.content("summary").to_live()
                              if self._section_list.content("summary") else (live.get("summary") or {}),
                "experience": self._section_list.content("experience").to_live()
                              if self._section_list.content("experience") else (live.get("experience") or []),
                "education": self._section_list.content("education").to_live()
                              if self._section_list.content("education") else (live.get("education") or []),
                "languages": self._section_list.content("languages").to_live()
                              if self._section_list.content("languages") else (live.get("languages") or []),
                "projects":  self._section_list.content("projects").to_live()
                              if self._section_list.content("projects") else (live.get("projects") or []),
                "keywords":  self._section_list.content("keywords").to_live()
                              if self._section_list.content("keywords") else (live.get("keywords") or []),
                "template":   live.get("template") or {},
                "date_format": live.get("date_format") or "YYYY",
            },
        }

    # ── regenerate + save ──────────────────────────────────────────

    def _on_change(self):
        if self._is_processing:
            self._pending_regen = True
            return
        self._status_lbl.setText("Updating...")
        self._debounce.start()

    def _regenerate(self):
        from resume.generator import render_pdf_from_snapshot

        self._is_processing = True
        self._regen_token += 1
        token = self._regen_token
        snap = copy.deepcopy(self._current_snapshot())
        task = _Task(render_pdf_from_snapshot, snap)
        self._active_tasks.add(task)
        task.sigs.done.connect(lambda pdf, t=token, tk=task: self._on_regen_done(pdf, t, tk))
        task.sigs.error.connect(lambda msg, tk=task: self._on_regen_error(msg, tk))
        QThreadPool.globalInstance().start(task)

    def _on_regen_done(self, pdf_bytes: bytes, token: int, task):
        self._active_tasks.discard(task)
        if token != self._regen_token:
            self._is_processing = False
            return
        self._pdf_bytes = pdf_bytes
        self._preview.load_bytes(pdf_bytes)
        self._status_lbl.setText("Preview updated")
        self._save()

    def _on_regen_error(self, msg: str, task):
        self._active_tasks.discard(task)
        self._is_processing = False
        self._status_lbl.setText(f"Error: {msg}")
        if self._pending_regen:
            self._pending_regen = False
            self._on_change()

    def _save(self):
        try:
            self._do_save()
        except Exception as e:  # noqa: BLE001
            self._status_lbl.setText(f"Save failed: {e}")
        finally:
            self._is_processing = False
            if self._pending_regen:
                self._pending_regen = False
                self._on_change()

    def _do_save(self):
        snap = self._current_snapshot()
        # keep self._snapshot up to date so any subsequent picker (which reads
        # from original) operates against the same data
        self._snapshot = snap
        jd = self.job_data
        self.application_id = self.db.upsert_application(
            profile_id=jd.get("profile_id"),
            status_id=jd.get("status_id", 1),
            position_name=jd["position_name"],
            company_name=jd["company_name"],
            date_applied=jd.get("date_applied"),
            job_posting_url=jd.get("job_posting_url"),
            job_posting_description=jd.get("job_posting_description"),
            snapshot=json.dumps(snap),
            id=self.application_id,
        )
        self.saved.emit(self.application_id)
        self._status_lbl.setText("Saved")

    def _download(self):
        if not self._pdf_bytes:
            QMessageBox.warning(self, "Not ready", "Wait for the preview to finish.")
            return
        settings = self.db.get_settings()
        folder = settings.get("pdf_output_folder") or str(Path.home())
        tmpl = settings.get("pdf_filename_template") or "{company}_{position}_{date}"
        auto_name = (
            tmpl.replace("{company}", self.job_data["company_name"])
                .replace("{position}", self.job_data["position_name"])
                .replace("{date}", date.today().strftime("%Y-%m-%d"))
                .replace(" ", "_")
        )
        out_path = Path(folder) / f"{auto_name}.pdf"
        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(self._pdf_bytes)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Download failed", str(e))
            return
        if self.application_id:
            self.db.execute(
                "UPDATE job_application SET resume_pdf_path=? WHERE id=?",
                (str(out_path), self.application_id),
            )
        self._status_lbl.setText(f"Downloaded: {out_path.name}")
