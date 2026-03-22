"""
ui/wizard/step_preview.py
Wizard step 2: live resume editor + PDF preview.
"""

from __future__ import annotations
import json
from pathlib import Path
from datetime import date

from PySide6.QtCore import Qt, Signal, QTimer, QThreadPool, QRunnable, QObject
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QLabel, QLineEdit, QPushButton, QCheckBox, QButtonGroup, QRadioButton,
    QScrollArea, QFrame, QDialog, QListWidget, QListWidgetItem,
    QDialogButtonBox, QMessageBox, QSizePolicy, QTextEdit, QComboBox,
)

from db.database import Database
from pdf.display import PdfPreviewWidget
from ui.widgets import primary_btn, flat_link_btn, small_danger_btn

SECTION_LABELS = {
    "contact":    "Contact",
    "summary":    "Summary",
    "experience": "Experience",
    "education":  "Education",
    "projects":   "Projects",
    "keywords":   "Skills / Keywords",
}
DEBOUNCE_MS = 500


# ── shared layout helpers ─────────────────────────────────────────────

def _reorder_layout(layout, items: list) -> None:
    """Remove all items from layout then reinsert in current list order."""
    for item in items:
        layout.removeWidget(item)
    for i, item in enumerate(items):
        layout.insertWidget(i, item)


def _toggle_expand(btn: QPushButton, body: QWidget,
                   expanded: str, collapsed: str) -> None:
    """Toggle body visibility and update btn text accordingly."""
    v = not body.isVisible()
    body.setVisible(v)
    btn.setText(expanded if v else collapsed)


# ── worker ────────────────────────────────────────────────────────────

class _Sig(QObject):
    done  = Signal(bytes)
    error = Signal(str)

class _Task(QRunnable):
    def __init__(self, fn, *args):
        super().__init__()
        self.fn = fn; self.args = args; self.sigs = _Sig()
    def run(self):
        try:    self.sigs.done.emit(self.fn(*self.args))
        except Exception as e: self.sigs.error.emit(str(e))


# ── picker dialog ─────────────────────────────────────────────────────

class _PickerDialog(QDialog):
    def __init__(self, title: str, items: list[tuple[int, str]], parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(400)
        layout = QVBoxLayout(self)
        self._list = QListWidget()
        for item_id, label in items:
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, item_id)
            self._list.addItem(item)
        layout.addWidget(self._list)
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def selected_id(self):
        item = self._list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None


# ── bullet sub-item ───────────────────────────────────────────────────

class _BulletSubItem(QWidget):
    changed    = Signal()
    removed    = Signal(object)
    moved_up   = Signal(object)
    moved_down = Signal(object)

    def __init__(self, bullet: dict | None = None,
                 override: str | None = None, parent=None):
        super().__init__(parent)
        self.bullet_id = bullet["id"] if bullet else None
        self._original = bullet["text"] if bullet else ""

        hl = QHBoxLayout(self)
        hl.setContentsMargins(0, 1, 0, 1)
        hl.setSpacing(4)

        for arrow, sig in [("▲", self.moved_up), ("▼", self.moved_down)]:
            btn = QPushButton(arrow)
            btn.setFixedSize(48, 48); btn.setFlat(True)
            btn.setStyleSheet(
                "QPushButton { font-size: 22px; color: #89b4fa;"
                " background-color: #313244; border-radius: 6px; border: none;"
                " min-height: 0; min-width: 0; }"
                "QPushButton:hover { background-color: #45475a; }"
            )
            btn.clicked.connect(lambda _=None, s=sig: s.emit(self))
            hl.addWidget(btn)

        self.edit = QTextEdit(override if override is not None else self._original)
        self.edit.setFixedHeight(72)
        self.edit.setStyleSheet(
            "QTextEdit { font-size: 16px; border: 1px solid #313244; border-radius: 4px; }"
        )
        self.edit.textChanged.connect(self.changed)
        hl.addWidget(self.edit, 1)

        rst = QPushButton("↺")
        rst.setFixedSize(28, 28); rst.setFlat(True)
        rst.setStyleSheet("QPushButton { color: #a6adc8; background: transparent; border: none; min-height:0; min-width:0; }")
        rst.setToolTip("Reset to original")
        rst.clicked.connect(lambda: self.edit.setText(self._original))
        hl.addWidget(rst)

        rm = small_danger_btn()
        rm.clicked.connect(lambda: self.removed.emit(self))
        hl.addWidget(rm)

    def current_text(self) -> str: return self.edit.toPlainText()
    def is_overridden(self) -> bool:
        return self.bullet_id is not None and self.edit.toPlainText() != self._original


