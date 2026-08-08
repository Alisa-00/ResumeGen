"""
pdf/convert.py
HTML → PDF via WeasyPrint.

  html_to_pdf_bytes_sync — blocking, call from a worker thread
"""

from __future__ import annotations

from weasyprint import HTML


def html_to_pdf_bytes_sync(html: str, base_url: str | None = None) -> bytes:
    """Blocking WeasyPrint call. Safe to call from any worker thread."""
    return HTML(string=html, base_url=base_url).write_pdf()
