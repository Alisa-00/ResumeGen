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
import os
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
    fd, tmp_name = tempfile.mkstemp(suffix=".db")
    os.close(fd)  # we only need the path; sqlite opens its own handle below
    tmp = Path(tmp_name)
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


def _check_sqlite_ok(db_path: Path) -> None:
    """Raise ``SyncError`` unless ``db_path`` is a healthy SQLite file.

    A pre-swap sanity gate so a truncated/garbage download can never replace a
    working database. Uses ``PRAGMA quick_check`` (far cheaper than
    ``integrity_check`` on a large DB, and this runs on the UI thread) over a
    private connection.
    """
    try:
        conn = sqlite3.connect(db_path)
        try:
            row = conn.execute("PRAGMA quick_check").fetchone()
        finally:
            conn.close()
    except sqlite3.DatabaseError as e:
        raise SyncError(f"Downloaded snapshot is not a valid database: {e}") from e
    if not row or row[0] != "ok":
        raise SyncError(f"Downloaded snapshot failed quick_check: {row!r}")


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

    def push(self, *, first_sync_ok: bool = False) -> bool:
        """Upload the local DB as a snapshot. No-op if unchanged. Returns True if pushed.

        A machine that has never synced refuses to push over existing server
        history unless ``first_sync_ok`` — the caller must first resolve the
        download-or-upload choice (see the first-sync dialog in the UI).
        """
        if not self.available():
            return False
        payload, sha, chunks = make_snapshot(self.db.db_path)
        if sha == self.cfg.last_synced_hash:
            return False  # nothing changed since last sync

        client = self.client()
        major, minor = read_data_version(self.db.db_path)
        next_seq = client.next_seq()
        if not first_sync_ok and self.cfg.last_synced_seq == 0 and next_seq > 1:
            raise SyncError(
                "server already has snapshots but this machine has never synced — "
                "use Settings → Sync → 'Sync now' to choose download or upload first"
            )
        seq = max(next_seq, self.cfg.last_synced_seq + 1)
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

        Backs up the current DB first (LWW is destructive and hard to undo), and
        validates the incoming bytes before swapping so a corrupt download can
        never replace a working database. If the swap/reopen fails partway, the
        backup is restored so the app is never left on a broken DB.
        """
        db_path = self.db.db_path

        # 1. Stage + validate the incoming DB *before* touching the live one, so a
        #    bad payload leaves the running database (and its open connection) intact.
        incoming = db_path.with_name(f"{db_path.name}.incoming")
        incoming.write_bytes(db_bytes)
        try:
            _check_sqlite_ok(incoming)
        except Exception:
            incoming.unlink(missing_ok=True)
            raise

        # 2. Swap it in, keeping a timestamped backup we can roll back to.
        self.db.close()  # WAL is checkpointed on close
        backup: Path | None = None
        if db_path.exists():
            ts = datetime.now().strftime("%Y%m%d-%H%M%S")
            backup = db_path.with_name(f"{db_path.name}.bak-{ts}")
            shutil.copy2(db_path, backup)

        def _clear_sidecars() -> None:
            for sidecar in (f"{db_path.name}-wal", f"{db_path.name}-shm"):
                db_path.with_name(sidecar).unlink(missing_ok=True)

        try:
            incoming.replace(db_path)  # atomic swap
            _clear_sidecars()  # stale WAL/SHM belong to the old DB
            self.db.reopen()  # reconnect, migrate, re-stamp user_version
        except Exception:
            # Failed after we began swapping — restore the backup so the app is
            # never left pointing at a broken/half-written database.
            incoming.unlink(missing_ok=True)
            if backup is not None and backup.exists():
                shutil.copy2(backup, db_path)
                _clear_sidecars()
            self.db.reopen()
            raise

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
