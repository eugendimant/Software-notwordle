"""Recursive endgame solver for the Duel hot-potato game.

Duel is a finite, alternating, perfect-information game *once the hidden
word is fixed*: players take turns naming a word from the current
consistent pool; whoever names the secret loses; every other word
shrinks the pool deterministically (the words still consistent with the
feedback it earns). The pool always contains the secret and strictly
shrinks, so the tree is finite.

That makes it solvable by **backward induction (minimax)**:

    a position is a forced LOSS for the player to move
    iff every legal move hands the opponent a forced WIN.

``solve`` computes that value recursively (memoised). The Hard duel bot
does NOT know the secret, so it applies the solver across its *belief*
over which pool word is the secret — the same frequency-weighted prior
the game actually draws from — and plays the move that maximises its
probability of forcing the opponent to say the word. This is genuine
recursive, higher-order reasoning under uncertainty, and it never reads
the real secret (the move function has no secret parameter).
"""

from __future__ import annotations

import math
import random
from functools import lru_cache

from .engine import score_guess

#: only engage the exact solver at or below this pool size — above it the
#: tree is too wide and the caller falls back to the heuristic bot.
MAX_SOLVE_POOL = 14
#: hard ceiling on recursion nodes per decision, so a pathological tree
#: can never stall a turn (caller falls back on overflow).
NODE_BUDGET = 200_000


class _Budget:
    __slots__ = ("n",)

    def __init__(self, n: int):
        self.n = n


class SolveAborted(Exception):
    """Raised when the node budget is exhausted; caller falls back."""


def _next_pool(pool: tuple[str, ...], guess: str, secret: str
               ) -> tuple[str, ...]:
    """Pool after ``guess`` is played against ``secret`` — the words still
    consistent with the feedback (mirrors the engine's filter exactly).
    Always contains ``secret``; never contains ``guess``."""
    fb = score_guess(guess, secret)
    return tuple(w for w in pool
                 if w != guess and score_guess(guess, w) == fb)


def solve(pool: tuple[str, ...], secret: str, memo: dict, budget: _Budget
          ) -> tuple[bool, int]:
    """Backward-induction value of the position (player to move).

    Returns ``(mover_loses, plies)``: whether optimal play forces the
    mover to eventually say the secret, and the length of the optimal
    line (shortest forced win, or longest survival when losing)."""
    if len(pool) == 1:               # only the secret remains
        return True, 1               # mover must say it now
    key = (pool, secret)
    cached = memo.get(key)
    if cached is not None:
        return cached
    budget.n -= 1
    if budget.n < 0:
        raise SolveAborted
    mover_loses = True
    win_plies = None                 # fastest way to force the opponent
    lose_plies = 1                   # longest the mover can hold out
    for guess in pool:
        if guess == secret:
            continue                 # nobody volunteers the secret
        opp_loses, d = solve(_next_pool(pool, guess, secret), secret,
                             memo, budget)
        if opp_loses:
            mover_loses = False
            win_plies = 1 + d if win_plies is None else min(win_plies, 1 + d)
        else:
            lose_plies = max(lose_plies, 1 + d)
    result = (False, win_plies) if not mover_loses else (True, lose_plies)
    memo[key] = result
    return result


def forced_win_plies(pool, secret: str,
                     max_pool: int = MAX_SOLVE_POOL) -> int | None:
    """God's-eye helper: if the player to move can force the *opponent*
    to say the word, how many plies until that's sealed? ``None`` if no
    forced win (or the pool is too large to solve)."""
    pool = tuple(sorted(set(pool)))
    if not (1 <= len(pool) <= max_pool):
        return None
    try:
        mover_loses, plies = solve(pool, secret, {}, _Budget(NODE_BUDGET))
    except SolveAborted:
        return None
    return None if mover_loses else plies


@lru_cache(maxsize=8)
def _secret_prior(lang: str, length: int) -> dict[str, float]:
    """The TRUE generative weight of each answer word (1/√rank), matching
    how the game draws secrets. Public knowledge — fair for the bot."""
    from . import words as W
    answers = W.answers(lang, length)
    return {w: 1.0 / math.sqrt(i + 1) for i, w in enumerate(answers)}


def recursive_bot_move(pool: list[str], lang: str, length: int,
                       rng: random.Random,
                       max_pool: int = MAX_SOLVE_POOL) -> str | None:
    """Hard bot's endgame move via recursive reasoning over its belief
    about the secret. Returns the chosen word, or ``None`` if the pool is
    too large / the search overflows (caller falls back to heuristics).

    Fair by construction: the secret is never an input. The bot weights
    each pool word by the real secret-prior and, for every candidate
    move, recursively asks "would an optimal opponent then be forced to
    lose?" — averaging over its belief."""
    ptuple = tuple(sorted(set(pool)))
    if not (2 <= len(ptuple) <= max_pool):
        return None
    prior = _secret_prior(lang, length)
    # candidate secrets: pool words that COULD be the secret (answers),
    # weighted; non-answer pool words can never be it.
    hyps = {s: prior[s] for s in ptuple if s in prior}
    if not hyps:
        return None                  # no pool word is a possible secret
    total = sum(hyps.values())
    budget = _Budget(NODE_BUDGET)
    win_prob = {w: 0.0 for w in ptuple}
    secret_prob = {w: hyps.get(w, 0.0) / total for w in ptuple}
    try:
        for s, weight in hyps.items():
            memo: dict = {}
            for w in ptuple:
                if w == s:
                    continue         # playing w==s loses this hypothesis
                opp_loses, _ = solve(_next_pool(ptuple, w, s), s, memo,
                                     budget)
                if opp_loses:        # opponent forced to say it -> bot wins
                    win_prob[w] += weight
    except SolveAborted:
        return None
    for w in win_prob:
        win_prob[w] /= total
    # maximise forced-win probability; break ties toward the word least
    # likely to be the secret (the classic safe-play heuristic); then rng
    best = max(win_prob.values())
    contenders = [w for w in ptuple if win_prob[w] >= best - 1e-12]
    safest = min(secret_prob[w] for w in contenders)
    final = [w for w in contenders if secret_prob[w] <= safest + 1e-12]
    return rng.choice(sorted(final))
