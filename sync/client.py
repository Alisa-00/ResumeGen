"""
sync/client.py
Pluggable transport for talking to a central sync backend.

``SyncClient`` is the interface the engine depends on; ``SpacetimeHttpClient`` is
the concrete backend that talks to a SpacetimeDB module over its HTTP API. Only
the stdlib is used (urllib) so syncing adds no new dependencies.

Wire-format note: SpacetimeDB encodes values in its SATN-JSON format. To avoid
depending on Option/sum-type encodings we keep the server schema to plain
scalars (e.g. base_seq is a u64 where 0 means "no base"). Byte columns come back
as an array of ints; ``_decode_bytes`` also tolerates a hex string. The exact
encoding should be confirmed against the running SpacetimeDB version (see the
sync verification steps).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass


class SyncError(Exception):
    """Any sync transport failure (network, auth, server rejection)."""


@dataclass
class SnapshotMeta:
    snapshot_id: str
    device_id: str
    major: int
    minor: int
    seq: int
    is_full: bool
    base_seq: int          # 0 == full snapshot with no base
    sha256: str
    size: int
    chunk_count: int


# ── interface ─────────────────────────────────────────────────────────


class SyncClient(ABC):
    @abstractmethod
    def next_seq(self) -> int:
        """Return the next sequence number to use for a push (max existing + 1)."""

    @abstractmethod
    def get_latest(self, major: int, minor: int) -> SnapshotMeta | None:
        """Latest snapshot with the same major and minor >= the given minor."""

    @abstractmethod
    def fetch_payload(self, meta: SnapshotMeta) -> bytes:
        """Download and reassemble the gzipped DB payload for a snapshot."""

    @abstractmethod
    def push(self, meta: SnapshotMeta, chunks: list[bytes]) -> None:
        """Upload a snapshot's metadata and its payload chunks."""


# ── SpacetimeDB over HTTP ───────────────────────────────────────────────


class SpacetimeHttpClient(SyncClient):
    # columns selected from the snapshot table, in order (we map rows by index)
    _SNAPSHOT_COLS = (
        "snapshot_id, device_id, major, minor, seq, "
        "is_full, base_seq, sha256, size, chunk_count"
    )

    def __init__(self, server_url: str, module_name: str, token: str, timeout: float = 15.0):
        base = server_url.strip().rstrip("/")
        if base and "://" not in base:
            base = "https://" + base  # bare hostname → assume HTTPS
        self._base = base
        self._module = module_name
        self._token = token
        self._timeout = timeout

    # -- low-level HTTP ------------------------------------------------

    def _request(self, path: str, body: str, content_type: str) -> str:
        url = f"{self._base}/v1/database/{self._module}/{path}"
        try:
            req = urllib.request.Request(
                url,
                data=body.encode("utf-8"),
                method="POST",
                headers={
                    "Content-Type": content_type,
                    "Authorization": f"Bearer {self._token}",
                },
            )
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                return resp.read().decode("utf-8")
        except ValueError as e:  # e.g. "unknown url type" from a malformed server URL
            raise SyncError(f"Invalid sync server URL: {url}") from e
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")
            raise SyncError(f"HTTP {e.code} from sync server: {detail}") from e
        except urllib.error.URLError as e:
            raise SyncError(f"Cannot reach sync server: {e.reason}") from e
        except OSError as e:
            raise SyncError(f"Network error talking to sync server: {e}") from e

    def _sql(self, query: str) -> list[list]:
        """Run a one-off SQL query, returning the first statement's rows."""
        raw = self._request("sql", query, "text/plain")
        try:
            results = json.loads(raw)
        except json.JSONDecodeError as e:
            raise SyncError(f"Malformed SQL response: {raw[:200]}") from e
        if not results:
            return []
        return results[0].get("rows", [])

    def _call(self, reducer: str, args: list) -> None:
        """Invoke a reducer with positional args (JSON array, SATN form)."""
        self._request(f"call/{reducer}", json.dumps(args), "application/json")

    # -- byte (de)coding -----------------------------------------------

    @staticmethod
    def _decode_bytes(value) -> bytes:
        if isinstance(value, list):
            return bytes(value)
        if isinstance(value, str):
            return bytes.fromhex(value)
        raise SyncError(f"Unexpected byte column encoding: {type(value).__name__}")

    @staticmethod
    def _encode_bytes(data: bytes) -> list[int]:
        return list(data)

    # -- SyncClient API -------------------------------------------------

    def next_seq(self) -> int:
        rows = self._sql("SELECT seq FROM snapshot ORDER BY seq DESC LIMIT 1")
        if not rows:
            return 1
        return int(rows[0][0]) + 1

    def get_latest(self, major: int, minor: int) -> SnapshotMeta | None:
        rows = self._sql(
            f"SELECT {self._SNAPSHOT_COLS} FROM snapshot "
            f"WHERE major = {int(major)} AND minor >= {int(minor)} "
            f"ORDER BY seq DESC LIMIT 1"
        )
        if not rows:
            return None
        r = rows[0]
        return SnapshotMeta(
            snapshot_id=str(r[0]),
            device_id=str(r[1]),
            major=int(r[2]),
            minor=int(r[3]),
            seq=int(r[4]),
            is_full=bool(r[5]),
            base_seq=int(r[6]),
            sha256=str(r[7]),
            size=int(r[8]),
            chunk_count=int(r[9]),
        )

    def fetch_payload(self, meta: SnapshotMeta) -> bytes:
        rows = self._sql(
            "SELECT idx, data FROM snapshot_chunk "
            f"WHERE snapshot_id = '{meta.snapshot_id}' ORDER BY idx"
        )
        if len(rows) != meta.chunk_count:
            raise SyncError(
                f"Expected {meta.chunk_count} chunks, server returned {len(rows)}"
            )
        return b"".join(self._decode_bytes(r[1]) for r in rows)

    def push(self, meta: SnapshotMeta, chunks: list[bytes]) -> None:
        # chunks first, so a snapshot row only exists once its payload is present
        for idx, chunk in enumerate(chunks):
            self._call("push_chunk", [meta.snapshot_id, idx, self._encode_bytes(chunk)])
        self._call(
            "push_snapshot",
            [
                meta.snapshot_id,
                meta.device_id,
                meta.major,
                meta.minor,
                meta.seq,
                meta.is_full,
                meta.base_seq,
                meta.sha256,
                meta.size,
                meta.chunk_count,
            ],
        )
