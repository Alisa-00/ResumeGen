"""
ui/ui.py
Main window. Manages the primary nav stack and wizard overlay.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, QThreadPool, QRunnable, Signal, QObject
from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QListWidget,
    QListWidgetItem,
    QStackedWidget,
    QMessageBox,
)

from db.database import Database
from ui.views.contact import ContactView
from ui.views.experience import ExperienceView
from ui.views.education import EducationView
from ui.views.projects import ProjectsView
from ui.views.keywords import KeywordsView
from ui.views.languages import LanguagesView
from ui.views.profiles import ProfilesView
from ui.views.templates import TemplatesView
from ui.views.settings import SettingsView
from ui.views.applications import ApplicationsView
from ui.widgets import PlaceholderView, primary_btn

_log = logging.getLogger(__name__)


NAV_ITEMS: list[tuple[str, str]] = [
    ("Contact", "contact"),
    ("Summary", "profiles"),
    ("Experience", "experience"),
    ("Education", "education"),
    ("Languages", "languages"),
    ("Projects", "projects"),
    ("Keywords", "keywords"),
    ("Templates", "templates"),
    ("Applications", "applications"),
    ("Settings", "settings"),
]


def _build_view(key: str, db: Database, window: "AppWindow") -> QWidget:
    return {
        "contact": lambda: ContactView(db),
        "experience": lambda: ExperienceView(db),
        "education": lambda: EducationView(db),
        "languages": lambda: LanguagesView(db),
        "projects": lambda: ProjectsView(db),
        "keywords": lambda: KeywordsView(db),
        "profiles": lambda: ProfilesView(db),
        "templates": lambda: TemplatesView(db),
        "applications": lambda: ApplicationsView(db),
        "settings": lambda: SettingsView(db, window=window),
    }.get(key, lambda: PlaceholderView(key))()


# ── worker thread helper ─────────────────────────────────────────────


class _Signals(QObject):
    finished = Signal(object)
    error = Signal(str)


class _Task(QRunnable):
    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = _Signals()

    def run(self):
        try:
            self.signals.finished.emit(self.fn(*self.args, **self.kwargs))
        except Exception as e:
            _log.exception("background task failed")  # keep the full traceback
            self.signals.error.emit(str(e))


# ── main window ──────────────────────────────────────────────────────


class AppWindow(QMainWindow):
    def __init__(self, db: Database, engine=None, parent=None):
        super().__init__(parent)
        self.db = db
        self.engine = engine
        self._wizard_widget = None
        self._tasks: list[_Task] = []  # keep refs so QRunnables aren't GC'd
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
            QListWidget { background: #181825; border: none; border-right: 1px solid #45475a; }
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
        self._populate_views()

        np_l.addWidget(self._content_stack)

        self._wizard_placeholder = QWidget()

        self._main_stack.addWidget(self._normal_page)
        self._main_stack.addWidget(self._wizard_placeholder)

        root_l.addWidget(self._nav)
        root_l.addWidget(self._main_stack, 1)

        self._nav.setCurrentRow(0)

    def _populate_views(self):
        """(Re)build the content stack against the live db connection."""
        while self._content_stack.count():
            w = self._content_stack.widget(0)
            self._content_stack.removeWidget(w)
            w.deleteLater()

        for _, key in NAV_ITEMS:
            self._content_stack.addWidget(_build_view(key, self.db, self))

        apps_idx = next(i for i, (_, k) in enumerate(NAV_ITEMS) if k == "applications")
        apps_view = self._content_stack.widget(apps_idx)
        apps_view.new_application_requested.connect(lambda: self._open_wizard(None))
        apps_view.open_application_requested.connect(self._open_wizard)

    def reload_views(self):
        """Rebuild views after the underlying db file has been swapped by a sync."""
        current = self._content_stack.currentIndex()
        self._populate_views()
        self._content_stack.setCurrentIndex(max(0, current))

    # ── background sync ───────────────────────────────────────────────

    def _submit(self, fn, on_done=None, on_error=None):
        """Run ``fn`` on the thread pool, delivering results back on the UI thread."""
        task = _Task(fn)
        if on_done:
            task.signals.finished.connect(on_done)
        task.signals.error.connect(on_error or (lambda msg: print(f"[SYNC] {msg}")))
        task.signals.finished.connect(lambda *_: self._tasks.remove(task))
        task.signals.error.connect(lambda *_: self._tasks.remove(task))
        self._tasks.append(task)
        QThreadPool.globalInstance().start(task)

    def start_initial_sync(self):
        """Best-effort pull on launch. Silent on failure — local use never blocks."""
        if not (self.engine and self.engine.available()):
            return
        self._submit(self.engine.pull_fetch, on_done=self._apply_pull)

    def sync_now(self, on_status=None):
        """Manual sync: push then pull. ``on_status`` (optional) gets a result string."""
        if not (self.engine and self.engine.available()):
            if on_status:
                on_status("Sync is not configured.")
            return

        def work():
            if self.engine.cfg.last_synced_seq == 0:
                # Never synced: look at the server BEFORE pushing, so existing
                # history triggers the first-sync choice instead of being
                # buried under a stale upload.
                fetched = self.engine.pull_fetch()
                if fetched:
                    return None, fetched  # push decision deferred to the dialog
                return self.engine.push(), None  # server empty — normal bootstrap
            pushed = self.engine.push()
            return pushed, self.engine.pull_fetch()

        def done(result):
            pushed, fetched = result
            self._apply_pull(fetched)
            if on_status:
                if pushed is None:
                    on_status("First sync complete.")
                    return
                bits = []
                bits.append("pushed local changes" if pushed else "nothing to push")
                bits.append("pulled update" if fetched else "no remote update")
                on_status("Sync complete: " + ", ".join(bits) + ".")

        def failed(msg):
            if on_status:
                on_status(f"Sync failed: {msg}")
            else:
                print(f"[SYNC] {msg}")

        self._submit(work, on_done=done, on_error=failed)

    def _apply_pull(self, fetched):
        """UI-thread application of a fetched snapshot (db file swap + reload)."""
        if not fetched:
            print("[SYNC] pull: no newer snapshot on server")
            return
        if self._wizard_widget is not None:
            # Never swap the DB out from under an open wizard with unsaved edits;
            # skip this apply — the next sync trigger will re-fetch and apply.
            print("[SYNC] pull: wizard open, deferring snapshot apply")
            return
        meta, db_bytes = fetched

        if self.engine.cfg.last_synced_seq == 0:
            # First-ever sync on this machine and the server already has
            # history — let the user pick a winner instead of guessing.
            box = QMessageBox(self)
            box.setWindowTitle("Sync — first connection")
            box.setText(
                f"The sync server already has data (snapshot seq {meta.seq}).\n\n"
                "Download it and replace this machine's data (the local database "
                "is backed up first), or keep this machine's data and upload it "
                "to the server?"
            )
            download = box.addButton("Download server copy", QMessageBox.ButtonRole.AcceptRole)
            box.addButton("Keep local and upload", QMessageBox.ButtonRole.RejectRole)
            box.setDefaultButton(download)
            box.exec()
            if box.clickedButton() is not download:
                print("[SYNC] first sync: keeping local data, uploading")
                self._submit(
                    lambda: self.engine.push(first_sync_ok=True),
                    on_done=lambda pushed: print(
                        "[SYNC] first sync: uploaded local data"
                        if pushed else "[SYNC] first sync: nothing to upload"
                    ),
                )
                return

        self.engine.pull_apply(meta, db_bytes, on_applied=self.reload_views)
        print(f"[SYNC] adopted server snapshot seq {meta.seq}")

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
            db=self.db,
            db_path=self.db.db_path,
            application_id=application_id,
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
