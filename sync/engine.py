"""
sync/engine.py
Whole-database snapshot sync (last-write-wins).

Threading contract (the app drives this from QThreadPool workers):
  * ``push`` and ``pull_fetch`` only do network + read a *consistent copy* of the
    DB through a private connection — safe to call from a worker thread.
  * ``pull_apply`` swaps the DB file and reopens the live connection — it MUST be
    called on the main (UI) thread, after the live connection is idle.
"""

from __future__ import annotations

import gzip
import hashlib
import shutil
import sqlite3
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from db.database import Database
from sync.client import SnapshotMeta, SyncClient, SpacetimeHttpClient, SyncError
from sync.config import SyncConfig
from version import decode_version, is_compatible

# Keep chunks modest: SpacetimeDB caps row/message sizes, and bytes are sent as
# JSON int arrays which inflate ~4-6x on the wire.
CHUNK_SIZE = 128 * 1024


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_data_version(db_path: Path) -> tuple[int, int]:
    """Read PRAGMA user_version via a private connection (worker-thread safe)."""
    conn = sqlite3.connect(db_path)
    try:
        packed = conn.execute("PRAGMA user_version").fetchone()[0]
    finally:
        conn.close()
    return decode_version(packed)


def _consistent_db_bytes(db_path: Path) -> bytes:
    """A transactionally consistent copy of the DB file via the sqlite backup API.

    Uses a private connection (not the app's live one), so it is thread-safe and
    correctly captures data still sitting in the WAL.
    """
    tmp = Path(tempfile.mkstemp(suffix=".db")[1])
    src = sqlite3.connect(db_path)
    try:
        dst = sqlite3.connect(tmp)
        try:
            src.backup(dst)
        finally:
            dst.close()
        return tmp.read_bytes()
    finally:
        src.close()
        tmp.unlink(missing_ok=True)


def make_snapshot(db_path: Path) -> tuple[bytes, str, list[bytes]]:
    """Build the gzipped payload for ``db_path``.

    Returns (payload, sha256_hex, chunks). gzip mtime is fixed at 0 so identical
    DB content always yields an identical payload (and hash), which is how we
    detect "nothing changed" and skip a push.
    """
    raw = _consistent_db_bytes(db_path)
    payload = gzip.compress(raw, mtime=0)
    sha = hashlib.sha256(payload).hexdigest()
    chunks = [payload[i : i + CHUNK_SIZE] for i in range(0, len(payload), CHUNK_SIZE)]
    return payload, sha, chunks


class SyncEngine:
    def __init__(self, db: Database, cfg: SyncConfig, client: SyncClient | None = None):
        self.db = db
        self.cfg = cfg
        self._client = client  # injectable for tests

    # ------------------------------------------------------------------

    def available(self) -> bool:
        return self.cfg.is_ready()

    def reset_client(self) -> None:
        """Drop the cached client so new server URL / token settings take effect."""
        self._client = None

    def client(self) -> SyncClient:
        if self._client is None:
            self._client = SpacetimeHttpClient(
                self.cfg.server_url, self.cfg.module_name, self.cfg.identity_token
            )
        return self._client

    # ── push (worker-thread safe) ─────────────────────────────────────

    def push(self) -> bool:
        """Upload the local DB as a snapshot. No-op if unchanged. Returns True if pushed."""
        if not self.available():
            return False
        payload, sha, chunks = make_snapshot(self.db.db_path)
        if sha == self.cfg.last_synced_hash:
            return False  # nothing changed since last sync

        client = self.client()
        major, minor = read_data_version(self.db.db_path)
        seq = max(client.next_seq(), self.cfg.last_synced_seq + 1)
        meta = SnapshotMeta(
            snapshot_id=uuid.uuid4().hex,
            device_id=self.cfg.device_id,
            major=major,
            minor=minor,
            seq=seq,
            is_full=True,   # full snapshots for now; base_seq reserved for diffs
            base_seq=0,
            sha256=sha,
            size=len(payload),
            chunk_count=len(chunks),
        )
        client.push(meta, chunks)

        self.cfg.last_synced_seq = seq
        self.cfg.last_synced_hash = sha
        self.cfg.last_synced_at = _utcnow_iso()
        self.cfg.save()
        return True

    # ── pull: fetch (worker) then apply (main thread) ─────────────────

    def pull_fetch(self) -> tuple[SnapshotMeta, bytes] | None:
        """Download the latest compatible snapshot if it is newer than ours.

        Returns (meta, decompressed_db_bytes) or None. Network only — safe off
        the UI thread.
        """
        if not self.available():
            return None
        local = read_data_version(self.db.db_path)
        meta = self.client().get_latest(local[0], local[1])
        if meta is None:
            return None
        if meta.seq <= self.cfg.last_synced_seq:
            return None  # already have it (or older)
        if not is_compatible(local, (meta.major, meta.minor)):
            return None  # defensive: server returned something incompatible

        payload = self.client().fetch_payload(meta)
        if hashlib.sha256(payload).hexdigest() != meta.sha256:
            raise SyncError("Downloaded snapshot failed integrity check (sha256)")
        return meta, gzip.decompress(payload)

    def pull_apply(self, meta: SnapshotMeta, db_bytes: bytes, on_applied=None) -> None:
        """Replace the local DB with a fetched snapshot. MUST run on the UI thread.

        Always backs up the current DB first (LWW is destructive and hard to undo).
        """
        db_path = self.db.db_path
        self.db.close()  # WAL is checkpointed on close

        if db_path.exists():
            ts = datetime.now().strftime("%Y%m%d-%H%M%S")
            shutil.copy2(db_path, db_path.with_name(f"{db_path.name}.bak-{ts}"))

        tmp = db_path.with_name(f"{db_path.name}.incoming")
        tmp.write_bytes(db_bytes)
        tmp.replace(db_path)  # atomic swap

        # stale WAL/SHM belong to the old DB — remove so they don't corrupt the new one
        for sidecar in (f"{db_path.name}-wal", f"{db_path.name}-shm"):
            db_path.with_name(sidecar).unlink(missing_ok=True)

        self.db.reopen()  # reconnect, migrate, re-stamp user_version

        # Store OUR canonical hash of the adopted (and possibly migrated) DB, not
        # the remote payload hash. make_snapshot is machine-dependent (page layout),
        # so reusing meta.sha256 would make our next push look "changed" and bounce
        # an identical snapshot back — a push/pull ping-pong between idle machines.
        _, local_sha, _ = make_snapshot(db_path)

        self.cfg.last_synced_seq = meta.seq
        self.cfg.last_synced_hash = local_sha
        self.cfg.last_synced_at = _utcnow_iso()
        self.cfg.save()

        if on_applied is not None:
            on_applied()
