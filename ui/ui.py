"""
ui/ui.py
Main window. Manages the primary nav stack and wizard overlay.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QThreadPool, QRunnable, Signal, QObject
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QListWidget, QListWidgetItem, QStackedWidget, QMessageBox,
)

from db.database import Database
from ui.views.contact      import ContactView
from ui.views.experience   import ExperienceView
from ui.views.education    import EducationView
from ui.views.projects     import ProjectsView
from ui.views.keywords     import KeywordsView
from ui.views.profiles     import ProfilesView
from ui.views.templates    import TemplatesView
from ui.views.settings     import SettingsView
from ui.views.applications import ApplicationsView
from ui.widgets import PlaceholderView, primary_btn


NAV_ITEMS: list[tuple[str, str]] = [
    ("Contact",        "contact"),
    ("Summary",        "profiles"),
    ("Experience",     "experience"),
    ("Education",      "education"),
    ("Projects",       "projects"),
    ("Keywords",       "keywords"),
    ("Templates",      "templates"),
    ("Applications",   "applications"),
    ("Settings",       "settings"),
]


def _build_view(key: str, db: Database) -> QWidget:
    return {
        "contact":      lambda: ContactView(db),
        "experience":   lambda: ExperienceView(db),
        "education":    lambda: EducationView(db),
        "projects":     lambda: ProjectsView(db),
        "keywords":     lambda: KeywordsView(db),
        "profiles":     lambda: ProfilesView(db),
        "templates":    lambda: TemplatesView(db),
        "applications": lambda: ApplicationsView(db),
        "settings":     lambda: SettingsView(db),
    }.get(key, lambda: PlaceholderView(key))()


# ── worker thread helper ─────────────────────────────────────────────

class _Signals(QObject):
    finished = Signal(object)
    error    = Signal(str)


class _Task(QRunnable):
    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self.fn      = fn
        self.args    = args
        self.kwargs  = kwargs
        self.signals = _Signals()

    def run(self):
        try:
            self.signals.finished.emit(self.fn(*self.args, **self.kwargs))
        except Exception as e:
            self.signals.error.emit(str(e))


# ── main window ──────────────────────────────────────────────────────

class AppWindow(QMainWindow):
    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self._wizard_widget = None
        self.setWindowTitle("Resume Orchestrator")
        self.resize(1400, 900)
        self._build_ui()

    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        root_l = QHBoxLayout(root)
        root_l.setContentsMargins(0, 0, 0, 0)
        root_l.setSpacing(0)

        # sidebar nav
        self._nav = QListWidget()
        self._nav.setFixedWidth(240)
        self._nav.setStyleSheet("""
            QListWidget { background: #1e1e2e; border: none; }
            QListWidget::item { color: #cdd6f4; padding: 12px 16px; font-size: 13px; }
            QListWidget::item:selected { background: #313244; color: #89b4fa; }
            QListWidget::item:hover { background: #2a2a3d; }
        """)
        for label, _ in NAV_ITEMS:
            self._nav.addItem(QListWidgetItem(label))
        self._nav.currentRowChanged.connect(self._on_nav_change)

        self._main_stack = QStackedWidget()

        self._normal_page = QWidget()
        np_l = QHBoxLayout(self._normal_page)
        np_l.setContentsMargins(0, 0, 0, 0)

        self._content_stack = QStackedWidget()
        for _, key in NAV_ITEMS:
            self._content_stack.addWidget(_build_view(key, self.db))

        apps_idx = next(i for i, (_, k) in enumerate(NAV_ITEMS) if k == "applications")
        apps_view = self._content_stack.widget(apps_idx)
        apps_view.new_application_requested.connect(lambda: self._open_wizard(None))
        apps_view.open_application_requested.connect(self._open_wizard)

        np_l.addWidget(self._content_stack)

        self._wizard_placeholder = QWidget()

        self._main_stack.addWidget(self._normal_page)
        self._main_stack.addWidget(self._wizard_placeholder)

        root_l.addWidget(self._nav)
        root_l.addWidget(self._main_stack, 1)

        self._nav.setCurrentRow(0)

    def _on_nav_change(self, row: int):
        if self._main_stack.currentIndex() == 1:
            self._close_wizard()
        self._content_stack.setCurrentIndex(row)

    def _open_wizard(self, application_id: int | None):
        from ui.wizard.wizard import WizardWidget

        if self._main_stack.count() > 1:
            old = self._main_stack.widget(1)
            self._main_stack.removeWidget(old)
            old.deleteLater()

        wizard = WizardWidget(
            db             = self.db,
            db_path        = self.db.db_path,
            application_id = application_id,
        )
        wizard.closed.connect(self._close_wizard)
        self._wizard_widget = wizard
        self._main_stack.addWidget(wizard)
        self._main_stack.setCurrentIndex(1)

    def _close_wizard(self):
        self._main_stack.setCurrentIndex(0)
        self._wizard_widget = None
        apps_idx = next(i for i, (_, k) in enumerate(NAV_ITEMS) if k == "applications")
        apps_view = self._content_stack.widget(apps_idx)
        apps_view.refresh()