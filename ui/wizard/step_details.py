"""
ui/wizard/step_details.py
Wizard step 1: job details + profile + extra keywords + job posting URL + referrals.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QLabel,
    QComboBox,
    QMessageBox,
    QLineEdit,
    QPushButton,
    QDialog,
)

from db.database import Database
from ui.widgets import section_title, hline, primary_btn, field, KeywordTagger


class _ReferralDialog(QDialog):
    """Dialog for adding/editing a referral during application creation."""

    def __init__(
        self,
        parent=None,
        name: str = "",
        email: str = "",
        phone: str = "",
        linkedin_url: str = "",
        description: str = "",
        title: str = "Add Referral",
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(350)
        self._build_ui(name, email, phone, linkedin_url, description)

    def _build_ui(self, name: str, email: str, phone: str, linkedin_url: str, description: str):
        from PySide6.QtWidgets import QFormLayout, QDialogButtonBox, QTextEdit

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        form = QFormLayout()
        form.setSpacing(8)

        self.name_edit = QLineEdit(name)
        self.name_edit.setPlaceholderText("Referral name")
        form.addRow("Name:*", self.name_edit)

        self.email_edit = QLineEdit(email)
        self.email_edit.setPlaceholderText("email@example.com")
        form.addRow("Email:", self.email_edit)

        self.phone_edit = QLineEdit(phone)
        self.phone_edit.setPlaceholderText("+1 (555) 123-4567")
        form.addRow("Phone:", self.phone_edit)

        self.linkedin_edit = QLineEdit(linkedin_url)
        self.linkedin_edit.setPlaceholderText("https://linkedin.com/in/...")
        form.addRow("LinkedIn:", self.linkedin_edit)

        self.desc_edit = QTextEdit(description)
        self.desc_edit.setPlaceholderText("How you know this person, context, notes...")
        self.desc_edit.setMinimumHeight(80)
        form.addRow("Description:", self.desc_edit)

        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_save(self):
        if not self.name_edit.text().strip():
            QMessageBox.warning(self, "Required", "Name is required.")
            return
        self.accept()

    def get_data(self) -> dict:
        return {
            "name": self.name_edit.text().strip(),
            "email": self.email_edit.text().strip() or None,
            "phone": self.phone_edit.text().strip() or None,
            "linkedin_url": self.linkedin_edit.text().strip() or None,
            "description": self.desc_edit.toPlainText().strip() or None,
        }


class StepDetails(QWidget):
    next_requested = Signal(dict)

    def __init__(self, db: Database, application: dict | None = None, parent=None):
        super().__init__(parent)
        self.db = db
        self._application = application

        outer = QVBoxLayout(self)
        outer.setContentsMargins(48, 32, 48, 32)
        outer.setSpacing(16)

        outer.addWidget(section_title("New Application — Step 1 of 2"))
        outer.addWidget(
            QLabel(
                "Fill in the job details and choose a profile to base this resume on."
            )
        )
        outer.addWidget(hline())

        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        form.setVerticalSpacing(10)

        self.f_company = field(
            "e.g. Acme Corp", (application or {}).get("company_name", "")
        )
        self.f_position = field(
            "e.g. Senior Python Engineer", (application or {}).get("position_name", "")
        )

        self.f_profile = QComboBox()
        self.f_profile.setMinimumWidth(220)
        self._load_profiles((application or {}).get("profile_id"))

        # Job posting URL
        self.f_url = QLineEdit()
        self.f_url.setPlaceholderText("https://careers.example.com/jobs/12345")
        self.f_url.setText((application or {}).get("job_posting_url", ""))

        for lbl, w in [
            ("Company", self.f_company),
            ("Position", self.f_position),
            ("Profile", self.f_profile),
            ("Job URL", self.f_url),
        ]:
            form.addRow(lbl, w)

        outer.addLayout(form)

        outer.addWidget(QLabel("Extra keywords for this specific position:"))
        hint = QLabel(
            "Keywords from the selected profile are pre-filled. Add more as needed."
        )
        hint.setStyleSheet("color: #a6adc8; font-size: 12px;")
        outer.addWidget(hint)

        import json

        saved_extra = json.loads((application or {}).get("extra_keywords", "[]"))
        all_kw = self.db.get_keywords()
        self.kw_tagger = KeywordTagger(all_kw, saved_extra)
        outer.addWidget(self.kw_tagger)

        # Referrals section
        outer.addWidget(hline())
        outer.addWidget(QLabel("Referrals:"))
        hint_ref = QLabel(
            "People who referred you or you contacted about this application."
        )
        hint_ref.setStyleSheet("color: #a6adc8; font-size: 12px;")
        outer.addWidget(hint_ref)

        # Container for referral widgets
        self._referrals_container = QWidget()
        self._referrals_layout = QVBoxLayout(self._referrals_container)
        self._referrals_layout.setContentsMargins(0, 0, 0, 0)
        self._referrals_layout.setSpacing(6)
        self._referrals_layout.addStretch()
        outer.addWidget(self._referrals_container)

        # Add Referral button
        add_ref_btn = QPushButton("+ Add Referral")
        add_ref_btn.setStyleSheet("""
            QPushButton {
                background: #313244;
                color: #cdd6f4;
                border: 1px solid #45475a;
                border-radius: 4px;
                padding: 6px 12px;
            }
            QPushButton:hover {
                background: #45475a;
            }
        """)
        add_ref_btn.clicked.connect(self._on_add_referral)
        outer.addWidget(add_ref_btn)

        # Initialize empty referrals list
        self._referrals: list[dict] = []

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

    def _on_add_referral(self):
        dialog = _ReferralDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            data = dialog.get_data()
            self._referrals.append(data)
            self._refresh_referrals()

    def _on_edit_referral(self, index: int):
        if index >= len(self._referrals):
            return
        ref = self._referrals[index]
        dialog = _ReferralDialog(
            self,
            name=ref.get("name", ""),
            email=ref.get("email", ""),
            phone=ref.get("phone", ""),
            linkedin_url=ref.get("linkedin_url", ""),
            description=ref.get("description", ""),
            title="Edit Referral",
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._referrals[index] = dialog.get_data()
            self._refresh_referrals()

    def _on_delete_referral(self, index: int):
        if index >= len(self._referrals):
            return
        ref = self._referrals[index]
        if (
            QMessageBox.question(
                self,
                "Delete Referral",
                f"Delete referral for '{ref.get('name', 'Unnamed')}'?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            == QMessageBox.StandardButton.Yes
        ):
            self._referrals.pop(index)
            self._refresh_referrals()

    def _refresh_referrals(self):
        # Clear existing widgets (except the stretch at the end)
        while self._referrals_layout.count() > 1:
            item = self._referrals_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Add widgets for each referral
        for i, ref in enumerate(self._referrals):
            widget = self._create_referral_widget(ref, i)
            self._referrals_layout.insertWidget(self._referrals_layout.count() - 1, widget)

    def _create_referral_widget(self, ref: dict, index: int) -> QWidget:
        from PySide6.QtWidgets import QTextEdit

        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)
        widget.setStyleSheet("""
            QWidget {
                background: #181825;
                border: 1px solid #313244;
                border-radius: 4px;
            }
        """)

        # Name
        name_lbl = QLabel(ref.get("name", "Unnamed"))
        name_lbl.setStyleSheet("font-weight: bold; color: #cdd6f4; background: transparent; border: none;")
        layout.addWidget(name_lbl)

        # Contact info
        contact_parts = []
        if ref.get("email"):
            contact_parts.append(f"📧 {ref['email']}")
        if ref.get("phone"):
            contact_parts.append(f"📞 {ref['phone']}")
        if ref.get("linkedin_url"):
            contact_parts.append(f"🔗 LinkedIn")

        if contact_parts:
            contact_lbl = QLabel(" | ".join(contact_parts))
            contact_lbl.setStyleSheet("color: #89b4fa; font-size: 11px; background: transparent; border: none;")
            layout.addWidget(contact_lbl)

        # Description
        if ref.get("description"):
            desc_lbl = QLabel(ref["description"])
            desc_lbl.setWordWrap(True)
            desc_lbl.setStyleSheet("color: #a6adc8; font-size: 11px; background: transparent; border: none;")
            layout.addWidget(desc_lbl)

        # Edit/Delete buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(4)

        edit_btn = QPushButton("Edit")
        edit_btn.setStyleSheet("""
            QPushButton {
                background: #313244;
                color: #cdd6f4;
                border: 1px solid #45475a;
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 11px;
            }
            QPushButton:hover {
                background: #45475a;
            }
        """)
        edit_btn.clicked.connect(lambda: self._on_edit_referral(index))

        del_btn = QPushButton("Delete")
        del_btn.setStyleSheet("""
            QPushButton {
                background: #313244;
                color: #f38ba8;
                border: 1px solid #45475a;
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 11px;
            }
            QPushButton:hover {
                background: #45475a;
            }
        """)
        del_btn.clicked.connect(lambda: self._on_delete_referral(index))

        btn_layout.addWidget(edit_btn)
        btn_layout.addWidget(del_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        return widget

    def _on_next(self):
        from datetime import date as _date

        company = self.f_company.text().strip()
        position = self.f_position.text().strip()
        profile_id = self.f_profile.currentData()
        url = self.f_url.text().strip()

        if not company:
            QMessageBox.warning(self, "Missing field", "Please enter a company name.")
            return
        if not position:
            QMessageBox.warning(self, "Missing field", "Please enter a position name.")
            return
        if profile_id is None:
            QMessageBox.warning(self, "Missing field", "Please select a profile.")
            return

        self.next_requested.emit(
            {
                "company_name": company,
                "position_name": position,
                "profile_id": profile_id,
                "date_applied": _date.today().strftime("%Y-%m-%d"),
                "extra_kw_ids": self.kw_tagger.selected_ids(),
                "job_posting_url": url,
                "referrals": self._referrals,
            }
        )
