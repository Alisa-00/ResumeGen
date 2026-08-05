# AGENTS.md - ResumeGen Development Guide

This file provides guidelines for agents working on the ResumeGen codebase.

## Project Overview

ResumeGen is a PySide6 desktop application that lets users maintain a master database of their work experience, education, projects, and skills, then generate tailored resumes for each job application.

- **UI Framework**: PySide6 (Qt for Python)
- **Database**: SQLite (local, private storage)
- **Templating**: Jinja2 for HTML resume templates
- **PDF Generation**: WeasyPrint

---

## Running the Application

```bash
# Install dependencies
pip install -r requirements.txt

# Run the application
python main.py
```

## Build/Lint/Test Commands

tests/test_sync.py

### Adding Tests (Recommended)

If you add tests in the future:

```bash
# pytest
pip install pytest pytest-qt
pytest                          # run all tests
pytest tests/test_database.py   # run specific test file
pytest -k test_name             # run tests matching pattern
```

### Code Quality Tools (Recommended)

```bash
# Install
pip install ruff black mypy

# Lint with ruff
ruff check .

# Format with black
black .

# Type check with mypy
mypy .
```

---

## Code Style Guidelines

### General Principles

- Use Python 3.10+ syntax and features
- Use `from __future__ import annotations` for forward reference type hints
- Keep functions focused and small (under 50 lines when possible)
- Use descriptive variable names - avoid single letters except in tight loops
- Document public APIs with docstrings; private methods may skip docstrings

### Imports

```python
# Standard library first, then third-party, then local
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout

from db.database import Database
from ui.views.contact import ContactView
from ui.widgets import section_title, primary_btn
```

- Sort imports alphabetically within each group
- Use explicit relative imports for local modules (`from db.database import Database`)
- Avoid wildcard imports (`from x import *`)

### Type Hints

```python
# Use Python 3.10+ union syntax
def fetch_one(self, sql: str, params: tuple = ()) -> dict | None:
    ...

# Class attributes need type annotations
class ContactView(QWidget):
    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db: Database = db
        self._website_rows: list[_WebsiteRow] = []
```

- Always provide return types for functions/methods
- Use `dict | None` not `Optional[dict]`
- Use `list[dict]` not `List[dict]`
- Type private methods if they are complex or public-facing

### Naming Conventions

| Element | Convention | Example |
|---------|------------|---------|
| Modules | snake_case | `database.py`, `resume_generator.py` |
| Classes | PascalCase | `Database`, `ContactView`, `_WebsiteRow` |
| Functions/methods | snake_case | `get_contact()`, `_build_ui()` |
| Private methods | leading underscore | `_save()`, `_load()` |
| Constants | UPPER_SNAKE_CASE | `SCHEMA_SQL` |
| Database columns | snake_case | `organization_name`, `is_ongoing` |
| UI widget variables | descriptive with prefix | `self.f_name`, `self._nav`, `self._main_stack` |

### Function Organization

1. Type hints on all functions
2. Keep functions under 60 lines
3. Extract helper functions when logic repeats
4. Database class: group methods by concern (lifecycle, helpers, contact, experience, etc.)

### Error Handling

```python
# For expected errors (column missing, etc.), handle gracefully
try:
    self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}")
except sqlite3.OperationalError as e:
    if "duplicate column name" in str(e).lower():
        pass  # expected - column already exists
    else:
        raise

# For unexpected errors, raise with context
raise RuntimeError(f"[MIGRATE] Unexpected error adding {table}.{column}: {e}") from e

# For database errors
except sqlite3.DatabaseError as e:
    raise RuntimeError(f"[MIGRATE] Database error: {e}") from e
```

- Never silently swallow exceptions unless explicitly expected
- Provide context in error messages (what operation failed)
- Use `from e` to preserve the original traceback

### Database Patterns

```python
# Connection lifecycle
db = Database(db_path)
db.connect()
try:
    # work with db
    db.execute(...)
finally:
    db.close()

# Always use parameterized queries - never f-strings for SQL
self.conn.execute("SELECT * FROM table WHERE id=?", (id,))

# Use fetch_one/fetch_all helpers (see db/database.py)
def fetch_one(self, sql: str, params: tuple = ()) -> dict | None:
    cur = self.conn.execute(sql, params)
    row = cur.fetchone()
    return dict(row) if row else None
```

