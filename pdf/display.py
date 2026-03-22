"""
pdf/display.py
PySide6 widget that embeds a PDF viewer via QPdfView.
Accepts raw PDF bytes and renders them in-process — no external viewer.
"""

from __future__ import annotations
import tempfile
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtPdf import QPdfDocument
from PySide6.QtPdfWidgets import QPdfView
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel


class PdfPreviewWidget(QWidget):
    """
    Drop-in widget that displays a PDF.
    Call load_bytes() or load_file() to update the preview.
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._doc = QPdfDocument(self)
        self._view = QPdfView(self)
        self._view.setDocument(self._doc)
        self._view.setPageMode(QPdfView.PageMode.MultiPage)
        self._view.setZoomMode(QPdfView.ZoomMode.FitToWidth)

        self._placeholder = QLabel("No preview yet.\nGenerate a resume to see it here.")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setStyleSheet("color: grey; font-size: 14px;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._placeholder)
        layout.addWidget(self._view)

        self._view.hide()
        self._tmp: Path | None = None

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def load_bytes(self, pdf_bytes: bytes) -> None:
        """Write bytes to a temp file and display it."""
        if self._tmp is None:
            tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
            self._tmp = Path(tmp.name)
            tmp.close()
        self._tmp.write_bytes(pdf_bytes)
        self._load_path(self._tmp)

    def load_file(self, path: Path) -> None:
        self._load_path(path)

    def clear(self) -> None:
        self._doc.close()
        self._view.hide()
        self._placeholder.show()

    # ------------------------------------------------------------------
    # internal
    # ------------------------------------------------------------------

    def _load_path(self, path: Path) -> None:
        self._doc.close()
        err = self._doc.load(str(path))
        if err == QPdfDocument.Error.None_:
            self._placeholder.hide()
            self._view.show()
        else:
            self._placeholder.setText(f"Failed to load PDF (error {err})")
            self._view.hide()
            self._placeholder.show()

    def closeEvent(self, event):
        self._doc.close()
        if self._tmp and self._tmp.exists():
            self._tmp.unlink(missing_ok=True)
        super().closeEvent(event)
