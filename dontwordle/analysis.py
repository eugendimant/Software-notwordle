"""Move-quality analysis: how well did a guess preserve the word pool?

In Don't Wordle a *good* move keeps as many valid words as possible for
the next row. For a candidate move ``w`` against the true secret, the
retained pool is the set of words consistent with the feedback ``w``
would receive. This module ranks the played word against the
alternatives that were available, fully vectorized with numpy so even
the 14,855-word opening pool is analyzed in well under a second.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from functools import lru_cache

import numpy as np

from .engine import GRAY, GREEN, YELLOW, score_guess

_CODE = {GRAY: 0, YELLOW: 1, GREEN: 2}


def pattern_id(feedback: str) -> int:
    """Base-3 integer id of a 'G/Y/-' feedback string."""
    n = 0
    for c in reversed(feedback):
        n = n * 3 + _CODE[c]
    return n


class Analyzer:
    """Vectorized feedback computation over one fixed dictionary."""

    def __init__(self, dictionary: frozenset[str] | tuple[str, ...]):
        self.words: list[str] = sorted(dictionary)
        self.index = {w: i for i, w in enumerate(self.words)}
        alphabet = sorted({c for w in self.words for c in w})
        self.char_idx = {c: i for i, c in enumerate(alphabet)}
        n, a = len(self.words), len(alphabet)
        self.enc = np.empty((n, 5), dtype=np.int8)
        for i, w in enumerate(self.words):
            for j, c in enumerate(w):
                self.enc[i, j] = self.char_idx[c]
        # letter histogram per word, for duplicate-aware yellow accounting
        self.counts = np.zeros((n, a), dtype=np.int8)
        rows = np.arange(n)
        for j in range(5):
            np.add.at(self.counts, (rows, self.enc[:, j]), 1)

    def _rows(self, pool: list[str]) -> np.ndarray:
        return np.fromiter((self.index[w] for w in pool), dtype=np.int64,
                           count=len(pool))

    def feedback_codes(self, guess: str, rows: np.ndarray) -> np.ndarray:
        """Pattern id of ``guess`` scored against each word in ``rows``,
        replicating score_guess() (greens first, then yellows L→R)."""
        g = np.array([self.char_idx[c] for c in guess], dtype=np.int8)
        sub = self.enc[rows]                      # (M, 5)
        greens = sub == g                         # (M, 5)
        avail = self.counts[rows].astype(np.int16)
        m = np.arange(len(rows))
        for j in range(5):
            np.subtract.at(avail, (m[greens[:, j]], g[j]), 1)
        codes = np.zeros(len(rows), dtype=np.int16)
        p3 = 1
        for j in range(5):
            a = avail[:, g[j]]
            yellow = ~greens[:, j] & (a > 0)
            avail[yellow, g[j]] -= 1
            codes += (2 * greens[:, j] + yellow).astype(np.int16) * p3
            p3 *= 3
        return codes

    def retained_counts(self, candidates: list[str], pool: list[str],
                        secret: str) -> np.ndarray:
        """For each candidate move: how many pool words stay playable
        after the feedback it would earn against ``secret``."""
        rows = self._rows(pool)
        out = np.empty(len(candidates), dtype=np.int32)
        for k, w in enumerate(candidates):
            target = pattern_id(score_guess(w, secret))
            out[k] = int((self.feedback_codes(w, rows) == target).sum())
        return out


@dataclass(frozen=True)
class MoveRating:
    """How the played word compared to the alternatives available."""
    word: str
    retained: int          # words kept for the next row
    pool_size: int         # options that were available
    percentile: float      # 0–100 mid-rank: share of alternatives beaten
    best_word: str         # safest alternative found
    best_retained: int
    exact: bool            # True if every alternative was checked
    fatal: bool = False    # the played word WAS the secret
    forced: bool = False   # there was nothing else to play

    @property
    def grade(self) -> str:
        if self.forced:
            return "⚰️ forced"   # no alternatives — not the player's fault
        if self.fatal:
            return "💀 fatal"
        p = self.percentile
        if p >= 90:
            return "🟢 brilliant"
        if p >= 70:
            return "🟢 great"
        if p >= 45:
            return "🟡 fine"
        if p >= 20:
            return "🟠 risky"
        return "🔴 reckless"


EXACT_LIMIT = 2500     # analyze every candidate when the pool is this small
SAMPLE_SIZE = 600      # otherwise rate against a random sample


def rate_move(analyzer: Analyzer, played: str, pool_before: list[str],
              secret: str, rng: random.Random | None = None,
              exact_limit: int = EXACT_LIMIT,
              sample_size: int = SAMPLE_SIZE) -> MoveRating:
    """Rate ``played`` (already guessed) against the pool it was chosen
    from. Exhaustive for small pools, sampled for the huge early ones."""
    rng = rng or random.Random(0)
    exact = len(pool_before) <= exact_limit
    if exact:
        candidates = list(pool_before)
    else:
        candidates = rng.sample(pool_before, sample_size)
        if played not in candidates:
            candidates.append(played)
    retained = analyzer.retained_counts(candidates, pool_before, secret)
    mine = retained[candidates.index(played)]
    best_i = int(np.argmax(retained))
    # mid-rank percentile among the *other* options: ties count half, so
    # the worst move reads 0%, an all-tie field reads 50%
    others = len(retained) - 1
    if others > 0:
        worse = int((retained < mine).sum())
        ties = int((retained == mine).sum()) - 1  # exclude the move itself
        percentile = 100.0 * (worse + 0.5 * ties) / others
    else:
        percentile = 100.0
    return MoveRating(
        word=played,
        retained=int(mine),
        pool_size=len(pool_before),
        percentile=percentile,
        best_word=candidates[best_i],
        best_retained=int(retained[best_i]),
        exact=exact,
        fatal=played == secret,
        forced=len(pool_before) == 1,
    )


@lru_cache(maxsize=8)
def analyzer_for(lang: str) -> Analyzer:
    from . import words as W
    return Analyzer(W.allowed_guesses(lang))
