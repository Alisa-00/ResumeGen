# Manual / Real-Scenario Test Plan

Remaining real-scenario tests for this round of fixes. Cases that were already
executed successfully **and cleanly** have been removed; items proven by the
automated suite are listed in
[§4 Already covered](#4-already-covered-by-automation--no-manual-test-needed) and
have no manual case.

What's left:
- **A1, A2** — the change under test passed, but both surfaced an unrelated
  window-geometry glitch (see [Open issue W1](#open-issue-w1--window-geometry-glitch))
  that still needs triage.
- **B1, B2** — sync tests; **not yet run** (need a live SpacetimeDB server).

---

## 1. Remaining items & UI impact

"UI change?" = did the change touch a file under `ui/` or a user-facing widget?

| Item | What changed | Files | UI change? | Status |
|------|--------------|-------|------------|--------|
| **H1** | Atomic application save (`transaction()`) | `db/database.py`, `ui/wizard/step_preview.py` | **Yes** (wizard save) | Passed (A1); W1 open |
| **Dead code** | Removed unused string-template path, async PDF wrapper, dead language method | `templates/templates.py`, `pdf/convert.py`, `ui/wizard/step_preview.py` | **Yes** (dead method removed; no behaviour change) | Passed (A2); W1 open |
| **M1** | Validate incoming DB before swap + rollback on failure | `sync/engine.py` | No (effect refreshes UI via `reload_views`) | Pending (B1) |
| **M2** | Defer pull while a wizard is open | `ui/ui.py` | **Yes** (pull-apply guard) | Pending (B2) |

> Removed as done-and-clean: **S2** (config `0600`), **M3** (worker traceback
> logging), **L6** (preview temp-file cleanup).

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
- **Run from a terminal** — the sync/status messages (`[SYNC] …`) print to stdout.

**Sync tests (§3.B) additionally need** a running SpacetimeDB module and two app
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

#### Results
- Application was created successfully, edits are being made and stored correctly
- Application preview and pdf generation work correctly
- **H1 functionality: PASS.**
- Note: window size "weirds out" when going from the Applications view to the
  wizard → tracked as [W1](#open-issue-w1--window-geometry-glitch) (unrelated to H1).

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

#### Results
- Application pdf renders correctly.
- Application regenerates automatically on edits.
- Application pdf can be downloaded correctly.
- **Dead-code regression: PASS.**
- Note: the **Download** button reproduces the same window-geometry glitch →
  tracked as [W1](#open-issue-w1--window-geometry-glitch) (unrelated to the removed code).

---

#### Open issue W1 — window geometry glitch
Surfaced while running A1 and A2. **Not a regression from this round's changes.**

**Symptoms:** the window size "weirds out" (a) when navigating from the
Applications view into the wizard, and (b) when clicking the **Download** button
in the preview step.

**Investigation:**
- None of this round's diffs touch window geometry — no `resize` / `showMaximized`
  / `showNormal` / `setFixedSize` / size-policy / splitter changes were made.
  `_download` only writes the file and sets a status label; it cannot resize the
  window. So this is a **pre-existing UI/layout quirk**, independent of
  S1/S2/S3/H1/dead-code/M3/M1/M2/L6.
- Likely contributing factors for a future fix (not yet confirmed against a live
  GUI): the app runs `showMaximized()` (`main.py:240`) while child widgets set
  large minimum widths (`step_preview.py:99` `setMinimumWidth(400)`,
  `applications.py:438` `setMinimumWidth(420)`, etc.) and the embedded `QPdfView`
  reports a page-sized `sizeHint`; when the `QStackedWidget` swaps pages the
  top-level window may re-fit to those hints.

**Next step:** triage as a standalone UI bug (out of scope for the fixes this doc
verifies). No code change made yet.

---

### B. Cross-machine sync (live SpacetimeDB required) — NOT YET RUN

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

#### Results
- Tests not yet done

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

#### Results
- Tests not yet done

---

## 4. Already covered by automation — no manual test needed

| Item | Why no manual test |
|------|--------------------|
| **S1** — fd leak fix | Deterministic; verified by counting open fds across 200 `make_snapshot` calls (delta 0). No real-world variance. |
| **S3** — `snapshot_id` validation | Pure input-validation logic; verified against injection strings, wrong lengths/case, empty, and a newline-bypass attempt, plus a valid uuid4 passing the guard. Real legitimate pulls are additionally exercised by **B1**. |
| **H1** — atomic rollback edge | The failure path (mid-save error → full rollback, connection still usable, tx depth reset) is verified by automated tests, including a realistic `upsert_application` + bad-FK bullet override. The **happy path** was checked manually in **A1** (passed). |
| **M1** — corrupt-download / rollback edges | Verified by automated tests: garbage bytes refused with the live DB untouched, and a simulated mid-swap `reopen()` failure restoring the backup. The **happy path** is checked manually in **B1**. |

---

## 5. Not in scope (unchanged this round)

`S4` (close-time push UX) and `S5` (surface incompatible-version pull) were
analysed but **not implemented**, so they have no test cases here. Remaining P3
quality items (`L4`, `L7`, `L8`, `L9`) are likewise untouched.
