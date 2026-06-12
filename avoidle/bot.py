"""Fair duel opponents of selectable strength.

Every level plays with PUBLIC information only — the playable pool,
the published answer list and the frequency ordering. None of them ever
look at the secret, so a bot "blunder" is a genuine gamble, exactly
like a human's.

The strategic insight the stronger bots exploit (and good humans can
too): secrets are always drawn from the curated answer list, weighted
toward common words. A pool word that is NOT in the answer list is a
provably safe play; a rare answer word is safer than a common one.
"""

from __future__ import annotations

import random
from functools import lru_cache

from . import words as W

BOT_LEVELS = {
    "easy": "😴 Easy — picks any playable word, blunders happily",
    "normal": "🤖 Normal — avoids the likeliest secrets",
    "hard": "🧠 Hard — plays provably-safe words while they exist",
}

#: score multiplier for duel wins, by opponent strength
BOT_MULTIPLIER = {"easy": 1.0, "normal": 1.5, "hard": 2.5}


@lru_cache(maxsize=16)
def _answer_rank(lang: str, length: int) -> dict[str, int]:
    """word -> frequency rank (1 = likeliest secret); answer words only."""
    return {w: i + 1 for i, w in enumerate(W.answers(lang, length))}


def bot_pick(level: str, pool: list[str], lang: str, length: int,
             rng: random.Random) -> str:
    """The bot's move. ``pool`` is the current playable pool (the bot,
    like any player, must pick from it)."""
    if len(pool) == 1:
        return pool[0]  # trapped: forced, exactly like a human
    ranks = _answer_rank(lang, length)
    if level == "hard":
        # non-answer words can never be the secret: provably safe
        safe = [w for w in pool if w not in ranks]
        if safe:
            return rng.choice(safe)
        # cornered among answers: gamble on the rarest one
        return max(pool, key=lambda w: ranks.get(w, 0))
    if level == "normal":
        # dodge the likeliest quartile of secrets, otherwise play freely
        cutoff = len(ranks) // 4
        cautious = [w for w in pool if ranks.get(w, cutoff + 1) > cutoff]
        return rng.choice(cautious or pool)
    # easy: reckless — half the time it deliberately gravitates toward
    # common answer words (the likeliest secrets), tuned by simulation
    # to give beginners a winnable opponent
    cutoff = len(ranks) // 4
    risky = [w for w in pool if ranks.get(w, cutoff + 1) <= cutoff]
    if risky and rng.random() < 0.5:
        return rng.choice(risky)
    return rng.choice(pool)
