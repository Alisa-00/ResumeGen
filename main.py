"""
main.py
Entry point. Handles DB path resolution, DB init, and app launch.
"""

from __future__ import annotations
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox, QWidget

from db.database import Database
from ui.ui import AppWindow


def resolve_db_path() -> Path | None:
    config_file = Path.home() / ".resume_orchestrator"

    if config_file.exists():
        stored = config_file.read_text().strip()
        if stored:
            return Path(stored)

    parent = QWidget()

    msg = QMessageBox(parent)
    msg.setIcon(QMessageBox.Information)
    msg.setWindowTitle("Welcome to Resume Orchestrator")
    msg.setText("Choose a folder where your resume database will be stored.")
    msg.setInformativeText("Tip: put it inside Dropbox / iCloud Drive for automatic sync.")
    msg.exec()

    folder = QFileDialog.getExistingDirectory(
        None, "Select storage folder", str(Path.home())
    )
    if not folder:
        return None

    db_path = Path(folder) / "resume_orchestrator.db"
    config_file.write_text(str(db_path))
    return db_path


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Resume Orchestrator")

    # scale UI to ~2.5x by setting base font size
    from PySide6.QtGui import QFont
    font = QFont()
    font.setPointSize(22)
    app.setFont(font)

    # global stylesheet scaling — margins, padding, widget sizes
    app.setStyleSheet("""
        QWidget {
            background-color: #1e1e2e;
            color: #cdd6f4;
            font-size: 22px;
        }
        QLabel {
            background-color: transparent;
            color: #cdd6f4;
            font-size: 22px;
        }
        QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {
            background-color: #141618;
            color: #cdd6f4;
            border: 1px solid #313244;
            border-radius: 4px;
            min-height: 42px;
            padding: 4px 8px;
            font-size: 22px;
            selection-background-color: #89b4fa;
            selection-color: #1e1e2e;
        }
        QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus,
        QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {
            border: 1px solid #89b4fa;
        }
        QComboBox QAbstractItemView {
            background-color: #1e1e2e;
            color: #cdd6f4;
            border: 1px solid #313244;
            selection-background-color: #313244;
            selection-color: #cdd6f4;
        }
        QPushButton {
            background-color: #313244;
            color: #cdd6f4;
            border: none;
            border-radius: 4px;
            min-height: 38px;
            padding: 4px 14px;
            font-size: 22px;
        }
        QPushButton:hover {
            background-color: #45475a;
        }
        QPushButton:flat {
            background-color: transparent;
        }
        QCheckBox {
            background-color: transparent;
            color: #cdd6f4;
            font-size: 22px;
            spacing: 10px;
        }
        QCheckBox::indicator {
            width: 20px;
            height: 20px;
            background-color: #141618;
            border: 1px solid #585b70;
            border-radius: 3px;
        }
        QCheckBox::indicator:checked {
            background-color: #89b4fa;
            border: 1px solid #89b4fa;
        }
        QRadioButton {
            background-color: transparent;
            color: #cdd6f4;
            font-size: 22px;
            spacing: 10px;
        }
        QRadioButton::indicator {
            width: 20px;
            height: 20px;
            background-color: #141618;
            border: 1px solid #585b70;
            border-radius: 10px;
        }
        QRadioButton::indicator:checked {
            background-color: #89b4fa;
            border: 1px solid #89b4fa;
        }
        QListWidget {
            background-color: #1e1e2e;
            color: #cdd6f4;
            border: none;
        }
        QListWidget::item {
            padding: 18px 20px;
            font-size: 22px;
        }
        QListWidget::item:selected {
            background-color: #313244;
            color: #89b4fa;
        }
        QScrollArea {
            background-color: #1e1e2e;
            border: none;
        }
        QFrame {
            color: #313244;
        }
        QScrollBar:vertical {
            background-color: #181825;
            width: 16px;
            margin: 0;
        }
        QScrollBar:horizontal {
            background-color: #181825;
            height: 16px;
            margin: 0;
        }
        QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
            background-color: #45475a;
            border-radius: 6px;
        }
        QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {
            background-color: #585b70;
        }
        QScrollBar::add-line, QScrollBar::sub-line {
            width: 0; height: 0; border: none; background: none;
        }
        QScrollBar::add-page, QScrollBar::sub-page {
            background: none;
        }
        QSplitter::handle {
            background-color: #313244;
        }
        QMessageBox, QDialog {
            background-color: #1e1e2e;
            color: #cdd6f4;
        }
        QToolTip {
            background-color: #313244;
            color: #cdd6f4;
            border: 1px solid #45475a;
        }
        QHeaderView::section {
            background-color: #313244;
            color: #cdd6f4;
            font-size: 22px;
            padding: 8px;
        }
        QDoubleSpinBox::up-button, QDoubleSpinBox::down-button,
        QSpinBox::up-button, QSpinBox::down-button {
            width: 0; height: 0; border: none;
        }
    """)

    db_path = resolve_db_path()
    if db_path is None:
        sys.exit(0)

    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = Database(db_path)
    db.connect()

    window = AppWindow(db=db)
    window.showMaximized()

    exit_code = app.exec()
    db.close()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
