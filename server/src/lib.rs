//! Central sync backend for ResumeGen, as a SpacetimeDB module (2.7.x API).
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
//!   * `Vec<u8>` travels as a SATS-JSON array of numbers, matching
//!     `sync/client.py`'s `_encode_bytes` / `_decode_bytes`.

use spacetimedb::{client_visibility_filter, reducer, table, Filter, Identity, ReducerContext, Table, Timestamp};

/// Orphan chunks (uploaded but never claimed by a `push_snapshot`) may be
/// pruned once they are older than this. Generous enough that no in-flight
/// push loses its chunks mid-upload.
const ORPHAN_CHUNK_TTL_MICROS: i64 = 3_600_000_000; // 1 hour

#[table(accessor = snapshot, public)]
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

#[table(accessor = snapshot_chunk, public,
        index(accessor = by_snapshot_idx, btree(columns = [snapshot_id, idx])))]
pub struct SnapshotChunk {
    #[primary_key]
    #[auto_inc]
    id: u64,
    #[index(btree)]
    snapshot_id: String,
    idx: u32,
    data: Vec<u8>,
    created_at: Timestamp,
}

// ── row-level security: each identity sees only its own rows ───────────────
// NOTE: the module owner's identity bypasses RLS entirely; validate isolation
// with a non-owner identity.

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
/// Enforces a per-owner monotonic `seq` so concurrent pushers can't collide,
/// and refuses metadata whose payload is not fully uploaded.
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
    let owner = ctx.sender();

    if ctx.db.snapshot().snapshot_id().find(&snapshot_id).is_some() {
        return Err("snapshot_id already exists".to_string());
    }

    let max_seq = ctx
        .db
        .snapshot()
        .owner()
        .filter(&owner)
        .map(|s| s.seq)
        .max()
        .unwrap_or(0);
    if seq <= max_seq {
        // Client should re-read next_seq and retry.
        return Err(format!("seq {seq} is not greater than current max {max_seq}"));
    }

    let uploaded = ctx
        .db
        .snapshot_chunk()
        .snapshot_id()
        .filter(&snapshot_id)
        .count() as u32;
    if uploaded != chunk_count {
        return Err(format!(
            "payload incomplete: {uploaded} chunks uploaded, metadata claims {chunk_count}"
        ));
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
    if data.is_empty() {
        return Err("chunk data is empty".to_string());
    }
    if let Some(existing) = ctx.db.snapshot().snapshot_id().find(&snapshot_id) {
        if existing.owner != ctx.sender() {
            return Err("snapshot belongs to another identity".to_string());
        }
    }
    if ctx
        .db
        .snapshot_chunk()
        .by_snapshot_idx()
        .filter((&snapshot_id, &idx))
        .next()
        .is_some()
    {
        return Err(format!("chunk {idx} already uploaded for this snapshot"));
    }
    ctx.db.snapshot_chunk().insert(SnapshotChunk {
        id: 0, // auto_inc
        snapshot_id,
        idx,
        data,
        created_at: ctx.timestamp,
    });
    Ok(())
}

/// Maintenance: delete the caller's old snapshots, keeping the newest
/// `keep_latest` (by `seq`), plus any orphan chunks older than an hour.
/// The desktop app never calls this; run it manually, e.g.
/// `spacetime call <db> prune_snapshots 5`.
#[reducer]
pub fn prune_snapshots(ctx: &ReducerContext, keep_latest: u32) -> Result<(), String> {
    if keep_latest == 0 {
        return Err("keep_latest must be at least 1".to_string());
    }
    let owner = ctx.sender();

    let mut mine: Vec<(u64, String)> = ctx
        .db
        .snapshot()
        .owner()
        .filter(&owner)
        .map(|s| (s.seq, s.snapshot_id))
        .collect();
    mine.sort_unstable_by(|a, b| b.0.cmp(&a.0)); // newest first

    for (_seq, snapshot_id) in mine.into_iter().skip(keep_latest as usize) {
        ctx.db.snapshot_chunk().snapshot_id().delete(&snapshot_id);
        ctx.db.snapshot().snapshot_id().delete(&snapshot_id);
    }

    // Orphan chunks belong to no snapshot row, so they have no owner to scope
    // to; anyone may reclaim the storage once they are safely stale.
    let now = ctx.timestamp.to_micros_since_unix_epoch();
    let stale: Vec<u64> = ctx
        .db
        .snapshot_chunk()
        .iter()
        .filter(|c| {
            ctx.db.snapshot().snapshot_id().find(&c.snapshot_id).is_none()
                && now - c.created_at.to_micros_since_unix_epoch() > ORPHAN_CHUNK_TTL_MICROS
        })
        .map(|c| c.id)
        .collect();
    for id in stale {
        ctx.db.snapshot_chunk().id().delete(&id);
    }
    Ok(())
}
