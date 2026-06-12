"""Server-side persistence for Avoidle.

Two things live here, shared across EVERY visitor of the deployment:

* the global games odometer — one number counting every finished game
  by everyone, ever;
* nickname profiles — each saved slot's compressed progress token, so a
  player can type their name on any device and continue.

Backends, picked automatically:

1. **External database** (truly permanent, survives redeploys): set a
   ``DATABASE_URL`` secret/env var (e.g. a free Neon/Supabase Postgres,
   ``postgresql+psycopg2://...``) and add the matching driver to
   requirements. Used whenever SQLAlchemy can connect to it.
2. **SQLite file** (default, zero setup): ``AVOIDLE_DB_PATH`` or
   ``data/avoidle.db``. Persists across sessions and app restarts on the
   same machine; on ephemeral hosts a redeploy resets the file — the
   browser-cookie layer still restores each player's own progress, and
   the odometer resumes from the largest per-profile count it sees.

Every public call is exception-safe at the call site (the app wraps
them): persistence must never be able to crash a game.
"""

from __future__ import annotations

import os
import sqlite3
import threading

_LOCK = threading.Lock()
_STORE = None

GLOBAL_GAMES_KEY = "global_games"


class SqliteStore:
    """Tiny key/value + profile store on a single SQLite file."""

    def __init__(self, path: str):
        self.path = path
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
        with self._conn() as c:
            c.execute("CREATE TABLE IF NOT EXISTS meta ("
                      "key TEXT PRIMARY KEY, value INTEGER NOT NULL)")
            c.execute("CREATE TABLE IF NOT EXISTS profiles ("
                      "nick TEXT PRIMARY KEY, token TEXT NOT NULL, "
                      "xp INTEGER NOT NULL DEFAULT 0, "
                      "wins INTEGER NOT NULL DEFAULT 0, "
                      "updated TEXT NOT NULL DEFAULT (datetime('now')))")
            for col in ("xp", "wins"):   # migrate pre-leaderboard files
                try:
                    c.execute(f"ALTER TABLE profiles ADD COLUMN {col} "
                              "INTEGER NOT NULL DEFAULT 0")
                except sqlite3.OperationalError:
                    pass                 # column already exists

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=5)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def bump_games(self, n: int = 1) -> int:
        """Atomically add ``n`` finished games; returns the new total."""
        with _LOCK, self._conn() as c:
            c.execute(
                "INSERT INTO meta (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = value + ?",
                (GLOBAL_GAMES_KEY, n, n))
            row = c.execute("SELECT value FROM meta WHERE key = ?",
                            (GLOBAL_GAMES_KEY,)).fetchone()
            return int(row[0])

    def raise_games_floor(self, n: int) -> int:
        """The odometer never goes backward: lift it to at least ``n``
        (used to re-seed after an ephemeral host lost the file)."""
        with _LOCK, self._conn() as c:
            c.execute(
                "INSERT INTO meta (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = MAX(value, ?)",
                (GLOBAL_GAMES_KEY, n, n))
            row = c.execute("SELECT value FROM meta WHERE key = ?",
                            (GLOBAL_GAMES_KEY,)).fetchone()
            return int(row[0])

    def games(self) -> int:
        with self._conn() as c:
            row = c.execute("SELECT value FROM meta WHERE key = ?",
                            (GLOBAL_GAMES_KEY,)).fetchone()
            return int(row[0]) if row else 0

    def save_profile(self, nick: str, token: str,
                     xp: int = 0, wins: int = 0) -> None:
        if not nick:
            return  # the anonymous guest slot is cookie-only by design
        with _LOCK, self._conn() as c:
            c.execute(
                "INSERT INTO profiles (nick, token, xp, wins, updated) "
                "VALUES (?, ?, ?, ?, datetime('now')) "
                "ON CONFLICT(nick) DO UPDATE SET token = excluded.token, "
                "xp = excluded.xp, wins = excluded.wins, "
                "updated = excluded.updated",
                (nick, token, int(xp), int(wins)))

    def load_profile(self, nick: str) -> str | None:
        if not nick:
            return None
        with self._conn() as c:
            row = c.execute("SELECT token FROM profiles WHERE nick = ?",
                            (nick,)).fetchone()
            return row[0] if row else None

    def profile_count(self) -> int:
        with self._conn() as c:
            return int(c.execute(
                "SELECT COUNT(*) FROM profiles").fetchone()[0])

    def leaderboard(self, limit: int = 10) -> list[tuple[str, int, int]]:
        """Top named players: (nick, xp, wins), best first."""
        with self._conn() as c:
            return [(r[0], int(r[1]), int(r[2])) for r in c.execute(
                "SELECT nick, xp, wins FROM profiles "
                "ORDER BY xp DESC, wins DESC, nick ASC LIMIT ?",
                (int(limit),))]


