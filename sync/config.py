"""
sync/config.py
Per-machine sync configuration and state.

This deliberately lives OUTSIDE the synced database (in a sibling JSON file next
to the ~/.resume_orchestrator path file). If it lived in the app_settings table
it would be clobbered every time a remote snapshot is pulled.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, asdict
from pathlib import Path

CONFIG_PATH = Path.home() / ".resume_orchestrator_sync.json"


@dataclass
class SyncConfig:
    # user-configurable
    sync_enabled: bool = False
    server_url: str = ""          # e.g. https://maincloud.spacetimedb.com  (no default)
    module_name: str = ""         # the published SpacetimeDB module / database name
    identity_token: str = ""      # SpacetimeDB identity (OIDC) bearer token

    # machine-local state (managed by the sync engine, not the user)
    device_id: str = ""           # uuid4, generated once per machine
    last_synced_seq: int = 0      # highest snapshot seq this machine has adopted/pushed
    last_synced_hash: str = ""    # sha256 of the DB file at last successful sync
    last_synced_at: str = ""      # ISO timestamp of last successful sync

    def is_ready(self) -> bool:
        """True if there is enough configuration to attempt a network sync."""
        return bool(
            self.sync_enabled
            and self.server_url.strip()
            and self.module_name.strip()
            and self.identity_token.strip()
        )

    # ------------------------------------------------------------------

    @classmethod
    def load(cls, path: Path | None = None) -> "SyncConfig":
        """Load config, tolerating a missing/corrupt file. Always has a device_id."""
        path = path or CONFIG_PATH
        data: dict = {}
        if path.exists():
            try:
                data = json.loads(path.read_text() or "{}")
            except (json.JSONDecodeError, OSError):
                data = {}  # corrupt or unreadable — fall back to defaults

        # keep only known fields so an old/new file shape never breaks construction
        known = {f for f in cls.__dataclass_fields__}
        cfg = cls(**{k: v for k, v in data.items() if k in known})

        if not cfg.device_id:
            cfg.device_id = uuid.uuid4().hex
            cfg.save(path)
        return cfg

    def save(self, path: Path | None = None) -> None:
        path = path or CONFIG_PATH
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2))
        tmp.replace(path)  # atomic on the same filesystem
