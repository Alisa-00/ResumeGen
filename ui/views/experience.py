from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QPushButton, QCheckBox, QTextEdit, QLabel, QMessageBox, QSizePolicy,
)

from db.database import Database
from ui.widgets import (
    section_title, hline, primary_btn, flat_link_btn,
    field, date_field, scrollable, Card, KeywordTagger,
    CollapsiblePanel, small_danger_btn,
)


def _clean_date(val: str) -> str | None:
    cleaned = val.replace("_", "").strip("-").strip()
    return cleaned if len(cleaned) == 7 else None


# ── single bullet row ────────────────────────────────────────────────

class _BulletRow(QWidget):
    def __init__(self, text: str = "", kw_ids: list[int] | None = None,
                 all_kw: list[dict] | None = None,
                 data: dict | None = None, parent=None):
        super().__init__(parent)
        self._data = data

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 4, 0, 4)
        root.setSpacing(4)

        outer = QHBoxLayout()
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)
        outer.addStretch(3)

        content = QVBoxLayout()
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(4)

        # text box row: text edit + X button aligned to top
        text_row = QHBoxLayout()
        text_row.setContentsMargins(0, 0, 0, 0)
        text_row.setSpacing(8)
        text_row.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.text_edit = QTextEdit()
        self.text_edit.setPlainText(text)
        self.text_edit.setPlaceholderText("Bullet point text…")
        self.text_edit.setFixedHeight(120)
        text_row.addWidget(self.text_edit, 1)

        self._rm = small_danger_btn()
        self._rm.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        text_row.addWidget(self._rm, 0, Qt.AlignmentFlag.AlignTop)

        content.addLayout(text_row)

        self.tagger = KeywordTagger(all_kw or [], kw_ids or [])
        content.addWidget(self.tagger)

        outer.addLayout(content, 60)
        outer.addStretch(37)
        root.addLayout(outer)

    def connect_remove(self, slot):
        self._rm.clicked.connect(slot)


# ── bullet panel ─────────────────────────────────────────────────────

class _BulletPanel(QWidget):
    def __init__(self, work_experience_id: int | None,
                 db: Database, parent=None):
        super().__init__(parent)
        self._db    = db
        self._we_id = work_experience_id
        self._rows: list[_BulletRow] = []

        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(0, 0, 0, 0)
        self._root.setSpacing(4)

        self._rows_container = QWidget()
        self._rows_layout    = QVBoxLayout(self._rows_container)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(4)
        self._root.addWidget(self._rows_container)

        add_btn = flat_link_btn("+ Add bullet point")
        add_btn.clicked.connect(lambda: self._add_row())
        self._root.addWidget(add_btn)

        self._load()

    def _load(self):
        if not self._we_id:
            return
        all_kw = self._db.get_keywords()
        for bp in self._db.get_bullet_points(self._we_id):
            kw_ids = self._db.get_bullet_point_keywords(bp["id"])
            self._add_row(bp["text"], kw_ids, all_kw, bp)

    def _add_row(self, text: str = "", kw_ids: list[int] | None = None,
                 all_kw: list[dict] | None = None, data: dict | None = None):
        if all_kw is None:
            all_kw = self._db.get_keywords()
        row = _BulletRow(text, kw_ids or [], all_kw, data)
        row.connect_remove(lambda _=None, r=row: self._remove_row(r))
        self._rows.append(row)
        self._rows_layout.addWidget(row)

    def _remove_row(self, row: _BulletRow):
        if row._data:
            self._db.delete_bullet_point(row._data["id"])
        self._rows.remove(row)
        self._rows_layout.removeWidget(row)
        row.deleteLater()

    def save(self, work_experience_id: int) -> None:
        self._we_id = work_experience_id
        for i, row in enumerate(self._rows):
            text   = row.text_edit.toPlainText().strip()
            kw_ids = row.tagger.selected_ids()
            if not text:
                continue
            bp_id = self._db.upsert_bullet_point(
                work_experience_id=work_experience_id,
                text=text,
                sort_order=i,
                id=(row._data or {}).get("id"),
            )
            self._db.set_bullet_point_keywords(bp_id, kw_ids)
            row._data = {**(row._data or {}), "id": bp_id}


# ── experience view ──────────────────────────────────────────────────

class ExperienceView(QWidget):
    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self._cards: list[tuple[Card, dict | None]] = []

        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(24, 16, 24, 16)
        layout.setSpacing(12)
        layout.addWidget(section_title("Work Experience"))
        layout.addWidget(hline())

        self._cards_container = QWidget()
        self._cards_layout    = QVBoxLayout(self._cards_container)
        self._cards_layout.setContentsMargins(0, 0, 0, 0)
        self._cards_layout.setSpacing(10)
        layout.addWidget(self._cards_container)

        btn_row = QHBoxLayout()
        add_btn  = flat_link_btn("+ Add Experience")
        add_btn.clicked.connect(lambda: self._add_card())
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
        for row in self.db.get_work_experiences():
            self._add_card(row)

    def _add_card(self, data: dict | None = None):
        card = Card()
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)

        f_org      = field("Organization", (data or {}).get("organization_name", ""))
        f_position = field("Position",     (data or {}).get("position_name", ""))
        f_location = field("Location",     (data or {}).get("location", ""))
        f_start    = date_field((data or {}).get("start_date", ""))
        f_end      = date_field((data or {}).get("end_date", ""))
        f_ongoing  = QCheckBox("Currently ongoing")
        f_ongoing.setChecked(bool((data or {}).get("is_ongoing", False)))
        f_ongoing.toggled.connect(lambda checked: f_end.setDisabled(checked))
        f_end.setDisabled(f_ongoing.isChecked())

        for lbl, w in [
            ("Organization", f_org),
            ("Position",     f_position),
            ("Location",     f_location),
            ("Start date",   f_start),
            ("End date",     f_end),
            ("",             f_ongoing),
        ]:
            form.addRow(lbl, w)

        bp_panel    = _BulletPanel(
            work_experience_id=(data or {}).get("id"),
            db=self.db,
        )
        collapsible = CollapsiblePanel("Edit bullet points", collapsed=True)
        collapsible.set_content(bp_panel)

        card._fields   = dict(org=f_org, position=f_position, location=f_location,
                              start=f_start, end=f_end, ongoing=f_ongoing)
        card._bp_panel = bp_panel
        card._data     = data
        card.add_form(form)
        card.add_widget(collapsible)
        card.add_delete_button()
        card.delete_requested.connect(self._delete_card)

        self._cards.append((card, data))
        self._cards_layout.addWidget(card)

    def _delete_card(self, card: Card):
        if card._data:
            self.db.delete_work_experience(card._data["id"])
        self._cards = [(c, d) for c, d in self._cards if c is not card]
        self._cards_layout.removeWidget(card)
        card.deleteLater()

    def _save_all(self):
        for card, _ in self._cards:
            f = card._fields
            new_id = self.db.upsert_work_experience(
                org        = f["org"].text().strip(),
                position   = f["position"].text().strip(),
                location   = f["location"].text().strip(),
                is_ongoing = f["ongoing"].isChecked(),
                start_date = _clean_date(f["start"].text()),
                end_date   = None if f["ongoing"].isChecked() else _clean_date(f["end"].text()),
                id         = (card._data or {}).get("id"),
            )
            card._bp_panel.save(new_id)
            card._data = {**(card._data or {}), "id": new_id}
        QMessageBox.information(self, "Saved", "Work experience saved.")