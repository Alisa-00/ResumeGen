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
- `snapshot_chunk` — the gzipped payload split into `CHUNK_SIZE` pieces.

Row-level security scopes both tables to `owner = :sender`, so each identity
only sees its own data. All of a single user's devices should authenticate as
the **same** identity so they share one snapshot history.

## Prerequisites

- Rust toolchain (with the `wasm32-unknown-unknown` target).
- The `spacetime` CLI — see https://spacetimedb.com/install. Confirm the crate
  version in `Cargo.toml` matches your CLI (`spacetime version`).

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

## Notes / things to verify against your SpacetimeDB version

- The `#[table]` / `#[reducer]` / `#[client_visibility_filter]` APIs target the
  SpacetimeDB 1.x line. Adjust if your CLI differs.
- The HTTP byte encoding for `Vec<u8>` (SQL results and reducer args) is handled
  defensively in `sync/client.py` (`_decode_bytes` / `_encode_bytes`); confirm
  the array-vs-hex form your server uses and tighten if needed.
- Old snapshots/chunks are never garbage-collected here. Add a cleanup reducer
  later if storage grows.
