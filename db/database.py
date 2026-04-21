"""
db/database.py
Synchronous SQLite interface via stdlib sqlite3.
"""

import json
import shutil
import sqlite3
from pathlib import Path

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS keyword (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT    NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS contact (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    name     TEXT NOT NULL,
    email    TEXT,
    phone    TEXT,
    location TEXT
);

CREATE TABLE IF NOT EXISTS contact_website (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    contact_id INTEGER NOT NULL REFERENCES contact(id) ON DELETE CASCADE,
    label      TEXT    NOT NULL,
    url        TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS work_experience (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    organization_name TEXT    NOT NULL,
    position_name     TEXT    NOT NULL,
    organization_description TEXT,
    organization_website TEXT,
    location          TEXT,
    is_ongoing        INTEGER NOT NULL DEFAULT 0 CHECK (is_ongoing IN (0,1)),
    start_date        TEXT,
    end_date          TEXT
);

CREATE TABLE IF NOT EXISTS bullet_point (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    work_experience_id INTEGER NOT NULL REFERENCES work_experience(id) ON DELETE CASCADE,
    text               TEXT    NOT NULL,
    sort_order         INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS bullet_point_keyword (
    bullet_point_id INTEGER NOT NULL REFERENCES bullet_point(id) ON DELETE CASCADE,
    keyword_id      INTEGER NOT NULL REFERENCES keyword(id)      ON DELETE CASCADE,
    PRIMARY KEY (bullet_point_id, keyword_id)
);

CREATE TABLE IF NOT EXISTS education (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    degree     TEXT    NOT NULL,
    school     TEXT    NOT NULL,
    school_url TEXT,
    location   TEXT,
    field      TEXT,
    gpa        TEXT,
    is_ongoing INTEGER NOT NULL DEFAULT 0 CHECK (is_ongoing IN (0,1)),
    start_date TEXT,
    end_date   TEXT
);

CREATE TABLE IF NOT EXISTS language (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    name              TEXT    NOT NULL UNIQUE,
    proficiency_level TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS project (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    link       TEXT,
    start_date TEXT,
    end_date   TEXT,
    is_ongoing INTEGER NOT NULL DEFAULT 0 CHECK (is_ongoing IN (0,1)),
    text       TEXT
);

CREATE TABLE IF NOT EXISTS project_keyword (
    project_id INTEGER NOT NULL REFERENCES project(id)  ON DELETE CASCADE,
    keyword_id INTEGER NOT NULL REFERENCES keyword(id)  ON DELETE CASCADE,
    PRIMARY KEY (project_id, keyword_id)
);

CREATE TABLE IF NOT EXISTS profile (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    name    TEXT NOT NULL UNIQUE,
    summary TEXT
);

CREATE TABLE IF NOT EXISTS profile_keyword (
    profile_id INTEGER NOT NULL REFERENCES profile(id) ON DELETE CASCADE,
    keyword_id INTEGER NOT NULL REFERENCES keyword(id) ON DELETE CASCADE,
    PRIMARY KEY (profile_id, keyword_id)
);

CREATE TABLE IF NOT EXISTS resume_template (
    id                        INTEGER PRIMARY KEY AUTOINCREMENT,
    name                      TEXT    NOT NULL,
    font_family               TEXT    NOT NULL DEFAULT 'Arial',
    font_size                 REAL    NOT NULL DEFAULT 11.0,
    margin_top                REAL    NOT NULL DEFAULT 8.0,
    margin_bottom             REAL    NOT NULL DEFAULT 8.0,
    margin_left               REAL    NOT NULL DEFAULT 8.0,
    margin_right              REAL    NOT NULL DEFAULT 8.0,
    min_bullet_points_per_job INTEGER NOT NULL DEFAULT 2,
    max_bullet_points_per_job INTEGER NOT NULL DEFAULT 5
);

CREATE TABLE IF NOT EXISTS app_settings (
    id                  INTEGER PRIMARY KEY DEFAULT 1,
    section_order       TEXT    NOT NULL DEFAULT
        '["contact","summary","experience","education","languages","projects","keywords","custom"]',
    sections_enabled    TEXT    NOT NULL DEFAULT
        '{"contact":1,"summary":1,"experience":1,"education":1,"languages":1,"projects":1,"keywords":1,"custom":0}',
    default_template_id INTEGER REFERENCES resume_template(id),
    pdf_output_folder   TEXT,
    pdf_filename_template TEXT  NOT NULL DEFAULT '{company}_{position}_{date}',
    date_format         TEXT    NOT NULL DEFAULT 'YYYY'
);

CREATE TABLE IF NOT EXISTS profile_settings (
    profile_id       INTEGER PRIMARY KEY REFERENCES profile(id) ON DELETE CASCADE,
    section_order    TEXT,
    sections_enabled TEXT
);

CREATE TABLE IF NOT EXISTS resume_config (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT    NOT NULL,
    profile_id   INTEGER REFERENCES profile(id),
    template_id  INTEGER REFERENCES resume_template(id),
    show_summary INTEGER NOT NULL DEFAULT 1 CHECK (show_summary IN (0,1)),
    date_format  TEXT    NOT NULL DEFAULT 'YYYY'
);

CREATE TABLE IF NOT EXISTS job_application_status (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    status TEXT NOT NULL UNIQUE
);

INSERT OR IGNORE INTO job_application_status (status) VALUES
    ('to-apply'), ('applied'), ('phone-screen'), ('interview'),
    ('offer'), ('accepted'), ('ghosted'), ('rejected'), ('withdrawn');

CREATE TABLE IF NOT EXISTS job_application (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id           INTEGER REFERENCES profile(id),
    status_id            INTEGER NOT NULL REFERENCES job_application_status(id),
    position_name        TEXT    NOT NULL,
    company_name         TEXT    NOT NULL,
    date_created         TEXT    NOT NULL,
    date_applied         TEXT,
    date_last_updated    TEXT,
    section_order        TEXT,
    sections_enabled     TEXT,
    resume_pdf_path      TEXT,
    job_posting_url      TEXT,
    job_posting_description TEXT,
    contact_name         TEXT,
    contact_email        TEXT,
    contact_phone        TEXT,
    contact_location     TEXT,
    summary_text         TEXT
);

CREATE TABLE IF NOT EXISTS application_referral (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id INTEGER NOT NULL REFERENCES job_application(id) ON DELETE CASCADE,
    name           TEXT    NOT NULL,
    email          TEXT,
    phone          TEXT,
    linkedin_url   TEXT,
    description    TEXT,
    date_added     TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS application_experience (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id           INTEGER NOT NULL REFERENCES job_application(id) ON DELETE CASCADE,
    source_experience_id     INTEGER,
    sort_order               INTEGER NOT NULL DEFAULT 0,
    organization_name        TEXT    NOT NULL,
    position_name            TEXT    NOT NULL,
    organization_description TEXT,
    organization_website     TEXT,
    location                 TEXT,
    is_ongoing               INTEGER NOT NULL DEFAULT 0 CHECK (is_ongoing IN (0,1)),
    start_date               TEXT,
    end_date                 TEXT
);

CREATE TABLE IF NOT EXISTS application_bullet (
    id                        INTEGER PRIMARY KEY AUTOINCREMENT,
    application_experience_id INTEGER NOT NULL REFERENCES application_experience(id) ON DELETE CASCADE,
    source_bullet_id          INTEGER,
    sort_order                INTEGER NOT NULL DEFAULT 0,
    text                      TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS application_education (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id      INTEGER NOT NULL REFERENCES job_application(id) ON DELETE CASCADE,
    source_education_id INTEGER,
    sort_order          INTEGER NOT NULL DEFAULT 0,
    degree              TEXT    NOT NULL,
    school              TEXT    NOT NULL,
    school_url          TEXT,
    location            TEXT,
    field               TEXT,
    gpa                 TEXT,
    is_ongoing          INTEGER NOT NULL DEFAULT 0 CHECK (is_ongoing IN (0,1)),
    start_date          TEXT,
    end_date            TEXT
);

CREATE TABLE IF NOT EXISTS application_project (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id    INTEGER NOT NULL REFERENCES job_application(id) ON DELETE CASCADE,
    source_project_id INTEGER,
    sort_order        INTEGER NOT NULL DEFAULT 0,
    name              TEXT    NOT NULL,
    link              TEXT,
    start_date        TEXT,
    end_date          TEXT,
    is_ongoing        INTEGER NOT NULL DEFAULT 0 CHECK (is_ongoing IN (0,1)),
    text              TEXT
);

CREATE TABLE IF NOT EXISTS application_language (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id     INTEGER NOT NULL REFERENCES job_application(id) ON DELETE CASCADE,
    source_language_id INTEGER,
    sort_order         INTEGER NOT NULL DEFAULT 0,
    name               TEXT    NOT NULL,
    proficiency_level  TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS application_website (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id INTEGER NOT NULL REFERENCES job_application(id) ON DELETE CASCADE,
    sort_order     INTEGER NOT NULL DEFAULT 0,
    label          TEXT    NOT NULL,
    url            TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS application_keyword (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id INTEGER NOT NULL REFERENCES job_application(id) ON DELETE CASCADE,
    sort_order     INTEGER NOT NULL DEFAULT 0,
    name           TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS schema_version (
    id      INTEGER PRIMARY KEY DEFAULT 1,
    version INTEGER NOT NULL
);
"""

CURRENT_SCHEMA_VERSION = 2


class Database:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._conn: sqlite3.Connection | None = None

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    def connect(self) -> None:
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        # WAL mode allows the generator's worker-thread connection to read
        # concurrently without blocking or being blocked by the main connection
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(SCHEMA_SQL)
        self._conn.commit()
        self._migrate()

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def _migrate(self) -> None:
        """Add any columns that exist in the schema but not in the live DB."""
        # Create new tables that might not exist in older databases
        table_creations = [
            """
            CREATE TABLE IF NOT EXISTS language (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                name              TEXT    NOT NULL UNIQUE,
                proficiency_level TEXT    NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS application_referral (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                application_id INTEGER NOT NULL REFERENCES job_application(id) ON DELETE CASCADE,
                name           TEXT    NOT NULL,
                email          TEXT,
                phone          TEXT,
                linkedin_url   TEXT,
                description    TEXT,
                date_added     TEXT    NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS application_experience (
                id                       INTEGER PRIMARY KEY AUTOINCREMENT,
                application_id           INTEGER NOT NULL REFERENCES job_application(id) ON DELETE CASCADE,
                source_experience_id     INTEGER,
                sort_order               INTEGER NOT NULL DEFAULT 0,
                organization_name        TEXT    NOT NULL,
                position_name            TEXT    NOT NULL,
                organization_description TEXT,
                organization_website     TEXT,
                location                 TEXT,
                is_ongoing               INTEGER NOT NULL DEFAULT 0 CHECK (is_ongoing IN (0,1)),
                start_date               TEXT,
                end_date                 TEXT
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS application_bullet (
                id                        INTEGER PRIMARY KEY AUTOINCREMENT,
                application_experience_id INTEGER NOT NULL REFERENCES application_experience(id) ON DELETE CASCADE,
                source_bullet_id          INTEGER,
                sort_order                INTEGER NOT NULL DEFAULT 0,
                text                      TEXT    NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS application_education (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                application_id      INTEGER NOT NULL REFERENCES job_application(id) ON DELETE CASCADE,
                source_education_id INTEGER,
                sort_order          INTEGER NOT NULL DEFAULT 0,
                degree              TEXT    NOT NULL,
                school              TEXT    NOT NULL,
                school_url          TEXT,
                location            TEXT,
                field               TEXT,
                gpa                 TEXT,
                is_ongoing          INTEGER NOT NULL DEFAULT 0 CHECK (is_ongoing IN (0,1)),
                start_date          TEXT,
                end_date            TEXT
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS application_project (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                application_id    INTEGER NOT NULL REFERENCES job_application(id) ON DELETE CASCADE,
                source_project_id INTEGER,
                sort_order        INTEGER NOT NULL DEFAULT 0,
                name              TEXT    NOT NULL,
                link              TEXT,
                start_date        TEXT,
                end_date          TEXT,
                is_ongoing        INTEGER NOT NULL DEFAULT 0 CHECK (is_ongoing IN (0,1)),
                text              TEXT
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS application_language (
                id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                application_id     INTEGER NOT NULL REFERENCES job_application(id) ON DELETE CASCADE,
                source_language_id INTEGER,
                sort_order         INTEGER NOT NULL DEFAULT 0,
                name               TEXT    NOT NULL,
                proficiency_level  TEXT    NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS application_website (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                application_id INTEGER NOT NULL REFERENCES job_application(id) ON DELETE CASCADE,
                sort_order     INTEGER NOT NULL DEFAULT 0,
                label          TEXT    NOT NULL,
                url            TEXT    NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS application_keyword (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                application_id INTEGER NOT NULL REFERENCES job_application(id) ON DELETE CASCADE,
                sort_order     INTEGER NOT NULL DEFAULT 0,
                name           TEXT    NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS schema_version (
                id      INTEGER PRIMARY KEY DEFAULT 1,
                version INTEGER NOT NULL
            )
            """,
        ]
        for sql in table_creations:
            try:
                self._conn.execute(sql)
                self._conn.commit()
            except sqlite3.Error as e:
                print(f"[MIGRATE] Warning creating table: {e}")

        # Column migrations — legacy dead columns for job_application are
        # added here so the v1 snapshot migration can read them from old DBs,
        # then the v2 migration drops them.
        migrations = [
            ("work_experience", "organization_description", "TEXT"),
            ("work_experience", "organization_website", "TEXT"),
            ("job_application", "summary_text_override", "TEXT"),
            ("job_application", "contact_override", "TEXT"),
            ("job_application", "websites_override", "TEXT"),
            ("job_application", "experience_overrides", "TEXT"),
            ("job_application", "selected_summary_id", "INTEGER"),
            ("job_application", "included_experiences", "TEXT"),
            ("job_application", "included_education", "TEXT"),
            ("job_application", "included_projects", "TEXT"),
            ("app_settings", "pdf_output_folder", "TEXT"),
            (
                "app_settings",
                "pdf_filename_template",
                "TEXT NOT NULL DEFAULT '{company}_{position}_{date}'",
            ),
            ("job_application", "included_bullets", "TEXT"),
            ("profile", "summary", "TEXT"),
            ("job_application", "education_overrides", "TEXT"),
            ("app_settings", "date_format", "TEXT NOT NULL DEFAULT 'YYYY'"),
            ("education", "school_url", "TEXT"),
            ("job_application", "job_posting_url", "TEXT"),
            ("job_application", "job_posting_description", "TEXT"),
            ("job_application", "included_languages", "TEXT"),
            ("job_application", "date_created", "TEXT"),
            ("job_application", "date_last_updated", "TEXT"),
            ("job_application", "contact_name", "TEXT"),
            ("job_application", "contact_email", "TEXT"),
            ("job_application", "contact_phone", "TEXT"),
            ("job_application", "contact_location", "TEXT"),
            ("job_application", "summary_text", "TEXT"),
        ]
        for table, column, col_def in migrations:
            try:
                self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}")
                self._conn.commit()
                print(f"[MIGRATE] Added column {table}.{column}")
            except sqlite3.OperationalError as e:
                msg = str(e).lower()
                if "duplicate column name" in msg:
                    pass  # expected — column already exists
                else:
                    # unexpected schema error (corrupt DB, type mismatch, etc.)
                    raise RuntimeError(
                        f"[MIGRATE] Unexpected error adding {table}.{column}: {e}"
                    ) from e
            except sqlite3.DatabaseError as e:
                # covers corrupt file, disk full, locked DB, etc.
                raise RuntimeError(
                    f"[MIGRATE] Database error adding {table}.{column}: {e}"
                ) from e

        # Eager batch migration of legacy applications into the snapshot tables.
        # Runs once, gated by schema_version.
        self._migrate_legacy_applications()

    # ------------------------------------------------------------------
    # legacy application snapshot migration (one-time, on startup)
    # ------------------------------------------------------------------

    def _migrate_legacy_applications(self) -> None:
        version = self.get_schema_version()
        if version >= CURRENT_SCHEMA_VERSION:
            return

        if version < 1:
            apps = self.fetch_all("SELECT id FROM job_application")
            if apps:
                backup = Path(str(self.db_path) + ".pre-snapshot.bak")
                try:
                    shutil.copy2(self.db_path, backup)
                    print(f"[MIGRATE] Backed up DB to {backup}")
                except OSError as e:
                    print(f"[MIGRATE] Backup failed (continuing): {e}")
                for row in apps:
                    app_id = row["id"]
                    existing = self.fetch_one(
                        "SELECT COUNT(*) AS n FROM application_experience WHERE application_id=?",
                        (app_id,),
                    )
                    has_contact = self.fetch_one(
                        """SELECT contact_name, summary_text
                           FROM job_application WHERE id=?""",
                        (app_id,),
                    ) or {}
                    already_snapshotted = (
                        (existing or {}).get("n", 0) > 0
                        or has_contact.get("contact_name")
                        or has_contact.get("summary_text")
                    )
                    if already_snapshotted:
                        continue
                    try:
                        self._materialize_legacy_snapshot(app_id)
                    except Exception as e:
                        print(f"[MIGRATE] App {app_id} migration failed (skipping): {e}")
            self.set_schema_version(1)

        if version < 2:
            self._drop_legacy_columns()
            self.set_schema_version(2)

    def _drop_legacy_columns(self) -> None:
        dead_cols = [
            "extra_keywords", "summary_text_override", "contact_override",
            "websites_override", "experience_overrides", "education_overrides",
            "included_experiences", "included_education", "included_projects",
            "included_languages", "included_bullets", "keyword_list",
            "selected_summary_id",
        ]
        existing = {
            r["name"]
            for r in self.fetch_all("PRAGMA table_info(job_application)")
        }
        for col in dead_cols:
            if col in existing:
                try:
                    self.conn.execute(
                        f"ALTER TABLE job_application DROP COLUMN {col}"
                    )
                    self.conn.commit()
                except Exception as e:
                    print(f"[MIGRATE] Could not drop {col}: {e}")
        try:
            self.conn.execute("DROP TABLE IF EXISTS application_bullet_override")
            self.conn.commit()
            print("[MIGRATE] Dropped application_bullet_override table")
        except Exception as e:
            print(f"[MIGRATE] Could not drop application_bullet_override: {e}")

    def _materialize_legacy_snapshot(self, application_id: int) -> None:
        """Replay the pre-refactor merge (master data + override JSON columns)
        and fan the result out into the new snapshot tables.
        """
        app = self.fetch_one(
            "SELECT * FROM job_application WHERE id=?", (application_id,)
        )
        if not app:
            return
        profile_id = app.get("profile_id")

        def _parse(col, default):
            raw = app.get(col)
            if not raw:
                return default
            try:
                return json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                return default

        extra_kw_ids = _parse("extra_keywords", []) or []
        contact_override = _parse("contact_override", None)
        websites_override = _parse("websites_override", None)
        experience_overrides_raw = _parse("experience_overrides", {}) or {}
        education_overrides_raw = _parse("education_overrides", {}) or {}
        included_experiences = _parse("included_experiences", None)
        included_education = _parse("included_education", None)
        included_projects = _parse("included_projects", None)
        included_bullets = _parse("included_bullets", None)
        included_languages = _parse("included_languages", None)
        summary_text_override = app.get("summary_text_override")

        section_order_raw = app.get("section_order")
        sections_enabled_raw = app.get("sections_enabled")

        bullet_overrides = self.get_bullet_overrides(application_id)

        if profile_id:
            data = self.get_resume_data(profile_id)
        else:
            data = {
                "contact": self.get_contact(),
                "websites": [],
                "summary_text": "",
                "experiences": [],
                "education": [],
                "languages": [],
                "projects": [],
                "profile_keywords": [],
                "settings": self.get_settings(),
                "profile_settings": None,
                "template": None,
            }

        # contact
        master_contact = data.get("contact") or {}
        merged_contact = {**master_contact, **(contact_override or {})}
        self.update_application_contact(
            application_id,
            merged_contact.get("name") or "",
            merged_contact.get("email") or "",
            merged_contact.get("phone") or "",
            merged_contact.get("location") or "",
        )

        # websites
        websites = (
            websites_override if websites_override is not None
            else (data.get("websites") or [])
        )
        self.replace_application_websites(
            application_id,
            [{"label": w.get("label", ""), "url": w.get("url", "")} for w in websites],
        )

        # summary
        summary_text = summary_text_override or data.get("summary_text") or ""
        self.update_application_summary(application_id, summary_text)

        # keywords (profile ∪ extras, deduped; preserve name-order)
        profile_kws = data.get("profile_keywords") or []
        kw_names: list[str] = []
        seen_ids: set[int] = set()
        for kw in profile_kws:
            if kw["id"] not in seen_ids:
                seen_ids.add(kw["id"])
                kw_names.append(kw["name"])
        if extra_kw_ids:
            kw_map = {kw["id"]: kw for kw in self.get_keywords()}
            for kid in extra_kw_ids:
                if kid in kw_map and kid not in seen_ids:
                    seen_ids.add(kid)
                    kw_names.append(kw_map[kid]["name"])
        self.replace_application_keywords(application_id, kw_names)

        kw_id_set: set[int] = {kw["id"] for kw in profile_kws}
        kw_id_set.update(extra_kw_ids)

        template = data.get("template") or {}
        min_bp = template.get("min_bullet_points_per_job", 2)
        max_bp = template.get("max_bullet_points_per_job", 5)

        # experiences
        exp_ov_map = {int(k): (v or {}) for k, v in experience_overrides_raw.items()}
        inc_bullets_map: dict[int, list[int]] | None = None
        if included_bullets is not None:
            inc_bullets_map = {int(k): list(v or []) for k, v in included_bullets.items()}

        exp_pool = data.get("experiences") or []
        if included_experiences is not None:
            order = {eid: i for i, eid in enumerate(included_experiences)}
            exp_pool = sorted(
                [e for e in exp_pool if e["id"] in order],
                key=lambda e: order[e["id"]],
            )

        experiences_payload = []
        for job in exp_pool:
            ov = exp_ov_map.get(job["id"], {})
            bullets_all = list(job.get("bullet_points") or [])
            if inc_bullets_map is not None and job["id"] in inc_bullets_map:
                id_list = inc_bullets_map[job["id"]]
                bid_map = {b["id"]: b for b in bullets_all}
                matched = []
                for bid in id_list:
                    if bid in bid_map:
                        b = bid_map[bid]
                        matched.append({
                            "id": b["id"],
                            "text": bullet_overrides.get(bid, b.get("text", "")),
                        })
            else:
                def _has_match(b):
                    return bool(set(b.get("keyword_ids") or []) & kw_id_set)
                matched_bs = [b for b in bullets_all if _has_match(b)]
                unmatched_bs = [b for b in bullets_all if not _has_match(b)]
                if len(matched_bs) < min_bp:
                    matched_bs += unmatched_bs[: min_bp - len(matched_bs)]
                matched_bs.sort(key=lambda b: b.get("sort_order", 0))
                matched_bs = matched_bs[:max_bp]
                matched = [
                    {
                        "id": b["id"],
                        "text": bullet_overrides.get(b["id"], b.get("text", "")),
                    }
                    for b in matched_bs
                ]

            def _pick(key, default=None):
                return ov[key] if key in ov else job.get(key, default)

            experiences_payload.append({
                "source_experience_id": job["id"],
                "organization_name": _pick("organization_name", "") or "",
                "position_name": _pick("position_name", "") or "",
                "organization_description": _pick("organization_description"),
                "organization_website": _pick("organization_website"),
                "location": _pick("location"),
                "is_ongoing": bool(_pick("is_ongoing")),
                "start_date": _pick("start_date"),
                "end_date": _pick("end_date"),
                "bullets": [
                    {"source_bullet_id": b["id"], "text": b["text"]}
                    for b in matched
                ],
            })
        self.replace_application_experiences(application_id, experiences_payload)

        # education
        edu_ov_map = {int(k): (v or {}) for k, v in education_overrides_raw.items()}
        edu_pool = data.get("education") or []
        if included_education is not None:
            order = {eid: i for i, eid in enumerate(included_education)}
            edu_pool = sorted(
                [e for e in edu_pool if e["id"] in order],
                key=lambda e: order[e["id"]],
            )

        education_payload = []
        for e in edu_pool:
            ov = edu_ov_map.get(e["id"], {})

            def _pick(key, default=None):
                return ov[key] if key in ov else e.get(key, default)

            education_payload.append({
                "source_education_id": e["id"],
                "degree": _pick("degree", "") or "",
                "school": _pick("school", "") or "",
                "school_url": _pick("school_url"),
                "location": _pick("location"),
                "field": _pick("field"),
                "gpa": _pick("gpa"),
                "is_ongoing": bool(_pick("is_ongoing")),
                "start_date": _pick("start_date"),
                "end_date": _pick("end_date"),
            })
        self.replace_application_education(application_id, education_payload)

        # projects
        prj_pool = data.get("projects") or []
        if included_projects is not None:
            order = {pid: i for i, pid in enumerate(included_projects)}
            proj_list = sorted(
                [p for p in prj_pool if p["id"] in order],
                key=lambda p: order[p["id"]],
            )
        else:
            proj_list = [
                p for p in prj_pool if set(p.get("keyword_ids") or []) & kw_id_set
            ]
        self.replace_application_projects(
            application_id,
            [
                {
                    "source_project_id": p["id"],
                    "name": p.get("name", ""),
                    "link": p.get("link"),
                    "start_date": p.get("start_date"),
                    "end_date": p.get("end_date"),
                    "is_ongoing": bool(p.get("is_ongoing")),
                    "text": p.get("text"),
                }
                for p in proj_list
            ],
        )

        # languages
        if included_languages is not None:
            lang_pool = data.get("languages") or []
            lang_map = {lang["id"]: lang for lang in lang_pool}
            languages_payload = []
            for lang_data in included_languages:
                lid = lang_data.get("id")
                original = lang_map.get(lid) if lid else None
                name = lang_data.get("name") or ((original or {}).get("name") or "")
                prof = lang_data.get("proficiency_level") or (
                    (original or {}).get("proficiency_level") or ""
                )
                if name:
                    languages_payload.append({
                        "source_language_id": lid,
                        "name": name,
                        "proficiency_level": prof,
                    })
        else:
            languages_payload = [
                {
                    "source_language_id": lang["id"],
                    "name": lang.get("name", ""),
                    "proficiency_level": lang.get("proficiency_level", ""),
                }
                for lang in (data.get("languages") or [])
            ]
        self.replace_application_languages(application_id, languages_payload)

        # layout
        if not section_order_raw or not sections_enabled_raw:
            ps = data.get("profile_settings") or {}
            settings = data.get("settings") or {}
            if not section_order_raw:
                section_order_raw = ps.get("section_order") or settings.get("section_order")
            if not sections_enabled_raw:
                sections_enabled_raw = ps.get("sections_enabled") or settings.get("sections_enabled")
        self.update_application_layout(
            application_id, section_order_raw, sections_enabled_raw
        )

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("Database not connected.")
        return self._conn

    def fetch_all(self, sql: str, params: tuple = ()) -> list[dict]:
        cur = self.conn.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]

    def fetch_one(self, sql: str, params: tuple = ()) -> dict | None:
        cur = self.conn.execute(sql, params)
        row = cur.fetchone()
        return dict(row) if row else None

    def execute(self, sql: str, params: tuple = ()) -> int:
        cur = self.conn.execute(sql, params)
        self.conn.commit()
        return cur.lastrowid

    # ------------------------------------------------------------------
    # contact
    # ------------------------------------------------------------------

    def get_contact(self) -> dict | None:
        return self.fetch_one("SELECT * FROM contact LIMIT 1")

    def get_contact_websites(self, contact_id: int) -> list[dict]:
        return self.fetch_all(
            "SELECT * FROM contact_website WHERE contact_id=? ORDER BY id",
            (contact_id,),
        )

    def upsert_contact(self, name: str, email: str, phone: str, location: str) -> int:
        existing = self.get_contact()
        if existing:
            self.execute(
                "UPDATE contact SET name=?, email=?, phone=?, location=? WHERE id=?",
                (name, email, phone, location, existing["id"]),
            )
            return existing["id"]
        return self.execute(
            "INSERT INTO contact (name, email, phone, location) VALUES (?,?,?,?)",
            (name, email, phone, location),
        )

    def delete_contact_websites(self, contact_id: int) -> None:
        self.execute("DELETE FROM contact_website WHERE contact_id=?", (contact_id,))

    def add_contact_website(self, contact_id: int, label: str, url: str) -> int:
        return self.execute(
            "INSERT INTO contact_website (contact_id, label, url) VALUES (?,?,?)",
            (contact_id, label, url),
        )

    # ------------------------------------------------------------------
    # full resume data assembly
    # ------------------------------------------------------------------

    def get_resume_data(self, profile_id: int) -> dict:
        contact = self.get_contact()
        websites = self.get_contact_websites(contact["id"]) if contact else []

        # get profile summary directly
        profile = self.fetch_one("SELECT * FROM profile WHERE id=?", (profile_id,))
        summary_text = (profile or {}).get("summary") or ""

        experiences = []
        for job in self.get_work_experiences():
            bullets = []
            for bp in self.get_bullet_points(job["id"]):
                bullets.append(
                    {
                        **bp,
                        "keyword_ids": self.get_bullet_point_keywords(bp["id"]),
                    }
                )
            experiences.append({**job, "bullet_points": bullets})

        education = self.get_education()

        languages = self.get_languages()

        projects = []
        for p in self.get_projects():
            projects.append({**p, "keyword_ids": self.get_project_keywords(p["id"])})

        profile_keywords = self.get_profile_keywords(profile_id)
        settings = self.get_settings()
        profile_settings = self.get_profile_settings(profile_id)

        template = None
        config = self.fetch_one(
            "SELECT * FROM resume_config WHERE profile_id=? LIMIT 1", (profile_id,)
        )
        tmpl_id = (config or {}).get("template_id") or (settings or {}).get(
            "default_template_id"
        )
        if tmpl_id:
            template = self.fetch_one(
                "SELECT * FROM resume_template WHERE id=?", (tmpl_id,)
            )

        return dict(
            contact=contact,
            websites=websites,
            summary_text=summary_text,
            experiences=experiences,
            education=education,
            languages=languages,
            projects=projects,
            profile_keywords=profile_keywords,
            settings=settings,
            profile_settings=profile_settings,
            template=template,
        )

    # ------------------------------------------------------------------
    # templates
    # ------------------------------------------------------------------

    def get_templates(self) -> list[dict]:
        return self.fetch_all("SELECT * FROM resume_template ORDER BY name")

    def upsert_template(
        self,
        name: str,
        font_family: str,
        font_size: float,
        margin_top: float,
        margin_bottom: float,
        margin_left: float,
        margin_right: float,
        min_bp: int,
        max_bp: int,
        id: int | None = None,
    ) -> int:
        if id:
            self.execute(
                """UPDATE resume_template SET name=?, font_family=?, font_size=?,
                   margin_top=?, margin_bottom=?, margin_left=?, margin_right=?,
                   min_bullet_points_per_job=?, max_bullet_points_per_job=?
                   WHERE id=?""",
                (
                    name,
                    font_family,
                    font_size,
                    margin_top,
                    margin_bottom,
                    margin_left,
                    margin_right,
                    min_bp,
                    max_bp,
                    id,
                ),
            )
            return id
        return self.execute(
            """INSERT INTO resume_template
               (name, font_family, font_size,
                margin_top, margin_bottom, margin_left, margin_right,
                min_bullet_points_per_job, max_bullet_points_per_job)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                name,
                font_family,
                font_size,
                margin_top,
                margin_bottom,
                margin_left,
                margin_right,
                min_bp,
                max_bp,
            ),
        )

    def delete_template(self, id: int) -> None:
        self.execute("DELETE FROM resume_template WHERE id=?", (id,))

    # ------------------------------------------------------------------
    # settings
    # ------------------------------------------------------------------

    def get_settings(self) -> dict:
        row = self.fetch_one("SELECT * FROM app_settings WHERE id=1")
        if not row:
            self.execute("INSERT OR IGNORE INTO app_settings (id) VALUES (1)")
            row = self.fetch_one("SELECT * FROM app_settings WHERE id=1")
        return row

    def save_settings(
        self,
        section_order: str,
        sections_enabled: str,
        default_template_id: int | None,
        pdf_output_folder: str | None = None,
        pdf_filename_template: str = "{company}_{position}_{date}",
        date_format: str = "YYYY",
    ) -> None:
        self.execute(
            """INSERT INTO app_settings
               (id, section_order, sections_enabled, default_template_id,
                pdf_output_folder, pdf_filename_template, date_format)
               VALUES (1,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET
                 section_order=excluded.section_order,
                 sections_enabled=excluded.sections_enabled,
                 default_template_id=excluded.default_template_id,
                 pdf_output_folder=excluded.pdf_output_folder,
                 pdf_filename_template=excluded.pdf_filename_template,
                 date_format=excluded.date_format""",
            (
                section_order,
                sections_enabled,
                default_template_id,
                pdf_output_folder,
                pdf_filename_template,
                date_format,
            ),
        )

    def get_profile_settings(self, profile_id: int) -> dict | None:
        return self.fetch_one(
            "SELECT * FROM profile_settings WHERE profile_id=?", (profile_id,)
        )

    def save_profile_settings(
        self,
        profile_id: int,
        section_order: str | None,
        sections_enabled: str | None,
    ) -> None:
        self.execute(
            """INSERT INTO profile_settings (profile_id, section_order, sections_enabled)
               VALUES (?, ?, ?)
               ON CONFLICT(profile_id) DO UPDATE SET
                 section_order=excluded.section_order,
                 sections_enabled=excluded.sections_enabled""",
            (profile_id, section_order, sections_enabled),
        )

    # ------------------------------------------------------------------
    # keywords
    # ------------------------------------------------------------------

    def get_keywords(self) -> list[dict]:
        return self.fetch_all("SELECT * FROM keyword ORDER BY name")

    def add_keyword(self, name: str) -> int:
        return self.execute("INSERT OR IGNORE INTO keyword (name) VALUES (?)", (name,))

    def delete_keyword(self, keyword_id: int) -> None:
        self.execute("DELETE FROM keyword WHERE id=?", (keyword_id,))

    # ------------------------------------------------------------------
    # work experience
    # ------------------------------------------------------------------

    def get_work_experiences(self) -> list[dict]:
        rows = self.fetch_all("SELECT * FROM work_experience")
        return sorted(
            rows,
            key=lambda r: (
                1 if r.get("is_ongoing") else 0,
                r.get("start_date") or "0000-00-00",
            ),
            reverse=True,
        )

    def upsert_work_experience(
        self,
        org: str,
        position: str,
        organization_description: str,
        organization_website: str,
        location: str,
        is_ongoing: bool,
        start_date: str,
        end_date: str | None,
        id: int | None = None,
    ) -> int:
        if id:
            self.execute(
                """UPDATE work_experience SET organization_name=?, position_name=?,
                   organization_description=?, organization_website=?,
                   location=?, is_ongoing=?, start_date=?, end_date=? WHERE id=?""",
                (
                    org,
                    position,
                    organization_description,
                    organization_website,
                    location,
                    int(is_ongoing),
                    start_date,
                    end_date,
                    id,
                ),
            )
            return id
        return self.execute(
            """INSERT INTO work_experience
               (organization_name, position_name, organization_description,
                organization_website, location, is_ongoing, start_date, end_date)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                org,
                position,
                organization_description,
                organization_website,
                location,
                int(is_ongoing),
                start_date,
                end_date,
            ),
        )

    def delete_work_experience(self, id: int) -> None:
        self.execute("DELETE FROM work_experience WHERE id=?", (id,))

    def get_bullet_points(self, work_experience_id: int) -> list[dict]:
        return self.fetch_all(
            "SELECT * FROM bullet_point WHERE work_experience_id=? ORDER BY sort_order",
            (work_experience_id,),
        )

    def upsert_bullet_point(
        self,
        work_experience_id: int,
        text: str,
        sort_order: int = 0,
        id: int | None = None,
    ) -> int:
        if id:
            self.execute(
                "UPDATE bullet_point SET text=?, sort_order=? WHERE id=?",
                (text, sort_order, id),
            )
            return id
        return self.execute(
            "INSERT INTO bullet_point (work_experience_id, text, sort_order) VALUES (?,?,?)",
            (work_experience_id, text, sort_order),
        )

    def delete_bullet_point(self, id: int) -> None:
        self.execute("DELETE FROM bullet_point WHERE id=?", (id,))

    def get_bullet_point_keywords(self, bullet_point_id: int) -> list[int]:
        rows = self.fetch_all(
            "SELECT keyword_id FROM bullet_point_keyword WHERE bullet_point_id=?",
            (bullet_point_id,),
        )
        return [r["keyword_id"] for r in rows]

    def set_bullet_point_keywords(
        self, bullet_point_id: int, keyword_ids: list[int]
    ) -> None:
        self.execute(
            "DELETE FROM bullet_point_keyword WHERE bullet_point_id=?",
            (bullet_point_id,),
        )
        for kw_id in keyword_ids:
            self.execute(
                "INSERT OR IGNORE INTO bullet_point_keyword (bullet_point_id, keyword_id) VALUES (?,?)",
                (bullet_point_id, kw_id),
            )

    # ------------------------------------------------------------------
    # education
    # ------------------------------------------------------------------

    def get_education(self) -> list[dict]:
        return self.fetch_all(
            "SELECT * FROM education ORDER BY is_ongoing DESC, start_date DESC"
        )

    def upsert_education(
        self,
        degree: str,
        school: str,
        school_url: str,
        location: str,
        field: str,
        gpa: str,
        is_ongoing: bool,
        start_date: str,
        end_date: str | None,
        id: int | None = None,
    ) -> int:
        if id:
            self.execute(
                """UPDATE education SET degree=?, school=?, school_url=?, location=?, field=?,
                   gpa=?, is_ongoing=?, start_date=?, end_date=? WHERE id=?""",
                (
                    degree,
                    school,
                    school_url,
                    location,
                    field,
                    gpa,
                    int(is_ongoing),
                    start_date,
                    end_date,
                    id,
                ),
            )
            return id
        return self.execute(
            """INSERT INTO education
               (degree, school, school_url, location, field, gpa, is_ongoing, start_date, end_date)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                degree,
                school,
                school_url,
                location,
                field,
                gpa,
                int(is_ongoing),
                start_date,
                end_date,
            ),
        )

    def delete_education(self, id: int) -> None:
        self.execute("DELETE FROM education WHERE id=?", (id,))

    # ------------------------------------------------------------------
    # languages
    # ------------------------------------------------------------------

    def get_languages(self) -> list[dict]:
        return self.fetch_all("SELECT * FROM language ORDER BY name")

    def upsert_language(
        self, name: str, proficiency_level: str, id: int | None = None
    ) -> int:
        if id:
            self.execute(
                "UPDATE language SET name=?, proficiency_level=? WHERE id=?",
                (name, proficiency_level, id),
            )
            return id
        # Use INSERT OR REPLACE to handle unique constraint on name
        # This updates proficiency_level if language with this name already exists
        return self.execute(
            """INSERT INTO language (name, proficiency_level)
               VALUES (?,?)
               ON CONFLICT(name) DO UPDATE SET proficiency_level=excluded.proficiency_level""",
            (name, proficiency_level),
        )

    def delete_language(self, id: int) -> None:
        self.execute("DELETE FROM language WHERE id=?", (id,))

    # ------------------------------------------------------------------
    # projects
    # ------------------------------------------------------------------

    def get_projects(self) -> list[dict]:
        return self.fetch_all(
            "SELECT * FROM project ORDER BY is_ongoing DESC, start_date DESC"
        )

    def upsert_project(
        self,
        name: str,
        link: str,
        start_date: str,
        end_date: str | None,
        is_ongoing: bool,
        text: str,
        id: int | None = None,
    ) -> int:
        if id:
            self.execute(
                """UPDATE project SET name=?, link=?, start_date=?, end_date=?,
                   is_ongoing=?, text=? WHERE id=?""",
                (name, link, start_date, end_date, int(is_ongoing), text, id),
            )
            return id
        return self.execute(
            """INSERT INTO project (name, link, start_date, end_date, is_ongoing, text)
               VALUES (?,?,?,?,?,?)""",
            (name, link, start_date, end_date, int(is_ongoing), text),
        )

    def delete_project(self, id: int) -> None:
        self.execute("DELETE FROM project WHERE id=?", (id,))

    def get_project_keywords(self, project_id: int) -> list[int]:
        rows = self.fetch_all(
            "SELECT keyword_id FROM project_keyword WHERE project_id=?", (project_id,)
        )
        return [r["keyword_id"] for r in rows]

    def set_project_keywords(self, project_id: int, keyword_ids: list[int]) -> None:
        self.execute("DELETE FROM project_keyword WHERE project_id=?", (project_id,))
        for kw_id in keyword_ids:
            self.execute(
                "INSERT OR IGNORE INTO project_keyword (project_id, keyword_id) VALUES (?,?)",
                (project_id, kw_id),
            )

    # ------------------------------------------------------------------
    # profiles
    # ------------------------------------------------------------------

    def get_profiles(self) -> list[dict]:
        return self.fetch_all("SELECT * FROM profile ORDER BY name")

    def upsert_profile(
        self, name: str, summary: str = "", id: int | None = None
    ) -> int:
        if id:
            self.execute(
                "UPDATE profile SET name=?, summary=? WHERE id=?", (name, summary, id)
            )
            return id
        return self.execute(
            "INSERT INTO profile (name, summary) VALUES (?,?)", (name, summary)
        )

    def delete_profile(self, id: int) -> None:
        self.execute(
            "UPDATE job_application SET profile_id=NULL WHERE profile_id=?", (id,)
        )
        self.execute(
            "UPDATE resume_config SET profile_id=NULL WHERE profile_id=?", (id,)
        )
        self.execute("DELETE FROM profile WHERE id=?", (id,))

    def get_profile_keywords(self, profile_id: int) -> list[dict]:
        return self.fetch_all(
            """SELECT k.id, k.name
               FROM profile_keyword pk
               JOIN keyword k ON k.id = pk.keyword_id
               WHERE pk.profile_id = ?
               ORDER BY k.name""",
            (profile_id,),
        )

    def set_profile_keywords(self, profile_id: int, keyword_ids: list[int]) -> None:
        self.execute("DELETE FROM profile_keyword WHERE profile_id=?", (profile_id,))
        for kw_id in keyword_ids:
            self.execute(
                "INSERT INTO profile_keyword (profile_id, keyword_id) VALUES (?,?)",
                (profile_id, kw_id),
            )

    # ------------------------------------------------------------------
    # job applications
    # ------------------------------------------------------------------

    def get_applications(self) -> list[dict]:
        return self.fetch_all(
            """SELECT ja.*, jas.status, p.name AS profile_name
               FROM job_application ja
               JOIN job_application_status jas ON jas.id = ja.status_id
               LEFT JOIN profile p ON p.id = ja.profile_id
               ORDER BY ja.date_applied DESC"""
        )

    def get_application(self, id: int) -> dict | None:
        return self.fetch_one(
            """SELECT ja.*, jas.status, p.name AS profile_name
               FROM job_application ja
               JOIN job_application_status jas ON jas.id = ja.status_id
               LEFT JOIN profile p ON p.id = ja.profile_id
               WHERE ja.id=?""",
            (id,),
        )

    def upsert_application(
        self,
        profile_id: int | None,
        status_id: int,
        position_name: str,
        company_name: str,
        date_applied: str,
        job_posting_url: str | None = None,
        job_posting_description: str | None = None,
        id: int | None = None,
        date_created: str | None = None,
        date_last_updated: str | None = None,
        **_kwargs,
    ) -> int:
        from datetime import date as _date

        today = _date.today().strftime("%Y-%m-%d")
        if date_last_updated is None:
            date_last_updated = today

        if id:
            self.execute(
                """UPDATE job_application SET
                   profile_id=?, status_id=?, position_name=?, company_name=?,
                   date_applied=?, date_last_updated=?,
                   job_posting_url=?, job_posting_description=?
                   WHERE id=?""",
                (
                    profile_id, status_id, position_name, company_name,
                    date_applied, date_last_updated,
                    job_posting_url, job_posting_description, id,
                ),
            )
            return id
        if date_created is None:
            date_created = _date.today().strftime("%Y-%m-%d")
        return self.execute(
            """INSERT INTO job_application
               (profile_id, status_id, position_name, company_name,
                date_created, date_applied, date_last_updated,
                job_posting_url, job_posting_description)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                profile_id, status_id, position_name, company_name,
                date_created, date_applied, date_last_updated,
                job_posting_url, job_posting_description,
            ),
        )

    def delete_application(self, id: int) -> None:
        self.execute("DELETE FROM job_application WHERE id=?", (id,))

    def get_statuses(self) -> list[dict]:
        return self.fetch_all("SELECT * FROM job_application_status")

    # ------------------------------------------------------------------
    # application referrals
    # ------------------------------------------------------------------

    def get_application_referrals(self, application_id: int) -> list[dict]:
        return self.fetch_all(
            """SELECT id, name, email, phone, linkedin_url, description, date_added
               FROM application_referral
               WHERE application_id=?
               ORDER BY date_added DESC""",
            (application_id,),
        )

    def get_referral(self, referral_id: int) -> dict | None:
        return self.fetch_one(
            """SELECT id, application_id, name, email, phone, linkedin_url, description, date_added
               FROM application_referral
               WHERE id=?""",
            (referral_id,),
        )

    def add_application_referral(
        self,
        application_id: int,
        name: str,
        email: str | None = None,
        phone: str | None = None,
        linkedin_url: str | None = None,
        description: str | None = None,
        date_added: str | None = None,
    ) -> int:
        from datetime import date as _date

        if date_added is None:
            date_added = _date.today().strftime("%Y-%m-%d")
        return self.execute(
            """INSERT INTO application_referral
               (application_id, name, email, phone, linkedin_url, description, date_added)
               VALUES (?,?,?,?,?,?,?)""",
            (application_id, name, email, phone, linkedin_url, description, date_added),
        )

    def update_application_referral(
        self,
        referral_id: int,
        name: str,
        email: str | None = None,
        phone: str | None = None,
        linkedin_url: str | None = None,
        description: str | None = None,
    ) -> None:
        self.execute(
            """UPDATE application_referral
               SET name=?, email=?, phone=?, linkedin_url=?, description=?
               WHERE id=?""",
            (name, email, phone, linkedin_url, description, referral_id),
        )

    def delete_application_referral(self, referral_id: int) -> None:
        self.execute("DELETE FROM application_referral WHERE id=?", (referral_id,))

    # ------------------------------------------------------------------
    # application snapshot (self-contained per-application data)
    # ------------------------------------------------------------------

    def get_schema_version(self) -> int:
        row = self.fetch_one("SELECT version FROM schema_version WHERE id=1")
        return (row or {}).get("version") or 0

    def set_schema_version(self, version: int) -> None:
        self.execute(
            """INSERT INTO schema_version (id, version) VALUES (1, ?)
               ON CONFLICT(id) DO UPDATE SET version=excluded.version""",
            (version,),
        )

    def snapshot_master_into_application(
        self,
        application_id: int,
        profile_id: int | None,
        extra_keyword_ids: list[int] | None = None,
    ) -> None:
        """Copy the user's current master data into this application's snapshot tables.

        Applies the same keyword filter the legacy generator used at render time
        (profile keywords ∪ extras) so the initial snapshot reflects the same
        bullet / project set the user would have seen pre-refactor. After this
        call, the application is self-contained — edits go to the snapshot
        tables, not back to master.
        """
        extra_keyword_ids = extra_keyword_ids or []

        data: dict = self.get_resume_data(profile_id) if profile_id else {
            "contact": self.get_contact(),
            "websites": [],
            "summary_text": "",
            "experiences": [],
            "education": [],
            "languages": [],
            "projects": [],
            "profile_keywords": [],
            "settings": self.get_settings(),
            "profile_settings": None,
            "template": None,
        }

        contact = data.get("contact") or {}
        self.update_application_contact(
            application_id,
            contact.get("name") or "",
            contact.get("email") or "",
            contact.get("phone") or "",
            contact.get("location") or "",
        )
        self.replace_application_websites(
            application_id,
            [{"label": w["label"], "url": w["url"]} for w in (data.get("websites") or [])],
        )

        self.update_application_summary(application_id, data.get("summary_text") or "")

        kw_names: list[str] = []
        seen: set[int] = set()
        for kw in data.get("profile_keywords") or []:
            if kw["id"] not in seen:
                seen.add(kw["id"])
                kw_names.append(kw["name"])
        if extra_keyword_ids:
            kw_map = {kw["id"]: kw for kw in self.get_keywords()}
            for kid in extra_keyword_ids:
                if kid in kw_map and kid not in seen:
                    seen.add(kid)
                    kw_names.append(kw_map[kid]["name"])
        self.replace_application_keywords(application_id, kw_names)

        kw_id_set: set[int] = {kw["id"] for kw in (data.get("profile_keywords") or [])}
        kw_id_set.update(extra_keyword_ids)

        template = data.get("template") or {}
        min_bp = template.get("min_bullet_points_per_job", 2)
        max_bp = template.get("max_bullet_points_per_job", 5)

        experiences_payload = []
        for job in data.get("experiences") or []:
            bullets = list(job.get("bullet_points") or [])
            matched = [b for b in bullets if kw_id_set & set(b.get("keyword_ids") or [])]
            unmatched = [b for b in bullets if not (kw_id_set & set(b.get("keyword_ids") or []))]
            if len(matched) < min_bp:
                matched += unmatched[: min_bp - len(matched)]
            matched.sort(key=lambda b: b.get("sort_order", 0))
            matched = matched[:max_bp]
            experiences_payload.append({
                "source_experience_id": job["id"],
                "organization_name": job.get("organization_name", ""),
                "position_name": job.get("position_name", ""),
                "organization_description": job.get("organization_description"),
                "organization_website": job.get("organization_website"),
                "location": job.get("location"),
                "is_ongoing": bool(job.get("is_ongoing")),
                "start_date": job.get("start_date"),
                "end_date": job.get("end_date"),
                "bullets": [
                    {
                        "source_bullet_id": b["id"],
                        "text": b.get("text", ""),
                    }
                    for b in matched
                ],
            })
        self.replace_application_experiences(application_id, experiences_payload)

        education_payload = [
            {
                "source_education_id": e["id"],
                "degree": e.get("degree", ""),
                "school": e.get("school", ""),
                "school_url": e.get("school_url"),
                "location": e.get("location"),
                "field": e.get("field"),
                "gpa": e.get("gpa"),
                "is_ongoing": bool(e.get("is_ongoing")),
                "start_date": e.get("start_date"),
                "end_date": e.get("end_date"),
            }
            for e in (data.get("education") or [])
        ]
        self.replace_application_education(application_id, education_payload)

        projects_payload = []
        for p in data.get("projects") or []:
            if kw_id_set & set(p.get("keyword_ids") or []):
                projects_payload.append({
                    "source_project_id": p["id"],
                    "name": p.get("name", ""),
                    "link": p.get("link"),
                    "start_date": p.get("start_date"),
                    "end_date": p.get("end_date"),
                    "is_ongoing": bool(p.get("is_ongoing")),
                    "text": p.get("text"),
                })
        self.replace_application_projects(application_id, projects_payload)

        languages_payload = [
            {
                "source_language_id": lang["id"],
                "name": lang.get("name", ""),
                "proficiency_level": lang.get("proficiency_level", ""),
            }
            for lang in (data.get("languages") or [])
        ]
        self.replace_application_languages(application_id, languages_payload)

        ps = data.get("profile_settings") or {}
        settings = data.get("settings") or self.get_settings()
        section_order = ps.get("section_order") or settings.get("section_order")
        sections_enabled = ps.get("sections_enabled") or settings.get("sections_enabled")
        self.update_application_layout(application_id, section_order, sections_enabled)

    def get_application_snapshot(self, application_id: int) -> dict:
        """Return the full self-contained data needed to render this application."""
        app = self.fetch_one(
            """SELECT contact_name, contact_email, contact_phone, contact_location,
                      summary_text, section_order, sections_enabled, profile_id
               FROM job_application WHERE id=?""",
            (application_id,),
        ) or {}

        websites = self.fetch_all(
            """SELECT id, sort_order, label, url
               FROM application_website
               WHERE application_id=?
               ORDER BY sort_order, id""",
            (application_id,),
        )

        experience_rows = self.fetch_all(
            """SELECT * FROM application_experience
               WHERE application_id=?
               ORDER BY sort_order, id""",
            (application_id,),
        )
        experiences = []
        for e in experience_rows:
            bullets = self.fetch_all(
                """SELECT id, source_bullet_id, sort_order, text
                   FROM application_bullet
                   WHERE application_experience_id=?
                   ORDER BY sort_order, id""",
                (e["id"],),
            )
            experiences.append({**e, "bullet_points": bullets})

        education = self.fetch_all(
            """SELECT * FROM application_education
               WHERE application_id=?
               ORDER BY sort_order, id""",
            (application_id,),
        )

        projects = self.fetch_all(
            """SELECT * FROM application_project
               WHERE application_id=?
               ORDER BY sort_order, id""",
            (application_id,),
        )

        languages = self.fetch_all(
            """SELECT * FROM application_language
               WHERE application_id=?
               ORDER BY sort_order, id""",
            (application_id,),
        )

        keywords = self.fetch_all(
            """SELECT id, sort_order, name
               FROM application_keyword
               WHERE application_id=?
               ORDER BY sort_order, id""",
            (application_id,),
        )

        settings = self.get_settings()
        template = None
        profile_id = app.get("profile_id")
        config = None
        if profile_id:
            config = self.fetch_one(
                "SELECT * FROM resume_config WHERE profile_id=? LIMIT 1", (profile_id,)
            )
        tmpl_id = (config or {}).get("template_id") or (settings or {}).get("default_template_id")
        if tmpl_id:
            template = self.fetch_one(
                "SELECT * FROM resume_template WHERE id=?", (tmpl_id,)
            )

        return dict(
            contact={
                "name": app.get("contact_name") or "",
                "email": app.get("contact_email") or "",
                "phone": app.get("contact_phone") or "",
                "location": app.get("contact_location") or "",
            },
            websites=websites,
            summary_text=app.get("summary_text") or "",
            experiences=experiences,
            education=education,
            projects=projects,
            languages=languages,
            keywords=keywords,
            section_order=app.get("section_order"),
            sections_enabled=app.get("sections_enabled"),
            settings=settings,
            template=template,
        )

    def replace_application_websites(
        self, application_id: int, rows: list[dict]
    ) -> None:
        with self.conn:
            self.conn.execute(
                "DELETE FROM application_website WHERE application_id=?",
                (application_id,),
            )
            for i, r in enumerate(rows):
                self.conn.execute(
                    """INSERT INTO application_website
                       (application_id, sort_order, label, url)
                       VALUES (?,?,?,?)""",
                    (application_id, i, r.get("label", ""), r.get("url", "")),
                )

    def replace_application_keywords(
        self, application_id: int, names: list[str]
    ) -> None:
        with self.conn:
            self.conn.execute(
                "DELETE FROM application_keyword WHERE application_id=?",
                (application_id,),
            )
            for i, name in enumerate(names):
                if not name:
                    continue
                self.conn.execute(
                    """INSERT INTO application_keyword
                       (application_id, sort_order, name)
                       VALUES (?,?,?)""",
                    (application_id, i, name),
                )

    def replace_application_experiences(
        self, application_id: int, experiences: list[dict]
    ) -> None:
        """Each experience dict may carry a 'bullets' list[dict] (source_bullet_id, text)."""
        with self.conn:
            self.conn.execute(
                "DELETE FROM application_experience WHERE application_id=?",
                (application_id,),
            )
            for i, e in enumerate(experiences):
                cur = self.conn.execute(
                    """INSERT INTO application_experience
                       (application_id, source_experience_id, sort_order,
                        organization_name, position_name, organization_description,
                        organization_website, location, is_ongoing, start_date, end_date)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        application_id,
                        e.get("source_experience_id"),
                        i,
                        e.get("organization_name", ""),
                        e.get("position_name", ""),
                        e.get("organization_description"),
                        e.get("organization_website"),
                        e.get("location"),
                        int(bool(e.get("is_ongoing"))),
                        e.get("start_date"),
                        e.get("end_date"),
                    ),
                )
                ae_id = cur.lastrowid
                for j, b in enumerate(e.get("bullets") or []):
                    self.conn.execute(
                        """INSERT INTO application_bullet
                           (application_experience_id, source_bullet_id, sort_order, text)
                           VALUES (?,?,?,?)""",
                        (ae_id, b.get("source_bullet_id"), j, b.get("text", "")),
                    )

    def replace_application_education(
        self, application_id: int, rows: list[dict]
    ) -> None:
        with self.conn:
            self.conn.execute(
                "DELETE FROM application_education WHERE application_id=?",
                (application_id,),
            )
            for i, r in enumerate(rows):
                self.conn.execute(
                    """INSERT INTO application_education
                       (application_id, source_education_id, sort_order, degree, school,
                        school_url, location, field, gpa, is_ongoing, start_date, end_date)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        application_id,
                        r.get("source_education_id"),
                        i,
                        r.get("degree", ""),
                        r.get("school", ""),
                        r.get("school_url"),
                        r.get("location"),
                        r.get("field"),
                        r.get("gpa"),
                        int(bool(r.get("is_ongoing"))),
                        r.get("start_date"),
                        r.get("end_date"),
                    ),
                )

    def replace_application_projects(
        self, application_id: int, rows: list[dict]
    ) -> None:
        with self.conn:
            self.conn.execute(
                "DELETE FROM application_project WHERE application_id=?",
                (application_id,),
            )
            for i, r in enumerate(rows):
                self.conn.execute(
                    """INSERT INTO application_project
                       (application_id, source_project_id, sort_order, name, link,
                        start_date, end_date, is_ongoing, text)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (
                        application_id,
                        r.get("source_project_id"),
                        i,
                        r.get("name", ""),
                        r.get("link"),
                        r.get("start_date"),
                        r.get("end_date"),
                        int(bool(r.get("is_ongoing"))),
                        r.get("text"),
                    ),
                )

    def replace_application_languages(
        self, application_id: int, rows: list[dict]
    ) -> None:
        with self.conn:
            self.conn.execute(
                "DELETE FROM application_language WHERE application_id=?",
                (application_id,),
            )
            for i, r in enumerate(rows):
                self.conn.execute(
                    """INSERT INTO application_language
                       (application_id, source_language_id, sort_order, name, proficiency_level)
                       VALUES (?,?,?,?,?)""",
                    (
                        application_id,
                        r.get("source_language_id"),
                        i,
                        r.get("name", ""),
                        r.get("proficiency_level", ""),
                    ),
                )

    def update_application_contact(
        self,
        application_id: int,
        name: str,
        email: str,
        phone: str,
        location: str,
    ) -> None:
        self.execute(
            """UPDATE job_application
               SET contact_name=?, contact_email=?, contact_phone=?, contact_location=?
               WHERE id=?""",
            (name, email, phone, location, application_id),
        )

    def update_application_summary(self, application_id: int, text: str) -> None:
        self.execute(
            "UPDATE job_application SET summary_text=? WHERE id=?",
            (text, application_id),
        )

    def update_application_layout(
        self,
        application_id: int,
        section_order: str | None,
        sections_enabled: str | None,
    ) -> None:
        self.execute(
            """UPDATE job_application
               SET section_order=?, sections_enabled=?
               WHERE id=?""",
            (section_order, sections_enabled, application_id),
        )

    # ------------------------------------------------------------------
    # bullet overrides
    # ------------------------------------------------------------------

    def get_bullet_overrides(self, application_id: int) -> dict[int, str]:
        rows = self.fetch_all(
            "SELECT bullet_point_id, text FROM application_bullet_override WHERE application_id=?",
            (application_id,),
        )
        return {r["bullet_point_id"]: r["text"] for r in rows}