### UI/PySide6 Patterns

```python
# Main window pattern
class AppWindow(QMainWindow):
    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self._build_ui()

    def _build_ui(self):
        ...

# Use signals for communication between threads
from PySide6.QtCore import Signal, QThreadPool, QRunnable

class _Signals(QObject):
    finished = Signal(object)
    error = Signal(str)

# Worker threads for long-running operations (PDF generation)
# Must create separate Database connection in worker thread
# Use WAL mode in Database for thread-safe concurrent reads
```

### File Structure

```
resumegen/
├── main.py              # Entry point, app initialization
├── db/
│   └── database.py      # SQLite interface
├── ui/
│   ├── ui.py           # Main window, navigation
│   ├── widgets.py      # Reusable UI components
│   ├── views/          # View widgets for each section
│   │   ├── contact.py
│   │   ├── experience.py
│   │   ├── education.py
│   │   └── ...
│   └── wizard/          # Application wizard
├── resume/
│   └── generator.py    # Resume PDF generation
├── pdf/
│   ├── convert.py      # HTML to PDF conversion
│   └── display.py      # PDF preview
├── templates/
│   ├── templates.py    # Jinja2 template loading
│   └── html/           # HTML templates
└── requirements.txt
```

---

## Common Development Tasks

### Adding a New Database Column

1. Add column to `SCHEMA_SQL` in `db/database.py`
2. Add migration in `_migrate()` method
3. Add getter/setter methods in Database class
4. Update UI views as needed
5. **Bump `APP_VERSION` in `version.py`** — minor for a backward-compatible
   addition (older clients can still read the file), major only for a change
   that older clients must NOT adopt. Sync uses this to decide which snapshots a
   client may pull (same major, minor >= local). The version is stamped into the
   DB file via `PRAGMA user_version` on connect and travels with the data.

### Adding a New UI View

1. Create `ui/views/<view_name>.py` with QWidget subclass
2. Add import in `ui/ui.py`
3. Add to `NAV_ITEMS` list in `ui/ui.py`
4. Add builder mapping in `_build_view()`

### Modifying the Resume Template

Edit HTML files in `templates/html/` directory. Use Jinja2 syntax for dynamic content. Context variables are defined in `templates/templates.py:build_context()`.

---

## Database Schema Reference

Key tables:
- `keyword` - searchable keywords for experiences/projects
- `contact` - user contact information
- `work_experience` - job history with bullet points
- `bullet_point` - accomplishments linked to experiences
- `education` - degrees and schools
- `project` - side projects with descriptions
- `profile` - resume profiles (summaries + keywords)
- `job_application` - applications with overrides
- `resume_template` - PDF styling settings

---

### Sync (cross-machine)

Optional, off by default, never required for local use. See `sync/` and
`server/`.

- Whole-DB **snapshot** sync, last-write-wins. The gzipped SQLite file is the
  unit; no per-row merge. A pull always backs up the local DB first.
- Per-machine config/state lives in `~/.resume_orchestrator_sync.json`
  (`sync/config.py`) — **never** in `app_settings`, which is inside the synced DB.
- Backend is a SpacetimeDB module (`server/`, Rust) reached over its HTTP API via
  `sync/client.py` (stdlib `urllib` only). `SyncClient` is the abstraction.
- `sync/engine.py`: `push`/`pull_fetch` are network-only and worker-thread safe
  (they use private sqlite connections + `make_snapshot`); `pull_apply` swaps the
  DB file and **must run on the UI thread** (`AppWindow._apply_pull`).
- Triggers: pull on startup, push on app close, manual "Sync now" (Settings → Sync).
- Tests: `python3 tests/test_sync.py` (no pytest/PySide6 needed).

## Notes for Agents

- The app stores its database path in `~/.resume_orchestrator`
- Database uses WAL mode for thread-safe concurrent reads
- PDF generation runs in a QThreadPool worker thread
- All dates stored as ISO strings (YYYY-MM-DD)
- Boolean columns use INTEGER (0/1) for SQLite compatibility
- The DB schema/app version lives in `version.py` (`APP_VERSION`) and is stamped
  into each DB file's `PRAGMA user_version`; sync relies on it
