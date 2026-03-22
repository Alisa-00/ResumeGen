from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QPushButton, QLabel, QMessageBox, QDoubleSpinBox, QSpinBox,
    QComboBox,
)

from db.database import Database
from ui.widgets import (
    section_title, hline, primary_btn, flat_link_btn,
    field, scrollable, Card,
)

FONT_OPTIONS = [
    "Arial", "Helvetica", "Georgia", "Times New Roman",
    "Calibri", "Garamond", "Palatino", "Verdana",
    "DejaVu Serif", "DejaVu Sans", "Liberation Serif", "Liberation Sans",
]


def _spinbox(min_: float, max_: float, step: float,
             value: float, decimals: int = 1) -> QDoubleSpinBox:
    sb = QDoubleSpinBox()
    sb.setRange(min_, max_)
    sb.setSingleStep(step)
    sb.setDecimals(decimals)
    sb.setValue(value)
    sb.setFixedWidth(90)
    return sb


def _intbox(min_: int, max_: int, value: int) -> QSpinBox:
    sb = QSpinBox()
    sb.setRange(min_, max_)
    sb.setValue(value)
    sb.setFixedWidth(90)
    return sb


class TemplatesView(QWidget):
    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self._cards: list[tuple[Card, dict | None]] = []

        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(24, 16, 24, 16)
        layout.setSpacing(12)
        layout.addWidget(section_title("Resume Templates"))

        hint = QLabel(
            "Templates control typography and layout. "
            "The underlying HTML/CSS file can be edited directly outside this app if needed."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #a6adc8; font-size: 12px;")
        layout.addWidget(hint)
        layout.addWidget(hline())

        self._cards_container = QWidget()
        self._cards_layout    = QVBoxLayout(self._cards_container)
        self._cards_layout.setContentsMargins(0, 0, 0, 0)
        self._cards_layout.setSpacing(10)
        layout.addWidget(self._cards_container)

        btn_row = QHBoxLayout()
        add_btn  = flat_link_btn("+ Add Template")
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

    # ------------------------------------------------------------------

    def _load(self):
        for row in self.db.get_templates():
            self._add_card(row)
        # seed default template if none exist
        if not self._cards:
            self._add_card(_default_template_data())

    def _add_card(self, data: dict | None = None):
        card = Card()
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)

        d = data or {}

        f_name = field("Template name", d.get("name", ""))

        f_font = QComboBox()
        f_font.addItems(FONT_OPTIONS)
        saved_font = d.get("font_family", "Arial")
        idx = f_font.findText(saved_font)
        f_font.setCurrentIndex(idx if idx >= 0 else 0)
        f_font.setFixedWidth(200)

        f_font_size    = _spinbox(6, 24, 0.5,  d.get("font_size",     11.0))
        f_margin_top   = _spinbox(0, 60, 1.0,  d.get("margin_top",    15.0))
        f_margin_bot   = _spinbox(0, 60, 1.0,  d.get("margin_bottom", 15.0))
        f_margin_left  = _spinbox(0, 60, 1.0,  d.get("margin_left",   15.0))
        f_margin_right = _spinbox(0, 60, 1.0,  d.get("margin_right",  15.0))
        f_min_bp       = _intbox(0, 20,         d.get("min_bullet_points_per_job", 2))
        f_max_bp       = _intbox(0, 20,         d.get("max_bullet_points_per_job", 5))

        for lbl, w in [
            ("Name",              f_name),
            ("Font family",       f_font),
            ("Font size (pt)",    f_font_size),
            ("Margin top (mm)",   f_margin_top),
            ("Margin bottom (mm)",f_margin_bot),
            ("Margin left (mm)",  f_margin_left),
            ("Margin right (mm)", f_margin_right),
            ("Min bullets/job",   f_min_bp),
            ("Max bullets/job",   f_max_bp),
        ]:
            form.addRow(lbl, w)

        card._fields = dict(
            name=f_name, font=f_font, font_size=f_font_size,
            mt=f_margin_top, mb=f_margin_bot,
            ml=f_margin_left, mr=f_margin_right,
            min_bp=f_min_bp, max_bp=f_max_bp,
        )
        card._data = data
        card.add_form(form)
        card.add_delete_button()
        card.delete_requested.connect(self._delete_card)

        self._cards.append((card, data))
        self._cards_layout.addWidget(card)

    def _delete_card(self, card: Card):
        if card._data and card._data.get("id"):
            self.db.delete_template(card._data["id"])
        self._cards = [(c, d) for c, d in self._cards if c is not card]
        self._cards_layout.removeWidget(card)
        card.deleteLater()

    def _save_all(self):
        for card, _ in self._cards:
            f      = card._fields
            min_bp = f["min_bp"].value()
            max_bp = f["max_bp"].value()
            if min_bp > max_bp:
                QMessageBox.warning(
                    self, "Invalid",
                    f"Min bullets ({min_bp}) cannot exceed max ({max_bp})."
                )
                return
            new_id = self.db.upsert_template(
                name        = f["name"].text().strip() or "Untitled",
                font_family = f["font"].currentText(),
                font_size   = f["font_size"].value(),
                margin_top  = f["mt"].value(),
                margin_bottom = f["mb"].value(),
                margin_left = f["ml"].value(),
                margin_right = f["mr"].value(),
                min_bp      = min_bp,
                max_bp      = max_bp,
                id          = (card._data or {}).get("id"),
            )
            card._data = {**(card._data or {}), "id": new_id}
        QMessageBox.information(self, "Saved", "Templates saved.")


def _default_template_data() -> dict:
    return dict(
        name="Default — Clean Minimal",
        font_family="Liberation Serif",
        font_size=11.0,
        margin_top=15.0, margin_bottom=15.0,
        margin_left=15.0, margin_right=15.0,
        min_bullet_points_per_job=2,
        max_bullet_points_per_job=5,
    )