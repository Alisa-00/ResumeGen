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
        description: str = "",
        title: str = "Add Referral",
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(350)
        self._build_ui(name, email, phone, linkedin_url, description)

    def _build_ui(
        self, name: str, email: str, phone: str, linkedin_url: str, description: str
    ):
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
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
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


# ── sidebar panel ──────────────────────────────────────────────────────


class _DetailsPanel(QWidget):
    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self._app_id: int | None = None
        self.setMinimumWidth(280)
        self.setMaximumWidth(360)
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

        self.title_lbl = QLabel("Select an application")
        self.title_lbl.setStyleSheet(
            "font-size: 16px; font-weight: bold; color: #cdd6f4;"
        )
        outer.addWidget(self.title_lbl)

        grid = QGridLayout()
        grid.setVerticalSpacing(8)
        grid.setHorizontalSpacing(8)
        grid.setColumnStretch(1, 1)

        grid.addWidget(self._label("Company:"), 0, 0)
        self.company_lbl = QLabel("—")
        self.company_lbl.setWordWrap(True)
        grid.addWidget(self.company_lbl, 0, 1)

        grid.addWidget(self._label("Position:"), 1, 0)
        self.position_lbl = QLabel("—")
        self.position_lbl.setWordWrap(True)
        grid.addWidget(self.position_lbl, 1, 1)

        grid.addWidget(self._label("Status:"), 2, 0)
        self.status_lbl = QLabel("—")
        grid.addWidget(self.status_lbl, 2, 1)

        grid.addWidget(self._label("Profile:"), 3, 0)
        self.profile_lbl = QLabel("—")
        self.profile_lbl.setWordWrap(True)
        grid.addWidget(self.profile_lbl, 3, 1)

        outer.addLayout(grid)

        # Dates section
        outer.addWidget(self._label("Dates:"))
        self.date_created_lbl = QLabel("Created: —")
        self.date_created_lbl.setStyleSheet("color: #a6adc8; font-size: 11px;")
        outer.addWidget(self.date_created_lbl)
        self.date_applied_lbl = QLabel("Applied: —")
        self.date_applied_lbl.setStyleSheet("color: #a6adc8; font-size: 11px;")
        outer.addWidget(self.date_applied_lbl)

        # Referrals section (moved up)
        outer.addWidget(self._label("Referrals:"))
        self.referrals_container = QWidget()
        referrals_layout = QVBoxLayout(self.referrals_container)
        referrals_layout.setContentsMargins(0, 0, 0, 0)
        referrals_layout.setSpacing(8)

        self.referrals_list = QWidget()
        self._referrals_layout = QVBoxLayout(self.referrals_list)
        self._referrals_layout.setContentsMargins(0, 0, 0, 0)
        self._referrals_layout.setSpacing(6)
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
            }
            QPushButton:hover {
                background: #313244;
            }
        """)
        add_ref_btn.clicked.connect(self._on_add_referral)
        referrals_layout.addWidget(add_ref_btn)

        outer.addWidget(self.referrals_container)

        # Job URL (moved below referrals)
        outer.addWidget(self._label("Job URL:"))
        self.url_edit = QLineEdit()
        self.url_edit.setReadOnly(True)
        self.url_edit.setStyleSheet("""
            QLineEdit {
                background: #181825;
                border: 1px solid #313244;
                border-radius: 4px;
                padding: 6px;
                color: #89b4fa;
            }
        """)
        outer.addWidget(self.url_edit)

        outer.addStretch()

    def _label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("color: #a6adc8; font-size: 12px; font-weight: bold;")
        return lbl

    def _create_referral_widget(self, referral: dict) -> QWidget:
        """Create a compact single-line referral widget with edit/delete buttons."""
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(8)
        widget.setStyleSheet("background: transparent; border: none;")

        # Build the contact text (pick the first available: phone, email, or linkedin)
        contact_text = ""
        if referral.get("phone"):
            contact_text = referral["phone"]
        elif referral.get("email"):
            contact_text = referral["email"]
        elif referral.get("linkedin_url"):
            contact_text = "LinkedIn"

        # Main label: "Name - contact"
        if contact_text:
            main_text = f"{referral.get('name', 'Unnamed')} - {contact_text}"
        else:
            main_text = referral.get("name", "Unnamed")

        main_lbl = QLabel(main_text)
        main_lbl.setStyleSheet(
            "color: #cdd6f4; font-size: 12px; background: transparent; border: none;"
        )
        main_lbl.setWordWrap(False)
        layout.addWidget(main_lbl, 1)

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

        layout.addWidget(edit_btn)
        layout.addWidget(del_btn)

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
            description=referral.get("description", ""),
            title="Edit Referral",
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            data = dialog.get_data()
            self.db.update_application_referral(
                referral_id=referral["id"],
                name=data["name"],
                email=data["email"],
                phone=data["phone"],
                linkedin_url=data["linkedin_url"],
                description=data["description"],
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
        self.title_lbl.setText(f"Application #{app.get('id', '')}")
        self.company_lbl.setText(app.get("company_name", "—") or "—")
        self.position_lbl.setText(app.get("position_name", "—") or "—")
        self.status_lbl.setText(app.get("status", "—") or "—")
        self.profile_lbl.setText(app.get("profile_name", "—") or "—")
        self.url_edit.setText(app.get("job_posting_url", "") or "")

        date_created = app.get("date_created", "") or "—"
        self.date_created_lbl.setText(f"Created: {date_created}")

        date_applied = app.get("date_applied", "") or "Not yet applied"
        self.date_applied_lbl.setText(f"Applied: {date_applied}")

        self._load_referrals()

    def clear(self):
        self._app_id = None
        self.title_lbl.setText("Select an application")
        self.company_lbl.setText("—")
        self.position_lbl.setText("—")
        self.status_lbl.setText("—")
        self.profile_lbl.setText("—")
        self.url_edit.setText("")
        self.date_created_lbl.setText("Created: —")
        self.date_applied_lbl.setText("Applied: —")

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

        # Check if dropping to "applied" column
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
                    self.db.execute(
                        "UPDATE job_application SET status_id=?, date_applied=? WHERE id=?",
                        (new_status_id, today, app_id),
                    )
                else:
                    # Only update status, keep existing date_applied
                    self.db.execute(
                        "UPDATE job_application SET status_id=? WHERE id=?",
                        (new_status_id, app_id),
                    )
            else:
                # No existing date_applied, set both status and date
                self.db.execute(
                    "UPDATE job_application SET status_id=?, date_applied=? WHERE id=?",
                    (new_status_id, today, app_id),
                )
        else:
            # Not moving to "applied", only update status
            self.db.execute(
                "UPDATE job_application SET status_id=? WHERE id=?",
                (new_status_id, app_id),
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
