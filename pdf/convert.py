"""
pdf/convert.py
HTML → PDF via WeasyPrint.

Two entry points:
  html_to_pdf_bytes_sync  — blocking, call from a worker thread
  html_to_pdf_bytes       — async wrapper, for use in async contexts
"""

from __future__ import annotations
import asyncio
from concurrent.futures import ThreadPoolExecutor

from weasyprint import HTML

_executor = ThreadPoolExecutor(max_workers=2)


def html_to_pdf_bytes_sync(html: str, base_url: str | None = None) -> bytes:
    """Blocking WeasyPrint call. Safe to call from any worker thread."""
    return HTML(string=html, base_url=base_url).write_pdf()


async def html_to_pdf_bytes(html: str, base_url: str | None = None) -> bytes:
    """Async wrapper — runs WeasyPrint in a thread pool."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        _executor, html_to_pdf_bytes_sync, html, base_url
    )