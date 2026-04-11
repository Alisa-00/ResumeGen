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
        date = app.get("date_applied", "") or ""
        date_lbl = f"Updated: {date}" if date else "Updated: —"
        self.setText(f"{company}\n{position}\n{date_lbl}")
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


# ── sidebar panel ──────────────────────────────────────────────────────


class _DetailsPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
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

        outer.addWidget(self._label("Job Description:"))
        self.desc_edit = QTextEdit()
        self.desc_edit.setReadOnly(True)
        self.desc_edit.setMinimumHeight(120)
        self.desc_edit.setStyleSheet("""
            QTextEdit {
                background: #181825;
                border: 1px solid #313244;
                border-radius: 4px;
                padding: 8px;
                color: #cdd6f4;
            }
        """)
        outer.addWidget(self.desc_edit, 1)

        self.last_updated_lbl = QLabel("")
        self.last_updated_lbl.setStyleSheet("color: #585b70; font-size: 11px;")
        outer.addWidget(self.last_updated_lbl)

        outer.addStretch()

    def _label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("color: #a6adc8; font-size: 12px; font-weight: bold;")
        return lbl

    def set_application(self, app: dict):
        self.title_lbl.setText(f"Application #{app.get('id', '')}")
        self.company_lbl.setText(app.get("company_name", "—") or "—")
        self.position_lbl.setText(app.get("position_name", "—") or "—")
        self.status_lbl.setText(app.get("status", "—") or "—")
        self.profile_lbl.setText(app.get("profile_name", "—") or "—")
        self.url_edit.setText(app.get("job_posting_url", "") or "")
        self.desc_edit.setPlainText(app.get("job_posting_description", "") or "")
        date = app.get("date_applied", "") or "—"
        self.last_updated_lbl.setText(f"Last updated: {date}")

    def clear(self):
        self.title_lbl.setText("Select an application")
        self.company_lbl.setText("—")
        self.position_lbl.setText("—")
        self.status_lbl.setText("—")
        self.profile_lbl.setText("—")
        self.url_edit.setText("")
        self.desc_edit.setPlainText("")
        self.last_updated_lbl.setText("")


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
        self._details_panel = _DetailsPanel()
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
        if new_status_id:
            self.db.execute(
                "UPDATE job_application SET status_id=?, date_applied=? WHERE id=?",
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
            self.refresh()
