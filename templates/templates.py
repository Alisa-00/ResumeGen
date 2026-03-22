"""
templates/templates.py
Loads and renders Jinja2 HTML resume templates.
"""

from __future__ import annotations
from pathlib import Path
from datetime import datetime

from jinja2 import Environment, FileSystemLoader, BaseLoader, select_autoescape

TEMPLATES_DIR = Path(__file__).parent / "html"
TEMPLATES_DIR.mkdir(exist_ok=True)


# ── date filter ─────────────────────────────────────────────────────

def _format_date(value: str | None, fmt: str = "MMM YYYY") -> str:
    if not value or not value.strip("_- "):
        return ""
    value = value.strip("_").rstrip("-")
    strftime_fmt = fmt.replace("YYYY", "%Y").replace("MMM", "%b").replace("MM", "%m")
    for pattern in ("%Y-%m-%d", "%Y-%m", "%Y"):
        try:
            return datetime.strptime(value, pattern).strftime(strftime_fmt)
        except ValueError:
            continue
    return value


def _configure_env(env: Environment) -> None:
    env.filters["format_date"] = _format_date


# ── filesystem env ───────────────────────────────────────────────────

_fs_env = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=select_autoescape(["html"]),
)
_configure_env(_fs_env)


# ── string loader ────────────────────────────────────────────────────

class _StringLoader(BaseLoader):
    def __init__(self, source: str):
        self._source = source

    def get_source(self, environment, template):
        return self._source, None, lambda: True


def _make_string_env(source: str) -> Environment:
    env = Environment(
        loader=_StringLoader(source),
        autoescape=select_autoescape(["html"]),
    )
    _configure_env(env)
    return env


# ── public API ───────────────────────────────────────────────────────

def render_from_file(template_name: str, context: dict) -> str:
    tmpl = _fs_env.get_template(template_name)
    return tmpl.render(**context)


def render_from_string(html_source: str, context: dict) -> str:
    env  = _make_string_env(html_source)
    tmpl = env.get_template("template")
    return tmpl.render(**context)


def build_context(
    contact: dict | None,
    websites: list[dict],
    summary: dict | None,
    experiences: list[dict],
    education: list[dict],
    projects: list[dict],
    keywords: list[dict],
    section_order: list[str],
    sections_enabled: dict[str, bool],
    template_settings: dict | None,
    date_format: str = "MMM YYYY",
) -> dict:
    contact_full = {**(contact or {}), "websites": websites}
    return {
        "contact":          contact_full,
        "summary":          summary or {},
        "experiences":      experiences,
        "education":        education,
        "projects":         projects,
        "keywords":         keywords,
        "section_order":    section_order,
        "sections_enabled": {k: bool(v) for k, v in sections_enabled.items()},
        "font_family":      (template_settings or {}).get("font_family", "Arial"),
        "font_size":        (template_settings or {}).get("font_size", 11.0),
        "margin_top":       (template_settings or {}).get("margin_top", 15.0),
        "margin_bottom":    (template_settings or {}).get("margin_bottom", 15.0),
        "margin_left":      (template_settings or {}).get("margin_left", 15.0),
        "margin_right":     (template_settings or {}).get("margin_right", 15.0),
        "date_format":      date_format,
    }