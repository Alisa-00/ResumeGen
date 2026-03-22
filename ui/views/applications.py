"""
ui/views/applications.py
Kanban board for job applications.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QDrag, QFont, QPainter, QColor
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QAbstractItemView,
    QStyledItemDelegate, QStyleOptionViewItem,
    QScrollArea, QFrame, QMessageBox, QSizePolicy,
)

from db.database import Database
from ui.widgets import primary_btn, danger_btn, section_title

COLUMNS: list[tuple[str, str]] = [
    ("to-apply",  "To Apply"),
    ("applied",   "Applied"),
    ("interview", "Interview"),
    ("offer",     "Offer"),
    ("ghosted",   "Ghosted"),
    ("rejected",  "Rejected"),
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

        text  = index.data(Qt.ItemDataRole.DisplayRole) or ""
        lines = text.split("\n")
        x = option.rect.x() + 12
        y = option.rect.y() + 28

        styles = [
            (True,  13, "#cdd6f4"),
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
        self.app_id  = app["id"]
        company  = app.get("company_name", "")
        position = app.get("position_name", "")
        date     = app.get("date_applied", "") or ""
        date_lbl = f"Updated: {date}" if date else "Updated: —"
        self.setText(f"{company}\n{position}\n{date_lbl}")
        self.setData(Qt.ItemDataRole.UserRole, app["id"])
        self.setSizeHint(QSize(0, 110))


# ── column list ───────────────────────────────────────────────────────

class _ColumnList(QListWidget):
    card_dropped = Signal(int, str)
    card_opened  = Signal(int)

    def __init__(self, status_key: str, drag_state: dict, parent=None):
        super().__init__(parent)
        self.status_key  = status_key
        self._drag_state = drag_state   # shared dict owned by ApplicationsView

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

        self.itemDoubleClicked.connect(
            lambda item: self.card_opened.emit(item.data(Qt.ItemDataRole.UserRole))
        )

    def add_card(self, app: dict):
        self.addItem(_AppCard(app))

    def selected_app_id(self) -> int | None:
        items = self.selectedItems()
        return items[0].data(Qt.ItemDataRole.UserRole) if items else None

    def startDrag(self, supported_actions):
        # always reset state at drag start so any previously interrupted
        # drag can never leave dirty state that bleeds into this one
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


# ── applications view ─────────────────────────────────────────────────

class ApplicationsView(QWidget):
    new_application_requested  = Signal()
    open_application_requested = Signal(int)

    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self._columns: dict[str, _ColumnList] = {}
        self._selected_list: _ColumnList | None = None
        # drag state owned here, passed by reference into each _ColumnList
        self._drag_state: dict = {"source": None, "app_id": None}
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(12)

        # top bar
        top = QHBoxLayout()
        top.addWidget(section_title("Job Applications"))
        top.addStretch()
        new_btn  = primary_btn("+ New Application")
        open_btn = primary_btn("Open Selected")
        del_btn  = danger_btn("Delete Selected")
        new_btn.clicked.connect(self.new_application_requested)
        open_btn.clicked.connect(self._on_open)
        del_btn.clicked.connect(self._on_delete)
        top.addWidget(new_btn)
        top.addWidget(open_btn)
        top.addWidget(del_btn)
        outer.addLayout(top)

        # kanban board
        board = QWidget()
        board_l = QHBoxLayout(board)
        board_l.setContentsMargins(0, 0, 0, 0)
        board_l.setSpacing(12)

        for key, label in COLUMNS:
            col_w = QWidget()
            col_w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
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

            lst = _ColumnList(key, self._drag_state)
            lst.card_dropped.connect(self._on_card_dropped)
            lst.card_opened.connect(self._on_card_opened)
            lst.itemClicked.connect(lambda _, l=lst: self._on_list_clicked(l))
            self._columns[key] = lst
            col_l.addWidget(lst, 1)

            board_l.addWidget(col_w, 1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(board)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll, 1)

    def refresh(self):
        for lst in self._columns.values():
            lst.clear()
        status_map = {s["id"]: s["status"] for s in self.db.get_statuses()}
        for app in self.db.get_applications():
            status = status_map.get(app["status_id"], "to-apply")
            key    = status if status in COLUMN_KEYS else self._map_status(status)
            if key in self._columns:
                self._columns[key].add_card(app)

    def _map_status(self, status: str) -> str:
        return {"phone-screen": "applied", "accepted": "offer",
                "withdrawn": "rejected"}.get(status, "to-apply")

    def _on_list_clicked(self, clicked_list: _ColumnList):
        for lst in self._columns.values():
            if lst is not clicked_list:
                lst.clearSelection()
        self._selected_list = clicked_list

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

    def _on_card_dropped(self, app_id: int, new_status_key: str):
        from datetime import date as _date
        today         = _date.today().strftime("%Y-%m-%d")
        statuses      = {s["status"]: s["id"] for s in self.db.get_statuses()}
        new_status_id = statuses.get(new_status_key)
        if new_status_id:
            self.db.execute(
                "UPDATE job_application SET status_id=?, date_applied=? WHERE id=?",
                (new_status_id, today, app_id)
            )
        for lst in self._columns.values():
            for i in range(lst.count()):
                item = lst.item(i)
                if item.data(Qt.ItemDataRole.UserRole) == app_id:
                    lines = item.text().split("\n")
                    if len(lines) >= 3:
                        lines[2] = f"Updated: {today}"
                        item.setText("\n".join(lines))
            lst.clearSelection()

    def _on_card_opened(self, app_id: int):
        self.open_application_requested.emit(app_id)

    def _on_open(self):
        app_id = self._selected_app_id()
        if app_id:
            self.open_application_requested.emit(app_id)
        else:
            QMessageBox.information(self, "No selection", "Click a card to select it first.")

    def _on_delete(self):
        app_id = self._selected_app_id()
        if not app_id:
            QMessageBox.information(self, "No selection", "Click a card to select it first.")
            return
        if QMessageBox.question(
            self, "Delete", "Delete this application?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        ) == QMessageBox.StandardButton.Yes:
            self.db.delete_application(app_id)
            self.refresh()