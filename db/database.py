"""
db/database.py
Synchronous SQLite interface via stdlib sqlite3.
"""

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
    location   TEXT,
    field      TEXT,
    gpa        TEXT,
    is_ongoing INTEGER NOT NULL DEFAULT 0 CHECK (is_ongoing IN (0,1)),
    start_date TEXT,
    end_date   TEXT
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
    margin_top                REAL    NOT NULL DEFAULT 15.0,
    margin_bottom             REAL    NOT NULL DEFAULT 15.0,
    margin_left               REAL    NOT NULL DEFAULT 15.0,
    margin_right              REAL    NOT NULL DEFAULT 15.0,
    min_bullet_points_per_job INTEGER NOT NULL DEFAULT 2,
    max_bullet_points_per_job INTEGER NOT NULL DEFAULT 5
);

CREATE TABLE IF NOT EXISTS app_settings (
    id                  INTEGER PRIMARY KEY DEFAULT 1,
    section_order       TEXT    NOT NULL DEFAULT
        '["contact","summary","experience","education","projects","keywords","custom"]',
    sections_enabled    TEXT    NOT NULL DEFAULT
        '{"contact":1,"summary":1,"experience":1,"education":1,"projects":1,"keywords":1,"custom":0}',
    default_template_id INTEGER REFERENCES resume_template(id),
    pdf_output_folder   TEXT,
    pdf_filename_template TEXT  NOT NULL DEFAULT '{company}_{position}_{date}'
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
    date_format  TEXT    NOT NULL DEFAULT 'MMM YYYY'
);

CREATE TABLE IF NOT EXISTS job_application_status (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    status TEXT NOT NULL UNIQUE
);

INSERT OR IGNORE INTO job_application_status (status) VALUES
    ('to-apply'), ('applied'), ('phone-screen'), ('interview'),
    ('offer'), ('accepted'), ('ghosted'), ('rejected'), ('withdrawn');

CREATE TABLE IF NOT EXISTS application_bullet_override (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id INTEGER NOT NULL REFERENCES job_application(id) ON DELETE CASCADE,
    bullet_point_id INTEGER NOT NULL REFERENCES bullet_point(id)   ON DELETE CASCADE,
    text           TEXT NOT NULL,
    UNIQUE(application_id, bullet_point_id)
);

