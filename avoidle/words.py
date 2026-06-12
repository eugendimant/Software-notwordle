"""Word list loading, language support, and secret-word selection."""

from __future__ import annotations

import datetime as _dt
import math
import random
import unicodedata
import zlib
from functools import lru_cache
from pathlib import Path

_DATA_DIR = Path(__file__).parent / "data"

WORD_LENGTH = 5            # default/classic length
WORD_LENGTHS = (4, 5, 6)   # supported board sizes

#: dictionary languages (the interface itself stays English)
LANGUAGES = {
    "en": "🇺🇸 English",
    "de": "🇩🇪 German",
    "es": "🇪🇸 Spanish",
    "ru": "🇷🇺 Russian",
}

#: on-screen keyboard rows per language
KEYBOARDS = {
    "en": ("qwertyuiop", "asdfghjkl", "zxcvbnm"),
    "de": ("qwertzuiopü", "asdfghjklöä", "yxcvbnm"),
    "es": ("qwertyuiop", "asdfghjklñ", "zxcvbnm"),
    "ru": ("йцукенгшщзхъ", "фывапролджэ", "ячсмитьбю"),
}


def _load(lang: str, name: str, length: int) -> tuple[str, ...]:
    if lang not in LANGUAGES:
        raise ValueError(f"unsupported language {lang!r}")
    if length not in WORD_LENGTHS:
        raise ValueError(f"unsupported word length {length!r}")
    text = (_DATA_DIR / lang / name).read_text(encoding="utf-8")
    words = tuple(
        w for w in (line.strip().lower() for line in text.splitlines())
        if len(w) == length and w.isalpha()
    )
    if not words:
        raise RuntimeError(f"word list {lang}/{name} is empty")
    return words


@lru_cache(maxsize=16)
def allowed_guesses(lang: str = "en", length: int = WORD_LENGTH) -> frozenset[str]:
    """Every word the player may type (and every possible secret)."""
    return (frozenset(_load(lang, f"allowed_{length}.txt", length))
            | frozenset(answers(lang, length)))


@lru_cache(maxsize=16)
def answers(lang: str = "en", length: int = WORD_LENGTH) -> tuple[str, ...]:
    """Curated common words used as hidden secrets, ordered most-frequent
    first (file order = corpus frequency rank)."""
    return _load(lang, f"answers_{length}.txt", length)


@lru_cache(maxsize=16)
def _cumulative_weights(lang: str, length: int) -> tuple[float, ...]:
    """Zipf-flavoured weights (1/√rank): everyday words are several times
    likelier secrets than obscure ones, so frequency intuition pays off,
    while the tail still appears often enough to stay surprising."""
    total = 0.0
    cum = []
    for rank in range(1, len(answers(lang, length)) + 1):
        total += 1.0 / math.sqrt(rank)
        cum.append(total)
    return tuple(cum)


def frequency_rank(word: str, lang: str = "en",
                   length: int = WORD_LENGTH) -> int | None:
    """1-based how-common rank of a secret (1 = most common), or None."""
    pool = answers(lang, length)
    try:
        return pool.index(word) + 1
    except ValueError:
        return None


def normalize_guess(word: str, lang: str) -> str:
    """Fold typed input onto the dictionary's alphabet conventions:
    Russian ё→е; Spanish accented vowels fold to base (ñ stays distinct)."""
    word = word.strip().lower()
    if lang == "ru":
        return word.replace("ё", "е")
    if lang == "es":
        word = word.replace("ñ", "\x00")
        word = "".join(c for c in unicodedata.normalize("NFD", word)
                       if not unicodedata.combining(c))
        return word.replace("\x00", "ñ")
    return word


def daily_secret(lang: str = "en", length: int = WORD_LENGTH,
                 date: _dt.date | None = None) -> str:
    """Deterministic, frequency-weighted secret of the day — the same
    word for every player."""
    date = date or _dt.date.today()
    pool = answers(lang, length)
    cum = _cumulative_weights(lang, length)
    # crc32 is stable across platforms and Python versions (hash() is not).
    # the historical seed string is kept VERBATIM so daily words stay
    # identical across the Avoidle rebrand — do not modernize it
    seed = f"dontwordle:{lang}:{length}:{date.isoformat()}"
    u = (zlib.crc32(seed.encode()) / 0xFFFFFFFF) * cum[-1]
    import bisect
    return pool[min(bisect.bisect_left(cum, u), len(pool) - 1)]


def random_secret(lang: str = "en", length: int = WORD_LENGTH,
                  rng: random.Random | None = None) -> str:
    """Frequency-weighted random secret (common words come up more)."""
    rng = rng or random.Random()
    pool = answers(lang, length)
    cum = _cumulative_weights(lang, length)
    return rng.choices(pool, cum_weights=cum, k=1)[0]
