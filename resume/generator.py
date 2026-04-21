"""
resume/generator.py
Two public entry points:
  generate_resume_pdf            — profile-only, toolbar Generate button
  generate_resume_pdf_for_app    — application-specific; reads the
                                   application's self-contained snapshot
                                   (or accepts an in-memory snapshot dict
                                   for the live-regen path from the wizard).
Both are synchronous and safe to run on a QThreadPool worker thread.
"""

from __future__ import annotations
import json
from pathlib import Path

from db.database import Database
from templates.templates import build_context, render_from_file
from pdf.convert import html_to_pdf_bytes_sync

TEMPLATES_DIR = Path(__file__).parent.parent / "templates" / "html"


# ── master-mode scoring (used only by profile-only toolbar generation) ─


def _kw_set(keywords: list[dict]) -> set[int]:
    return {kw["id"] for kw in keywords}


def _any_match(item_kw_ids: list[int], profile_kw_ids: set[int]) -> bool:
    return bool(set(item_kw_ids) & profile_kw_ids)


def _filter_bullets_by_keywords(
    bullets: list[dict],
    profile_kw_ids: set[int],
    min_bp: int,
    max_bp: int,
) -> list[dict]:
    matched = [b for b in bullets if _any_match(b["keyword_ids"], profile_kw_ids)]
    unmatched = [b for b in bullets if not _any_match(b["keyword_ids"], profile_kw_ids)]
    if len(matched) < min_bp:
        matched += unmatched[: min_bp - len(matched)]
    matched.sort(key=lambda b: b["sort_order"])
    return matched[:max_bp]


# ── assembly ─────────────────────────────────────────────────────────


def _assemble_from_snapshot(snapshot: dict) -> dict:
    """Build the Jinja context directly from an application snapshot.

    The snapshot already carries a fully-resolved, self-contained view of the
    resume — experiences/bullets are pre-filtered and ordered, keywords are
    denormalized, contact/websites/summary are materialized. No master-data
    merge happens here.
    """
    settings = snapshot.get("settings") or {}
    section_order_raw = snapshot.get("section_order")
    sections_enabled_raw = snapshot.get("sections_enabled")

    section_order = (
        json.loads(section_order_raw)
        if section_order_raw
        else json.loads(settings.get("section_order") or "[]")
    )
    sections_enabled_source = (
        json.loads(sections_enabled_raw)
        if sections_enabled_raw
        else json.loads(settings.get("sections_enabled") or "{}")
    )
    sections_enabled = {k: bool(v) for k, v in sections_enabled_source.items()}

    summary_text = snapshot.get("summary_text") or ""
    summary = {"text": summary_text} if summary_text else {}

    return build_context(
        contact=snapshot.get("contact") or {},
        websites=snapshot.get("websites") or [],
        summary=summary,
        experiences=snapshot.get("experiences") or [],
        education=snapshot.get("education") or [],
        languages=snapshot.get("languages") or [],
        projects=snapshot.get("projects") or [],
        keywords=snapshot.get("keywords") or [],
        section_order=section_order,
        sections_enabled=sections_enabled,
        template_settings=snapshot.get("template") or {},
        date_format=settings.get("date_format") or "YYYY",
    )


def _assemble_from_master(db: Database, profile_id: int) -> dict:
    """Build Jinja context from master data with keyword-based filtering.

    Used only by the toolbar Generate button (profile-only path).
    """
    data = db.get_resume_data(profile_id)
    profile_kw_ids = _kw_set(data["profile_keywords"])

    template = data["template"] or {}
    min_bp = template.get("min_bullet_points_per_job", 2)
    max_bp = template.get("max_bullet_points_per_job", 5)

    contact = data["contact"] or {}
    websites = data["websites"]

    summary_text = data["summary_text"] or ""
    summary = {"text": summary_text} if summary_text else {}

    experiences = []
    for job in data["experiences"]:
        bullets = _filter_bullets_by_keywords(
            job["bullet_points"], profile_kw_ids, min_bp, max_bp
        )
        experiences.append({**job, "bullet_points": bullets})

    projects = [
        p for p in data["projects"] if _any_match(p["keyword_ids"], profile_kw_ids)
    ]

    education = data["education"]
    languages = data["languages"]

    ps = data["profile_settings"]
    if ps and ps.get("section_order"):
        section_order = json.loads(ps["section_order"])
        sections_enabled = {
            k: bool(v) for k, v in json.loads(ps["sections_enabled"]).items()
        }
    else:
        section_order = json.loads(data["settings"]["section_order"])
        sections_enabled = {
            k: bool(v)
            for k, v in json.loads(data["settings"]["sections_enabled"]).items()
        }

    date_fmt = (data["settings"] or {}).get("date_format") or "YYYY"

    return build_context(
        contact=contact,
        websites=websites,
        summary=summary,
        experiences=experiences,
        education=education,
        languages=languages,
        projects=projects,
        keywords=data["profile_keywords"],
        section_order=section_order,
        sections_enabled=sections_enabled,
        template_settings=template,
        date_format=date_fmt,
    )


def _render(context: dict) -> bytes:
    html = render_from_file("default.html", context)
    base_url = TEMPLATES_DIR.as_uri() + "/"
    return html_to_pdf_bytes_sync(html, base_url=base_url)


# ── public API ────────────────────────────────────────────────────────


def generate_resume_pdf(db_path: Path, profile_id: int) -> bytes:
    """Profile-only generation. Used by the toolbar Generate button."""
    db = Database(db_path)
    db.connect()
    try:
        return _render(_assemble_from_master(db, profile_id))
    finally:
        db.close()


def generate_resume_pdf_for_app(
    db_path: Path,
    *,
    application_id: int | None = None,
    snapshot: dict | None = None,
) -> bytes:
    """Render an application's PDF.

    Exactly one of the keyword args must be provided:
      - `snapshot` — render directly from an in-memory snapshot (the wizard's
        live-regen path; a failed render never touches saved state).
      - `application_id` — load the application's snapshot from the DB.
    """
    if snapshot is not None:
        return _render(_assemble_from_snapshot(snapshot))
    if application_id is not None:
        db = Database(db_path)
        db.connect()
        try:
            return _render(
                _assemble_from_snapshot(db.get_application_snapshot(application_id))
            )
        finally:
            db.close()
    raise ValueError("Either application_id or snapshot must be provided")
