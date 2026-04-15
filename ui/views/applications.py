"""
ui/views/applications.py
Kanban board for job applications with counts and detail sidebar.
"""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QDrag, QFont, QPainter, QColor
from PySide6.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QAbstractItemView,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QScrollArea,
    QFrame,
    QMessageBox,
    QSizePolicy,
    QTextEdit,
    QLineEdit,
    QGridLayout,
    QDialog,
    QFormLayout,
    QDialogButtonBox,
    QPushButton,
    QMenu,
)

from db.database import Database
from ui.widgets import primary_btn, danger_btn, section_title


def _fmt_date(value: str | None) -> str:
    """Format ISO date YYYY-MM-DD -> DD Mon YYYY."""
    if not value:
        return ""
    try:
        dt = datetime.strptime(value, "%Y-%m-%d")
        return dt.strftime("%d %b %Y")
    except ValueError:
        return value


COLUMNS: list[tuple[str, str]] = [
    ("to-apply", "To Apply"),
    ("applied", "Applied"),
    ("interview", "Interview"),
    ("offer", "Offer"),
    ("ghosted", "Ghosted"),
    ("rejected", "Rejected"),
]
COLUMN_KEYS = [c[0] for c in COLUMNS]


# ── card delegate ─────────────────────────────────────────────────────


class _CardDelegate(QStyledItemDelegate):
    LINE_H = 30

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index):
        from PySide6.QtWidgets import QStyle

        painter.save()

        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, QColor("#313244"))
        else:
            painter.fillRect(option.rect, QColor("#1e1e2e"))

        painter.setPen(QColor("#313244"))
        painter.drawRoundedRect(option.rect.adjusted(1, 1, -1, -1), 6, 6)

        text = index.data(Qt.ItemDataRole.DisplayRole) or ""
        lines = text.split("\n")
        x = option.rect.x() + 12
        y = option.rect.y() + 28

        styles = [
            (True, 13, "#cdd6f4"),
            (False, 12, "#a6adc8"),
            (False, 10, "#585b70"),
        ]
        for i, line in enumerate(lines):
            if i >= len(styles):
                break
            bold, pt, color = styles[i]
            f = QFont(painter.font())
            f.setBold(bold)
            f.setPointSize(pt)
            painter.setFont(f)
            painter.setPen(QColor(color))
            painter.drawText(x, y, line)
            y += self.LINE_H

        painter.restore()

    def sizeHint(self, option, index) -> QSize:
        return QSize(0, 110)


# ── card item ─────────────────────────────────────────────────────────


class _AppCard(QListWidgetItem):
    def __init__(self, app: dict):
        super().__init__()
        self.app_id = app["id"]
        self._app_data = app  # store full app data for sidebar
        company = app.get("company_name", "")
        position = app.get("position_name", "")

        # Show creation date and applied date
        date_created = app.get("date_created", "") or ""
        date_applied = app.get("date_applied", "") or ""

        if date_created:
            date_str = f"Created: {_fmt_date(date_created)}"
            if date_applied:
                date_str += f" | Applied: {_fmt_date(date_applied)}"
        else:
            date_str = "No dates"

        self.setText(f"{company}\n{position}\n{date_str}")
        self.setData(Qt.ItemDataRole.UserRole, app["id"])
        self.setSizeHint(QSize(0, 110))

    def get_app_data(self) -> dict:
        return self._app_data


# ── column list ───────────────────────────────────────────────────────


