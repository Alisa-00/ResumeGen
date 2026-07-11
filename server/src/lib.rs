//! Central sync backend for ResumeGen, as a SpacetimeDB module.
//!
//! The desktop app uploads a gzip of its whole SQLite database, split into
//! chunks, and downloads the latest snapshot whose version is compatible. The
//! module stores one row per snapshot plus its payload chunks, scoped to the
//! uploading identity via row-level security so users only ever see their own
//! data.
//!
//! Wire-format choices (kept deliberately simple so the Python HTTP client does
//! not have to deal with sum-type / Option encodings):
//!   * `base_seq` is a plain `u64`; `0` means "full snapshot, no base".
//!   * `snapshot_id` is a client-generated UUID (hex string) used as the link
//!     between a snapshot and its chunks, so no server-assigned id round-trip is
//!     needed over HTTP.

use spacetimedb::{client_visibility_filter, reducer, table, Filter, Identity, ReducerContext, Table, Timestamp};

#[table(name = snapshot, public)]
pub struct Snapshot {
    #[primary_key]
    snapshot_id: String,
    #[index(btree)]
    owner: Identity,
    device_id: String,
    major: u32,
    minor: u32,
    #[index(btree)]
    seq: u64,
    is_full: bool,
    base_seq: u64, // 0 == full snapshot
    sha256: String,
    size: u64,
    chunk_count: u32,
    created_at: Timestamp,
}

#[table(name = snapshot_chunk, public)]
pub struct SnapshotChunk {
    #[primary_key]
    #[auto_inc]
    id: u64,
    #[index(btree)]
    snapshot_id: String,
    idx: u32,
    data: Vec<u8>,
}

// ── row-level security: each identity sees only its own rows ───────────────
// Note: confirm the exact RLS/JOIN syntax against your SpacetimeDB version.

#[client_visibility_filter]
const SNAPSHOT_RLS: Filter = Filter::Sql("SELECT * FROM snapshot WHERE owner = :sender");

#[client_visibility_filter]
const CHUNK_RLS: Filter = Filter::Sql(
    "SELECT snapshot_chunk.* FROM snapshot_chunk \
     JOIN snapshot ON snapshot_chunk.snapshot_id = snapshot.snapshot_id \
     WHERE snapshot.owner = :sender",
);

// ── reducers ───────────────────────────────────────────────────────────────

/// Record a snapshot's metadata. Called *after* its chunks are uploaded.
/// Enforces a per-owner monotonic `seq` so concurrent pushers can't collide.
#[reducer]
pub fn push_snapshot(
    ctx: &ReducerContext,
    snapshot_id: String,
    device_id: String,
    major: u32,
    minor: u32,
    seq: u64,
    is_full: bool,
    base_seq: u64,
    sha256: String,
    size: u64,
    chunk_count: u32,
) -> Result<(), String> {
    let owner = ctx.sender;

    if ctx.db.snapshot().snapshot_id().find(&snapshot_id).is_some() {
        return Err("snapshot_id already exists".to_string());
    }

    let max_seq = ctx
        .db
        .snapshot()
        .iter()
        .filter(|s| s.owner == owner)
        .map(|s| s.seq)
        .max()
        .unwrap_or(0);
    if seq <= max_seq {
        // Client should re-read next_seq and retry.
        return Err(format!("seq {seq} is not greater than current max {max_seq}"));
    }

    ctx.db.snapshot().insert(Snapshot {
        snapshot_id,
        owner,
        device_id,
        major,
        minor,
        seq,
        is_full,
        base_seq,
        sha256,
        size,
        chunk_count,
        created_at: ctx.timestamp,
    });
    Ok(())
}

/// Upload one payload chunk. Chunks are sent before `push_snapshot`, so the
/// snapshot row may not exist yet; if it does, it must belong to the caller.
/// `snapshot_id` is an unguessable UUID, so orphan/hijack risk is negligible.
#[reducer]
pub fn push_chunk(
    ctx: &ReducerContext,
    snapshot_id: String,
    idx: u32,
    data: Vec<u8>,
) -> Result<(), String> {
    if let Some(existing) = ctx.db.snapshot().snapshot_id().find(&snapshot_id) {
        if existing.owner != ctx.sender {
            return Err("snapshot belongs to another identity".to_string());
        }
    }
    ctx.db.snapshot_chunk().insert(SnapshotChunk {
        id: 0, // auto_inc
        snapshot_id,
        idx,
        data,
    });
    Ok(())
}
