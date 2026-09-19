"""Retired compatibility namespace.

The active unattended runtime is implemented by scripts.pasi_overnight_engine_v2.
This module intentionally contains no wrapper or runtime behavior; it exists only
so older tooling that checks import availability fails closed without reintroducing
the former monkeypatch-based execution path.
"""