class _ColumnList(QListWidget):
    card_dropped = Signal(int, str)
    card_clicked = Signal(dict)
    card_opened = Signal(int)

    def __init__(self, status_key: str, drag_state: dict, parent=None):
        super().__init__(parent)
        self.status_key = status_key
        self._drag_state = drag_state

        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setItemDelegate(_CardDelegate(self))

        self.setStyleSheet("""
            QListWidget {
                background: #181825;
                border: none;
                border-radius: 4px;
            }
            QListWidget::item {
                background: transparent;
                margin: 4px 2px;
            }
            QListWidget::item:selected {
                background: transparent;
            }
        """)

        self.itemClicked.connect(self._on_item_clicked)
        self.itemDoubleClicked.connect(
            lambda item: self.card_opened.emit(item.data(Qt.ItemDataRole.UserRole))
        )

    def add_card(self, app: dict):
        self.addItem(_AppCard(app))

    def selected_app_id(self) -> int | None:
        items = self.selectedItems()
        return items[0].data(Qt.ItemDataRole.UserRole) if items else None

    def selected_app_data(self) -> dict | None:
        items = self.selectedItems()
        if items and isinstance(items[0], _AppCard):
            return items[0].get_app_data()
        return None

    def _on_item_clicked(self, item: QListWidgetItem):
        if isinstance(item, _AppCard):
            self.card_clicked.emit(item.get_app_data())

    def startDrag(self, supported_actions):
        self._drag_state["source"] = None
        self._drag_state["app_id"] = None

        item = self.currentItem()
        if item:
            self._drag_state["source"] = self
            self._drag_state["app_id"] = item.data(Qt.ItemDataRole.UserRole)
        super().startDrag(supported_actions)

    def dropEvent(self, event):
        source = self._drag_state.get("source")
        app_id = self._drag_state.get("app_id")

        if source is self:
            super().dropEvent(event)
            self._drag_state["source"] = None
            self._drag_state["app_id"] = None
            return

        if source is not None and app_id is not None:
            for i in range(source.count()):
                if source.item(i).data(Qt.ItemDataRole.UserRole) == app_id:
                    source.takeItem(i)
                    break

            super().dropEvent(event)
            self._drag_state["source"] = None
            self._drag_state["app_id"] = None
            self.card_dropped.emit(app_id, self.status_key)
        else:
            super().dropEvent(event)


# ── referral dialog ─────────────────────────────────────────────────────


