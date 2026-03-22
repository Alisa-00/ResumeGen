"""
ui/wizard/step_details.py
Wizard step 1: job details + profile + extra keywords.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QComboBox, QMessageBox,
)

from db.database import Database
from ui.widgets import section_title, hline, primary_btn, field, KeywordTagger


class StepDetails(QWidget):
    next_requested = Signal(dict)

    def __init__(self, db: Database, application: dict | None = None, parent=None):
        super().__init__(parent)
        self.db = db

        outer = QVBoxLayout(self)
        outer.setContentsMargins(48, 32, 48, 32)
        outer.setSpacing(16)

        outer.addWidget(section_title("New Application — Step 1 of 2"))
        outer.addWidget(QLabel("Fill in the job details and choose a profile to base this resume on."))
        outer.addWidget(hline())

        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        form.setVerticalSpacing(10)

        self.f_company  = field("e.g. Acme Corp",             (application or {}).get("company_name", ""))
        self.f_position = field("e.g. Senior Python Engineer", (application or {}).get("position_name", ""))

        self.f_profile = QComboBox()
        self.f_profile.setMinimumWidth(220)
        self._load_profiles((application or {}).get("profile_id"))

        for lbl, w in [
            ("Company",  self.f_company),
            ("Position", self.f_position),
            ("Profile",  self.f_profile),
        ]:
            form.addRow(lbl, w)
        outer.addLayout(form)

        outer.addWidget(QLabel("Extra keywords for this specific position:"))
        hint = QLabel("Keywords from the selected profile are pre-filled. Add more as needed.")
        hint.setStyleSheet("color: #a6adc8; font-size: 12px;")
        outer.addWidget(hint)

        import json
        saved_extra = json.loads((application or {}).get("extra_keywords", "[]"))
        all_kw      = self.db.get_keywords()
        self.kw_tagger = KeywordTagger(all_kw, saved_extra)
        outer.addWidget(self.kw_tagger)

        outer.addStretch()

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        next_btn = primary_btn("Next →")
        next_btn.setFixedWidth(120)
        next_btn.clicked.connect(self._on_next)
        btn_row.addWidget(next_btn)
        outer.addLayout(btn_row)

        # wire profile change after tagger is built
        self.f_profile.currentIndexChanged.connect(self._on_profile_changed)

        # seed keywords for the initially selected profile (new application only)
        if application is None:
            self._on_profile_changed(self.f_profile.currentIndex())

    # ------------------------------------------------------------------

    def _load_profiles(self, selected_id: int | None = None):
        self.f_profile.clear()
        self.f_profile.addItem("— select profile —", userData=None)
        for p in self.db.get_profiles():
            self.f_profile.addItem(p["name"], userData=p["id"])
            if p["id"] == selected_id:
                self.f_profile.setCurrentIndex(self.f_profile.count() - 1)

    def _on_profile_changed(self, index: int):
        profile_id = self.f_profile.itemData(index)
        if profile_id is None:
            return
        # clear all current tags first
        for kw_id in list(self.kw_tagger.selected_ids()):
            self.kw_tagger._remove_tag(kw_id)
        # populate with the selected profile's keywords
        kw_ids = [kw["id"] for kw in self.db.get_profile_keywords(profile_id)]
        for kw_id in kw_ids:
            name = self.kw_tagger._all.get(kw_id)
            if name:
                self.kw_tagger._add_tag(kw_id, name)

    def _on_next(self):
        from datetime import date as _date
        company    = self.f_company.text().strip()
        position   = self.f_position.text().strip()
        profile_id = self.f_profile.currentData()

        if not company:
            QMessageBox.warning(self, "Missing field", "Please enter a company name.")
            return
        if not position:
            QMessageBox.warning(self, "Missing field", "Please enter a position name.")
            return
        if profile_id is None:
            QMessageBox.warning(self, "Missing field", "Please select a profile.")
            return

        self.next_requested.emit({
            "company_name":  company,
            "position_name": position,
            "profile_id":    profile_id,
            "date_applied":  _date.today().strftime("%Y-%m-%d"),
            "extra_kw_ids":  self.kw_tagger.selected_ids(),
        })