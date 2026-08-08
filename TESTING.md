# Manual / Real-Scenario Test Plan

Covers the behavior changed in this round of fixes that the **automated** checks
could not exercise in a real running application — i.e. the real GUI, real files
on disk, and (where noted) a live SpacetimeDB sync server.

Pure-logic changes are already covered by `tests/test_sync.py` and the ad-hoc
verification scripts run during development; those are listed under
[§4 Already covered — no manual test needed](#4-already-covered-by-automation--no-manual-test-needed)
and deliberately have **no** manual cases here.

---

## 1. Change summary & UI impact

"UI change?" = did the change touch a file under `ui/` or a user-facing widget?

| Item | What changed | Files | UI change? | Needs real-scenario test? |
|------|--------------|-------|------------|---------------------------|
| **S1** | Close leaked fd from `mkstemp` | `sync/engine.py` | No | No — deterministic, auto-verified |
| **S2** | Sync config written `0600` | `sync/config.py` | No | Yes (light) — verify via the Settings save path |
| **H1** | Atomic application save (`transaction()`) | `db/database.py`, `ui/wizard/step_preview.py` | **Yes** (wizard save) | Yes — real wizard save/edit flow |
| **Dead code** | Removed unused string-template path, async PDF wrapper, dead language method | `templates/templates.py`, `pdf/convert.py`, `ui/wizard/step_preview.py` | **Yes** (dead method removed from wizard file; no behaviour change) | Yes — regression: generation + preview still work |
| **M3** | Worker failures log full traceback | `ui/ui.py` | **Yes** (worker infra in the UI module; not a visible widget) | Yes — confirm traceback in console + short message in UI |
| **S3** | Validate `snapshot_id` before SQL interpolation | `sync/client.py` | No | No — logic auto-verified; real pulls covered by B1 |
| **M1** | Validate incoming DB before swap + rollback on failure | `sync/engine.py` | No (effect refreshes UI via `reload_views`) | Yes — real live-server pull (happy path) |
| **M2** | Defer pull while a wizard is open | `ui/ui.py` | **Yes** (pull-apply guard) | Yes — real pull arriving with wizard open |
| **L6** | Preview temp-file cleanup (atexit + close) | `pdf/display.py` | **Yes** (the preview widget) | Yes — temp-file lifecycle in the real app |

---

## 2. Setup

**App:**
```bash
cd /home/sandbox/ResumeGen/dev
.venv/bin/python main.py          # run from a terminal so stdout/stderr are visible
```
- On first launch the app asks for a database folder (`resolve_db_path`). Use a
  throwaway folder for testing. To re-trigger the picker, delete
  `~/.resume_orchestrator`.
- **Run from a terminal** for every test below — the sync/status messages
  (`[SYNC] …`) print to stdout and the M3 tracebacks go to stderr.

**Sync tests (§3) additionally need** a running SpacetimeDB module and two app
instances that share one identity token. Follow `DEPLOYMENT.md` →
"Deployment steps" and "Post-deployment verification". Simulate a second machine
with a second checkout/instance under a separate `HOME` so it has its own
`~/.resume_orchestrator*` files but the same token.

---

## 3. Test cases

### A. Local app (no server needed)

#### A1 — H1: wizard save persists all fields  · **[UI change]**
The application save was refactored from a hand-rolled `BEGIN`/`commit` on a
private connection to `Database.transaction()`. Verify the real save still writes
everything.

**Preconditions:** at least one profile, some work experience with bullet points,
and a few keywords exist.

**Steps:**
1. Applications → **New application**. Fill in company, position, status.
2. In the preview step, make edits that touch several tables at once: toggle a few
   keywords, edit/override a bullet point, change section order / enabled sections,
   edit the summary, include/exclude an experience or language.
3. Click **Save**. Confirm the status shows "Saved".
4. Close the wizard, reopen the same application.

**Expected:** every edit from step 2 is present after reopening — keywords,
bullet override text, section order/enabled flags, summary, and inclusion lists
all round-trip. Nothing is silently dropped, and no error appears in the terminal.

> The atomic-rollback edge (partial failure → nothing persists) is covered by
> automated tests and is not easily reproducible by hand; this case verifies the
> happy-path regression of the refactor.

---

#### A2 — Dead-code regression: generation + preview still work  · **[UI change: dead method removed]**
Removing `render_from_string`, the async `html_to_pdf_bytes`, and the dead
language method must not affect the live generation path (`render_from_file` →
WeasyPrint) or the preview.

**Steps:**
1. Open an application in the wizard and reach the preview step.
2. Let the resume PDF generate; make an edit and let it regenerate.
3. Use the **Download** button to export the PDF.

**Expected:** the PDF renders in the preview pane, regenerates on edits, and the
downloaded file opens correctly in an external viewer. No import/attribute errors
in the terminal.

---

#### A3 — L6: preview temp-file cleanup  · **[UI change]**
Preview PDFs are written to per-widget temp files; cleanup was hardened
(close-before-rewrite + `atexit` backstop + cleanup on `closeEvent`).

**Steps:**
1. Note temp dir contents: `ls /tmp/*.pdf` (or `$TMPDIR`).
2. In the wizard preview, trigger several regenerations (make multiple edits).
   Confirm no errors and each regeneration updates the preview.
3. Close the wizard and/or quit the app normally.
4. Re-check the temp dir.

**Expected:** repeated regeneration never errors (no file-lock failure); after the
app exits, no leftover preview `*.pdf` temp files remain. While running, the temp
file(s) should be owner-only (`-rw-------`).

---

#### A4 — M3: background failure logs a full traceback  · **[UI change: worker infra]**
A worker exception used to surface only as a one-line string; it now also logs the
full traceback while still delivering the short message to the UI.

**Preconditions:** none — trigger a guaranteed sync failure.

**Steps:**
1. Settings → Sync: enable sync and set the server URL to something unreachable
   (e.g. `https://127.0.0.1:9`), any module name, any token.
2. Click **Sync now**.

**Expected:**
- The Settings status shows a short message like `Sync failed: Cannot reach sync
  server: …`.
- The **terminal (stderr)** shows a full Python traceback under
  `background task failed` (from `logging.exception`) — not just the one-liner.

---

#### A5 — S2: sync config file is owner-only  · (no UI change; reached via Settings)
The per-machine config holds the bearer token and must be written `0600`.

**Steps:**
1. Delete any existing `~/.resume_orchestrator_sync.json`.
2. Settings → Sync: enter server URL, module, and token; enable sync and save
   (or click Sync now). This writes the config through the real Settings path.
3. `ls -l ~/.resume_orchestrator_sync.json`.

**Expected:** permissions are `-rw-------` (0600). (POSIX only; on Windows this is
a no-op by design.)

---

### B. Cross-machine sync (live SpacetimeDB required)

#### B1 — M1: a normal pull applies safely  · (no UI change; triggers `reload_views`)
Also exercises **S3** implicitly — real snapshot ids are uuid4 hex and must pass
the new validation.

**Preconditions:** two instances (A and B) sharing one token, both synced once.

**Steps:**
1. On instance B, edit some data (e.g. add a project) and close the app (push on
   close), or use Sync now.
2. On instance A, click **Sync now** (or restart to trigger the startup pull).

**Expected:**
- Instance A adopts B's changes; the views refresh to show them.
- A timestamped `*.db.bak-*` backup file appears next to the database.
- Terminal shows `[SYNC] adopted server snapshot seq N`.
- No `Unsafe snapshot_id` or integrity errors (confirms S3 accepts real ids and
  M1's `quick_check` passes on a healthy download).

---

#### B2 — M2: pull is deferred while a wizard is open  · **[UI change]**
A pull must not swap the database out from under an open wizard with unsaved edits.

**Preconditions:** the server has a **newer** snapshot than instance A (create it
from instance B first). A larger DB makes the pull slower and the race easier to
hit.

**Steps:**
1. On instance A, launch the app and **immediately** open a new-application wizard
   (before the startup pull finishes downloading), and start entering data.
2. Watch the terminal.
3. Close the wizard, then trigger another sync (Settings → **Sync now**).

**Expected:**
- While the wizard is open, the terminal logs
  `[SYNC] pull: wizard open, deferring snapshot apply`, and your in-progress
  wizard edits are **not** disturbed (no view rebuild, no data swap).
- After closing the wizard, the next sync applies the server snapshot normally
  (`[SYNC] adopted server snapshot seq N`).

> This is timing-dependent. If the pull completes before you open the wizard, redo
> with a larger database (slower download) to widen the window. The deferral logic
> itself is also covered by automated tests.

---

## 4. Already covered by automation — no manual test needed

| Item | Why no manual test |
|------|--------------------|
| **S1** — fd leak fix | Deterministic; verified by counting open fds across 200 `make_snapshot` calls (delta 0). No real-world variance. |
| **S3** — `snapshot_id` validation | Pure input-validation logic; verified against injection strings, wrong lengths/case, empty, and a newline-bypass attempt, plus a valid uuid4 passing the guard. Real legitimate pulls are additionally exercised by **B1**. |
| **H1** — atomic rollback edge | The failure path (mid-save error → full rollback, connection still usable, tx depth reset) is verified by automated tests, including a realistic `upsert_application` + bad-FK bullet override. The **happy path** is checked manually in **A1**. |
| **M1** — corrupt-download / rollback edges | Verified by automated tests: garbage bytes refused with the live DB untouched, and a simulated mid-swap `reopen()` failure restoring the backup. The **happy path** is checked manually in **B1**. |

---

## 5. Not in scope (unchanged this round)

`S4` (close-time push UX) and `S5` (surface incompatible-version pull) were
analysed but **not implemented**, so they have no test cases here. Remaining P3
quality items (`L4`, `L7`, `L8`, `L9`) are likewise untouched.
