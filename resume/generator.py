"""
resume/generator.py
Two public entry points:
  generate_resume_pdf            — profile-only, toolbar Generate button
  generate_resume_pdf_for_app    — application-specific, all overrides
Both are synchronous and safe to run on a QThreadPool worker thread.
"""

from __future__ import annotations
import json
from pathlib import Path

from db.database import Database
from templates.templates import build_context, render_from_file
from pdf.convert import html_to_pdf_bytes_sync

TEMPLATES_DIR = Path(__file__).parent.parent / "templates" / "html"


# ── scoring ──────────────────────────────────────────────────────────

def _kw_set(keywords: list[dict]) -> set[int]:
    return {kw["id"] for kw in keywords}


def _any_match(item_kw_ids: list[int], profile_kw_ids: set[int]) -> bool:
    return bool(set(item_kw_ids) & profile_kw_ids)


def _filter_bullets_by_keywords(
    bullets: list[dict],
    profile_kw_ids: set[int],
    min_bp: int,
    max_bp: int,
    overrides: dict[int, str] | None = None,
) -> list[dict]:
    """Used for profile-only generation — keyword-based filtering."""
    overrides = overrides or {}
    bullets   = [{**b, "text": overrides.get(b["id"], b["text"])} for b in bullets]
    matched   = [b for b in bullets if _any_match(b["keyword_ids"], profile_kw_ids)]
    unmatched = [b for b in bullets if not _any_match(b["keyword_ids"], profile_kw_ids)]
    if len(matched) < min_bp:
        matched += unmatched[:min_bp - len(matched)]
    matched.sort(key=lambda b: b["sort_order"])
    return matched[:max_bp]


def _apply_bullets_explicit(
    bullets: list[dict],
    included_ids: list[int],
    overrides: dict[int, str] | None = None,
) -> list[dict]:
    """
    Used for application generation — respect explicit inclusion list
    and order from the wizard, applying text overrides.
    """
    overrides = overrides or {}
    id_map    = {b["id"]: b for b in bullets}
    result    = []
    for bid in included_ids:
        if bid in id_map:
            b = id_map[bid]
            result.append({**b, "text": overrides.get(bid, b["text"])})
    return result


# ── assembly ─────────────────────────────────────────────────────────

