"""Cross-machine sync package.

Sync is optional, off by default, and never required for local use. It uploads
and downloads whole-database snapshots (last-write-wins) to a central server
backend (a SpacetimeDB module, talked to over its HTTP API).
"""
