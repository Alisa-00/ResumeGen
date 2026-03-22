from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QPushButton, QCheckBox, QTextEdit, QLabel, QMessageBox,
)

from db.database import Database
from ui.widgets import (
    section_title, hline, primary_btn, flat_link_btn,
    field, date_field, scrollable, Card, KeywordTagger,
)


def _clean_date(val: str) -> str | None:
    cleaned = val.replace("_", "").strip("-").strip()
    return cleaned if len(cleaned) == 7 else None


class ProjectsView(QWidget):
    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self._cards: list[tuple[Card, dict | None]] = []

        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(24, 16, 24, 16)
        layout.setSpacing(12)
        layout.addWidget(section_title("Projects"))
        layout.addWidget(hline())

        self._cards_container = QWidget()
        self._cards_layout    = QVBoxLayout(self._cards_container)
        self._cards_layout.setContentsMargins(0, 0, 0, 0)
        self._cards_layout.setSpacing(10)
        layout.addWidget(self._cards_container)

        btn_row = QHBoxLayout()
        add_btn  = flat_link_btn("+ Add Project")
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
        for row in self.db.get_projects():
            selected = self.db.get_project_keywords(row["id"])
            self._add_card(row, selected)

    def _add_card(self, data: dict | None = None, selected_kw_ids: list[int] | None = None):
        card = Card()
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)

        f_name    = field("Project name", (data or {}).get("name", ""))
        f_link    = field("URL / repo",   (data or {}).get("link", ""))
        f_start   = date_field((data or {}).get("start_date", ""))
        f_end     = date_field((data or {}).get("end_date", ""))
        f_ongoing = QCheckBox("Currently ongoing")
        f_ongoing.setChecked(bool((data or {}).get("is_ongoing", False)))
        f_ongoing.toggled.connect(lambda checked: f_end.setDisabled(checked))
        f_end.setDisabled(f_ongoing.isChecked())
        f_text    = QTextEdit((data or {}).get("text", ""))
        f_text.setPlaceholderText("Project description…")
        f_text.setFixedHeight(90)

        for lbl, w in [
            ("Name",        f_name),
            ("Link",        f_link),
            ("Start",       f_start),
            ("End",         f_end),
            ("",            f_ongoing),
            ("Description", f_text),
        ]:
            form.addRow(lbl, w)

        all_kw = self.db.get_keywords()
        tagger = KeywordTagger(all_kw, selected_kw_ids or [])

        card._fields = dict(name=f_name, link=f_link, start=f_start,
                            end=f_end, ongoing=f_ongoing, text=f_text, tagger=tagger)
        card._data = data
        card.add_form(form)
        card.add_widget(tagger)
        card.add_delete_button()
        card.delete_requested.connect(self._delete_card)

        self._cards.append((card, data))
        self._cards_layout.addWidget(card)

    def _delete_card(self, card: Card):
        if card._data:
            self.db.delete_project(card._data["id"])
        self._cards = [(c, d) for c, d in self._cards if c is not card]
        self._cards_layout.removeWidget(card)
        card.deleteLater()

    def _save_all(self):
        for card, _ in self._cards:
            f = card._fields
            new_id = self.db.upsert_project(
                name       = f["name"].text().strip(),
                link       = f["link"].text().strip(),
                is_ongoing = f["ongoing"].isChecked(),
                start_date = _clean_date(f["start"].text()),
                end_date   = None if f["ongoing"].isChecked() else _clean_date(f["end"].text()),
                text       = f["text"].toPlainText().strip(),
                id         = (card._data or {}).get("id"),
            )
            self.db.set_project_keywords(new_id, f["tagger"].selected_ids())
            card._data = {**(card._data or {}), "id": new_id}
        QMessageBox.information(self, "Saved", "Projects saved.")