class _BulletSubList(QWidget):
    changed = Signal()

    def __init__(self, bullets: list[dict], overrides: dict[int, str],
                 all_bullets: list[dict], parent=None):
        super().__init__(parent)
        self._all_bullets = all_bullets
        self._items: list[_BulletSubItem] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(2)

        self._list_layout = QVBoxLayout()
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(2)
        root.addLayout(self._list_layout)

        add_btn = flat_link_btn("+ Add bullet point")
        add_btn.clicked.connect(self._pick_bullet)
        root.addWidget(add_btn)

        for bp in bullets:
            self._add_item(bp, overrides.get(bp["id"]))

    def _add_item(self, bullet: dict | None, override: str | None = None):
        item = _BulletSubItem(bullet, override)
        item.changed.connect(self.changed)
        item.removed.connect(self._remove)
        item.moved_up.connect(lambda i: self._move(i, -1))
        item.moved_down.connect(lambda i: self._move(i, +1))
        self._items.append(item)
        self._list_layout.addWidget(item)

    def _remove(self, item: _BulletSubItem):
        self._items.remove(item)
        self._list_layout.removeWidget(item)
        item.deleteLater()
        self.changed.emit()

    def _move(self, item: _BulletSubItem, delta: int):
        idx = self._items.index(item)
        new = idx + delta
        if new < 0 or new >= len(self._items): return
        self._items[idx], self._items[new] = self._items[new], self._items[idx]
        _reorder_layout(self._list_layout, self._items)
        self.changed.emit()

    def _pick_bullet(self):
        current_ids = {i.bullet_id for i in self._items if i.bullet_id is not None}
        available   = [
            (bp["id"], bp["text"][:70] + ("…" if len(bp["text"]) > 70 else ""))
            for bp in self._all_bullets if bp["id"] not in current_ids
        ]
        if not available:
            QMessageBox.information(self.window(), "Nothing to add", "All bullet points are already included.")
            return
        dlg = _PickerDialog("Add Bullet Point", available, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            bid = dlg.selected_id()
            if bid:
                bp = next(b for b in self._all_bullets if b["id"] == bid)
                self._add_item(bp)
                self.changed.emit()

    def get_overrides(self) -> dict[int, str]:
        return {i.bullet_id: i.current_text() for i in self._items if i.is_overridden()}

    def get_included_ids(self) -> list[int]:
        return [i.bullet_id for i in self._items if i.bullet_id is not None]


# ── sub-item base ─────────────────────────────────────────────────────

class _SubItem(QWidget):
    removed    = Signal(object)
    moved_up   = Signal(object)
    moved_down = Signal(object)
    changed    = Signal()

    def __init__(self, item_id: int, header_text: str, parent=None):
        super().__init__(parent)
        self.item_id = item_id

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 2)
        root.setSpacing(0)

        hdr = QWidget()
        hdr.setStyleSheet("QWidget { background: #252535; border: 1px solid #313244; border-radius: 3px; }")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(8, 4, 8, 4)
        hl.setSpacing(6)

        for arrow, sig in [("▲", self.moved_up), ("▼", self.moved_down)]:
            btn = QPushButton(arrow)
            btn.setFixedSize(48, 48); btn.setFlat(True)
            btn.setStyleSheet(
                "QPushButton { font-size: 22px; color: #89b4fa;"
                " background-color: #313244; border-radius: 6px; border: none;"
                " min-height: 0; min-width: 0; }"
                "QPushButton:hover { background-color: #45475a; }"
            )
            btn.clicked.connect(lambda _=None, s=sig: s.emit(self))
            hl.addWidget(btn)

        lbl = QLabel(header_text)
        lbl.setStyleSheet("color: #cdd6f4; font-size: 18px;")
        hl.addWidget(lbl, 1)

        self._expand_btn = QPushButton("▶ Edit")
        self._expand_btn.setFixedHeight(48); self._expand_btn.setFlat(True)
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
        self._body.setStyleSheet("QWidget { background: #181825; border: 1px solid #313244; border-top: none; border-radius: 0 0 3px 3px; }")
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(12, 8, 12, 8)
        self._body_layout.setSpacing(6)
        self._body.setVisible(False)

        root.addWidget(hdr)
        root.addWidget(self._body)

    def _toggle(self):
        _toggle_expand(self._expand_btn, self._body, "▼ Edit", "▶ Edit")

    def _add_body_row(self, label: str, widget: QWidget):
        row = QHBoxLayout()
        lbl = QLabel(label); lbl.setFixedWidth(90)
        lbl.setStyleSheet("color: #a6adc8; font-size: 16px;")
        row.addWidget(lbl); row.addWidget(widget, 1)
        self._body_layout.addLayout(row)


# ── section content widgets ───────────────────────────────────────────

