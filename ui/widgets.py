"""
ui/widgets.py
Shared widget factories and reusable components used across views.
"""

from __future__ import annotations

from PySide6.QtGui import QFont, QPainter, QPen, QColor
from PySide6.QtCore import Qt, Signal, QSize, QRect
from PySide6.QtWidgets import (
    QWidget, QFrame, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QLineEdit, QScrollArea,
    QComboBox, QSizePolicy,
    QListWidget, QListWidgetItem,
)


# ----------------------------------------------------------------------
# Factories
# ----------------------------------------------------------------------

def section_title(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet("font-size: 26px; font-weight: bold; margin-top: 6px;")
    return lbl


def hline() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.Shape.HLine)
    f.setFrameShadow(QFrame.Shadow.Sunken)
    return f


def primary_btn(text: str) -> QPushButton:
    btn = QPushButton(text)
    btn.setStyleSheet(
        "QPushButton { background: #89b4fa; color: #1e1e2e; border-radius: 4px;"
        " padding: 6px 16px; font-weight: bold; font-size: 22px; min-height: 38px; }"
        "QPushButton:hover { background: #74c7ec; }"
    )
    return btn


def danger_btn(text: str) -> QPushButton:
    btn = QPushButton(text)
    btn.setStyleSheet(
        "QPushButton { background: #f38ba8; color: #1e1e2e; border-radius: 4px;"
        " padding: 4px 12px; font-size: 22px; font-weight: bold; min-height: 38px; }"
        "QPushButton:hover { background: #eba0ac; }"
    )
    return btn


