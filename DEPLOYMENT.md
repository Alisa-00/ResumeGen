# Sync Component — Deployment & Testing Guide (dev/testing)

This document covers deploying and testing the **sync component** of ResumeGen. It records the steps and known gaps as of 2026-08-05; nothing here has been executed yet against a live SpacetimeDB instance.

## Architecture recap

ResumeGen has two components:

1. **Local-first desktop app** — PySide6 + stdlib SQLite (WAL) + Jinja2 + WeasyPrint. Fully functional standalone; sync is optional and off by default.
2. **Sync component** — cross-machine sync built on **SpacetimeDB**:
   - `server/` — a Rust → WASM SpacetimeDB module (`server/src/lib.rs`): two tables (`snapshot`, `snapshot_chunk`), two reducers (`push_snapshot`, `push_chunk`), row-level security scoping rows to the owning SpacetimeDB `Identity`.
   - `sync/` — stdlib-only Python client and engine. Whole-database gzipped snapshot sync, last-write-wins, chunked at 128 KB. Reads go through SpacetimeDB's one-off SQL HTTP endpoint (`POST /v1/database/{module}/sql`), writes through reducer calls (`POST /v1/database/{module}/call/{reducer}`), authenticated with a static bearer identity token.
   - Triggers: pull on app startup, push on app close, manual "Sync now" (Settings → Sync). A pull always backs up the local DB to `*.db.bak-<timestamp>` before swapping the file.
   - Version gating: `version.py` `APP_VERSION = (0, 1)`; a client only pulls snapshots with the same major and remote minor ≥ local.

## Readiness status

| Area | Status |
|---|---|
| Python client/engine (`sync/`) | Ready for dev testing — unit-tested against fakes, thread-aware |
| Unit tests (`tests/test_sync.py`) | 6 tests, no server or PySide6 needed |
| Rust server module (`server/`) | **Rewritten for SpacetimeDB 2.7.1** (2026-08-05); compiles clean (`cargo check`, wasm release build, `spacetime build`); `Cargo.lock` committed |
| Deployment automation | None (no Dockerfile, compose, CI, scripts) |
| HTTP transport (`SpacetimeHttpClient`) | **Zero test coverage** — only the fake client is exercised |

Verdict: ready for a dev/testing deployment. The remaining unknowns are runtime-only (RLS enforcement, live wire round-trip) — see the verification steps.

## Prerequisites

- Rust toolchain via `rustup`, with the `wasm32-unknown-unknown` target added.
- The `spacetime` CLI — https://spacetimedb.com/install
- Python environment able to run the desktop app (see `requirements.txt`); the sync client itself needs only the stdlib.

## Deployment steps (local dev instance)

1. **Check CLI version** — `spacetime --version`. The module targets **2.7.1**; keep `server/Cargo.toml` in lockstep.
2. **Compile the module** — in `server/`: `spacetime build` (or `cargo build --target wasm32-unknown-unknown --release`). Already verified clean against 2.7.1; `wasm-opt` (binaryen) is optional for a smaller module.
3. **Start a local instance**:
   ```bash
   spacetime start &
   ```
   Serves on `http://127.0.0.1:3000`.
4. **Publish the module**:
   ```bash
   spacetime login
   spacetime publish --project-path server my-resume-sync --server local
   ```
5. **Get the identity token** — `spacetime login --token` (or read it from the `~/.spacetime` config). The **same token on every device** is what links devices to one snapshot history.
6. **Configure the app** — Settings → Sync: enable sync, server URL `http://127.0.0.1:3000`, module name `my-resume-sync`, paste the token. Config is stored per-machine in `~/.resume_orchestrator_sync.json` (never inside the synced DB).

**Maincloud alternative to steps 3–4:** `spacetime publish --project-path server my-resume-sync` and use `https://maincloud.spacetimedb.com` as the server URL.

