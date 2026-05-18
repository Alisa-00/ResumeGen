"""
resume/snapshot.py
Snapshot data model for job applications.

A snapshot is the self-contained document representation of an application:

    {
      "version": 1,
      "live":     { ... the editable, rendered document ... },
      "original": { ... immutable master snapshot at creation time ... }
    }

The renderer consumes only `live`. `original` exists so the editor can offer
"Reset to original" and "Add from master" affordances without reading the
master DB at edit/render time.

Two entry points:
  build_snapshot_from_profile  — used at application creation
  legacy_to_snapshot           — used at migration time to backfill existing
                                 applications from the old delta-based columns
"""

from __future__ import annotations

import json
from datetime import datetime

from db.database import Database


SCHEMA_VERSION = 1


# ── keyword helpers (moved from resume/generator.py) ─────────────────


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
    """Used for legacy backfill when an application predates included_bullets."""
    overrides = overrides or {}
    bullets = [{**b, "text": overrides.get(b["id"], b["text"])} for b in bullets]
    matched = [b for b in bullets if _any_match(b["keyword_ids"], profile_kw_ids)]
    unmatched = [
        b for b in bullets if not _any_match(b["keyword_ids"], profile_kw_ids)
    ]
    if len(matched) < min_bp:
        matched += unmatched[: min_bp - len(matched)]
    matched.sort(key=lambda b: b["sort_order"])
    return matched[:max_bp]


# ── shape helpers ────────────────────────────────────────────────────


def _template_to_live(template: dict | None) -> dict:
    t = template or {}
    return {
        "font_family":  t.get("font_family",  "Arial"),
        "font_size":    t.get("font_size",    11.0),
        "margin_top":   t.get("margin_top",   8.0),
        "margin_bottom":t.get("margin_bottom",8.0),
        "margin_left":  t.get("margin_left",  8.0),
        "margin_right": t.get("margin_right", 8.0),
        "min_bullet_points_per_job": t.get("min_bullet_points_per_job", 2),
        "max_bullet_points_per_job": t.get("max_bullet_points_per_job", 5),
    }


def _experience_to_live(exp: dict, bullets: list[dict]) -> dict:
    """Pack a master experience row + chosen bullets into the live shape."""
    return {
        "source_id":                exp["id"],
        "organization_name":        exp.get("organization_name") or "",
        "position_name":            exp.get("position_name") or "",
        "organization_description": exp.get("organization_description") or "",
        "organization_website":     exp.get("organization_website") or "",
        "location":                 exp.get("location") or "",
        "is_ongoing":               bool(exp.get("is_ongoing")),
        "start_date":               exp.get("start_date") or "",
        "end_date":                 exp.get("end_date") or "",
        "bullets": [
            {"source_id": b["id"], "text": b["text"]}
            for b in bullets
        ],
    }


def _education_to_live(edu: dict) -> dict:
    return {
        "source_id":  edu["id"],
        "degree":     edu.get("degree") or "",
        "school":     edu.get("school") or "",
        "school_url": edu.get("school_url") or "",
        "location":   edu.get("location") or "",
        "field":      edu.get("field") or "",
        "gpa":        edu.get("gpa") or "",
        "is_ongoing": bool(edu.get("is_ongoing")),
        "start_date": edu.get("start_date") or "",
        "end_date":   edu.get("end_date") or "",
    }


def _language_to_live(lang: dict) -> dict:
    return {
        "source_id":         lang["id"],
        "name":              lang.get("name") or "",
        "proficiency_level": lang.get("proficiency_level") or "",
    }


def _project_to_live(proj: dict) -> dict:
    return {
        "source_id":  proj["id"],
        "name":       proj.get("name") or "",
        "link":       proj.get("link") or "",
        "start_date": proj.get("start_date") or "",
        "end_date":   proj.get("end_date") or "",
        "is_ongoing": bool(proj.get("is_ongoing")),
        "text":       proj.get("text") or "",
    }


def _keyword_to_live(kw: dict) -> dict:
    return {"source_id": kw["id"], "name": kw.get("name") or ""}


# ── original-half builder ────────────────────────────────────────────