def _assemble(
    db: Database,
    profile_id: int,
    explicit_keyword_ids: list[int] | None = None,
    extra_kw_ids: list[int] | None = None,
    section_order_override: list[str] | None = None,
    sections_enabled_override: dict[str, bool] | None = None,
    bullet_overrides: dict[int, str] | None = None,
    included_bullets_map: dict[int, list[int]] | None = None,
    included_experience_ids: list[int] | None = None,
    included_education_ids: list[int] | None = None,
    included_project_ids: list[int] | None = None,
    education_overrides: dict[int, dict] | None = None,
    project_text_overrides: dict[int, str] | None = None,
    project_name_overrides: dict[int, str] | None = None,
    contact_override: dict | None = None,
    websites_override: list[dict] | None = None,
    summary_text_override: str | None = None,
) -> dict:
    data     = db.get_resume_data(profile_id)
    base_kws = data["profile_keywords"]

    if explicit_keyword_ids is not None:
        kw_map  = {kw["id"]: kw for kw in db.get_keywords()}
        all_kws = [kw_map[i] for i in explicit_keyword_ids if i in kw_map]
    else:
        extra_kws: list[dict] = []
        if extra_kw_ids:
            for kw in db.get_keywords():
                if kw["id"] in extra_kw_ids:
                    extra_kws.append(kw)
        all_kws = base_kws + extra_kws

    profile_kw_ids = _kw_set(all_kws)

    template = data["template"] or {}
    min_bp   = template.get("min_bullet_points_per_job", 2)
    max_bp   = template.get("max_bullet_points_per_job", 5)

    # contact
    contact  = {**(data["contact"] or {}), **(contact_override or {})}
    websites = websites_override if websites_override is not None else data["websites"]

    # summary — always use what the editor provides
    summary_text = summary_text_override or ""
    summary = {"text": summary_text} if summary_text else {}

    # experiences
    exp_pool = data["experiences"]
    if included_experience_ids is not None:
        id_order = {eid: i for i, eid in enumerate(included_experience_ids)}
        exp_pool = sorted(
            [e for e in exp_pool if e["id"] in id_order],
            key=lambda e: id_order[e["id"]]
        )

    experiences = []
    for job in exp_pool:
        if included_bullets_map is not None and job["id"] in included_bullets_map:
            bullets = _apply_bullets_explicit(
                job["bullet_points"],
                included_bullets_map[job["id"]],
                bullet_overrides,
            )
        else:
            bullets = _filter_bullets_by_keywords(
                job["bullet_points"], profile_kw_ids, min_bp, max_bp, bullet_overrides
            )
        experiences.append({**job, "bullet_points": bullets})

    # projects
    prj_pool = data["projects"]
    if included_project_ids is not None:
        id_order = {pid: i for i, pid in enumerate(included_project_ids)}
        projects = sorted(
            [p for p in prj_pool if p["id"] in id_order],
            key=lambda p: id_order[p["id"]]
        )
    else:
        projects = [p for p in prj_pool if _any_match(p["keyword_ids"], profile_kw_ids)]

    # apply per-project text and name overrides from the editor
    if project_text_overrides or project_name_overrides:
        def _apply(p):
            out = dict(p)
            if project_text_overrides and p["id"] in project_text_overrides:
                out["text"] = project_text_overrides[p["id"]]
            if project_name_overrides and p["id"] in project_name_overrides:
                out["name"] = project_name_overrides[p["id"]]
            return out
        projects = [_apply(p) for p in projects]

    # education
    education = data["education"]
    if included_education_ids is not None:
        id_order  = {eid: i for i, eid in enumerate(included_education_ids)}
        education = sorted(
            [e for e in education if e["id"] in id_order],
            key=lambda e: id_order[e["id"]]
        )

    # apply education overrides from the editor
    if education_overrides:
        def _apply_edu(e):
            ov = education_overrides.get(e["id"])
            return {**e, **ov} if ov else e
        education = [_apply_edu(e) for e in education]

    # section order + enabled
    ps = data["profile_settings"]
    if section_order_override is not None:
        section_order    = section_order_override
        sections_enabled = sections_enabled_override or {}
    elif ps and ps.get("section_order"):
        section_order    = json.loads(ps["section_order"])
        sections_enabled = {k: bool(v) for k, v in json.loads(ps["sections_enabled"]).items()}
    else:
        section_order    = json.loads(data["settings"]["section_order"])
        sections_enabled = {
            k: bool(v)
            for k, v in json.loads(data["settings"]["sections_enabled"]).items()
        }

    return build_context(
        contact           = contact,
        websites          = websites,
        summary           = summary,
        experiences       = experiences,
        education         = education,
        projects          = projects,
        keywords          = all_kws,
        section_order     = section_order,
        sections_enabled  = sections_enabled,
        template_settings = template,
        date_format       = "MMM YYYY",
    )


def _render(context: dict) -> bytes:
    html     = render_from_file("default.html", context)
    base_url = TEMPLATES_DIR.as_uri() + "/"
    return html_to_pdf_bytes_sync(html, base_url=base_url)


# ── public API ────────────────────────────────────────────────────────

def generate_resume_pdf(db_path: Path, profile_id: int) -> bytes:
    """Profile-only generation. Used by the toolbar Generate button."""
    db = Database(db_path)
    db.connect()
    try:
        return _render(_assemble(db, profile_id))
    finally:
        db.close()


def generate_resume_pdf_for_app(
    db_path: Path,
    profile_id: int,
    explicit_keyword_ids: list[int],
    section_order: list[str],
    sections_enabled: dict[str, bool],
    bullet_overrides: dict[int, str],
    included_bullets_map: dict[int, list[int]],
    included_experience_ids: list[int] | None = None,
    included_education_ids: list[int] | None = None,
    included_project_ids: list[int] | None = None,
    education_overrides: dict[int, dict] | None = None,
    project_text_overrides: dict[int, str] | None = None,
    project_name_overrides: dict[int, str] | None = None,
    contact_override: dict | None = None,
    websites_override: list[dict] | None = None,
    summary_text_override: str | None = None,
) -> bytes:
    """Application-specific generation with all per-application overrides."""
    db = Database(db_path)
    db.connect()
    try:
        return _render(_assemble(
            db, profile_id,
            explicit_keyword_ids      = explicit_keyword_ids,
            section_order_override    = section_order,
            sections_enabled_override = sections_enabled,
            bullet_overrides          = bullet_overrides,
            included_bullets_map      = included_bullets_map,
            included_experience_ids   = included_experience_ids,
            included_education_ids    = included_education_ids,
            included_project_ids      = included_project_ids,
            education_overrides       = education_overrides,
            project_text_overrides    = project_text_overrides,
            project_name_overrides    = project_name_overrides,
            contact_override          = contact_override,
            websites_override         = websites_override,
            summary_text_override     = summary_text_override,
        ))
    finally:
        db.close()