**Storage hygiene:** old snapshots are kept forever unless pruned. Occasionally run `spacetime call my-resume-sync prune_snapshots 5` (keeps each caller's newest 5 snapshots, deletes older ones plus stale orphan chunks).

## Testing

### Unit tests (no server needed)

```bash
uv run python tests/test_sync.py
```

Hand-rolled runner (not pytest); covers versioning helpers, deterministic snapshots, chunking round-trip, push skip-when-unchanged, two-engine end-to-end convergence, and major-version gating — all against temp SQLite files and an in-memory fake server.

### Post-deployment verification (in order)

1. **Wire-format smoke test — do this first.** Push once ("Sync now"), then:
   ```bash
   spacetime sql my-resume-sync "SELECT snapshot_id, seq, size, chunk_count FROM snapshot"
   ```
   Confirm the row landed, then pull on a second device/checkout and confirm the sha256 verifies. `sync/client.py` sends `Vec<u8>` chunk data as JSON int arrays and defensively decodes int-array *or* hex on read; SATS-JSON docs (2.x) confirm the int-array form, so this is expected to pass — but confirm once against the live server before trusting real data to it.
2. **Two-device convergence.** Second machine (or second checkout with its own `HOME`) with the same token: edit data → close app (push) → open on the first machine (pull) → confirm a `*.db.bak-*` backup was created and the data converged.
3. **Row-level-security isolation with two identities.** Create a second identity and confirm it cannot see the first identity's snapshots. This matters because `next_seq()` / `get_latest()` in `sync/client.py` issue SQL with **no owner predicate** and rely entirely on RLS — and the module *publisher's* identity typically bypasses RLS in SpacetimeDB, which is exactly the identity a solo dev test uses. Test with a non-publisher identity before concluding isolation works.

## Known gaps and notes

### Verify before trusting a deployment
- **`Vec<u8>` wire encoding** — SATS-JSON docs confirm byte arrays travel as JSON arrays of numbers, matching `sync/client.py` exactly; still confirm with the live smoke test above.
- **RLS is an unstable SpacetimeDB feature** (opt-in `unstable` crate feature; API may change) and the **module owner's identity bypasses RLS entirely** — the owner-unscoped SQL reads in `sync/client.py` depend on it completely. Run the two-identity RLS test above with a non-owner identity before trusting isolation.

### Design/security issues — acceptable for dev, fix before real use
- **Non-atomic push, no retry:** chunks upload before the `push_snapshot` metadata call; if that call fails (e.g. seq conflict from a concurrent pusher), the chunks are orphaned and the engine does not retry. (Mitigated: `prune_snapshots` reclaims orphan chunks older than 1 h, and `push_snapshot` now rejects metadata whose chunk count doesn't match the upload.)
- **`push_chunk` accepts chunks for nonexistent snapshot ids** (by design — chunks upload first). Hardened in the 2.7.1 rewrite: empty chunks and duplicate `(snapshot_id, idx)` are rejected, and orphans are reclaimable via `prune_snapshots`. Storage can still grow between prunes.
- **Garbage collection is manual:** run `prune_snapshots` occasionally (no automatic retention); client still accumulates `*.db.bak-*` files on every pull.
- **SQL string interpolation** of `snapshot_id` into the chunk query in `sync/client.py` (value is currently always a client-generated uuid4 hex, but unvalidated).
- **Identity token stored in plaintext** in `~/.resume_orchestrator_sync.json` with default file permissions; no keyring.
- **Silent last-write-wins pull on startup** overwrites the local DB (backup taken, but the user is not told), even if local has unpushed edits.
- **Synchronous push on app close** with a 15 s per-request timeout across many chunk requests — the app can appear to hang at exit; errors are only printed to stdout.
- **Payload inflation:** bytes-as-JSON-int-arrays costs ~4–6× on the wire (a 10 MB DB ≈ 50 MB over ~80 requests at 128 KB chunks).
- **fd leak:** `tempfile.mkstemp()[1]` in `sync/engine.py` discards the file descriptor on every push/pull.

### Version bumps
When changing the DB schema, bump `APP_VERSION` in `version.py`: minor for backward-compatible additions, major when older clients must not adopt the file. Note there is no UI surfacing of a version mismatch — an incompatible pull silently does nothing.
