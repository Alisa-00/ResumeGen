"""
ui/wizard/wizard.py
Two-step application wizard.
Step 1: job details form.
Step 2: live resume editor + PDF preview.

The application is auto-saved to the DB when entering step 2.
The back button on step 2 closes the wizard entirely (goes to Applications view).
"""

from __future__ import annotations
import json
from datetime import date
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget, QStackedWidget, QVBoxLayout

from db.database import Database
from ui.wizard.step_details import StepDetails
from ui.wizard.step_preview import StepPreview


class WizardWidget(QWidget):
    closed = Signal()

    def __init__(self, db: Database, db_path: Path,
                 application_id: int | None = None, parent=None):
        super().__init__(parent)
        self.db             = db
        self.db_path        = db_path
        self.application_id = application_id

        self._stack = QStackedWidget()
        QVBoxLayout(self).addWidget(self._stack)
        self.layout().setContentsMargins(0, 0, 0, 0)

        existing = db.get_application(application_id) if application_id else None

        self._step1 = StepDetails(db, existing)
        self._step1.next_requested.connect(self._on_next)
        self._stack.addWidget(self._step1)

        # if reopening an existing application go straight to step 2
        if existing:
            job_data = {
                "company_name":  existing["company_name"],
                "position_name": existing["position_name"],
                "profile_id":    existing["profile_id"],
                "status_id":     existing["status_id"],
                "date_applied":  existing.get("date_applied", ""),
                "extra_kw_ids":  json.loads(existing.get("extra_keywords", "[]")),
            }
            self._build_step2(job_data)
            self._stack.setCurrentIndex(1)

    # ------------------------------------------------------------------

    def _on_next(self, job_data: dict):
        """Called from step 1. Auto-saves the application, then shows step 2."""
        statuses   = {s["status"]: s["id"] for s in self.db.get_statuses()}
        status_id  = statuses.get("to-apply", 1)

        self.application_id = self.db.upsert_application(
            profile_id    = job_data["profile_id"],
            status_id     = status_id,
            position_name = job_data["position_name"],
            company_name  = job_data["company_name"],
            date_applied  = job_data.get("date_applied") or date.today().strftime("%Y-%m-%d"),
            extra_keywords= json.dumps(job_data.get("extra_kw_ids", [])),
            id            = self.application_id,
        )
        job_data["status_id"] = status_id

        self._build_step2(job_data)
        self._stack.setCurrentIndex(1)

    def _build_step2(self, job_data: dict):
        if self._stack.count() > 1:
            old = self._stack.widget(1)
            self._stack.removeWidget(old)
            old.deleteLater()

        step2 = StepPreview(
            db             = self.db,
            db_path        = self.db_path,
            job_data       = job_data,
            application_id = self.application_id,
        )
        step2.back_requested.connect(self.closed)
        step2.saved.connect(self._on_saved)
        self._stack.addWidget(step2)

    def _on_saved(self, application_id: int):
        self.application_id = application_id