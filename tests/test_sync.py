"""
tests/test_sync.py
Self-contained sync tests (no pytest / PySide6 required).

Run:  python3 tests/test_sync.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import sync.config as config_mod  # noqa: E402
from db.database import Database  # noqa: E402
from sync.client import SnapshotMeta, SyncClient  # noqa: E402
from sync.config import SyncConfig  # noqa: E402
from sync import engine as engine_mod  # noqa: E402
from sync.engine import SyncEngine, make_snapshot  # noqa: E402
from version import APP_VERSION, decode_version, encode_version, is_compatible  # noqa: E402

# Never touch the real ~/.resume_orchestrator_sync.json during tests.
config_mod.CONFIG_PATH = Path(tempfile.mkstemp(suffix=".json")[1])


# ── in-memory fake backend ──────────────────────────────────────────────


class FakeServer:
    def __init__(self):
        self.snapshots: dict[str, SnapshotMeta] = {}
        self.chunks: dict[str, dict[int, bytes]] = {}


class FakeClient(SyncClient):
    def __init__(self, server: FakeServer):
        self.server = server

    def next_seq(self) -> int:
        seqs = [m.seq for m in self.server.snapshots.values()]
        return (max(seqs) + 1) if seqs else 1

    def get_latest(self, major, minor):
        cands = [
            m for m in self.server.snapshots.values()
            if m.major == major and m.minor >= minor
        ]
        return max(cands, key=lambda m: m.seq) if cands else None

    def fetch_payload(self, meta):
        ch = self.server.chunks[meta.snapshot_id]
        return b"".join(ch[i] for i in sorted(ch))

    def push(self, meta, chunks):
        self.server.snapshots[meta.snapshot_id] = meta
        self.server.chunks[meta.snapshot_id] = dict(enumerate(chunks))


def _engine(tmp: Path, name: str, server: FakeServer) -> SyncEngine:
    db = Database(tmp / f"{name}.db")
    db.connect()
    cfg = SyncConfig(
        sync_enabled=True, server_url="x", module_name="x",
        identity_token="x", device_id=f"dev-{name}",
    )
    return SyncEngine(db, cfg, client=FakeClient(server))


def _set_contact(db: Database, name: str):
    db.execute("DELETE FROM contact")
    db.execute("INSERT INTO contact (name) VALUES (?)", (name,))


def _contact_name(db: Database) -> str | None:
    row = db.fetch_one("SELECT name FROM contact LIMIT 1")
    return row["name"] if row else None


# ── tests ────────────────────────────────────────────────────────────────


def test_version_helpers():
    assert decode_version(encode_version((3, 7))) == (3, 7)
    assert encode_version((0, 1)) == 1
    assert is_compatible((0, 1), (0, 1)) is True
    assert is_compatible((0, 1), (0, 2)) is True      # newer minor ok
    assert is_compatible((0, 2), (0, 1)) is False     # older minor rejected
    assert is_compatible((0, 1), (1, 0)) is False     # different major rejected


def test_snapshot_deterministic_and_valid():
    with tempfile.TemporaryDirectory() as d:
        db = Database(Path(d) / "a.db")
        db.connect()
        _set_contact(db, "Alice")
        p1, sha1, chunks1 = make_snapshot(db.db_path)
        p2, sha2, _ = make_snapshot(db.db_path)
        assert sha1 == sha2, "same content must hash identically (skip-push relies on this)"
        # payload reassembles and is a valid sqlite db
        import gzip
        raw = gzip.decompress(b"".join(chunks1))
        assert raw[:16] == b"SQLite format 3\x00"
        db.close()


def test_chunking_splits_and_reassembles():
    orig = engine_mod.CHUNK_SIZE
    engine_mod.CHUNK_SIZE = 1024  # force multiple chunks for a small db
    try:
        with tempfile.TemporaryDirectory() as d:
            db = Database(Path(d) / "a.db")
            db.connect()
            for i in range(50):
                db.execute("INSERT INTO keyword (name) VALUES (?)", (f"kw{i}",))
            payload, _, chunks = make_snapshot(db.db_path)
            assert len(chunks) > 1
            assert b"".join(chunks) == payload
            db.close()
    finally:
        engine_mod.CHUNK_SIZE = orig


def test_push_skips_when_unchanged():
    server = FakeServer()
    with tempfile.TemporaryDirectory() as d:
        eng = _engine(Path(d), "a", server)
        _set_contact(eng.db, "Alice")
        assert eng.push() is True            # first push uploads
        assert len(server.snapshots) == 1
        assert eng.push() is False           # unchanged -> skip
        assert len(server.snapshots) == 1


def test_end_to_end_convergence():
    server = FakeServer()
    with tempfile.TemporaryDirectory() as da, tempfile.TemporaryDirectory() as db_:
        a = _engine(Path(da), "a", server)
        b = _engine(Path(db_), "b", server)

        _set_contact(a.db, "Alice")
        assert a.push() is True

        assert _contact_name(b.db) is None
        fetched = b.pull_fetch()
        assert fetched is not None
        meta, raw = fetched
        b.pull_apply(meta, raw)

        assert _contact_name(b.db) == "Alice", "B should adopt A's data"
        # a timestamped backup of B's previous db must exist
        baks = list(Path(db_).glob("b.db.bak-*"))
        assert baks, "pull must back up the previous db"
        # B just adopted; pushing again must be a no-op (no ping-pong)
        assert b.push() is False


def test_version_gating_blocks_other_major():
    server = FakeServer()
    server.snapshots["x"] = SnapshotMeta(
        snapshot_id="x", device_id="other", major=1, minor=0, seq=5,
        is_full=True, base_seq=0, sha256="", size=0, chunk_count=0,
    )
    with tempfile.TemporaryDirectory() as d:
        eng = _engine(Path(d), "a", server)  # local data_version == APP_VERSION (0,1)
        assert APP_VERSION[0] == 0
        assert eng.pull_fetch() is None, "must not pull a different major"


def test_first_sync_guard_blocks_stale_push():
    """A never-synced machine must not silently bury existing server history."""
    from sync.client import SyncError

    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        server = FakeServer()

        a = _engine(tmp, "a", server)
        _set_contact(a.db, "Alice")
        assert a.push() is True, "empty server: bootstrap push must be allowed"

        b = _engine(tmp, "b", server)  # never synced, server now has history
        _set_contact(b.db, "StaleBob")
        try:
            b.push()
            raise AssertionError("expected SyncError from first-sync guard")
        except SyncError:
            pass
        assert b.cfg.last_synced_seq == 0, "blocked push must not record a sync"

        # explicit override — the UI dialog's "keep local and upload" choice
        assert b.push(first_sync_ok=True) is True
        assert b.cfg.last_synced_seq == 2

        # a machine that pulled first needs no override afterwards
        c = _engine(tmp, "c", server)
        fetched = c.pull_fetch()
        assert fetched is not None
        c.pull_apply(*fetched)
        _set_contact(c.db, "Carol")
        assert c.push() is True

        a.db.close(); b.db.close(); c.db.close()


def _run():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            import traceback
            print(f"FAIL {t.__name__}: {e}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_run())
