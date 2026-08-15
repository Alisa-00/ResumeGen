"""
version.py
Single source of truth for the application / database schema version.

The version is (major, minor). It is stamped into every synced snapshot and
into the SQLite file itself (PRAGMA user_version) so that the version travels
with the data. See AGENTS.md / the sync module for how this gates syncing.
"""

from __future__ import annotations

# (major, minor) — bump minor for backward-compatible schema additions,
# bump major for changes that are NOT safe to share with older clients.
APP_VERSION: tuple[int, int] = (0, 1)

# user_version is a single signed 32-bit int in SQLite. We pack major/minor as
# major * 1000 + minor, which leaves plenty of headroom for both fields.
_MINOR_BASE = 1000


def encode_version(version: tuple[int, int]) -> int:
    """Pack a (major, minor) tuple into a single int for PRAGMA user_version."""
    major, minor = version
    if minor >= _MINOR_BASE:
        raise ValueError(f"minor version {minor} exceeds {_MINOR_BASE - 1}")
    return major * _MINOR_BASE + minor


def decode_version(packed: int) -> tuple[int, int]:
    """Unpack an int produced by encode_version back into (major, minor)."""
    return divmod(packed, _MINOR_BASE)


def version_str(version: tuple[int, int]) -> str:
    """Human-readable 'major.minor' form, e.g. (0, 1) -> '0.1'."""
    return f"{version[0]}.{version[1]}"


def is_compatible(local: tuple[int, int], remote: tuple[int, int]) -> bool:
    """
    True if a snapshot at ``remote`` may be adopted by a client at ``local``.

    Rule: same major, and remote minor must be >= local minor (never downgrade,
    never cross a major boundary).
    """
    return remote[0] == local[0] and remote[1] >= local[1]
