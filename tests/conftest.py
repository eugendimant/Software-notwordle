"""Shared test setup: point the server-side store at a throwaway
database so tests never touch (or depend on) the real data/avoidle.db,
and keep word-definition lookups off the real network."""

import os
import tempfile

os.environ.setdefault(
    "AVOIDLE_DB_PATH",
    os.path.join(tempfile.mkdtemp(prefix="avoidle-test-"), "store.db"))

# Definition lookups must never reach the real Wiktionary during tests —
# that would make the whole suite slow and flaky (every rendered board
# triggers a lookup). Tests that exercise definitions monkeypatch
# ``_http_get`` themselves; this offline stub is the safe default for
# everyone else, so ``define()`` returns None instantly with no I/O.
import avoidle.definitions as _definitions  # noqa: E402


def _offline(url):
    raise OSError("network disabled in tests")


_definitions._http_get = _offline

# The GitHub-backed games counter must not reach the network during tests
# either — the sidebar renders on every AppTest run. Tests that exercise it
# monkeypatch ``_http`` (or read_count/publish) themselves.
import avoidle.ghcount as _ghcount  # noqa: E402


def _gh_offline(url, headers, data=None, method=None):
    raise OSError("network disabled in tests")


_ghcount._http = _gh_offline
