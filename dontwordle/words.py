"""Word list loading and secret-word selection."""

from __future__ import annotations

import datetime as _dt
import random
import zlib
from functools import lru_cache
from pathlib import Path

_DATA_DIR = Path(__file__).parent / "data"

WORD_LENGTH = 5


def _load(name: str) -> tuple[str, ...]:
    text = (_DATA_DIR / name).read_text(encoding="utf-8")
    words = tuple(
        w for w in (line.strip().lower() for line in text.splitlines())
        if len(w) == WORD_LENGTH and w.isalpha()
    )
    if not words:
        raise RuntimeError(f"word list {name!r} is empty")
    return words


@lru_cache(maxsize=1)
def allowed_guesses() -> frozenset[str]:
    """Every word the player may type (and every possible secret)."""
    return frozenset(_load("allowed_guesses.txt")) | frozenset(answers())


@lru_cache(maxsize=1)
def answers() -> tuple[str, ...]:
    """Curated common words used as hidden secrets (sorted, stable)."""
    return _load("answers.txt")


def daily_secret(date: _dt.date | None = None) -> str:
    """Deterministic secret of the day — same word for every player."""
    date = date or _dt.date.today()
    pool = answers()
    # crc32 is stable across platforms and Python versions (hash() is not).
    idx = zlib.crc32(f"dontwordle:{date.isoformat()}".encode()) % len(pool)
    return pool[idx]


def random_secret(rng: random.Random | None = None) -> str:
    rng = rng or random.Random()
    return rng.choice(answers())


def random_starting_word(rng: random.Random | None = None) -> str:
    """A random playable word, like the official 'Random Starting Word'."""
    rng = rng or random.Random()
    return rng.choice(sorted(allowed_guesses()))
