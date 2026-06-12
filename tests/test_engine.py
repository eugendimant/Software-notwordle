"""Unit tests for the Avoidle engine."""

import datetime
import random

import pytest

from avoidle import words
from avoidle.engine import (
    PRESETS,
    AvoidleGame,
    GameConfig,
    GameStatus,
    InvalidGuess,
    is_consistent,
    score_guess,
)


# ----------------------------------------------------------------------
# Feedback algorithm (the classic duplicate-letter minefield)
# ----------------------------------------------------------------------
@pytest.mark.parametrize(
    "guess,secret,expected",
    [
        ("crane", "crane", "GGGGG"),
        ("stone", "crane", "---GG"),
        ("speed", "abide", "--Y-Y"),   # one E in secret -> first E yellow only
        ("speed", "erase", "Y-YY-"),   # two Es in secret, none positioned
        ("allee", "level", "-YYGY"),
        ("loops", "spool", "YYGYY"),
        ("aaaaa", "abase", "G-G--"),
        ("abase", "aaaaa", "G-G--"),
    ],
)
def test_score_guess_cases(guess, secret, expected):
    assert score_guess(guess, secret) == expected


def test_score_guess_duplicate_accounting():
    # secret has one 'e'; guess has three -> exactly one colored
    fb = score_guess("eeeee", "abide")
    assert fb.count("G") + fb.count("Y") == 1
    # green consumes the duplicate budget first
    fb = score_guess("eexxe", "exeee")  # secret has 4 e's
    assert fb[0] == "G"


def test_score_symmetric_length_check():
    with pytest.raises(ValueError):
        score_guess("abc", "abcde")


def test_consistency_secret_always_consistent_with_own_feedback():
    rng = random.Random(42)
    pool = words.answers()
    for _ in range(200):
        secret, guess = rng.choice(pool), rng.choice(pool)
        fb = score_guess(guess, secret)
        assert is_consistent(secret, guess, fb)


# ----------------------------------------------------------------------
# Word lists
# ----------------------------------------------------------------------
def test_word_lists_load_and_nest():
    allowed = words.allowed_guesses()
    ans = words.answers()
    assert len(allowed) > 10_000
    assert len(ans) > 2_000
    assert set(ans) <= allowed
    assert all(len(w) == 5 and w.isalpha() and w.islower() for w in ans)


def test_daily_secret_is_deterministic_and_varies():
    d1 = datetime.date(2026, 6, 10)
    assert words.daily_secret("en", 5, d1) == words.daily_secret("en", 5, d1)
    week = {words.daily_secret("en", 5, d1 + datetime.timedelta(days=i))
            for i in range(7)}
    assert len(week) > 1
    assert all(w in words.answers() for w in week)
    # languages get different daily words (with overwhelming probability)
    langs = {lang: words.daily_secret(lang, 5, d1) for lang in words.LANGUAGES}
    assert len(set(langs.values())) > 1


# ----------------------------------------------------------------------
# Game flow
# ----------------------------------------------------------------------
@pytest.fixture()
def game():
    return AvoidleGame(
        secret="crane",
        dictionary=words.allowed_guesses(),
        config=PRESETS["classic"],
        rng=random.Random(7),
    )


def test_instant_loss_on_secret(game):
    game.submit("crane")
    assert game.status is GameStatus.WORDLED
    assert game.score() == 0


def test_survival_win():
    g = AvoidleGame("crane", words.allowed_guesses(), PRESETS["classic"],
                       rng=random.Random(1))
    for _ in range(g.config.max_guesses):
        assert g.status is GameStatus.PLAYING
        g.submit(next(w for w in g.remaining_words if w != "crane"))
    assert g.status is GameStatus.SURVIVED
    assert g.score() > 0
    txt = g.share_text()
    assert "SURVIVED" in txt and txt.count("\n") == 2 + g.config.max_guesses - 1


def test_invalid_guesses_rejected(game):
    for bad, frag in [
        ("cran", "5-letter"),
        ("zzzzz", "not in the dictionary"),
    ]:
        with pytest.raises(InvalidGuess, match=frag):
            game.submit(bad)
    game.submit("stone")
    with pytest.raises(InvalidGuess, match="already played"):
        game.submit("stone")
    # 'stone' vs 'crane' -> ---GG: 'tonne' fits the greens but uses gray T
    with pytest.raises(InvalidGuess, match="T was ruled out"):
        game.submit("tonne")
    assert game.guesses_made == 1


def test_violation_diagnosis_is_specific():
    # the bug-report scenario: TREAT vs CRANE gives E yellow in spot 3;
    # BREAK satisfies the green R but puts E right back in spot 3
    g = AvoidleGame("crane", words.allowed_guesses(), PRESETS["zen"])
    g.submit("treat")
    assert g.history[0].feedback == "-GYY-"
    with pytest.raises(InvalidGuess,
                       match="E can't sit in spot 3 again — it was yellow"):
        g.submit("break")
    # a word that ignores a green lock names the exact spot and letter
    g2 = AvoidleGame("crane", words.allowed_guesses(), PRESETS["zen"])
    g2.submit("stone")
    with pytest.raises(InvalidGuess, match="spot 4 is locked to N"):
        g2.submit("blare")
    # dropping a known (yellow) letter is called out by name
    g3 = AvoidleGame("crane", words.allowed_guesses(), PRESETS["zen"])
    g3.submit("treat")
    with pytest.raises(InvalidGuess, match="must use E"):
        g3.submit("braid")