class SqlAlchemyStore:
    """The same contract on any SQLAlchemy URL (Postgres, MySQL, …) —
    this is the truly permanent backend for cloud deployments."""

    def __init__(self, url: str):
        import sqlalchemy as sa
        self._sa = sa
        self.engine = sa.create_engine(url, pool_pre_ping=True)
        with self.engine.begin() as c:
            c.exec_driver_sql(
                "CREATE TABLE IF NOT EXISTS avoidle_meta ("
                "key VARCHAR(64) PRIMARY KEY, value BIGINT NOT NULL)")
            c.exec_driver_sql(
                "CREATE TABLE IF NOT EXISTS avoidle_profiles ("
                "nick VARCHAR(32) PRIMARY KEY, token TEXT NOT NULL, "
                "xp BIGINT NOT NULL DEFAULT 0, "
                "wins BIGINT NOT NULL DEFAULT 0, "
                "updated TIMESTAMP NOT NULL)")

    def bump_games(self, n: int = 1) -> int:
        sa = self._sa
        with _LOCK, self.engine.begin() as c:
            done = c.execute(sa.text(
                "UPDATE avoidle_meta SET value = value + :n "
                "WHERE key = :k"), {"n": n, "k": GLOBAL_GAMES_KEY})
            if done.rowcount == 0:
                c.execute(sa.text(
                    "INSERT INTO avoidle_meta (key, value) "
                    "VALUES (:k, :n)"), {"n": n, "k": GLOBAL_GAMES_KEY})
            row = c.execute(sa.text(
                "SELECT value FROM avoidle_meta WHERE key = :k"),
                {"k": GLOBAL_GAMES_KEY}).fetchone()
            return int(row[0])

    def raise_games_floor(self, n: int) -> int:
        sa = self._sa
        with _LOCK, self.engine.begin() as c:
            cur = c.execute(sa.text(
                "SELECT value FROM avoidle_meta WHERE key = :k"),
                {"k": GLOBAL_GAMES_KEY}).fetchone()
            if cur is None:
                c.execute(sa.text(
                    "INSERT INTO avoidle_meta (key, value) "
                    "VALUES (:k, :n)"), {"n": n, "k": GLOBAL_GAMES_KEY})
                return n
            if int(cur[0]) < n:
                c.execute(sa.text(
                    "UPDATE avoidle_meta SET value = :n WHERE key = :k"),
                    {"n": n, "k": GLOBAL_GAMES_KEY})
                return n
            return int(cur[0])

    def games(self) -> int:
        sa = self._sa
        with self.engine.connect() as c:
            row = c.execute(sa.text(
                "SELECT value FROM avoidle_meta WHERE key = :k"),
                {"k": GLOBAL_GAMES_KEY}).fetchone()
            return int(row[0]) if row else 0

    def save_profile(self, nick: str, token: str,
                     xp: int = 0, wins: int = 0) -> None:
        if not nick:
            return
        sa = self._sa
        params = {"t": token, "n": nick, "x": int(xp), "w": int(wins)}
        with _LOCK, self.engine.begin() as c:
            done = c.execute(sa.text(
                "UPDATE avoidle_profiles SET token = :t, xp = :x, "
                "wins = :w, updated = CURRENT_TIMESTAMP WHERE nick = :n"),
                params)
            if done.rowcount == 0:
                c.execute(sa.text(
                    "INSERT INTO avoidle_profiles "
                    "(nick, token, xp, wins, updated) "
                    "VALUES (:n, :t, :x, :w, CURRENT_TIMESTAMP)"), params)

    def load_profile(self, nick: str) -> str | None:
        if not nick:
            return None
        sa = self._sa
        with self.engine.connect() as c:
            row = c.execute(sa.text(
                "SELECT token FROM avoidle_profiles WHERE nick = :n"),
                {"n": nick}).fetchone()
            return row[0] if row else None

    def profile_count(self) -> int:
        sa = self._sa
        with self.engine.connect() as c:
            return int(c.execute(sa.text(
                "SELECT COUNT(*) FROM avoidle_profiles")).fetchone()[0])

    def leaderboard(self, limit: int = 10) -> list[tuple[str, int, int]]:
        sa = self._sa
        with self.engine.connect() as c:
            rows = c.execute(sa.text(
                "SELECT nick, xp, wins FROM avoidle_profiles "
                "ORDER BY xp DESC, wins DESC, nick ASC LIMIT :l"),
                {"l": int(limit)}).fetchall()
            return [(r[0], int(r[1]), int(r[2])) for r in rows]


def _database_url() -> str | None:
    url = os.environ.get("DATABASE_URL", "").strip()
    if url:
        return url
    try:  # Streamlit Cloud: secrets.toml -> DATABASE_URL = "postgresql://…"
        import streamlit as st
        return str(st.secrets["DATABASE_URL"]).strip() or None
    except Exception:
        return None


def get_store():
    """The process-wide store (created once, shared by all sessions)."""
    global _STORE
    if _STORE is None:
        with _LOCK:
            if _STORE is None:
                url = _database_url()
                if url:
                    try:
                        _STORE = SqlAlchemyStore(url)
                    except Exception:
                        _STORE = None  # fall through to SQLite
                if _STORE is None:
                    path = os.environ.get("AVOIDLE_DB_PATH",
                                          os.path.join("data", "avoidle.db"))
                    _STORE = SqliteStore(path)
    return _STORE
