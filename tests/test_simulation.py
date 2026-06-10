"""Property/invariant tests via self-play across all presets."""

import random

import pytest

from dontwordle import words
from dontwordle.engine import PRESETS, DontWordleGame, GameStatus
from dontwordle.simulate import POLICIES, play_one, run


@pytest.mark.parametrize("preset", list(PRESETS))
@pytest.mark.parametrize("policy_name", list(POLICIES))
def test_selfplay_invariants(preset, policy_name):
    """Hundreds of full games must uphold every engine invariant."""
    rng = random.Random(123)
    cfg = PRESETS[preset]
    policy = POLICIES[policy_name]
    answers = words.answers()
    for i in range(60):
        secret = rng.choice(answers)
        game = DontWordleGame(secret, words.allowed_guesses(), cfg,
                              rng=random.Random(i))
        prev_count = game.remaining_count
        while not game.is_over:
            if game.is_trapped and game.can_undo():
                assert game.undo()
                prev_count = game.remaining_count
                continue
            assert secret in game.remaining_words, "secret must stay playable"
            game.submit(policy(game.remaining_words, rng))
            assert game.remaining_count <= prev_count, "pool only shrinks"
            assert game.remaining_count >= 1
            prev_count = game.remaining_count
        # terminal state must be coherent
        if game.status is GameStatus.WORDLED:
            assert game.history[-1].guess == secret
            assert game.score() == 0
        else:
            assert game.status is GameStatus.SURVIVED
            assert game.guesses_made == cfg.max_guesses
            assert all(t.guess != secret for t in game.history)
            assert game.score() >= 10
        assert game.undos_used <= cfg.max_undos


def test_full_game_with_undo_recovery():
    """play_one with undo support always ends in a terminal state."""
    for preset in PRESETS:
        g = play_one("crane", PRESETS[preset], POLICIES["random"],
                     random.Random(99))
        assert g.is_over


def test_difficulty_ordering():
    """Sanity: Zen (infinite undos) must beat Impossible (none)."""
    zen = run(PRESETS["zen"], "random", 80, seed=1)
    imp = run(PRESETS["impossible"], "random", 80, seed=1)
    assert zen.win_rate >= imp.win_rate
    # "unlimited" is a huge-but-finite budget; near-perfect is expected
    assert zen.win_rate >= 0.95


def test_share_text_after_selfplay():
    g = play_one("quart", PRESETS["classic"], POLICIES["common"],
                 random.Random(5))
    txt = g.share_text("Don't Wordle Test")
    assert txt.startswith("Don't Wordle Test")
    assert any(e in txt for e in ("🟩", "🟨", "⬜")) or g.guesses_made == 0
