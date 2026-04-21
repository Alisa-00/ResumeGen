# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Companion docs

`AGENTS.md` in this directory contains the code-style guide (imports, type hints, naming, error handling, DB patterns, UI patterns). Follow it. This file covers only what that guide doesn't: commands and cross-file architecture.

## Commands

```bash
pip install -r requirements.txt
python main.py
```

There is no test suite, no linter, and no type-check config. Do not invent one.

## Architecture

The app is a single-user PySide6 desktop tool that keeps a master SQLite "experience database" and uses it to generate per-application tailored resumes.

### Two data paths

1. **Profile-only (toolbar Generate):** `generate_resume_pdf(db_path, profile_id)` reads master data, keyword-filters bullets, and renders. No per-application state.
2. **Application (wizard):** on creation, `snapshot_master_into_application()` copies master data into per-app snapshot tables (`application_experience`, `application_bullet`, `application_education`, `application_project`, `application_language`, `application_website`, `application_keyword`, plus flat `contact_*`/`summary_text` columns on `job_application`). The wizard editor edits the snapshot; the generator renders from the snapshot. No master-data merge at render time.

```
master data (db/database.py)
    ── snapshot_master_into_application() ──→ snapshot tables
    ── wizard step 2 edits snapshot ──→ replace_application_*() / update_application_*()
    ── _assemble_from_snapshot(snapshot) ──→ build_context() (templates/templates.py)
    ── render_from_file() → HTML → html_to_pdf_bytes_sync() → PDF bytes
```

### Key cross-file contracts

- **Database is the single source of truth.** `db/database.py` owns the schema (`SCHEMA_SQL`) and an in-code `_migrate()` that ALTERs columns on startup. `_migrate_legacy_applications()` runs a one-time batch migration (gated by `schema_version`) that materializes legacy override-JSON applications into snapshot tables, then drops dead columns.

- **Two resume generation paths**, both in `resume/generator.py`:
  - `generate_resume_pdf(db_path, profile_id)` — profile-only, keyword-filters bullets by profile match. Used by the toolbar "Generate" button.
  - `generate_resume_pdf_for_app(db_path, *, application_id=|snapshot=)` — renders from a self-contained application snapshot. `snapshot=` is the live-regen path (in-memory dict, so a failed render never touches saved state). `application_id=` loads from the DB.

- **Application wizard flow** (`ui/wizard/`): `wizard.py` is a 2-step QStackedWidget. `step_details.py` collects job info; on Next, the application row is upserted and `snapshot_master_into_application()` is called for new apps. `step_preview.py` opens with a live resume editor on the left and a PDF preview on the right. Edits are collected via `_get_state()`, translated to snapshot shape via `_state_to_snapshot()`, and saved via the `replace_application_*()` / `update_application_*()` methods. The preview is debounced (`DEBOUNCE_MS = 500`) and regenerates the PDF on a `QThreadPool` worker.

- **Thread boundary.** WeasyPrint blocks, so PDF generation always runs on a QRunnable (`ui/ui.py:_Task`, and similar in `step_preview.py`). Workers must construct their own `Database(db_path)` — never share the main thread's connection. The DB uses WAL mode for this reason.

- **Navigation** is a flat list in `ui/ui.py:NAV_ITEMS` mapped to view factories in `_build_view()`. The Applications view is special: it emits `new_application_requested` / `open_application_requested` signals that the main window converts into opening the wizard over a second page of `_main_stack`.

- **Templates.** `templates/templates.py` exposes both file-based and string-based Jinja rendering and registers a `format_date` filter that understands `YYYY-MM-DD`, `YYYY-MM`, `YYYY`. Template CSS is a sibling file (`default.css`) loaded via `base_url` when WeasyPrint renders.

## Local state outside the repo

- `~/.resume_orchestrator` — plain text file containing the absolute path to the user's SQLite DB. Created on first run; `main.py:resolve_db_path()` reads it.
- The SQLite DB itself lives wherever the user pointed the first-run picker (often a cloud-synced folder). It is not in the repo and must not be committed.
