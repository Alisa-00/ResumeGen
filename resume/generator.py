"""
resume/generator.py
Renders application snapshots to PDF.

Public entry point:
  render_pdf_from_snapshot(snapshot)
      — pure function; takes a full snapshot dict and returns PDF bytes.
        Reads no DB. Safe to call from any worker thread.
"""

from __future__ import annotations
from pathlib import Path

from templates.templates import build_context, render_from_file
from pdf.convert import html_to_pdf_bytes_sync

TEMPLATES_DIR = Path(__file__).parent.parent / "templates" / "html"


# ── public ───────────────────────────────────────────────────────────


def _context_from_live(live: dict) -> dict:
    """Map the snapshot's `live` sub-tree to the Jinja template context.

    The template expects fields named exactly as in build_context(); for
    historical reasons the section key is `experience` (singular) but the
    template variable is `experiences`."""
    template = live.get("template") or {}
    contact_full = live.get("contact") or {}
    contact = {k: v for k, v in contact_full.items() if k != "websites"}
    websites = contact_full.get("websites") or []
    return build_context(
        contact=contact,
        websites=websites,
        summary=live.get("summary") or {},
        experiences=_remap_experience_bullets(live.get("experience") or []),
        education=live.get("education") or [],
        languages=live.get("languages") or [],
        projects=live.get("projects") or [],
        keywords=live.get("keywords") or [],
        section_order=live.get("section_order") or [],
        sections_enabled=live.get("sections_enabled") or {},
        template_settings=template,
        date_format=live.get("date_format") or "YYYY",
    )


def _remap_experience_bullets(experiences: list[dict]) -> list[dict]:
    """The template iterates `job.bullet_points`; the snapshot stores `bullets`."""
    out = []
    for exp in experiences:
        item = dict(exp)
        item["bullet_points"] = exp.get("bullets") or []
        out.append(item)
    return out


def render_pdf_from_snapshot(snapshot: dict) -> bytes:
    """Render a snapshot to PDF bytes. Pure — does not touch the DB."""
    context = _context_from_live(snapshot["live"])
    html = render_from_file("default.html", context)
    base_url = TEMPLATES_DIR.as_uri() + "/"
    return html_to_pdf_bytes_sync(html, base_url=base_url)