def _build_original(db: Database, profile_id: int | None, data: dict) -> dict:
    """Capture a verbatim copy of master state at this moment."""
    # profile_summaries: all profiles that have a summary set
    profile_summaries = []
    for p in db.get_profiles():
        summary = (p.get("summary") or "").strip()
        if summary:
            profile_summaries.append(
                {"id": p["id"], "name": p["name"], "summary": summary}
            )

    settings = data.get("settings") or {}
    return {
        "captured_at": datetime.utcnow().isoformat(timespec="seconds"),
        "profile_id":  profile_id,
        "contact":     data.get("contact") or {},
        "websites":    data.get("websites") or [],
        "profile_summaries": profile_summaries,
        "experiences": data.get("experiences") or [],
        "education":   data.get("education") or [],
        "languages":   data.get("languages") or [],
        "projects":    data.get("projects") or [],
        "keywords":    db.get_keywords(),
        "template":    data.get("template") or {},
        "settings": {
            "section_order":    settings.get("section_order"),
            "sections_enabled": settings.get("sections_enabled"),
            "date_format":      settings.get("date_format") or "YYYY",
        },
    }


# ── section_order / sections_enabled resolution ──────────────────────


def _resolve_section_defaults(data: dict) -> tuple[list[str], dict[str, bool]]:
    """Mirror the precedence used in step_preview._populate_sections:
    profile_settings > app_settings."""
    ps = data.get("profile_settings")
    if ps and ps.get("section_order"):
        order = json.loads(ps["section_order"])
        enabled = {
            k: bool(v) for k, v in json.loads(ps["sections_enabled"]).items()
        }
        return order, enabled
    settings = data.get("settings") or {}
    order = (
        json.loads(settings["section_order"])
        if settings.get("section_order")
        else ["contact", "summary", "experience", "education",
              "languages", "projects", "keywords"]
    )
    enabled_raw = (
        json.loads(settings["sections_enabled"])
        if settings.get("sections_enabled")
        else {k: 1 for k in order}
    )
    enabled = {k: bool(v) for k, v in enabled_raw.items()}
    return order, enabled


# ── public: build snapshot from a profile (new application) ──────────


def build_snapshot_from_profile(
    db: Database,
    profile_id: int,
    extra_keyword_ids: list[int] | None = None,
) -> dict:
    """Freeze the current master state into a fresh snapshot for a new
    application. The editor will then mutate the `live` half."""
    data = db.get_resume_data(profile_id)
    extra_ids = list(extra_keyword_ids or [])

    # keywords: profile keywords + extras (dedup, preserve order)
    seen: set[int] = set()
    kw_live: list[dict] = []
    for kw in (data.get("profile_keywords") or []):
        if kw["id"] not in seen:
            seen.add(kw["id"])
            kw_live.append(_keyword_to_live(kw))
    if extra_ids:
        kw_map = {k["id"]: k for k in db.get_keywords()}
        for kid in extra_ids:
            if kid in seen:
                continue
            kw = kw_map.get(kid)
            if kw:
                seen.add(kid)
                kw_live.append(_keyword_to_live(kw))

    # experiences — include all, with every bullet
    experiences_live = [
        _experience_to_live(exp, exp.get("bullet_points") or [])
        for exp in (data.get("experiences") or [])
    ]

    education_live = [_education_to_live(e) for e in (data.get("education") or [])]
    languages_live = [_language_to_live(l) for l in (data.get("languages") or [])]
    projects_live  = [_project_to_live(p)  for p in (data.get("projects")  or [])]

    # summary text: current profile's summary by default
    profile_row = db.fetch_one("SELECT * FROM profile WHERE id=?", (profile_id,))
    summary_text = ((profile_row or {}).get("summary") or "").strip()

    section_order, sections_enabled = _resolve_section_defaults(data)
    date_format = (data.get("settings") or {}).get("date_format") or "YYYY"

    contact = dict(data.get("contact") or {})
    contact.pop("id", None)
    websites = [
        {"source_id": w["id"], "label": w.get("label", ""), "url": w.get("url", "")}
        for w in (data.get("websites") or [])
    ]
    contact["websites"] = websites

    live = {
        "section_order":    section_order,
        "sections_enabled": sections_enabled,
        "contact":          contact,
        "summary":          {"text": summary_text, "source_profile_id": profile_id},
        "experience":       experiences_live,
        "education":        education_live,
        "languages":        languages_live,
        "projects":         projects_live,
        "keywords":         kw_live,
        "template":         _template_to_live(data.get("template")),
        "date_format":      date_format,
    }

    return {
        "version":  SCHEMA_VERSION,
        "live":     live,
        "original": _build_original(db, profile_id, data),
    }


