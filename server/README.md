# ResumeGen sync server (SpacetimeDB module)

This is the central backend for cross-machine sync. It is a SpacetimeDB module
(Rust → WASM) that stores whole-database snapshots uploaded by the desktop app.
It is **not** imported by the Python app — the app talks to it over SpacetimeDB's
HTTP API (`sync/client.py`).

## What it stores

- `snapshot` — one row per uploaded DB snapshot: owning identity, device id,
  version (`major`/`minor`), monotonic `seq`, integrity `sha256`, payload `size`
  and `chunk_count`. `is_full`/`base_seq` are reserved for future incremental
  (diff) snapshots; today every snapshot is full (`is_full = true`,
  `base_seq = 0`).
- `snapshot_chunk` — the gzipped payload split into `CHUNK_SIZE` pieces, plus a
  server-side `created_at` used only for orphan pruning (the app never reads it).

Row-level security scopes both tables to `owner = :sender`, so each identity
only sees its own data. All of a single user's devices should authenticate as
the **same** identity so they share one snapshot history.

Reducers:
- `push_snapshot` — records metadata after chunks are uploaded. Rejects
  duplicate `snapshot_id`, non-monotonic per-owner `seq`, and metadata whose
  `chunk_count` doesn't match the chunks actually uploaded.
- `push_chunk` — uploads one chunk. Rejects empty data, duplicate
  `(snapshot_id, idx)`, and chunks for another identity's snapshot.
- `prune_snapshots keep_latest` — maintenance, never called by the app: deletes
  the caller's snapshots beyond the newest `keep_latest` (and their chunks),
  plus any orphan chunks older than 1 hour. Run e.g.
  `spacetime call <db> prune_snapshots 5`.

## Prerequisites

- Rust toolchain (with the `wasm32-unknown-unknown` target).
- The `spacetime` CLI — see https://spacetimedb.com/install. Keep the crate
  version in `Cargo.toml` in lockstep with your CLI (`spacetime --version`);
  the module currently targets **2.7.1**.
- Optional: `wasm-opt` (binaryen) for a smaller optimised module.

Build without publishing: `spacetime build` (or
`cargo build --target wasm32-unknown-unknown --release`) from this directory.

## Publish

Free hosting is SpacetimeDB Maincloud. There is intentionally **no default
server** baked into the app — you choose one here and configure it in the app's
Sync settings.

```bash
# log in (creates / loads your identity) and publish
spacetime login
spacetime publish --project-path . my-resume-sync       # Maincloud
# or against a local instance:
#   spacetime start &
#   spacetime publish --project-path . my-resume-sync --server local
```

## Configure the app

In the app: **Settings → Sync**
- Enable sync
- Sync server URL — e.g. `https://maincloud.spacetimedb.com` (or your local
  `http://127.0.0.1:3000`)
- Module / database name — e.g. `my-resume-sync`
- Identity token — print it with `spacetime login --token` / from
  `~/.spacetime` config, or your OIDC token. The same token (same identity) on
  every device is what links them to one snapshot history.

## Notes

- The module targets the **SpacetimeDB 2.7.x** API (`accessor =` table syntax,
  `ctx.sender()` method). Verified: compiles clean against crate 2.7.1 and
  `spacetime build` with CLI 2.7.1 succeeds.
- **RLS is an unstable SpacetimeDB feature** (enabled via the crate's
  `unstable` feature in `Cargo.toml`; the API may change). Two caveats:
  the **module owner's identity bypasses RLS entirely**, and upstream docs
  recommend views where possible. Always verify isolation with a
  **non-owner** identity before trusting a deployment — the app's SQL reads
  (`sync/client.py`) have no owner predicate and rely on RLS completely.
- Byte encoding over HTTP is SATS-JSON: `Vec<u8>` travels as a JSON array of
  numbers, which is exactly what `sync/client.py` sends and decodes.
- Storage hygiene is manual: run `prune_snapshots` occasionally (see above).
