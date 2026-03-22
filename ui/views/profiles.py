from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QTextEdit, QMessageBox, QSizePolicy,
)

from db.database import Database
from ui.widgets import (
    section_title, hline, primary_btn, flat_link_btn,
    field, scrollable, Card, KeywordTagger,
)


class ProfilesView(QWidget):
    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self._cards: list[tuple[Card, dict | None]] = []

        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(24, 16, 24, 16)
        layout.setSpacing(12)
        layout.addWidget(section_title("Summary"))

        hint = QLabel(
            "Each summary targets a specific job title. "
            "Assign keywords to control which resume content is prioritised."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #a6adc8; font-size: 16px;")
        layout.addWidget(hint)
        layout.addWidget(hline())

        self._cards_container = QWidget()
        self._cards_layout    = QVBoxLayout(self._cards_container)
        self._cards_layout.setContentsMargins(0, 0, 0, 0)
        self._cards_layout.setSpacing(10)
        layout.addWidget(self._cards_container)

        btn_row = QHBoxLayout()
        add_btn  = flat_link_btn("+ Add Summary")
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
        for row in self.db.get_profiles():
            selected = [kw["id"] for kw in self.db.get_profile_keywords(row["id"])]
            self._add_card(row, selected)

    def _add_card(self, data: dict | None = None, selected_kw_ids: list[int] | None = None):
        card = Card()
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)

        f_name = field("e.g. Senior Backend Engineer", (data or {}).get("name", ""))
        form.addRow("Target job title", f_name)

        f_summary = QTextEdit((data or {}).get("summary", ""))
        f_summary.setPlaceholderText("Write a summary for this profile…")
        f_summary.setFixedHeight(100)
        form.addRow("Summary", f_summary)

        all_kw   = self.db.get_keywords()
        selector = KeywordTagger(all_kw, selected_kw_ids or [])

        card.add_form(form)
        card.add_widget(selector)
        card.add_delete_button()
        card.delete_requested.connect(self._delete_card)

        card._fields = dict(name=f_name, summary=f_summary, selector=selector)
        card._data   = data

        self._cards.append((card, data))
        self._cards_layout.addWidget(card)

    def _delete_card(self, card: Card):
        if card._data:
            self.db.delete_profile(card._data["id"])
        self._cards = [(c, d) for c, d in self._cards if c is not card]
        self._cards_layout.removeWidget(card)
        card.deleteLater()

    def _save_all(self):
        for card, _ in self._cards:
            f      = card._fields
            name    = f["name"].text().strip()
            summary = f["summary"].toPlainText().strip()
            kw_ids  = f["selector"].selected_ids()
            new_id  = self.db.upsert_profile(name, summary, id=(card._data or {}).get("id"))
            self.db.set_profile_keywords(new_id, kw_ids)
            card._data = {**(card._data or {}), "id": new_id}
        QMessageBox.information(self, "Saved", "Summaries saved.")