"""Shared test setup: point the server-side store at a throwaway
database so tests never touch (or depend on) the real data/avoidle.db."""

import os
import tempfile

os.environ.setdefault(
    "AVOIDLE_DB_PATH",
    os.path.join(tempfile.mkdtemp(prefix="avoidle-test-"), "store.db"))