class _ContactContent(QWidget):
    changed = Signal()

    def __init__(self, contact: dict, websites: list[dict],
                 all_websites: list[dict], parent=None):
        super().__init__(parent)
        self._all_websites = all_websites
        self._site_rows: list[tuple[dict, QWidget, QLineEdit]] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        self._fields: dict[str, QLineEdit] = {}
        for key, label, placeholder in [
            ("name",     "Name",     "Full name"),
            ("email",    "Email",    "email@example.com"),
            ("phone",    "Phone",    "+1 555 000 0000"),
            ("location", "Location", "City, Country"),
        ]:
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(12)
            lbl = QLabel(label)
            lbl.setFixedWidth(100)
            lbl.setStyleSheet(
                "color: #a6adc8; font-size: 18px;"
                " border: 1px solid #313244; border-radius: 3px; padding: 4px 6px;"
            )
            f = QLineEdit(contact.get(key) or "")
            f.setPlaceholderText(placeholder)
            f.textChanged.connect(self.changed)
            self._fields[key] = f
            row.addWidget(lbl)
            row.addWidget(f, 1)
            root.addLayout(row)

        lbl_sites = QLabel("Websites")
        lbl_sites.setStyleSheet("color: #a6adc8; font-size: 18px; font-weight: bold; margin-top: 4px; border: none;")
        root.addWidget(lbl_sites)

        self._sites_layout = QVBoxLayout()
        self._sites_layout.setContentsMargins(0, 0, 0, 0)
        self._sites_layout.setSpacing(4)
        root.addLayout(self._sites_layout)

        for site in websites:
            self._add_site_row(site)

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
            "color: #a6adc8; font-size: 18px;"
            " border: 1px solid #313244; border-radius: 3px; padding: 4px 6px;"
        )
        url_edit = QLineEdit(site.get("url", ""))
        url_edit.textChanged.connect(self.changed)

        rm = small_danger_btn()
        rm.clicked.connect(lambda _=None, s=site, w=row_w: self._remove_site(s, w))

        hl.addWidget(lbl)
        hl.addWidget(url_edit, 1)
        hl.addWidget(rm)

        self._site_rows.append((site, row_w, url_edit))
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
            (i, f"{s.get('label','')} — {s.get('url','')}")
            for i, s in enumerate(self._all_websites)
            if s.get("label") not in active_labels
        ]
        if not available:
            QMessageBox.information(self.window(), "No more websites",
                "All saved websites are already included. Add more in the Contact section.")
            return
        dlg = _PickerDialog("Add Website", available, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            idx = dlg.selected_id()
            if idx is not None:
                self._add_site_row(self._all_websites[idx])

    def get_data(self) -> tuple[dict, list[dict]]:
        contact  = {k: f.text().strip() for k, f in self._fields.items()}
        websites = [
            {**s, "url": e.text().strip()}
            for s, _, e in self._site_rows
        ]
        return contact, websites


class _SummaryContent(QWidget):
    changed = Signal()

    def __init__(self, profiles: list[dict], current_profile_id: int,
                 saved_text_override: str | None = None, parent=None):
        super().__init__(parent)
        self._group = QButtonGroup(self)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        if not any(p.get("summary") for p in profiles):
            root.addWidget(QLabel("No summaries saved. Add one in the Summary section."))
            self._edit = QTextEdit()
            self._edit.setFixedHeight(120)
            self._edit.setStyleSheet(
                "QTextEdit { background: #141618; border: 2px solid #89b4fa;"
                " border-radius: 4px; padding: 4px 8px; }"
            )
            self._edit.textChanged.connect(self.changed)
            root.addWidget(self._edit)
            return

        # radio container
        radio_container = QWidget()
        radio_container.setStyleSheet(
            "QWidget#radioContainer { border: 1px solid #6c7086;"
            " border-radius: 4px; background: transparent; }"
        )
        radio_container.setObjectName("radioContainer")
        radio_layout = QVBoxLayout(radio_container)
        radio_layout.setContentsMargins(6, 4, 6, 4)
        radio_layout.setSpacing(2)

        for p in profiles:
            summary = (p.get("summary") or "").strip()
            if not summary:
                continue
            rb_row = QWidget()
            rb_row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
            rbl = QHBoxLayout(rb_row)
            rbl.setContentsMargins(4, 2, 4, 2); rbl.setSpacing(8)
            rb = QRadioButton()
            rb.setStyleSheet("""
                QRadioButton { border: none; background: transparent; }
                QRadioButton::indicator { width: 16px; height: 16px;
                    border: 2px solid #89b4fa; border-radius: 8px; background: transparent; }
                QRadioButton::indicator:checked { background: #89b4fa; }
                QRadioButton::indicator:hover { border-color: #cdd6f4; }
            """)
            rb.setProperty("profile_id",    p["id"])
            rb.setProperty("summary_text",  summary)
            self._group.addButton(rb)
            lbl = QLabel(f"<b>{p['name']}</b>  —  {summary}")
            lbl.setStyleSheet("QLabel { font-size: 15px; color: #a6adc8; border: none; background: transparent; }")
            lbl.setWordWrap(True)
            lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
            lbl.mousePressEvent = lambda _e, r=rb: r.setChecked(True)
            rbl.addWidget(rb); rbl.addWidget(lbl, 1)
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

        # pre-select current profile, fall back to first with a summary
        chosen_btn = None
        for btn in self._group.buttons():
            if btn.property("profile_id") == current_profile_id:
                chosen_btn = btn
                break
        if chosen_btn is None and self._group.buttons():
            chosen_btn = self._group.buttons()[0]

        if chosen_btn:
            initial = saved_text_override if saved_text_override is not None \
                      else chosen_btn.property("summary_text")
            self._edit.blockSignals(True)
            self._edit.setPlainText(initial)
            self._edit.blockSignals(False)
            chosen_btn.setChecked(True)

    def _on_radio_toggled(self, btn, checked: bool):
        if not checked:
            return
        actual = self._group.checkedButton()
        if actual is None:
            return
        self._edit.blockSignals(True)
        self._edit.setPlainText(actual.property("summary_text"))
        self._edit.blockSignals(False)
        self.changed.emit()

    def get_text_override(self) -> str:
        return self._edit.toPlainText().strip()


class _ExperienceItem(_SubItem):
    def __init__(self, job: dict, overrides: dict[int, str],
                 included_bullet_ids: list[int] | None = None, parent=None):
        label = f"{job['position_name']} — {job['organization_name']}"
        super().__init__(job["id"], label, parent)
        all_bullets = job.get("bullet_points", [])
        if included_bullet_ids is not None:
            id_order = {bid: i for i, bid in enumerate(included_bullet_ids)}
            active = sorted(
                [b for b in all_bullets if b["id"] in id_order],
                key=lambda b: id_order[b["id"]]
            )
        else:
            active = all_bullets
        self._bullet_list = _BulletSubList(active, overrides, all_bullets)
        self._bullet_list.changed.connect(self.changed)
        self._body_layout.addWidget(self._bullet_list)

    def get_overrides(self) -> dict[int, str]:
        return self._bullet_list.get_overrides()


class _EducationItem(_SubItem):
    def __init__(self, edu: dict, parent=None):
        label = f"{edu.get('degree','')} — {edu.get('school','')}"
        super().__init__(edu["id"], label, parent)
        for lbl, key in [("Field","field"),("GPA","gpa"),("Start","start_date"),("End","end_date")]:
            val = edu.get(key) or ""
            if val:
                w = QLabel(val); w.setStyleSheet("color: #a6adc8; font-size: 16px;")
                self._add_body_row(lbl, w)


class _ProjectItem(_SubItem):
    def __init__(self, proj: dict, parent=None):
        super().__init__(proj["id"], proj.get("name",""), parent)
        self._original_name = proj.get("name") or ""

        # replace the read-only header label with an editable QLineEdit
        hdr_layout = self.layout().itemAt(0).widget().layout()
        for i in range(hdr_layout.count()):
            w = hdr_layout.itemAt(i).widget()
            if isinstance(w, QLabel) and w.text() == self._original_name:
                self._name_edit = QLineEdit(self._original_name)
                self._name_edit.setStyleSheet(
                    "QLineEdit { color: #cdd6f4; font-size: 18px;"
                    " background: #141618; border: 1px solid #89b4fa;"
                    " border-radius: 4px; padding: 2px 6px; }"
                )
                self._name_edit.textChanged.connect(self.changed)
                hdr_layout.replaceWidget(w, self._name_edit)
                w.deleteLater()
                break

        for lbl, key in [("Link","link"),("Start","start_date")]:
            val = proj.get(key) or ""
            if val:
                w = QLabel(val); w.setStyleSheet("color: #a6adc8; font-size: 16px;")
                w.setWordWrap(True)
                self._add_body_row(lbl, w)

        self._text_edit = QTextEdit()
        self._text_edit.setPlainText(proj.get("text") or "")
        self._text_edit.setFixedHeight(120)
        self._text_edit.setStyleSheet(
            "QTextEdit { background: #141618; border: 2px solid #89b4fa;"
            " border-radius: 4px; padding: 4px 8px; }"
        )
        self._text_edit.textChanged.connect(self.changed)
        self._body_layout.addWidget(self._text_edit)

    def get_text(self) -> str:
        return self._text_edit.toPlainText().strip()

    def get_name(self) -> str:
        return self._name_edit.text().strip()


class _SubList(QWidget):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: list[_SubItem] = []
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(3)

    def add_item(self, item: _SubItem):
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
        idx = self._items.index(item); new = idx + delta
        if new < 0 or new >= len(self._items): return
        self._items[idx], self._items[new] = self._items[new], self._items[idx]
        _reorder_layout(self._layout, self._items)
        self.changed.emit()

    def item_ids(self) -> list[int]:
        return [i.item_id for i in self._items]


class _ExperienceContent(QWidget):
    changed = Signal()

    def __init__(self, experiences: list[dict], included_ids: list[int] | None,
                 overrides: dict[int, str],
                 included_bullets_map: dict[int, list[int]] | None = None,
                 parent=None):
        super().__init__(parent)
        self._all = experiences
        self._overrides = overrides
        self._included_bullets_map = included_bullets_map or {}
        root = QVBoxLayout(self); root.setContentsMargins(0,0,0,0); root.setSpacing(4)
        self._sublist = _SubList(); self._sublist.changed.connect(self.changed)
        root.addWidget(self._sublist)
        add_btn = flat_link_btn("+ Add experience"); add_btn.clicked.connect(self._add_picker)
        root.addWidget(add_btn)
        shown = experiences
        if included_ids is not None:
            id_map = {e["id"]: e for e in experiences}
            shown  = [id_map[i] for i in included_ids if i in id_map]
        for job in shown: self._add_item(job)

    def _add_item(self, job: dict):
        bullet_ids = self._included_bullets_map.get(job["id"])
        item = _ExperienceItem(job, self._overrides, bullet_ids)
        self._sublist.add_item(item)

    def _add_picker(self):
        current = set(self._sublist.item_ids())
        avail   = [(e["id"], f"{e['position_name']} — {e['organization_name']}")
                   for e in self._all if e["id"] not in current]
        if not avail:
            QMessageBox.information(self.window(),"Nothing to add","All experiences are already included.")
            return
        dlg = _PickerDialog("Add Experience", avail, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            eid = dlg.selected_id()
            if eid:
                job = next(e for e in self._all if e["id"] == eid)
                self._add_item(job); self.changed.emit()

    def included_ids(self) -> list[int]: return self._sublist.item_ids()
    def get_overrides(self) -> dict[int, str]:
        overrides = {}
        for item in self._sublist._items:
            if isinstance(item, _ExperienceItem):
                overrides.update(item.get_overrides())
        return overrides


class _EducationContent(QWidget):
    changed = Signal()

    def __init__(self, education: list[dict], included_ids: list[int] | None, parent=None):
        super().__init__(parent)
        self._all = education
        root = QVBoxLayout(self); root.setContentsMargins(0,0,0,0); root.setSpacing(4)
        self._sublist = _SubList(); self._sublist.changed.connect(self.changed)
        root.addWidget(self._sublist)
        add_btn = flat_link_btn("+ Add education"); add_btn.clicked.connect(self._add_picker)
        root.addWidget(add_btn)
        shown = education
        if included_ids is not None:
            id_map = {e["id"]: e for e in education}
            shown  = [id_map[i] for i in included_ids if i in id_map]
        for edu in shown: self._sublist.add_item(_EducationItem(edu))

    def _add_picker(self):
        current = set(self._sublist.item_ids())
        avail   = [(e["id"], f"{e.get('degree','')} — {e.get('school','')}")
                   for e in self._all if e["id"] not in current]
        if not avail:
            QMessageBox.information(self.window(),"Nothing to add","All education entries are already included.")
            return
        dlg = _PickerDialog("Add Education", avail, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            eid = dlg.selected_id()
            if eid:
                edu = next(e for e in self._all if e["id"] == eid)
                self._sublist.add_item(_EducationItem(edu)); self.changed.emit()

    def included_ids(self) -> list[int]: return self._sublist.item_ids()


class _ProjectsContent(QWidget):
    changed = Signal()

    def __init__(self, projects: list[dict], included_ids: list[int] | None, parent=None):
        super().__init__(parent)
        self._all = projects
        root = QVBoxLayout(self); root.setContentsMargins(0,0,0,0); root.setSpacing(4)
        self._sublist = _SubList(); self._sublist.changed.connect(self.changed)
        root.addWidget(self._sublist)
        add_btn = flat_link_btn("+ Add project"); add_btn.clicked.connect(self._add_picker)
        root.addWidget(add_btn)
        shown = projects
        if included_ids is not None:
            id_map = {p["id"]: p for p in projects}
            shown  = [id_map[i] for i in included_ids if i in id_map]
        for proj in shown: self._sublist.add_item(_ProjectItem(proj))

    def _add_picker(self):
        current = set(self._sublist.item_ids())
        avail   = [(p["id"], p.get("name","")) for p in self._all if p["id"] not in current]
        if not avail:
            QMessageBox.information(self.window(),"Nothing to add","All projects are already included.")
            return
        dlg = _PickerDialog("Add Project", avail, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            pid = dlg.selected_id()
            if pid:
                proj = next(p for p in self._all if p["id"] == pid)
                self._sublist.add_item(_ProjectItem(proj)); self.changed.emit()

    def included_ids(self) -> list[int]: return self._sublist.item_ids()

    def get_text_overrides(self) -> dict[int, str]:
        overrides = {}
        for item in self._sublist._items:
            if isinstance(item, _ProjectItem):
                text     = item.get_text()
                original = next((p.get("text") or "" for p in self._all if p["id"] == item.item_id), "")
                if text != original.strip():
                    overrides[item.item_id] = text
        return overrides

    def get_name_overrides(self) -> dict[int, str]:
        overrides = {}
        for item in self._sublist._items:
            if isinstance(item, _ProjectItem):
                name     = item.get_name()
                original = next((p.get("name") or "" for p in self._all if p["id"] == item.item_id), "")
                if name != original.strip():
                    overrides[item.item_id] = name
        return overrides


class _KeywordsContent(QWidget):
    changed = Signal()

    def __init__(self, all_keywords: list[dict], initial_ids: list[int], parent=None):
        super().__init__(parent)
        self._all_kw     = all_keywords
        self._active_ids = list(initial_ids)

        root = QVBoxLayout(self); root.setContentsMargins(0,4,0,0); root.setSpacing(4)

        # picker combo at the top — consistent with other keyword views
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
            QListWidget {
                background: transparent;
                border: none;
            }
            QListWidget::item {
                background: #313244;
                color: #cdd6f4;
                border-radius: 10px;
                padding: 4px 12px;
            }
            QListWidget::item:hover {
                background: #f38ba8;
                color: #1e1e2e;
            }
        """)
        self._list.itemClicked.connect(self._on_chip_clicked)
        root.addWidget(self._list)

        for kw_id in self._active_ids:
            kw = next((k for k in all_keywords if k["id"] == kw_id), None)
            if kw:
                self._add_chip(kw)

        self._refresh_combo()
        self._relax_height()

    def _refresh_combo(self):
        self._combo.blockSignals(True)
        self._combo.clear()
        self._combo.addItem("— add keyword —", userData=None)
        for kw in sorted(self._all_kw, key=lambda k: k["name"]):
            if kw["id"] not in self._active_ids:
                self._combo.addItem(kw["name"], userData=kw["id"])
        self._combo.blockSignals(False)

    def _on_pick(self, index: int):
        kid = self._combo.itemData(index)
        if kid is None:
            return
        self._active_ids.append(kid)
        kw = next(k for k in self._all_kw if k["id"] == kid)
        self._add_chip(kw)
        self._refresh_combo()
        self._combo.setCurrentIndex(0)
        self.changed.emit()

    def _add_chip(self, kw: dict):
        item = QListWidgetItem(f"{kw['name']}  ×")
        item.setData(Qt.ItemDataRole.UserRole, kw["id"])
        self._list.addItem(item)
        self._relax_height()

    def _on_chip_clicked(self, item: QListWidgetItem):
        kw_id = item.data(Qt.ItemDataRole.UserRole)
        if kw_id in self._active_ids:
            self._active_ids.remove(kw_id)
        self._list.takeItem(self._list.row(item))
        self._refresh_combo()
        self._relax_height()
        self.changed.emit()

    def _relax_height(self):
        count = self._list.count()
        row_h = self._list.sizeHintForRow(0) if count > 0 else 36
        self._list.setFixedHeight(row_h + 4 if count == 0
                                  else self._list.sizeHint().height())

    def _remove(self, kw_id: int):
        if kw_id in self._active_ids:
            self._active_ids.remove(kw_id)
        for i in range(self._list.count()):
            if self._list.item(i).data(Qt.ItemDataRole.UserRole) == kw_id:
                self._list.takeItem(i)
                break
        self._refresh_combo()
        self._relax_height()

    def active_ids(self) -> list[int]:
        return self._active_ids


# ── section row ───────────────────────────────────────────────────────

class SectionRow(QWidget):
    toggled   = Signal()
    move_up   = Signal()
    move_down = Signal()

    def __init__(self, key: str, enabled: bool, content_widget: QWidget, parent=None):
        super().__init__(parent)
        self.key             = key
        self._content_widget = content_widget

        root = QVBoxLayout(self); root.setContentsMargins(0,0,0,2); root.setSpacing(0)

        hdr = QWidget()
        hdr.setStyleSheet("QWidget { background: #1e1e2e; border: 1px solid #313244; border-radius: 4px; }")
        hl = QHBoxLayout(hdr); hl.setContentsMargins(8,6,10,6); hl.setSpacing(6)

        for arrow, sig in [("▲", self.move_up), ("▼", self.move_down)]:
            btn = QPushButton(arrow)
            btn.setFixedSize(48, 48)
            btn.setStyleSheet(
                "QPushButton { font-size: 22px; color: #89b4fa;"
                " background-color: #313244; border-radius: 6px; border: none;"
                " min-height: 0; min-width: 0; }"
                "QPushButton:hover { background-color: #45475a; }"
            )
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
        bl = QVBoxLayout(self._body); bl.setContentsMargins(12,10,12,10); bl.setSpacing(6)
        bl.addWidget(content_widget)
        self._body.setVisible(False)

        root.addWidget(hdr); root.addWidget(self._body)

        # wire checkbox after all widgets are constructed
        self.checkbox.stateChanged.connect(self.toggled)
        self.checkbox.stateChanged.connect(self._on_check_changed)
        self._on_check_changed()  # apply initial style

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


# ── section list ──────────────────────────────────────────────────────

class SectionList(QWidget):
    order_changed  = Signal()
    toggle_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[SectionRow] = []
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0,0,0,0)
        self._layout.setSpacing(4)
        self._layout.addStretch()

    def add_section(self, row: SectionRow):
        row.toggled.connect(self.toggle_changed)
        row.move_up.connect(lambda r=row: self._move(r, -1))
        row.move_down.connect(lambda r=row: self._move(r, +1))
        self._rows.append(row)
        self._layout.insertWidget(self._layout.count() - 1, row)

    def _move(self, row: SectionRow, delta: int):
        idx = self._rows.index(row); new = idx + delta
        if new < 0 or new >= len(self._rows): return
        self._rows[idx], self._rows[new] = self._rows[new], self._rows[idx]
        _reorder_layout(self._layout, self._rows)
        self.order_changed.emit()

    def get_order(self) -> list[str]: return [r.key for r in self._rows]
    def get_enabled(self) -> dict[str, bool]: return {r.key: r.is_enabled() for r in self._rows}

    def get_content(self, key: str) -> QWidget | None:
        for row in self._rows:
            if row.key == key: return row._content_widget
        return None


# ── step 2 ────────────────────────────────────────────────────────────

class StepPreview(QWidget):
    back_requested = Signal()
    saved          = Signal(int)

    def __init__(self, db: Database, db_path: Path, job_data: dict,
                 application_id: int | None = None, parent=None):
        super().__init__(parent)
        self.db             = db
        self.db_path        = db_path
        self.job_data       = job_data
        self.application_id = application_id
        self._pdf_bytes: bytes | None = None
        self._regen_token   = 0
        self._active_tasks: set = set()

        self._bullet_overrides: dict[int, str] = {}
        self._app: dict | None = None
        if application_id:
            self._bullet_overrides = db.get_bullet_overrides(application_id)
            self._app = db.get_application(application_id)

        self._resume_data    = db.get_resume_data(job_data["profile_id"])
        self._all_kw         = db.get_keywords()
        self._all_profiles   = db.get_profiles()
        self._profile_kw_ids = {k["id"] for k in self._resume_data["profile_keywords"]}

        self._debounce = QTimer()
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(DEBOUNCE_MS)
        self._debounce.timeout.connect(self._regenerate)

        self._save_debounce = QTimer()
        self._save_debounce.setSingleShot(True)
        self._save_debounce.setInterval(1000)
        self._save_debounce.timeout.connect(self._save)

        self._build_ui()
        self._schedule_regen()

    def _build_ui(self):
        root = QVBoxLayout(self); root.setContentsMargins(0,0,0,0); root.setSpacing(0)

        top = QWidget()
        top.setStyleSheet("background: #1e1e2e; border-bottom: 1px solid #313244;")
        top.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        tl = QHBoxLayout(top); tl.setContentsMargins(12,8,12,8); tl.setSpacing(10)

        back = QPushButton("← Back"); back.setFlat(True)
        back.setStyleSheet("color: #89b4fa;")
        back.clicked.connect(self.back_requested)

        title = QLabel(f"<b>{self.job_data['position_name']}</b> @ {self.job_data['company_name']}")
        title.setStyleSheet("font-size: 20px; color: #cdd6f4;")

        self._status_lbl = QLabel("Ready")
        self._status_lbl.setStyleSheet("color: #a6adc8; font-size: 16px;")

        save_btn = primary_btn("Save Application")
        dl_btn   = primary_btn("↓ Download PDF")
        save_btn.clicked.connect(self._save)
        dl_btn.clicked.connect(self._download)

        tl.addWidget(back); tl.addSpacing(8); tl.addWidget(title)
        tl.addStretch()
        tl.addWidget(self._status_lbl); tl.addSpacing(4)
        tl.addWidget(save_btn); tl.addWidget(dl_btn)
        root.addWidget(top)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        left_inner = QWidget()
        ll = QVBoxLayout(left_inner); ll.setContentsMargins(12,12,12,12); ll.setSpacing(8)
        hint = QLabel("▲▼ reorder  ·  ✓ enable section  ·  ▶ Edit to expand")
        hint.setStyleSheet("color: #585b70; font-size: 16px;")
        ll.addWidget(hint)
        self._section_list = SectionList()
        self._section_list.order_changed.connect(self._schedule_regen)
        self._section_list.toggle_changed.connect(self._schedule_regen)
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
        app = self._app

        if app and app.get("section_order"):
            order   = json.loads(app["section_order"])
            enabled = {k: bool(v) for k, v in json.loads(app["sections_enabled"]).items()}
        else:
            ps = self._resume_data.get("profile_settings")
            if ps and ps.get("section_order"):
                order   = json.loads(ps["section_order"])
                enabled = {k: bool(v) for k, v in json.loads(ps["sections_enabled"]).items()}
            else:
                s = self._resume_data["settings"]
                order   = json.loads(s["section_order"])
                enabled = {k: bool(v) for k, v in json.loads(s["sections_enabled"]).items()}

        inc_exp     = json.loads(app["included_experiences"]) if app and app.get("included_experiences") else None
        inc_edu     = json.loads(app["included_education"])   if app and app.get("included_education")   else None
        inc_prj     = json.loads(app["included_projects"])    if app and app.get("included_projects")    else None
        inc_bullets = {int(k): v for k, v in json.loads(app["included_bullets"]).items()} \
                      if app and app.get("included_bullets") else None
        sum_text    = app.get("summary_text_override")        if app else None
        extra       = json.loads(app["extra_keywords"]) if app and app.get("extra_keywords") else self.job_data.get("extra_kw_ids", [])
        kw_list     = json.loads(app["keyword_list"])    if app and app.get("keyword_list")    else None

        saved_contact  = json.loads(app["contact_override"])  if app and app.get("contact_override")  else None
        saved_websites = json.loads(app["websites_override"]) if app and app.get("websites_override") else None

        for key in order:
            if key == "custom":
                continue
            content = self._make_content(key, self._resume_data, inc_exp, inc_edu, inc_prj,
                                         None, extra, saved_contact, saved_websites,
                                         sum_text, kw_list, inc_bullets)
            if content is None:
                continue
            row = SectionRow(key, enabled.get(key, True), content)
            self._section_list.add_section(row)

    def _make_content(self, key, data, inc_exp, inc_edu, inc_prj,
                      sel_sum, extra_kw_ids, saved_contact=None,
                      saved_websites=None, saved_sum_text=None,
                      saved_kw_list=None, inc_bullets=None):
        if key == "contact":
            contact      = saved_contact  if saved_contact  is not None else (data.get("contact") or {})
            websites     = saved_websites if saved_websites is not None else (data.get("websites") or [])
            all_websites = data.get("websites") or []
            w = _ContactContent(contact, websites, all_websites)
            w.changed.connect(self._schedule_regen); return w
        if key == "summary":
            w = _SummaryContent(
                self._all_profiles,
                self.job_data["profile_id"],
                saved_sum_text,
            )
            w.changed.connect(self._schedule_regen)
            return w
        if key == "experience":
            w = _ExperienceContent(data.get("experiences") or [], inc_exp,
                                   self._bullet_overrides, inc_bullets)
            w.changed.connect(self._schedule_regen)
            w.changed.connect(self._save_debounce.start)
            return w
        if key == "education":
            w = _EducationContent(data.get("education") or [], inc_edu)
            w.changed.connect(self._schedule_regen); return w
        if key == "projects":
            w = _ProjectsContent(data.get("projects") or [], inc_prj)
            w.changed.connect(self._schedule_regen); return w
        if key == "keywords":
            if saved_kw_list is not None:
                initial_ids = saved_kw_list
            else:
                seen = set()
                initial_ids = []
                for i in list(self._profile_kw_ids) + (extra_kw_ids or []):
                    if i not in seen:
                        seen.add(i)
                        initial_ids.append(i)
            w = _KeywordsContent(self._all_kw, initial_ids)
            w.changed.connect(self._schedule_regen); return w
        return None

    def _schedule_regen(self):
        self._status_lbl.setText("Regenerating…")
        self._debounce.start()

    def _get_state(self) -> dict:
        exp_c = self._section_list.get_content("experience")
        edu_c = self._section_list.get_content("education")
        prj_c = self._section_list.get_content("projects")
        kw_c  = self._section_list.get_content("keywords")
        sum_c = self._section_list.get_content("summary")
        con_c = self._section_list.get_content("contact")

        contact_override, websites_override = (
            con_c.get_data() if isinstance(con_c, _ContactContent) else (None, None)
        )

        bullet_overrides:     dict[int, str]       = {}
        included_bullets_map: dict[int, list[int]] = {}
        if isinstance(exp_c, _ExperienceContent):
            for item in exp_c._sublist._items:
                if isinstance(item, _ExperienceItem):
                    bullet_overrides.update(item.get_overrides())
                    included_bullets_map[item.item_id] = item._bullet_list.get_included_ids()

        return dict(
            section_order          = self._section_list.get_order(),
            sections_enabled       = self._section_list.get_enabled(),
            bullet_overrides       = bullet_overrides,
            included_bullets_map   = included_bullets_map,
            included_experiences   = exp_c.included_ids()       if isinstance(exp_c, _ExperienceContent) else None,
            included_education     = edu_c.included_ids()       if isinstance(edu_c, _EducationContent)  else None,
            included_projects      = prj_c.included_ids()       if isinstance(prj_c, _ProjectsContent)   else None,
            project_text_overrides = prj_c.get_text_overrides() if isinstance(prj_c, _ProjectsContent)   else {},
            project_name_overrides = prj_c.get_name_overrides() if isinstance(prj_c, _ProjectsContent)   else {},
            keyword_ids            = kw_c.active_ids() if isinstance(kw_c, _KeywordsContent) else list(self._profile_kw_ids),
            contact_override       = contact_override,
            websites_override      = websites_override,
            summary_text_override  = sum_c.get_text_override() if isinstance(sum_c, _SummaryContent) else None,
        )

    def _regenerate(self):
        from resume.generator import generate_resume_pdf_for_app
        self._regen_token += 1
        token = self._regen_token
        s = self._get_state()
        task = _Task(
            generate_resume_pdf_for_app,
            self.db_path, self.job_data["profile_id"],
            s["keyword_ids"], s["section_order"], s["sections_enabled"],
            s["bullet_overrides"], s["included_bullets_map"],
            s["included_experiences"], s["included_education"],
            s["included_projects"], s["project_text_overrides"],
            s["project_name_overrides"],
            s["contact_override"], s["websites_override"],
            s["summary_text_override"],
        )
        self._active_tasks.add(task)
        task.sigs.done.connect(lambda pdf, t=token, tk=task: self._on_regen_done(pdf, t, tk))
        task.sigs.error.connect(lambda msg, tk=task: self._on_regen_error(msg, tk))
        QThreadPool.globalInstance().start(task)

    def _on_regen_done(self, pdf_bytes: bytes, token: int, task):
        self._active_tasks.discard(task)
        if token != self._regen_token:
            return
        self._pdf_bytes = pdf_bytes
        self._preview.load_bytes(pdf_bytes)
        self._status_lbl.setText("Preview updated ✓")

    def _on_regen_error(self, msg: str, task):
        self._active_tasks.discard(task)
        self._status_lbl.setText(f"Error: {msg}")

    def _save(self):
        s  = self._get_state()
        jd = self.job_data

        self.application_id = self.db.upsert_application(
            profile_id            = jd["profile_id"],
            status_id             = jd.get("status_id", 1),
            position_name         = jd["position_name"],
            company_name          = jd["company_name"],
            date_applied          = jd.get("date_applied", ""),
            extra_keywords        = json.dumps(s["keyword_ids"]),
            section_order         = json.dumps(s["section_order"]),
            sections_enabled      = json.dumps({k: int(v) for k, v in s["sections_enabled"].items()}),
            summary_text_override = s["summary_text_override"],
            contact_override      = json.dumps(s["contact_override"]) if s["contact_override"] else None,
            websites_override     = json.dumps(s["websites_override"]) if s["websites_override"] is not None else None,
            included_experiences  = json.dumps(s["included_experiences"]) if s["included_experiences"] is not None else None,
            included_education    = json.dumps(s["included_education"])   if s["included_education"]   is not None else None,
            included_projects     = json.dumps(s["included_projects"])    if s["included_projects"]    is not None else None,
            included_bullets      = json.dumps(s["included_bullets_map"]) if s["included_bullets_map"] is not None else None,
            id                    = self.application_id,
        )
        # save the full explicit keyword list so reopening uses it directly
        self.db.execute(
            "UPDATE job_application SET keyword_list=? WHERE id=?",
            (json.dumps(s["keyword_ids"]), self.application_id)
        )
        self.db.clear_bullet_overrides(self.application_id)
        for bp_id, text in s["bullet_overrides"].items():
            self.db.set_bullet_override(self.application_id, bp_id, text)

        self.saved.emit(self.application_id)
        self._status_lbl.setText("Saved ✓")
    def _download(self):
        if not self._pdf_bytes:
            QMessageBox.warning(self, "Not ready", "Wait for the preview to finish.")
            return
        settings  = self.db.get_settings()
        folder    = settings.get("pdf_output_folder") or str(Path.home())
        tmpl      = settings.get("pdf_filename_template") or "{company}_{position}_{date}"
        auto_name = (
            tmpl
            .replace("{company}",  self.job_data["company_name"])
            .replace("{position}", self.job_data["position_name"])
            .replace("{date}",     date.today().strftime("%Y-%m-%d"))
            .replace(" ", "_")
        )
        out_path = Path(folder) / f"{auto_name}.pdf"
        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(self._pdf_bytes)
        except Exception as e:
            QMessageBox.critical(self, "Download failed", str(e))
            return
        if self.application_id:
            self.db.execute(
                "UPDATE job_application SET resume_pdf_path=? WHERE id=?",
                (str(out_path), self.application_id),
            )
        self._status_lbl.setText(f"Downloaded: {out_path.name}")