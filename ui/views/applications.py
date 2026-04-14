"""
ui/views/applications.py
Kanban board for job applications with counts and detail sidebar.
"""

from __future__ import annotations

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
            date_str = f"Created: {date_created}"
            if date_applied:
                date_str += f" | Applied: {date_applied}"
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
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(350)
        self._initial_email = email
        self._initial_phone = phone
        self._initial_linkedin = linkedin_url
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

        # Company name as main title (bold)
        self.company_lbl = QLabel("Select an application")
        self.company_lbl.setWordWrap(True)
        self.company_lbl.setStyleSheet(
            "font-size: 16px; font-weight: bold; color: #cdd6f4;"
        )
        outer.addWidget(self.company_lbl)

        # Position name as subtitle
        self.position_lbl = QLabel()
        self.position_lbl.setWordWrap(True)
        self.position_lbl.setStyleSheet("font-size: 13px; color: #a6adc8;")
        outer.addWidget(self.position_lbl)

        # Job posting hyperlink (clickable)
        self.job_link_lbl = QLabel()
        self.job_link_lbl.setWordWrap(True)
        self.job_link_lbl.setOpenExternalLinks(True)
        self.job_link_lbl.setStyleSheet("font-size: 11px; color: #89b4fa;")
        outer.addWidget(self.job_link_lbl)

        # Dates (only shown when values exist)
        self.date_applied_lbl = QLabel()
        self.date_applied_lbl.setStyleSheet("font-size: 11px; color: #6c7086;")
        outer.addWidget(self.date_applied_lbl)

        self.date_last_updated_lbl = QLabel()
        self.date_last_updated_lbl.setStyleSheet("font-size: 11px; color: #6c7086;")
        outer.addWidget(self.date_last_updated_lbl)

        self.date_created_lbl = QLabel()
        self.date_created_lbl.setStyleSheet("font-size: 11px; color: #6c7086;")
        outer.addWidget(self.date_created_lbl)

        outer.addSpacing(8)

        # Referrals section
        self.referrals_title_lbl = QLabel("Referrals")
        self.referrals_title_lbl.setStyleSheet(
            "font-size: 12px; font-weight: bold; color: #a6adc8; margin-top: 8px;"
        )
        outer.addWidget(self.referrals_title_lbl)

        self.referrals_container = QWidget()
        referrals_layout = QVBoxLayout(self.referrals_container)
        referrals_layout.setContentsMargins(0, 0, 0, 0)
        referrals_layout.setSpacing(4)

        self.referrals_list = QWidget()
        self._referrals_layout = QVBoxLayout(self.referrals_list)
        self._referrals_layout.setContentsMargins(0, 0, 0, 0)
        self._referrals_layout.setSpacing(0)
        self._referrals_layout.addStretch()
        referrals_layout.addWidget(self.referrals_list)

        add_ref_btn = QPushButton("+ Add")
        add_ref_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #89b4fa;
                border: 1px solid #45475a;
                border-radius: 4px;
                padding: 4px 12px;
                font-size: 11px;
                margin-top: 8px;
            }
            QPushButton:hover {
                background: #313244;
            }
        """)
        add_ref_btn.clicked.connect(self._on_add_referral)
        referrals_layout.addWidget(add_ref_btn)

        outer.addWidget(self.referrals_container)

        outer.addStretch()

    def _label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("color: #a6adc8; font-size: 12px; font-weight: bold;")
        return lbl

    def _create_referral_widget(self, referral: dict) -> QWidget:
        """Create a referral widget with name, contact below, and buttons on right."""
        widget = QWidget()
        outer_layout = QHBoxLayout(widget)
        outer_layout.setContentsMargins(0, 4, 0, 4)
        outer_layout.setSpacing(8)
        widget.setStyleSheet("background: transparent; border: none;")

        # Left side: Name and contact info
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(2)
        left_widget.setStyleSheet("background: transparent; border: none;")

        # Name (bold)
        name_lbl = QLabel(referral.get("name", "Unnamed"))
        name_lbl.setStyleSheet(
            "font-weight: bold; color: #cdd6f4; font-size: 12px; background: transparent; border: none;"
        )
        left_layout.addWidget(name_lbl)

        # Contact info (if available)
        contact_text = ""
        if referral.get("phone"):
            contact_text = referral["phone"]
        elif referral.get("email"):
            contact_text = referral["email"]
        elif referral.get("linkedin_url"):
            contact_text = "LinkedIn profile"

        if contact_text:
            contact_lbl = QLabel(contact_text)
            contact_lbl.setStyleSheet(
                "color: #a6adc8; font-size: 11px; background: transparent; border: none;"
            )
            left_layout.addWidget(contact_lbl)

        outer_layout.addWidget(left_widget, 1)

        # Buttons on the right side
        btn_widget = QWidget()
        btn_layout = QHBoxLayout(btn_widget)
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_layout.setSpacing(4)
        btn_widget.setStyleSheet("background: transparent; border: none;")

        # Small edit button
        edit_btn = QPushButton("✎")
        edit_btn.setToolTip("Edit")
        edit_btn.setFixedSize(24, 24)
        edit_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #a6adc8;
                border: none;
                font-size: 12px;
            }
            QPushButton:hover {
                color: #cdd6f4;
            }
        """)
        edit_btn.clicked.connect(lambda: self._on_edit_referral(referral))

        # Small delete button
        del_btn = QPushButton("×")
        del_btn.setToolTip("Delete")
        del_btn.setFixedSize(24, 24)
        del_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #f38ba8;
                border: none;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                color: #eba0ac;
            }
        """)
        del_btn.clicked.connect(lambda: self._on_delete_referral(referral))

        btn_layout.addWidget(edit_btn)
        btn_layout.addWidget(del_btn)
        outer_layout.addWidget(btn_widget)

        return widget

    def _load_referrals(self):
        # Clear existing referrals
        while self._referrals_layout.count() > 1:
            item = self._referrals_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if self._app_id is None:
            return

        referrals = self.db.get_application_referrals(self._app_id)
        for referral in referrals:
            widget = self._create_referral_widget(referral)
            self._referrals_layout.insertWidget(
                self._referrals_layout.count() - 1, widget
            )

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
                description=data["description"],
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
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
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

    def _on_delete_referral(self, referral: dict):
        if (
            QMessageBox.question(
                self,
                "Delete Referral",
                f"Delete referral for '{referral.get('name', 'Unnamed')}'?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            == QMessageBox.StandardButton.Yes
        ):
            self.db.delete_application_referral(referral["id"])
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
            self.date_applied_lbl.setText(f"Applied in: {date_applied}")
            self.date_applied_lbl.setVisible(True)
        else:
            self.date_applied_lbl.setVisible(False)

        # Last update date (hide if empty)
        date_last_updated = (app.get("date_last_updated") or "").strip()
        if date_last_updated:
            self.date_last_updated_lbl.setText(f"Last update: {date_last_updated}")
            self.date_last_updated_lbl.setVisible(True)
        else:
            self.date_last_updated_lbl.setVisible(False)

        # Created date (hide if empty)
        date_created = (app.get("date_created") or "").strip()
        if date_created:
            self.date_created_lbl.setText(f"Created: {date_created}")
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
        while self._referrals_layout.count() > 1:
            item = self._referrals_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()


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
            if current_app and current_app.get("date_applied"):
                # Show warning dialog
                reply = QMessageBox.warning(
                    self,
                    "Update Application Date",
                    f"This application already has an application date of {current_app['date_applied']}.\n\n"
                    f"Do you want to overwrite it with today's date ({today})?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if reply == QMessageBox.StandardButton.Yes:
                    # Update status, date_applied, and date_last_updated
                    self.db.execute(
                        "UPDATE job_application SET status_id=?, date_applied=?, date_last_updated=? WHERE id=?",
                        (new_status_id, today, today, app_id),
                    )
                else:
                    # Only update status and date_last_updated, keep existing date_applied
                    self.db.execute(
                        "UPDATE job_application SET status_id=?, date_last_updated=? WHERE id=?",
                        (new_status_id, today, app_id),
                    )
            else:
                # No existing date_applied, set status, date_applied, and date_last_updated
                self.db.execute(
                    "UPDATE job_application SET status_id=?, date_applied=?, date_last_updated=? WHERE id=?",
                    (new_status_id, today, today, app_id),
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