class _XButton(QPushButton):
    """A button that paints a thick X using QPainter — font-independent."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(48, 44)
        self.setStyleSheet(
            "QPushButton { background: #f38ba8; border-radius: 4px; border: none; }"
            "QPushButton:hover { background: #eba0ac; }"
        )

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor("#1e1e2e"))
        pen.setWidth(4)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        m = 14
        r = self.rect()
        p.drawLine(r.left() + m, r.top() + m, r.right() - m, r.bottom() - m)
        p.drawLine(r.right() - m, r.top() + m, r.left() + m, r.bottom() - m)
        p.end()


def small_danger_btn(text: str = "X") -> _XButton:
    """Compact danger button with a painted thick X."""
    return _XButton()


def flat_link_btn(text: str) -> QPushButton:
    btn = QPushButton(text)
    btn.setFlat(True)
    btn.setStyleSheet("color: #89b4fa; text-align: left; font-size: 22px;")
    return btn


def field(placeholder: str = "", value: str = "") -> QLineEdit:
    w = QLineEdit(value)
    w.setPlaceholderText(placeholder)
    return w


def date_field(value: str = "") -> QLineEdit:
    if value and len(value) > 7:
        value = value[:7]
    w = QLineEdit()
    w.setInputMask("9999-99;_")
    w.setPlaceholderText("YYYY-MM")
    w.setFixedWidth(160)
    if value:
        w.setText(value)
    return w


def scrollable(inner: QWidget) -> QScrollArea:
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setWidget(inner)
    area.setFrameShape(QFrame.Shape.NoFrame)
    return area


# ----------------------------------------------------------------------
# TagList — keyword tag display using QListWidget
# ----------------------------------------------------------------------

class TagList(QWidget):
    removed = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ids: list[int] = []
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._list = QListWidget()
        self._list.setFlow(QListWidget.Flow.LeftToRight)
        self._list.setWrapping(True)
        self._list.setResizeMode(QListWidget.ResizeMode.Fixed)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.setSpacing(4)
        self._list.setFixedHeight(56)
        self._list.setStyleSheet("""
            QListWidget {
                background: transparent;
                border: none;
            }
            QListWidget::item {
                background: #313244;
                color: #cdd6f4;
                border-radius: 10px;
                padding: 4px 12px;
            }
            QListWidget::item:selected {
                background: #45475a;
                color: #cdd6f4;
            }
            QListWidget::item:hover {
                background: #45475a;
            }
        """)
        self._list.itemClicked.connect(self._on_click)
        layout.addWidget(self._list)

    def add_tag(self, kw_id: int, name: str):
        if kw_id in self._ids:
            return
        self._ids.append(kw_id)
        item = QListWidgetItem(f"{name}  ×")
        item.setData(Qt.ItemDataRole.UserRole, kw_id)
        self._list.addItem(item)
        self._resize()

    def remove_tag(self, kw_id: int):
        for i in range(self._list.count()):
            if self._list.item(i).data(Qt.ItemDataRole.UserRole) == kw_id:
                self._list.takeItem(i)
                break
        if kw_id in self._ids:
            self._ids.remove(kw_id)
        self._resize()

    def current_ids(self) -> list[int]:
        return list(self._ids)

    def _on_click(self, item: QListWidgetItem):
        kw_id = item.data(Qt.ItemDataRole.UserRole)
        self.removed.emit(kw_id)

    def _resize(self):
        count = self._list.count()
        if count == 0:
            self._list.setFixedHeight(56)
        else:
            self._list.setFixedHeight(min(count, 3) * 56 + 8)


# ----------------------------------------------------------------------
# KeywordTagger — dropdown + TagList
# ----------------------------------------------------------------------

class KeywordTagger(QWidget):
    def __init__(self, all_keywords: list[dict],
                 selected_ids: list[int] | None = None, parent=None):
        super().__init__(parent)
        self._all   : dict[int, str] = {kw["id"]: kw["name"] for kw in all_keywords}
        self._chosen: dict[int, str] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)

        pick_row = QHBoxLayout()
        self._combo = QComboBox()
        self._combo.setFixedWidth(220)
        self._combo.addItem("— add keyword —", userData=None)
        self._combo.currentIndexChanged.connect(self._on_pick)
        pick_row.addWidget(self._combo)
        pick_row.addStretch()
        root.addLayout(pick_row)

        self._tags = TagList()
        self._tags.removed.connect(self._remove_tag)
        root.addWidget(self._tags)

        self._refresh_combo()

        for kw_id in (selected_ids or []):
            if kw_id in self._all:
                self._add_tag(kw_id, self._all[kw_id])

    def selected_ids(self) -> list[int]:
        return list(self._chosen.keys())

    def _refresh_combo(self):
        self._combo.blockSignals(True)
        self._combo.clear()
        self._combo.addItem("— add keyword —", userData=None)
        for kw_id, name in sorted(self._all.items(), key=lambda x: x[1]):
            if kw_id not in self._chosen:
                self._combo.addItem(name, userData=kw_id)
        self._combo.blockSignals(False)

    def _on_pick(self, index: int):
        kw_id = self._combo.itemData(index)
        if kw_id is None:
            return
        self._add_tag(kw_id, self._all[kw_id])
        self._combo.setCurrentIndex(0)

    def _add_tag(self, kw_id: int, name: str):
        if kw_id in self._chosen:
            return
        self._chosen[kw_id] = name
        self._tags.add_tag(kw_id, name)
        self._refresh_combo()

    def _remove_tag(self, kw_id: int):
        self._chosen.pop(kw_id, None)
        self._tags.remove_tag(kw_id)
        self._refresh_combo()


# ----------------------------------------------------------------------
# CollapsiblePanel
# ----------------------------------------------------------------------

class CollapsiblePanel(QWidget):
    def __init__(self, label: str, collapsed: bool = True, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._toggle = QPushButton()
        self._toggle.setFlat(True)
        self._toggle.setStyleSheet(
            "QPushButton { text-align: left; color: #89b4fa;"
            " padding: 4px 0; font-size: 20px; }"
            "QPushButton:hover { color: #74c7ec; }"
        )
        self._toggle.clicked.connect(self._on_toggle)
        root.addWidget(self._toggle)

        self._content = QWidget()
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(8, 4, 0, 4)
        self._content.setVisible(not collapsed)
        root.addWidget(self._content)

        self._collapsed = collapsed
        self._label     = label
        self._update_label()

    def set_content(self, widget: QWidget) -> None:
        self._content_layout.addWidget(widget)

    def _on_toggle(self):
        self._collapsed = not self._collapsed
        self._content.setVisible(not self._collapsed)
        self._update_label()

    def _update_label(self):
        arrow = "▶" if self._collapsed else "▼"
        self._toggle.setText(f"{arrow}  {self._label}")


# ----------------------------------------------------------------------
# Card
# ----------------------------------------------------------------------

class Card(QFrame):
    delete_requested = Signal(QFrame)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.Box)
        self.setStyleSheet(
            "QFrame { border: 1px solid #313244; border-radius: 6px;"
            " background: #181825; padding: 4px; }"
        )
        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(12, 8, 12, 8)
        self._outer.setSpacing(4)

    def add_form(self, form) -> None:
        self._outer.addLayout(form)

    def add_widget(self, w: QWidget) -> None:
        self._outer.addWidget(w)

    def add_delete_button(self) -> None:
        row = QHBoxLayout()
        row.addStretch()
        btn = danger_btn("Delete")
        btn.clicked.connect(lambda: self.delete_requested.emit(self))
        row.addWidget(btn)
        self._outer.addLayout(row)


# ----------------------------------------------------------------------
# PlaceholderView
# ----------------------------------------------------------------------

class PlaceholderView(QWidget):
    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        lbl = QLabel(f"[ {label} — coming soon ]")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet("color: grey; font-size: 16px;")
        QVBoxLayout(self).addWidget(lbl)