class _ReferralDialog(QDialog):
    def __init__(
        self,
        parent=None,
        name: str = "",
        email: str = "",
        phone: str = "",
        linkedin_url: str = "",
        title: str = "Add Referral",
        show_delete: bool = False,
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(350)
        self._initial_email = email
        self._initial_phone = phone
        self._initial_linkedin = linkedin_url
        self._show_delete = show_delete
        self._delete_requested = False
        self._build_ui(name)

    def _build_ui(self, name: str):
        from PySide6.QtWidgets import QComboBox

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        form = QFormLayout()
        form.setSpacing(8)

        # Name field
        self.name_edit = QLineEdit(name)
        self.name_edit.setPlaceholderText("Referral name")
        form.addRow("Name:*", self.name_edit)

        # Contact method dropdown
        self.method_combo = QComboBox()
        self.method_combo.addItems(["Email", "Phone", "LinkedIn"])
        self.method_combo.currentIndexChanged.connect(self._on_method_changed)
        form.addRow("Contact method:", self.method_combo)

        # Single contact input field (changes based on method)
        self.contact_edit = QLineEdit()
        self.contact_edit.setPlaceholderText("email@example.com")
        form.addRow("Contact:", self.contact_edit)

        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        # Add delete button for edit mode
        if self._show_delete:
            delete_btn = QPushButton("Delete Referral")
            delete_btn.setStyleSheet("""
                QPushButton {
                    background: transparent;
                    color: #f38ba8;
                    border: 1px solid #f38ba8;
                    border-radius: 4px;
                    padding: 8px 16px;
                    margin-top: 12px;
                }
                QPushButton:hover {
                    background: #313244;
                }
            """)
            delete_btn.clicked.connect(self._on_delete)
            layout.addWidget(delete_btn)

        # Set initial method based on which field has data
        self._set_initial_method()

    def _set_initial_method(self):
        """Set the initial contact method based on existing data."""
        if self._initial_phone:
            self.method_combo.setCurrentText("Phone")
            self.contact_edit.setText(self._initial_phone)
        elif self._initial_linkedin:
            self.method_combo.setCurrentText("LinkedIn")
            self.contact_edit.setText(self._initial_linkedin)
        else:
            # Default to email
            self.method_combo.setCurrentText("Email")
            self.contact_edit.setText(self._initial_email)

    def _on_method_changed(self, index: int):
        """Update placeholder text when method changes."""
        method = self.method_combo.currentText()
        if method == "Email":
            self.contact_edit.setPlaceholderText("email@example.com")
        elif method == "Phone":
            self.contact_edit.setPlaceholderText("+1 (555) 123-4567")
        elif method == "LinkedIn":
            self.contact_edit.setPlaceholderText("https://linkedin.com/in/...")

    def _on_save(self):
        if not self.name_edit.text().strip():
            QMessageBox.warning(self, "Required", "Name is required.")
            return
        self.accept()

    def _on_delete(self):
        reply = QMessageBox.question(
            self,
            "Delete Referral",
            "Are you sure you want to delete this referral?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._delete_requested = True
            self.accept()

    def get_data(self) -> dict:
        """Return data with only the selected contact method populated."""
        method = self.method_combo.currentText()
        contact_value = self.contact_edit.text().strip() or None

        return {
            "name": self.name_edit.text().strip(),
            "email": contact_value if method == "Email" else None,
            "phone": contact_value if method == "Phone" else None,
            "linkedin_url": contact_value if method == "LinkedIn" else None,
        }

    def is_delete_requested(self) -> bool:
        return self._delete_requested


class _ApplicationEditDialog(QDialog):
    """Dialog to edit application company, position, and job URL."""

    def __init__(
        self,
        parent=None,
        company: str = "",
        position: str = "",
        job_url: str = "",
    ):
        super().__init__(parent)
        self.setWindowTitle("Edit Application")
        self.setMinimumWidth(400)
        self._build_ui(company, position, job_url)

    def _build_ui(self, company: str, position: str, job_url: str):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        form = QFormLayout()
        form.setSpacing(8)

        self.company_edit = QLineEdit(company)
        self.company_edit.setPlaceholderText("Company name")
        form.addRow("Company:*", self.company_edit)

        self.position_edit = QLineEdit(position)
        self.position_edit.setPlaceholderText("Position title")
        form.addRow("Position:*", self.position_edit)

        self.url_edit = QLineEdit(job_url)
        self.url_edit.setPlaceholderText("https://...")
        form.addRow("Job URL:", self.url_edit)

        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_save(self):
        if not self.company_edit.text().strip():
            QMessageBox.warning(self, "Required", "Company is required.")
            return
        if not self.position_edit.text().strip():
            QMessageBox.warning(self, "Required", "Position is required.")
            return
        self.accept()

    def get_data(self) -> dict:
        return {
            "company": self.company_edit.text().strip(),
            "position": self.position_edit.text().strip(),
            "job_url": self.url_edit.text().strip() or None,
        }


# ── sidebar panel ──────────────────────────────────────────────────────


class _DetailsPanel(QWidget):
    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self._app_id: int | None = None
        self.setMinimumWidth(420)
        self.setMaximumWidth(540)
        self.setStyleSheet("""
            QWidget {
                background: #1e1e2e;
                border-left: 1px solid #313244;
            }
            QLabel {
                background: transparent;
                border: none;
            }
        """)
        self._build_ui()
        self.clear()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(12)

        # Company name as main title (bold) - 20px, clickable
        self.company_lbl = QLabel("Select an application")
        self.company_lbl.setWordWrap(True)
        self.company_lbl.setStyleSheet(
            "font-size: 20px; font-weight: bold; color: #cdd6f4;"
        )
        self.company_lbl.setCursor(Qt.CursorShape.PointingHandCursor)
        self.company_lbl.mouseReleaseEvent = self._on_company_clicked
        outer.addWidget(self.company_lbl)

        # Position name as subtitle - 15px, clickable
        self.position_lbl = QLabel()
        self.position_lbl.setWordWrap(True)
        self.position_lbl.setStyleSheet("font-size: 15px; color: #a6adc8;")
        self.position_lbl.setCursor(Qt.CursorShape.PointingHandCursor)
        self.position_lbl.mouseReleaseEvent = self._on_position_clicked
        outer.addWidget(self.position_lbl)

        # Job posting hyperlink (clickable) - 13px
        self.job_link_lbl = QLabel()
        self.job_link_lbl.setWordWrap(True)
        self.job_link_lbl.setOpenExternalLinks(True)
        self.job_link_lbl.setStyleSheet("font-size: 13px; color: #89b4fa;")
        outer.addWidget(self.job_link_lbl)

        # Dates (only shown when values exist) - 13px, lighter color for readability
        self.date_applied_lbl = QLabel()
        self.date_applied_lbl.setStyleSheet("font-size: 13px; color: #a6adc8;")
        outer.addWidget(self.date_applied_lbl)

        self.date_last_updated_lbl = QLabel()
        self.date_last_updated_lbl.setStyleSheet("font-size: 13px; color: #a6adc8;")
        outer.addWidget(self.date_last_updated_lbl)

        self.date_created_lbl = QLabel()
        self.date_created_lbl.setStyleSheet("font-size: 13px; color: #a6adc8;")
        outer.addWidget(self.date_created_lbl)

        outer.addSpacing(12)

        # Referrals section - 20px title (matches company name size)
        self.referrals_title_lbl = QLabel("Referrals")
        self.referrals_title_lbl.setStyleSheet(
            "font-size: 20px; font-weight: bold; color: #a6adc8; margin-top: 12px;"
        )
        outer.addWidget(self.referrals_title_lbl)

        # Referrals list - widgets directly in sidebar (name + contact labels)
        self._referral_labels: list[tuple[QWidget, int]] = []  # (widget, referral_id)

        # Add button - 13px font
        add_ref_btn = QPushButton("+ Add")
        add_ref_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #89b4fa;
                border: 1px solid #45475a;
                border-radius: 4px;
                padding: 6px 16px;
                font-size: 13px;
                margin-top: 8px;
            }
            QPushButton:hover {
                background: #313244;
            }
        """)
        add_ref_btn.clicked.connect(self._on_add_referral)
        outer.addWidget(add_ref_btn)

        outer.addStretch()

    def _label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("color: #a6adc8; font-size: 12px; font-weight: bold;")
        return lbl

    def _create_referral_widget(self, referral: dict) -> tuple[QWidget, int]:
        """Create a referral widget with separate name and contact labels.
        Name is clickable for edit, contact is selectable for copying.
        Returns (widget, referral_id) tuple."""
        # Create horizontal layout widget
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(8)
        widget.setStyleSheet("background: transparent; border: none;")

        # Name label - 18px, bold, clickable (opens edit dialog)
        name_lbl = QLabel(referral.get("name", "Unnamed"))
        name_lbl.setStyleSheet("""
            font-weight: bold;
            color: #cdd6f4;
            font-size: 18px;
            background: transparent;
            border: none;
        """)
        name_lbl.setCursor(Qt.CursorShape.PointingHandCursor)
        name_lbl.setProperty("referral_data", referral)
        name_lbl.mouseReleaseEvent = lambda event, lbl=name_lbl: (
            self._on_referral_name_clicked(event, lbl)
        )
        layout.addWidget(name_lbl)

        # Contact label - 15px, selectable, LinkedIn as hyperlink
        contact_text = ""
        is_linkedin = False
        linkedin_url = ""
        if referral.get("phone"):
            contact_text = referral["phone"]
        elif referral.get("email"):
            contact_text = referral["email"]
        elif referral.get("linkedin_url"):
            contact_text = "LinkedIn profile"
            is_linkedin = True
            linkedin_url = referral["linkedin_url"]

        if contact_text:
            contact_lbl = QLabel()
            if is_linkedin and linkedin_url:
                # Create hyperlink for LinkedIn
                contact_lbl.setText(
                    f'<a href="{linkedin_url}" style="color: #89b4fa; text-decoration: underline;">LinkedIn profile</a>'
                )
                contact_lbl.setOpenExternalLinks(True)
                contact_lbl.setTextFormat(Qt.TextFormat.RichText)
            else:
                # Plain text for phone/email, selectable
                contact_lbl.setText(contact_text)
                contact_lbl.setTextInteractionFlags(
                    Qt.TextInteractionFlag.TextSelectableByMouse
                )
            contact_lbl.setStyleSheet("""
                color: #a6adc8;
                font-size: 15px;
                background: transparent;
                border: none;
            """)
            layout.addWidget(contact_lbl)

        layout.addStretch()

        # Store referral data on the widget
        widget.setProperty("referral_data", referral)
        return (widget, referral["id"])

    def _on_referral_name_clicked(self, event, label: QLabel):
        """Handle click on referral name to open edit dialog."""
        if event.button() == Qt.MouseButton.LeftButton:
            referral = label.property("referral_data")
            if referral:
                self._on_edit_referral(referral)

    def _load_referrals(self):
        # Clear existing referral widgets from the sidebar
        for widget, ref_id in self._referral_labels:
            widget.deleteLater()
        self._referral_labels.clear()

        if self._app_id is None:
            return

        # Get the layout (outer is the sidebar layout)
        outer = self.layout()
        if not outer:
            return

        # Find the index of the "+ Add" button to insert before it
        add_btn_index = -1
        for i in range(outer.count()):
            item = outer.itemAt(i)
            widget = item.widget() if item else None
            if isinstance(widget, QPushButton) and widget.text() == "+ Add":
                add_btn_index = i
                break

        # If we found it, insert referrals before it
        if add_btn_index > 0:
            insert_index = add_btn_index
        else:
            # Otherwise insert before the stretch at the end
            insert_index = outer.count() - 1

        referrals = self.db.get_application_referrals(self._app_id)
        for i, referral in enumerate(referrals):
            widget, ref_id = self._create_referral_widget(referral)
            self._referral_labels.append((widget, ref_id))
            # Insert the widget into the sidebar layout
            outer.insertWidget(insert_index + i, widget)

    def _on_add_referral(self):
        if self._app_id is None:
            return

        dialog = _ReferralDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            data = dialog.get_data()
            self.db.add_application_referral(
                application_id=self._app_id,
                name=data["name"],
                email=data["email"],
                phone=data["phone"],
                linkedin_url=data["linkedin_url"],
                description=None,
            )
            self._load_referrals()

    def _on_edit_referral(self, referral: dict):
        dialog = _ReferralDialog(
            self,
            name=referral.get("name", ""),
            email=referral.get("email", ""),
            phone=referral.get("phone", ""),
            linkedin_url=referral.get("linkedin_url", ""),
            title="Edit Referral",
            show_delete=True,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            if dialog.is_delete_requested():
                # Delete was requested
                self.db.delete_application_referral(referral["id"])
            else:
                # Update the referral
                data = dialog.get_data()
                self.db.update_application_referral(
                    referral_id=referral["id"],
                    name=data["name"],
                    email=data.get("email"),
                    phone=data.get("phone"),
                    linkedin_url=data.get("linkedin_url"),
                    description=None,
                )
            self._load_referrals()

    def set_application(self, app: dict):
        self._app_id = app.get("id")

        # Company as main title (hide if empty, show placeholder if no app selected)
        company = (app.get("company_name") or "").strip()
        if company:
            self.company_lbl.setText(company)
            self.company_lbl.setVisible(True)
        else:
            self.company_lbl.setText("—")
            self.company_lbl.setVisible(True)

        # Position as subtitle (hide if empty)
        position = (app.get("position_name") or "").strip()
        if position:
            self.position_lbl.setText(position)
            self.position_lbl.setVisible(True)
        else:
            self.position_lbl.setVisible(False)

        # Job posting hyperlink (hide if no URL)
        url = (app.get("job_posting_url") or "").strip()
        if url:
            # Create clickable hyperlink
            display_url = url if len(url) < 50 else url[:47] + "..."
            self.job_link_lbl.setText(
                f'<a href="{url}" style="color: #89b4fa;">Job posting</a>'
            )
            self.job_link_lbl.setVisible(True)
        else:
            self.job_link_lbl.setVisible(False)

        # Applied date (hide if empty)
        date_applied = (app.get("date_applied") or "").strip()
        if date_applied:
            self.date_applied_lbl.setText(f"Applied in: {_fmt_date(date_applied)}")
            self.date_applied_lbl.setVisible(True)
        else:
            self.date_applied_lbl.setVisible(False)

        # Last update date (hide if empty)
        date_last_updated = (app.get("date_last_updated") or "").strip()
        if date_last_updated:
            self.date_last_updated_lbl.setText(
                f"Last update: {_fmt_date(date_last_updated)}"
            )
            self.date_last_updated_lbl.setVisible(True)
        else:
            self.date_last_updated_lbl.setVisible(False)

        # Created date (hide if empty)
        date_created = (app.get("date_created") or "").strip()
        if date_created:
            self.date_created_lbl.setText(f"Created: {_fmt_date(date_created)}")
            self.date_created_lbl.setVisible(True)
        else:
            self.date_created_lbl.setVisible(False)

        self._load_referrals()

    def clear(self):
        self._app_id = None
        self.company_lbl.setText("Select an application")
        self.company_lbl.setVisible(True)
        self.position_lbl.setText("")
        self.position_lbl.setVisible(False)
        self.job_link_lbl.setVisible(False)
        self.date_applied_lbl.setVisible(False)
        self.date_last_updated_lbl.setVisible(False)
        self.date_created_lbl.setVisible(False)

        # Clear referrals
        for widget, ref_id in self._referral_labels:
            widget.deleteLater()
        self._referral_labels.clear()

    def _on_company_clicked(self, event):
        """Handle click on company label to open edit dialog."""
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self._app_id is None:
            return
        self._open_edit_dialog()

    def _on_position_clicked(self, event):
        """Handle click on position label to open edit dialog."""
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self._app_id is None:
            return
        self._open_edit_dialog()

    def _open_edit_dialog(self):
        """Open dialog to edit company, position, and job URL."""
        if self._app_id is None:
            return
        app = self.db.get_application(self._app_id)
        if not app:
            return

        dialog = _ApplicationEditDialog(
            parent=self,
            company=app.get("company_name", ""),
            position=app.get("position_name", ""),
            job_url=app.get("job_posting_url", ""),
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            data = dialog.get_data()
            # Update application with new data, preserving other fields
            self.db.upsert_application(
                id=self._app_id,
                profile_id=app.get("profile_id"),
                status_id=app.get("status_id"),
                position_name=data["position"],
                company_name=data["company"],
                date_applied=app.get("date_applied"),
                job_posting_url=data["job_url"],
                extra_keywords=app.get("extra_keywords", "[]"),
                section_order=app.get("section_order"),
                sections_enabled=app.get("sections_enabled"),
                education_overrides=app.get("education_overrides"),
                job_posting_description=app.get("job_posting_description"),
                date_created=app.get("date_created"),
                date_last_updated=None,  # Will be set to today
            )
            # Refresh display
            updated_app = self.db.get_application(self._app_id)
            if updated_app:
                self.set_application(updated_app)


# ── applications view ─────────────────────────────────────────────────


class ApplicationsView(QWidget):
    new_application_requested = Signal()
    open_application_requested = Signal(int)

    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self._columns: dict[str, _ColumnList] = {}
        self._selected_list: _ColumnList | None = None
        self._drag_state: dict = {"source": None, "app_id": None}
        self._headers: dict[str, QLabel] = {}
        self._title_lbl: QLabel | None = None
        self._details_panel = _DetailsPanel(db)
        self._details_panel.setVisible(False)  # Hide by default until selection
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # main content area
        main_widget = QWidget()
        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)

        # top bar with title and buttons
        top = QHBoxLayout()
        self._title_lbl = section_title("Job Applications")
        top.addWidget(self._title_lbl)
        top.addStretch()
        new_btn = primary_btn("+ New Application")
        open_btn = primary_btn("Open Selected")
        del_btn = danger_btn("Delete Selected")
        new_btn.clicked.connect(self.new_application_requested)
        open_btn.clicked.connect(self._on_open)
        del_btn.clicked.connect(self._on_delete)
        top.addWidget(new_btn)
        top.addWidget(open_btn)
        top.addWidget(del_btn)
        main_layout.addLayout(top)

        # kanban board
        board = QWidget()
        board_l = QHBoxLayout(board)
        board_l.setContentsMargins(0, 0, 0, 0)
        board_l.setSpacing(12)

        for key, label in COLUMNS:
            col_w = QWidget()
            col_w.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
            )
            col_l = QVBoxLayout(col_w)
            col_l.setContentsMargins(0, 0, 0, 0)
            col_l.setSpacing(6)

            header = QLabel(label)
            header.setAlignment(Qt.AlignmentFlag.AlignCenter)
            header.setStyleSheet(
                "QLabel { background: #313244; color: #cdd6f4; font-size: 20px;"
                " font-weight: bold; border-radius: 6px; padding: 8px; }"
            )
            col_l.addWidget(header)
            self._headers[key] = header

            lst = _ColumnList(key, self._drag_state)
            lst.card_dropped.connect(self._on_card_dropped)
            lst.card_clicked.connect(self._on_card_clicked)
            lst.card_opened.connect(self._on_card_opened)
            lst.itemClicked.connect(lambda _, l=lst: self._on_list_clicked(l))
            self._columns[key] = lst
            col_l.addWidget(lst, 1)

            board_l.addWidget(col_w, 1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(board)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        main_layout.addWidget(scroll, 1)

        outer.addWidget(main_widget, 1)
        outer.addWidget(self._details_panel)

    def refresh(self):
        for lst in self._columns.values():
            lst.clear()

        apps = self.db.get_applications()
        status_map = {s["id"]: s["status"] for s in self.db.get_statuses()}

        # count per status
        counts: dict[str, int] = {key: 0 for key in COLUMN_KEYS}
        total = 0

        for app in apps:
            total += 1
            status = status_map.get(app["status_id"], "to-apply")
            key = status if status in COLUMN_KEYS else self._map_status(status)
            if key in self._columns:
                self._columns[key].add_card(app)
                counts[key] += 1

        # update headers with counts
        for key, (_, label) in zip(COLUMN_KEYS, COLUMNS):
            self._headers[key].setText(f"{label} ({counts[key]})")

        # update title with total
        if self._title_lbl:
            self._title_lbl.setText(f"Job Applications ({total} total)")

        # clear sidebar
        self._details_panel.clear()

    def _map_status(self, status: str) -> str:
        return {
            "phone-screen": "applied",
            "accepted": "offer",
            "withdrawn": "rejected",
        }.get(status, "to-apply")

    def _on_list_clicked(self, clicked_list: _ColumnList):
        for lst in self._columns.values():
            if lst is not clicked_list:
                lst.clearSelection()
        self._selected_list = clicked_list

    def _on_card_clicked(self, app: dict):
        self._details_panel.set_application(app)
        self._details_panel.setVisible(True)

    def _selected_app_id(self) -> int | None:
        if self._selected_list:
            aid = self._selected_list.selected_app_id()
            if aid is not None:
                return aid
        for lst in self._columns.values():
            aid = lst.selected_app_id()
            if aid is not None:
                return aid
        return None

    def _selected_app_data(self) -> dict | None:
        if self._selected_list:
            data = self._selected_list.selected_app_data()
            if data is not None:
                return data
        for lst in self._columns.values():
            data = lst.selected_app_data()
            if data is not None:
                return data
        return None

    def _on_card_dropped(self, app_id: int, new_status_key: str):
        from datetime import date as _date

        today = _date.today().strftime("%Y-%m-%d")
        statuses = {s["status"]: s["id"] for s in self.db.get_statuses()}
        new_status_id = statuses.get(new_status_key)
        if not new_status_id:
            return

        # ALWAYS update date_last_updated on every status change
        if new_status_key == "applied":
            # Get current application to check if date_applied already exists
            current_app = self.db.get_application(app_id)
            if current_app and not current_app.get("date_applied"):
                # No existing date_applied, set it now along with last_updated
                self.db.execute(
                    "UPDATE job_application SET status_id=?, date_applied=?, date_last_updated=? WHERE id=?",
                    (new_status_id, today, today, app_id),
                )
            else:
                # date_applied already exists - leave it as-is, only update status and date_last_updated
                self.db.execute(
                    "UPDATE job_application SET status_id=?, date_last_updated=? WHERE id=?",
                    (new_status_id, today, app_id),
                )
        else:
            # Not moving to "applied", update status and date_last_updated only
            self.db.execute(
                "UPDATE job_application SET status_id=?, date_last_updated=? WHERE id=?",
                (new_status_id, today, app_id),
            )

        self.refresh()

    def _on_card_opened(self, app_id: int):
        self.open_application_requested.emit(app_id)

    def _on_open(self):
        app_id = self._selected_app_id()
        if app_id:
            self.open_application_requested.emit(app_id)
        else:
            QMessageBox.information(
                self, "No selection", "Click a card to select it first."
            )

    def _on_delete(self):
        app_id = self._selected_app_id()
        if not app_id:
            QMessageBox.information(
                self, "No selection", "Click a card to select it first."
            )
            return
        if (
            QMessageBox.question(
                self,
                "Delete",
                "Delete this application?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            == QMessageBox.StandardButton.Yes
        ):
            self.db.delete_application(app_id)
            self._details_panel.setVisible(False)
            self._details_panel.clear()
            self.refresh()
