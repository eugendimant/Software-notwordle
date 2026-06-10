"""Tests for the vectorized move-quality analyzer."""

import random
import time

import numpy as np
import pytest

from dontwordle import words as W
from dontwordle.analysis import Analyzer, analyzer_for, pattern_id, rate_move
from dontwordle.engine import DontWordleGame, PRESETS, score_guess


def test_pattern_id_bijective_on_examples():
    assert pattern_id("-----") == 0
    assert pattern_id("GGGGG") == 242
    seen = {pattern_id(fb) for fb in ("G----", "-G---", "YY---", "GYGYG")}
    assert len(seen) == 4


@pytest.mark.parametrize("lang", list(W.LANGUAGES))
def test_vectorized_feedback_matches_scalar(lang):
    """The numpy path must agree with score_guess on random pairs."""
    az = analyzer_for(lang)
    rng = random.Random(lang)
    pool = az.words
    sample = rng.sample(pool, 300)
    rows = az._rows(sample)
    for _ in range(40):
        guess = rng.choice(pool)
        codes = az.feedback_codes(guess, rows)
        for w, code in zip(sample, codes):
            assert code == pattern_id(score_guess(guess, w)), (guess, w)


def test_retained_matches_engine_pool():
    """Retained count of the played move == the engine's actual new pool."""
    rng = random.Random(11)
    az = analyzer_for("en")
    g = DontWordleGame("crane", W.allowed_guesses(), PRESETS["classic"],
                       rng=rng)
    for _ in range(4):
        if g.is_over:
            break
        pool_before = list(g.remaining_words)
        word = next(w for w in pool_before if w != g.secret)
        g.submit(word)
        retained = az.retained_counts([word], pool_before, g.secret)[0]
        assert retained == g.remaining_count


def test_rate_move_exact_small_pool():
    az = analyzer_for("en")
    g = DontWordleGame("crane", W.allowed_guesses(), PRESETS["classic"])
    g.submit("aahed")  # shrinks pool to a few hundred
    pool = list(g.remaining_words)
    word = next(w for w in pool if w != "crane")
    g.submit(word)
    r = rate_move(az, word, pool, "crane")
    assert r.exact
    assert r.retained == g.remaining_count
    assert r.best_retained >= r.retained
    assert 0 <= r.percentile <= 100
    assert r.best_word in pool


def test_rate_move_sampled_large_pool():
    az = analyzer_for("en")
    pool = az.words  # full 14,855-word opening pool
    r = rate_move(az, "aahed", pool, "crane", rng=random.Random(2))
    assert not r.exact
    assert r.pool_size == len(pool)
    assert r.best_retained >= r.retained
    # playing the secret itself retains only itself -> worst possible
    r_secret = rate_move(az, "crane", pool, "crane", rng=random.Random(2))
    assert r_secret.retained == 1
    assert r_secret.percentile <= 10


def test_grades_cover_scale():
    az = analyzer_for("en")
    g = DontWordleGame("crane", W.allowed_guesses(), PRESETS["classic"])
    g.submit("aahed")
    pool = list(g.remaining_words)
    rs = [rate_move(az, w, pool, "crane") for w in pool[:30]]
    assert all(r.grade.split()[0] in "🟢🟡🟠🔴" for r in rs)
    best = max(rs, key=lambda r: r.retained)
    worst = min(rs, key=lambda r: r.retained)
    assert best.percentile >= worst.percentile


def test_opening_move_rating_is_fast_enough():
    az = analyzer_for("en")
    az.feedback_codes("crane", az._rows(az.words[:100]))  # warm caches
    t0 = time.perf_counter()
    rate_move(az, "aahed", az.words, "crane", rng=random.Random(1))
    elapsed = time.perf_counter() - t0
    assert elapsed < 5.0, f"opening analysis took {elapsed:.2f}s"


@pytest.mark.parametrize("lang", ["de", "ru", "es"])
def test_new_language_dictionaries(lang):
    allowed = W.allowed_guesses(lang)
    ans = W.answers(lang)
    assert len(allowed) > 3000
    assert len(ans) >= 900  # ru: 998 curated noun secrets, others 1500
    assert set(ans) <= allowed
    assert all(len(w) == 5 for w in ans)
    # daily secret is deterministic per language and differs across them
    import datetime
    d = datetime.date(2026, 6, 12)
    assert W.daily_secret(lang, d) == W.daily_secret(lang, d)
    assert W.daily_secret(lang, d) in ans


def test_normalize_guess():
    assert W.normalize_guess("Ёлка!".strip("!"), "ru") == "елка"
    assert W.normalize_guess("común", "es") == "comun"
    assert W.normalize_guess("ñoño", "es") == "ñoño"
    assert W.normalize_guess("Straße", "de") == "straße"
    assert W.normalize_guess("CRANE", "en") == "crane"


def test_keyboards_cover_dictionary_alphabets():
    for lang in W.LANGUAGES:
        kbd_letters = set("".join(W.KEYBOARDS[lang]))
        dict_letters = {c for w in W.allowed_guesses(lang) for c in w}
        assert dict_letters <= kbd_letters, (
            lang, dict_letters - kbd_letters)
