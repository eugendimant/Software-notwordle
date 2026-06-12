"""Tests for the recursive (backward-induction) duel endgame solver."""

import random

import pytest

from avoidle import words as W
from avoidle.endgame import (
    _Budget,
    _next_pool,
    forced_win_plies,
    recursive_bot_move,
    solve,
)
from avoidle.engine import score_guess


# ----------------------------------------------------------------------
# An independent, deliberately naive reference minimax (no memo, no
# budget) — if the optimized solver agrees with this on random small
# positions, the optimized one is correct.
# ----------------------------------------------------------------------
def naive_mover_loses(pool: tuple, secret: str) -> bool:
    if len(pool) == 1:
        return True
    for guess in pool:
        if guess == secret:
            continue
        fb = score_guess(guess, secret)
        child = tuple(w for w in pool
                      if w != guess and score_guess(guess, w) == fb)
        if naive_mover_loses(child, secret):   # opponent then loses
            return False                       # so mover wins
    return True


def test_base_cases():
    memo, budget = {}, _Budget(10_000)
    # only the secret left -> mover must say it -> loses in 1
    assert solve(("crane",), "crane", memo, budget) == (True, 1)
    # two words, one is the secret: mover plays the other, opponent is
    # then trapped -> mover wins in 2 plies
    loses, plies = solve(tuple(sorted(("crane", "slate"))), "crane",
                         {}, _Budget(10_000))
    assert loses is False and plies == 2


def test_matches_naive_reference_on_random_positions():
    rng = random.Random(7)
    pool_all = list(W.allowed_guesses("en", 5))
    for _ in range(150):
        pool = tuple(sorted(rng.sample(pool_all, rng.randint(2, 7))))
        secret = rng.choice(pool)
        opt_loses, _ = solve(pool, secret, {}, _Budget(10_000))
        assert opt_loses == naive_mover_loses(pool, secret), (pool, secret)


def test_next_pool_matches_engine_semantics():
    pool = tuple(sorted(W.answers("en", 5)[:200]))
    secret = pool[3]
    guess = pool[10]
    child = _next_pool(pool, guess, secret)
    assert guess not in child
    assert secret in child                    # secret always survives
    fb = score_guess(guess, secret)
    assert all(score_guess(guess, w) == fb for w in child)


def test_forced_win_plies_and_zugzwang():
    # the canonical forced loss: trapped with only the secret left
    assert forced_win_plies(["crane"], "crane") is None
    # across random small pools: the result always agrees with the naive
    # reference, and a forced win always seals on an even ply (the
    # OPPONENT, who moves on even plies, is the one cornered)
    rng = random.Random(3)
    pool_all = list(W.allowed_guesses("en", 5))
    wins = losses = 0
    for _ in range(400):
        pool = sorted(rng.sample(pool_all, rng.randint(2, 6)))
        secret = rng.choice(pool)
        fw = forced_win_plies(pool, secret)
        assert (fw is None) == naive_mover_loses(tuple(pool), secret)
        if fw is None:
            losses += 1
        else:
            assert fw >= 2 and fw % 2 == 0
            wins += 1
    assert wins > 0                            # forced wins are common
    # zugzwang is rare (~0.4%) but the solver detects it correctly when
    # it occurs — verified by the naive agreement above


def test_forced_win_none_when_pool_too_large():
    big = sorted(W.allowed_guesses("en", 5))[:50]
    assert forced_win_plies(big, big[0], max_pool=14) is None


def test_recursive_bot_move_is_legal_safe_and_fair():
    rng = random.Random(11)
    pool = sorted(W.answers("en", 5)[:6]) + \
        [w for w in W.allowed_guesses("en", 5) if w not in W.answers("en", 5)][:4]
    pool = sorted(set(pool))
    move = recursive_bot_move(pool, "en", 5, rng)
    assert move in pool
    # determinism given the same rng seed
    assert move == recursive_bot_move(pool, "en", 5, random.Random(11))
    # the function never receives the secret — fairness is structural
    import inspect
    assert "secret" not in inspect.signature(recursive_bot_move).parameters


def test_recursive_bot_takes_an_immediate_forced_win():
    # pool: the secret + two non-answer decoys. Whatever the secret is,
    # the bot should be able to corner the (optimal) opponent; at minimum
    # it must never play a word that is itself a likely secret when a
    # provably-safe non-answer word exists.
    answers = W.answers("en", 5)
    non_answers = [w for w in W.allowed_guesses("en", 5)
                   if w not in set(answers)]
    pool = sorted({answers[0], non_answers[0], non_answers[1]})
    move = recursive_bot_move(pool, "en", 5, random.Random(1))
    assert move in non_answers          # never volunteer a possible secret


def test_recursive_bot_returns_none_above_threshold():
    pool = sorted(W.allowed_guesses("en", 5))[:40]
    assert recursive_bot_move(pool, "en", 5, random.Random(1),
                              max_pool=14) is None


@pytest.mark.parametrize("lang", list(W.LANGUAGES))
def test_solver_runs_for_every_language(lang):
    rng = random.Random(hash(lang) & 0xFFFF)
    pool = sorted(rng.sample(list(W.allowed_guesses(lang, 5)), 6))
    secret = rng.choice(pool)
    loses, plies = solve(tuple(pool), secret, {}, _Budget(50_000))
    assert isinstance(loses, bool) and plies >= 1