def test_clue_filtering_shrinks_pool_and_keeps_secret(game):
    before = game.remaining_count
    game.submit("stone")
    assert game.remaining_count < before
    assert "crane" in game.remaining_words
    # played word can never be guessed again: it's filtered out
    assert "stone" not in game.remaining_words


def test_undo_restores_everything(game):
    base_pool = list(game.remaining_words)
    game.submit("stone")
    assert game.undo()
    assert game.history == []
    assert game.remaining_words == base_pool
    assert game.undos_used == 1
    assert game.undos_left == game.config.max_undos - 1


def test_undo_can_revert_a_loss(game):
    game.submit("crane")
    assert game.status is GameStatus.WORDLED
    assert game.undo()
    assert game.status is GameStatus.PLAYING


def test_undo_limits():
    cfg = GameConfig("Test", max_guesses=6, max_undos=1)
    g = AvoidleGame("crane", words.allowed_guesses(), cfg)
    assert not g.undo()           # nothing to undo
    g.submit("stone")
    assert g.undo()
    g.submit("stone")
    assert not g.undo()           # budget exhausted
    assert g.undos_left == 0


def test_no_undo_after_win():
    g = AvoidleGame("crane", words.allowed_guesses(),
                       GameConfig("T", max_guesses=1, max_undos=5))
    g.submit("stone")
    assert g.status is GameStatus.SURVIVED
    assert not g.undo()


def test_hint_is_safe_and_limited(game):
    h = game.hint()
    assert h in game.remaining_words and h != game.secret
    assert game.hints_left == 0
    assert game.hint() is None


def test_peek_samples_remaining(game):
    sample = game.peek()
    assert 1 <= len(sample) <= 5
    assert all(w in game.remaining_words for w in sample)
    assert game.peek() == []      # budget spent


def test_trapped_detection():
    g = AvoidleGame("crane", words.allowed_guesses(), PRESETS["zen"])
    assert not g.is_trapped
    g._pools.append(["crane"])    # force endgame state directly
    assert g.is_trapped
    assert g.safe_words() == []


def test_score_components():
    g = AvoidleGame("crane", words.allowed_guesses(),
                       GameConfig("T", max_guesses=1, max_undos=5))
    g.submit("brand")             # vs CRANE -> -GGG-
    assert g.status is GameStatus.SURVIVED
    fb = g.history[0].feedback
    expected = 100 + sum(g.TILE_POINTS[c] for c in fb)
    assert g.score() == expected


def test_score_breakdown_matches_score():
    g = AvoidleGame("crane", words.allowed_guesses(),
                       GameConfig("T", max_guesses=2, max_undos=5,
                                  score_multiplier=1.5))
    g.submit("stone")
    g.undo()
    g.submit("stone")
    g.submit("brine")   # consistent with stone's ---GG clues vs CRANE
    bd = g.score_breakdown()
    assert g.status is GameStatus.SURVIVED
    assert bd["total"] == g.score()
    assert bd["base"] == 100
    assert bd["penalties"] == g.UNDO_COST
    assert bd["multiplier"] == 1.5
    assert bd["total"] == max(10, round(
        (bd["base"] + bd["tiles"] - bd["penalties"]) * 1.5))


def test_score_breakdown_zero_when_not_won(game):
    assert game.score_breakdown()["total"] == 0
    game.submit("crane")
    assert game.score_breakdown()["total"] == 0


def test_share_text_singular_undo():
    g = AvoidleGame("crane", words.allowed_guesses(),
                       GameConfig("T", max_guesses=1, max_undos=5))
    g.submit("stone")
    g.undos_used = 1
    assert "1 undo ·" in g.share_text()
    g.undos_used = 2
    assert "2 undos ·" in g.share_text()


def test_score_floor_flagged():
    g = AvoidleGame("crane", words.allowed_guesses(),
                       GameConfig("T", max_guesses=1, max_undos=0,
                                  max_hints=10, score_multiplier=0.25))
    g.hints_used = 10  # -300 penalty drives raw score negative
    g.submit("stone")
    bd = g.score_breakdown()
    assert bd["total"] == 10 and bd["floored"]


def test_trap_faced_semantics():
    # acting while trapped (submit or undo) marks the trap as faced
    g = AvoidleGame("crane", words.allowed_guesses(), PRESETS["classic"])
    g._pools[-1] = ["crane"]
    assert g.is_trapped and not g.was_ever_trapped
    g.submit("crane")
    assert g.was_ever_trapped
    # a final winning guess that merely collapses the pool does NOT count
    g2 = AvoidleGame("crane", words.allowed_guesses(),
                        GameConfig("T", max_guesses=1, max_undos=0))
    g2._pools[-1] = ["crane", "stone"]
    g2.submit("stone")  # survives; pool collapses to [crane] afterwards
    assert g2.status is GameStatus.SURVIVED
    assert g2.min_pool_seen == 1
    assert not g2.was_ever_trapped


def test_presets_sane():
    for key, cfg in PRESETS.items():
        assert cfg.max_guesses >= 6
        assert cfg.max_undos >= 0
    assert PRESETS["hard"].max_undos < PRESETS["classic"].max_undos
    with pytest.raises(ValueError):
        GameConfig(max_guesses=0)


def test_bad_secret_rejected():
    with pytest.raises(ValueError):
        AvoidleGame("xyzzy!", words.allowed_guesses())