CREATE TABLE IF NOT EXISTS job_application (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id           INTEGER REFERENCES profile(id),
    status_id            INTEGER NOT NULL REFERENCES job_application_status(id),
    position_name        TEXT    NOT NULL,
    company_name         TEXT    NOT NULL,
    date_applied         TEXT,
    extra_keywords       TEXT    NOT NULL DEFAULT '[]',
    section_order        TEXT,
    sections_enabled     TEXT,
    resume_pdf_path      TEXT,
    keyword_list         TEXT,
    selected_summary_id  INTEGER,
    summary_text_override TEXT,
    contact_override     TEXT,
    websites_override    TEXT,
    included_experiences TEXT,
    included_education   TEXT,
    included_projects    TEXT
);
"""


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
        migrations = [
            ("job_application", "summary_text_override", "TEXT"),
            ("job_application", "contact_override",      "TEXT"),
            ("job_application", "websites_override",     "TEXT"),
            ("job_application", "selected_summary_id",   "INTEGER"),
            ("job_application", "included_experiences",  "TEXT"),
            ("job_application", "included_education",    "TEXT"),
            ("job_application", "included_projects",     "TEXT"),
            ("app_settings",    "pdf_output_folder",     "TEXT"),
            ("app_settings",    "pdf_filename_template",
             "TEXT NOT NULL DEFAULT '{company}_{position}_{date}'"),
            ("job_application", "included_bullets",      "TEXT"),
            ("profile",         "summary",               "TEXT"),
            ("job_application", "education_overrides",   "TEXT"),
        ]
        for table, column, col_def in migrations:
            try:
                self._conn.execute(
                    f"ALTER TABLE {table} ADD COLUMN {column} {col_def}"
                )
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
            (contact_id,)
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
        contact  = self.get_contact()
        websites = self.get_contact_websites(contact["id"]) if contact else []

        # get profile summary directly
        profile  = self.fetch_one("SELECT * FROM profile WHERE id=?", (profile_id,))
        summary_text = (profile or {}).get("summary") or ""

        experiences = []
        for job in self.get_work_experiences():
            bullets = []
            for bp in self.get_bullet_points(job["id"]):
                bullets.append({
                    **bp,
                    "keyword_ids": self.get_bullet_point_keywords(bp["id"]),
                })
            experiences.append({**job, "bullet_points": bullets})

        education = self.get_education()

        projects = []
        for p in self.get_projects():
            projects.append({**p, "keyword_ids": self.get_project_keywords(p["id"])})

        profile_keywords = self.get_profile_keywords(profile_id)
        settings         = self.get_settings()
        profile_settings = self.get_profile_settings(profile_id)

        template = None
        config   = self.fetch_one(
            "SELECT * FROM resume_config WHERE profile_id=? LIMIT 1", (profile_id,)
        )
        tmpl_id  = (config or {}).get("template_id") or \
                   (settings or {}).get("default_template_id")
        if tmpl_id:
            template = self.fetch_one(
                "SELECT * FROM resume_template WHERE id=?", (tmpl_id,)
            )

        return dict(
            contact          = contact,
            websites         = websites,
            summary_text     = summary_text,
            experiences      = experiences,
            education        = education,
            projects         = projects,
            profile_keywords = profile_keywords,
            settings         = settings,
            profile_settings = profile_settings,
            template         = template,
        )

    # ------------------------------------------------------------------
    # templates
    # ------------------------------------------------------------------

    def get_templates(self) -> list[dict]:
        return self.fetch_all("SELECT * FROM resume_template ORDER BY name")

    def upsert_template(
        self, name: str,
        font_family: str, font_size: float,
        margin_top: float, margin_bottom: float,
        margin_left: float, margin_right: float,
        min_bp: int, max_bp: int,
        id: int | None = None,
    ) -> int:
        if id:
            self.execute(
                """UPDATE resume_template SET name=?, font_family=?, font_size=?,
                   margin_top=?, margin_bottom=?, margin_left=?, margin_right=?,
                   min_bullet_points_per_job=?, max_bullet_points_per_job=?
                   WHERE id=?""",
                (name, font_family, font_size,
                 margin_top, margin_bottom, margin_left, margin_right,
                 min_bp, max_bp, id),
            )
            return id
        return self.execute(
            """INSERT INTO resume_template
               (name, font_family, font_size,
                margin_top, margin_bottom, margin_left, margin_right,
                min_bullet_points_per_job, max_bullet_points_per_job)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (name, font_family, font_size,
             margin_top, margin_bottom, margin_left, margin_right,
             min_bp, max_bp),
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
    ) -> None:
        self.execute(
            """INSERT INTO app_settings
               (id, section_order, sections_enabled, default_template_id,
                pdf_output_folder, pdf_filename_template)
               VALUES (1,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET
                 section_order=excluded.section_order,
                 sections_enabled=excluded.sections_enabled,
                 default_template_id=excluded.default_template_id,
                 pdf_output_folder=excluded.pdf_output_folder,
                 pdf_filename_template=excluded.pdf_filename_template""",
            (section_order, sections_enabled, default_template_id,
             pdf_output_folder, pdf_filename_template),
        )

    def get_profile_settings(self, profile_id: int) -> dict | None:
        return self.fetch_one(
            "SELECT * FROM profile_settings WHERE profile_id=?", (profile_id,)
        )

    def save_profile_settings(
        self, profile_id: int,
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
                r.get("start_date") or "0000-00-00"
            ),
            reverse=True
        )

    def upsert_work_experience(
        self, org: str, position: str, location: str,
        is_ongoing: bool, start_date: str, end_date: str | None,
        id: int | None = None
    ) -> int:
        if id:
            self.execute(
                """UPDATE work_experience SET organization_name=?, position_name=?,
                   location=?, is_ongoing=?, start_date=?, end_date=? WHERE id=?""",
                (org, position, location, int(is_ongoing), start_date, end_date, id),
            )
            return id
        return self.execute(
            """INSERT INTO work_experience
               (organization_name, position_name, location, is_ongoing, start_date, end_date)
               VALUES (?,?,?,?,?,?)""",
            (org, position, location, int(is_ongoing), start_date, end_date),
        )

    def delete_work_experience(self, id: int) -> None:
        self.execute("DELETE FROM work_experience WHERE id=?", (id,))

    def get_bullet_points(self, work_experience_id: int) -> list[dict]:
        return self.fetch_all(
            "SELECT * FROM bullet_point WHERE work_experience_id=? ORDER BY sort_order",
            (work_experience_id,),
        )

    def upsert_bullet_point(
        self, work_experience_id: int, text: str,
        sort_order: int = 0, id: int | None = None,
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

    def set_bullet_point_keywords(self, bullet_point_id: int, keyword_ids: list[int]) -> None:
        self.execute(
            "DELETE FROM bullet_point_keyword WHERE bullet_point_id=?", (bullet_point_id,)
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
        self, degree: str, school: str, location: str, field: str,
        gpa: str, is_ongoing: bool, start_date: str, end_date: str | None,
        id: int | None = None
    ) -> int:
        if id:
            self.execute(
                """UPDATE education SET degree=?, school=?, location=?, field=?,
                   gpa=?, is_ongoing=?, start_date=?, end_date=? WHERE id=?""",
                (degree, school, location, field, gpa, int(is_ongoing), start_date, end_date, id),
            )
            return id
        return self.execute(
            """INSERT INTO education
               (degree, school, location, field, gpa, is_ongoing, start_date, end_date)
               VALUES (?,?,?,?,?,?,?,?)""",
            (degree, school, location, field, gpa, int(is_ongoing), start_date, end_date),
        )

    def delete_education(self, id: int) -> None:
        self.execute("DELETE FROM education WHERE id=?", (id,))

    # ------------------------------------------------------------------
    # projects
    # ------------------------------------------------------------------

    def get_projects(self) -> list[dict]:
        return self.fetch_all(
            "SELECT * FROM project ORDER BY is_ongoing DESC, start_date DESC"
        )

    def upsert_project(
        self, name: str, link: str, start_date: str, end_date: str | None,
        is_ongoing: bool, text: str, id: int | None = None
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

    def upsert_profile(self, name: str, summary: str = "", id: int | None = None) -> int:
        if id:
            self.execute(
                "UPDATE profile SET name=?, summary=? WHERE id=?",
                (name, summary, id)
            )
            return id
        return self.execute(
            "INSERT INTO profile (name, summary) VALUES (?,?)", (name, summary)
        )

    def delete_profile(self, id: int) -> None:
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
            (id,)
        )

    def upsert_application(
        self,
        profile_id: int | None,
        status_id: int,
        position_name: str,
        company_name: str,
        date_applied: str,
        extra_keywords: str = "[]",
        section_order: str | None = None,
        sections_enabled: str | None = None,
        resume_pdf_path: str | None = None,
        selected_summary_id: int | None = None,
        summary_text_override: str | None = None,
        contact_override: str | None = None,
        websites_override: str | None = None,
        included_experiences: str | None = None,
        included_education: str | None = None,
        included_projects: str | None = None,
        included_bullets: str | None = None,
        education_overrides: str | None = None,
        id: int | None = None,
    ) -> int:
        if id:
            self.execute(
                """UPDATE job_application SET
                   profile_id=?, status_id=?, position_name=?, company_name=?,
                   date_applied=?, extra_keywords=?, section_order=?,
                   sections_enabled=?, resume_pdf_path=?,
                   selected_summary_id=?, summary_text_override=?,
                   contact_override=?, websites_override=?,
                   included_experiences=?, included_education=?,
                   included_projects=?, included_bullets=?,
                   education_overrides=?
                   WHERE id=?""",
                (profile_id, status_id, position_name, company_name,
                 date_applied, extra_keywords, section_order, sections_enabled,
                 resume_pdf_path, selected_summary_id, summary_text_override,
                 contact_override, websites_override,
                 included_experiences, included_education,
                 included_projects, included_bullets,
                 education_overrides, id),
            )
            return id
        return self.execute(
            """INSERT INTO job_application
               (profile_id, status_id, position_name, company_name,
                date_applied, extra_keywords, section_order, sections_enabled,
                selected_summary_id, summary_text_override,
                contact_override, websites_override,
                included_experiences, included_education,
                included_projects, included_bullets,
                education_overrides)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (profile_id, status_id, position_name, company_name,
             date_applied, extra_keywords, section_order, sections_enabled,
             selected_summary_id, summary_text_override,
             contact_override, websites_override,
             included_experiences, included_education,
             included_projects, included_bullets,
             education_overrides),
        )

    def delete_application(self, id: int) -> None:
        self.execute("DELETE FROM job_application WHERE id=?", (id,))

    def get_statuses(self) -> list[dict]:
        return self.fetch_all("SELECT * FROM job_application_status")

    # ------------------------------------------------------------------
    # bullet overrides
    # ------------------------------------------------------------------

    def get_bullet_overrides(self, application_id: int) -> dict[int, str]:
        rows = self.fetch_all(
            "SELECT bullet_point_id, text FROM application_bullet_override WHERE application_id=?",
            (application_id,)
        )
        return {r["bullet_point_id"]: r["text"] for r in rows}

    def set_bullet_override(self, application_id: int, bullet_point_id: int, text: str) -> None:
        self.execute(
            """INSERT INTO application_bullet_override (application_id, bullet_point_id, text)
               VALUES (?,?,?)
               ON CONFLICT(application_id, bullet_point_id)
               DO UPDATE SET text=excluded.text""",
            (application_id, bullet_point_id, text),
        )

    def clear_bullet_overrides(self, application_id: int) -> None:
        self.execute(
            "DELETE FROM application_bullet_override WHERE application_id=?",
            (application_id,)
        )