# ── public: legacy migration (existing rows) ─────────────────────────


def _parse_json(value, default):
    if value is None or value == "":
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def legacy_to_snapshot(db: Database, app_row: dict) -> dict:
    """Reconstruct a snapshot from an existing job_application row's
    delta columns + application_bullet_override table.

    Reproduces the same data the legacy renderer would have used."""
    profile_id = app_row.get("profile_id")

    # If the application's profile was deleted, we still want to produce
    # *something*. Pick the first profile (or None) so get_resume_data works.
    effective_profile_id = profile_id
    if effective_profile_id is None:
        profiles = db.get_profiles()
        effective_profile_id = profiles[0]["id"] if profiles else None

    if effective_profile_id is not None:
        data = db.get_resume_data(effective_profile_id)
    else:
        data = {
            "contact": None, "websites": [], "summary_text": "",
            "experiences": [], "education": [], "languages": [],
            "projects": [], "profile_keywords": [], "settings": db.get_settings(),
            "profile_settings": None, "template": None,
        }

    bullet_overrides = db.get_bullet_overrides(app_row["id"]) if app_row.get("id") else {}

    # ── parse override columns ──
    contact_override   = _parse_json(app_row.get("contact_override"),   None)
    websites_override  = _parse_json(app_row.get("websites_override"),  None)
    exp_overrides      = _parse_json(app_row.get("experience_overrides"), {})
    edu_overrides      = _parse_json(app_row.get("education_overrides"),  {})
    inc_exp            = _parse_json(app_row.get("included_experiences"), None)
    inc_edu            = _parse_json(app_row.get("included_education"),   None)
    inc_prj            = _parse_json(app_row.get("included_projects"),    None)
    inc_lang           = _parse_json(app_row.get("included_languages"),   None)
    inc_bullets_raw    = _parse_json(app_row.get("included_bullets"),     None)
    inc_bullets: dict[int, list[int]] | None = (
        {int(k): v for k, v in inc_bullets_raw.items()}
        if isinstance(inc_bullets_raw, dict)
        else None
    )
    extra_keywords     = _parse_json(app_row.get("extra_keywords"),       [])
    keyword_list       = _parse_json(app_row.get("keyword_list"),         None)
    summary_text       = app_row.get("summary_text_override")
    selected_summary_id = app_row.get("selected_summary_id")

    # ── section order / enabled ──
    if app_row.get("section_order"):
        section_order = json.loads(app_row["section_order"])
        sections_enabled = {
            k: bool(v) for k, v in json.loads(app_row["sections_enabled"]).items()
        }
    else:
        section_order, sections_enabled = _resolve_section_defaults(data)

    # ── contact ──
    base_contact = dict(data.get("contact") or {})
    base_contact.pop("id", None)
    if contact_override is not None:
        contact = {**base_contact, **contact_override}
    else:
        contact = base_contact

    if websites_override is not None:
        # websites_override entries are dicts with label/url (and maybe source_id)
        websites = [
            {
                "source_id": w.get("source_id") or w.get("id"),
                "label":     w.get("label", ""),
                "url":       w.get("url", ""),
            }
            for w in websites_override
        ]
    else:
        websites = [
            {"source_id": w["id"], "label": w.get("label", ""), "url": w.get("url", "")}
            for w in (data.get("websites") or [])
        ]
    contact["websites"] = websites

    # ── summary ──
    if summary_text is None:
        # fall back to the current profile's summary text
        prof_row = (
            db.fetch_one("SELECT summary FROM profile WHERE id=?", (effective_profile_id,))
            if effective_profile_id else None
        )
        summary_text = (prof_row or {}).get("summary") or ""
    summary_live = {
        "text": summary_text,
        "source_profile_id": selected_summary_id or effective_profile_id,
    }

    # ── experiences ──
    template = data.get("template") or {}
    min_bp = template.get("min_bullet_points_per_job", 2)
    max_bp = template.get("max_bullet_points_per_job", 5)
    profile_kw_ids = _kw_set(data.get("profile_keywords") or [])

    exp_pool = data.get("experiences") or []
    if inc_exp is not None:
        order_map = {eid: i for i, eid in enumerate(inc_exp)}
        exp_pool_ordered = sorted(
            [e for e in exp_pool if e["id"] in order_map],
            key=lambda e: order_map[e["id"]],
        )
    else:
        exp_pool_ordered = exp_pool

    experiences_live: list[dict] = []
    for job in exp_pool_ordered:
        # determine the bullet list to keep
        if inc_bullets is not None and job["id"] in inc_bullets:
            id_order = {bid: i for i, bid in enumerate(inc_bullets[job["id"]])}
            id_map = {b["id"]: b for b in job.get("bullet_points") or []}
            chosen = []
            for bid in inc_bullets[job["id"]]:
                if bid in id_map:
                    b = id_map[bid]
                    chosen.append(
                        {**b, "text": bullet_overrides.get(bid, b["text"])}
                    )
            bullets = chosen
        else:
            # legacy: keyword-filter
            bullets = _filter_bullets_by_keywords(
                job.get("bullet_points") or [],
                profile_kw_ids, min_bp, max_bp, bullet_overrides,
            )
        live_exp = _experience_to_live(job, bullets)
        # apply experience override fields
        eo = (exp_overrides or {}).get(str(job["id"])) or (exp_overrides or {}).get(job["id"])
        if eo:
            for k, v in eo.items():
                live_exp[k] = v
        experiences_live.append(live_exp)

    # ── education ──
    edu_pool = data.get("education") or []
    if inc_edu is not None:
        order_map = {eid: i for i, eid in enumerate(inc_edu)}
        edu_ordered = sorted(
            [e for e in edu_pool if e["id"] in order_map],
            key=lambda e: order_map[e["id"]],
        )
    else:
        edu_ordered = edu_pool

    education_live: list[dict] = []
    for edu in edu_ordered:
        live_edu = _education_to_live(edu)
        eo = (edu_overrides or {}).get(str(edu["id"])) or (edu_overrides or {}).get(edu["id"])
        if eo:
            for k, v in eo.items():
                live_edu[k] = v
        education_live.append(live_edu)

    # ── projects ──
    prj_pool = data.get("projects") or []
    if inc_prj is not None:
        order_map = {pid: i for i, pid in enumerate(inc_prj)}
        prj_ordered = sorted(
            [p for p in prj_pool if p["id"] in order_map],
            key=lambda p: order_map[p["id"]],
        )
    else:
        # legacy default: keyword-filter
        prj_ordered = [
            p for p in prj_pool if _any_match(p.get("keyword_ids") or [], profile_kw_ids)
        ]
    projects_live = [_project_to_live(p) for p in prj_ordered]

    # ── languages ──
    if inc_lang is not None:
        # inc_lang entries are dicts {id, name, proficiency_level}
        languages_live = [
            {
                "source_id":         l.get("id"),
                "name":              l.get("name") or "",
                "proficiency_level": l.get("proficiency_level") or "",
            }
            for l in inc_lang if l.get("name")
        ]
    else:
        languages_live = [_language_to_live(l) for l in (data.get("languages") or [])]

    # ── keywords ──
    kw_all = {k["id"]: k for k in db.get_keywords()}
    seen: set[int] = set()
    keywords_live: list[dict] = []
    source_ids: list[int]
    if keyword_list is not None:
        source_ids = list(keyword_list)
    else:
        source_ids = [kw["id"] for kw in (data.get("profile_keywords") or [])] + list(
            extra_keywords or []
        )
    for kid in source_ids:
        if kid in seen:
            continue
        kw = kw_all.get(kid)
        if kw:
            seen.add(kid)
            keywords_live.append(_keyword_to_live(kw))

    date_format = (data.get("settings") or {}).get("date_format") or "YYYY"

    live = {
        "section_order":    section_order,
        "sections_enabled": sections_enabled,
        "contact":          contact,
        "summary":          summary_live,
        "experience":       experiences_live,
        "education":        education_live,
        "languages":        languages_live,
        "projects":         projects_live,
        "keywords":         keywords_live,
        "template":         _template_to_live(template),
        "date_format":      date_format,
    }

    return {
        "version":  SCHEMA_VERSION,
        "live":     live,
        "original": _build_original(db, effective_profile_id, data),
    }
