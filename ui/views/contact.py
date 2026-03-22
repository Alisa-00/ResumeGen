from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QMessageBox, QSizePolicy,
)

from db.database import Database
from ui.widgets import section_title, hline, primary_btn, flat_link_btn, field, small_danger_btn


class _WebsiteRow(QWidget):
    removed = Signal(QWidget)

    def __init__(self, label: str = "", url: str = "", parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self.label_edit = field("Label  (e.g. GitHub)", label)
        self.url_edit   = field("URL", url)
        self.label_edit.setFixedWidth(140)
        rm = small_danger_btn()
        rm.clicked.connect(lambda: self.removed.emit(self))
        row.addWidget(self.label_edit)
        row.addWidget(self.url_edit)
        row.addWidget(rm)


class ContactView(QWidget):
    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self._website_rows: list[_WebsiteRow] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 16, 24, 16)

        outer.addWidget(section_title("Contact Information"))
        outer.addWidget(hline())

        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.f_name     = field("Full name")
        self.f_email    = field("email@example.com")
        self.f_phone    = field("+1 555 000 0000")
        self.f_location = field("City, Country")
        self.f_linkedin = field("https://linkedin.com/in/…")
        for lbl, w in [
            ("Name",     self.f_name),
            ("Email",    self.f_email),
            ("Phone",    self.f_phone),
            ("Location", self.f_location),
            ("LinkedIn", self.f_linkedin),
        ]:
            form.addRow(lbl, w)
        outer.addLayout(form)

        outer.addSpacing(12)
        outer.addWidget(section_title("Additional Websites"))

        self._websites_container = QWidget()
        self._websites_layout    = QVBoxLayout(self._websites_container)
        self._websites_layout.setContentsMargins(0, 0, 0, 0)
        self._websites_layout.setSpacing(4)
        outer.addWidget(self._websites_container)

        add_btn = flat_link_btn("+ Add website")
        add_btn.clicked.connect(lambda: self._add_website_row())
        outer.addWidget(add_btn)

        outer.addSpacing(12)
        save_btn = primary_btn("Save Changes")
        save_btn.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        save_btn.clicked.connect(self._save)
        outer.addWidget(save_btn)
        outer.addStretch()

        self._load()

    def _load(self):
        contact = self.db.get_contact()
        if not contact:
            return
        self.f_name.setText(contact.get("name") or "")
        self.f_email.setText(contact.get("email") or "")
        self.f_phone.setText(contact.get("phone") or "")
        self.f_location.setText(contact.get("location") or "")
        for site in self.db.get_contact_websites(contact["id"]):
            if site["label"].lower() == "linkedin":
                self.f_linkedin.setText(site["url"])
            else:
                self._add_website_row(site["label"], site["url"])

    def _add_website_row(self, label: str = "", url: str = ""):
        row = _WebsiteRow(label, url)
        row.removed.connect(self._remove_website_row)
        self._website_rows.append(row)
        self._websites_layout.addWidget(row)

    def _remove_website_row(self, row: _WebsiteRow):
        self._website_rows.remove(row)
        self._websites_layout.removeWidget(row)
        row.deleteLater()

    def _save(self):
        contact_id = self.db.upsert_contact(
            self.f_name.text().strip(),
            self.f_email.text().strip(),
            self.f_phone.text().strip(),
            self.f_location.text().strip(),
        )
        self.db.delete_contact_websites(contact_id)
        li = self.f_linkedin.text().strip()
        if li:
            self.db.add_contact_website(contact_id, "LinkedIn", li)
        for row in self._website_rows:
            lbl = row.label_edit.text().strip()
            url = row.url_edit.text().strip()
            if lbl or url:
                self.db.add_contact_website(contact_id, lbl, url)
        QMessageBox.information(self, "Saved", "Contact information saved.")