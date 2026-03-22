"""
main.py
Entry point. Handles DB path resolution, DB init, and app launch.
"""

from __future__ import annotations
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from db.database import Database
from ui.ui import AppWindow


def resolve_db_path() -> Path | None:
    config_file = Path.home() / ".resume_orchestrator"

    if config_file.exists():
        stored = config_file.read_text().strip()
        if stored:
            return Path(stored)

    QMessageBox.information(
        None,
        "Welcome to Resume Orchestrator",
        "Choose a folder where your resume database will be stored.\n"
        "Tip: put it inside Dropbox / iCloud Drive for automatic sync.",
    )
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
            font-size: 22px;
        }
        QLineEdit, QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {
            min-height: 42px;
            padding: 4px 8px;
            font-size: 22px;
        }
        QPushButton {
            min-height: 38px;
            padding: 4px 14px;
            font-size: 22px;
        }
        QCheckBox {
            font-size: 22px;
            spacing: 10px;
        }
        QCheckBox::indicator {
            width: 20px;
            height: 20px;
        }
        QRadioButton {
            font-size: 22px;
            spacing: 10px;
        }
        QRadioButton::indicator {
            width: 20px;
            height: 20px;
        }
        QListWidget::item {
            padding: 18px 20px;
            font-size: 22px;
        }
        QLabel {
            font-size: 22px;
        }
        QScrollBar:vertical {
            width: 16px;
        }
        QScrollBar:horizontal {
            height: 16px;
        }
        QHeaderView::section {
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