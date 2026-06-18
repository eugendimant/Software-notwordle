"""Tests for the vectorized move-quality analyzer."""

import random
import time

import pytest

from avoidle import words as W
from avoidle.analysis import analyzer_for, pattern_id, rate_move
from avoidle.engine import AvoidleGame, PRESETS, score_guess


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
    g = AvoidleGame("crane", W.allowed_guesses(), PRESETS["classic"],
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
    g = AvoidleGame("crane", W.allowed_guesses(), PRESETS["classic"])
    g.submit("poise")  # shrinks pool to a few hundred
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
    r = rate_move(az, "poise", pool, "crane", rng=random.Random(2))
    assert not r.exact
    assert r.pool_size == len(pool)
    assert r.best_retained >= r.retained
    # playing the secret itself retains only itself -> worst possible
    r_secret = rate_move(az, "crane", pool, "crane", rng=random.Random(2))
    assert r_secret.retained == 1
    assert r_secret.percentile <= 10


def test_grades_cover_scale():
    az = analyzer_for("en")
    g = AvoidleGame("crane", W.allowed_guesses(), PRESETS["classic"])
    g.submit("poise")
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
    rate_move(az, "poise", az.words, "crane", rng=random.Random(1))
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
    assert W.daily_secret(lang, 5, d) == W.daily_secret(lang, 5, d)
    assert W.daily_secret(lang, 5, d) in ans


@pytest.mark.parametrize("length", [4, 6])
@pytest.mark.parametrize("lang", list(W.LANGUAGES))
def test_multilength_dictionaries(lang, length):
    allowed = W.allowed_guesses(lang, length)
    ans = W.answers(lang, length)
    assert len(allowed) > 2000
    assert len(ans) >= 600
    assert set(ans) <= allowed
    assert all(len(w) == length for w in allowed)
    import datetime
    d = datetime.date(2026, 6, 13)
    daily = W.daily_secret(lang, length, d)
    assert daily == W.daily_secret(lang, length, d)
    assert daily in ans and len(daily) == length
    # keyboard rows must cover every letter used at this length
    kbd = set("".join(W.KEYBOARDS[lang]))
    assert {c for w in allowed for c in w} <= kbd


@pytest.mark.parametrize("length", [4, 6])
def test_engine_plays_other_lengths(length):
    from avoidle.engine import GameStatus
    rng = random.Random(3)
    secret = W.random_secret("en", length, rng)
    g = AvoidleGame(secret, W.allowed_guesses("en", length),
                       PRESETS["classic"], rng=rng)
    assert g.word_length == length
    import pytest as _pt
    with _pt.raises(Exception, match=f"{length}-letter"):
        g.submit("x" * (length + 1))
    while not g.is_over:
        if g.is_trapped and g.can_undo():
            g.undo()
            continue
        pool = g.remaining_words
        word = next((w for w in pool if w != secret), secret)
        g.submit(word)
    assert g.status in (GameStatus.SURVIVED, GameStatus.WORDLED)
    assert all(len(t.guess) == length for t in g.history)


@pytest.mark.parametrize("length", [4, 6])
def test_vectorized_matches_scalar_other_lengths(length):
    az = analyzer_for("en", length)
    assert az.length == length
    rng = random.Random(length)
    sample = rng.sample(az.words, 200)
    rows = az._rows(sample)
    for _ in range(25):
        guess = rng.choice(az.words)
        codes = az.feedback_codes(guess, rows)
        for w, code in zip(sample, codes):
            assert code == pattern_id(score_guess(guess, w)), (guess, w)


def test_rate_move_works_at_length_six():
    az = analyzer_for("en", 6)
    secret = W.answers("en", 6)[10]
    pool = az.words
    played = next(w for w in pool if w != secret)
    r = rate_move(az, played, pool, secret, rng=random.Random(1))
    assert r.pool_size == len(pool)
    assert r.best_retained >= r.retained > 0


def test_frequency_rank_and_order():
    for lang in W.LANGUAGES:
        pool = W.answers(lang, 5)
        assert W.frequency_rank(pool[0], lang, 5) == 1
        assert W.frequency_rank(pool[-1], lang, 5) == len(pool)
        assert W.frequency_rank("zzzzz", lang, 5) is None


@pytest.mark.parametrize("lang", list(W.LANGUAGES))
def test_secret_selection_is_frequency_weighted(lang):
    """Common words must be drawn noticeably more often than rare ones."""
    rng = random.Random(99)
    pool = W.answers(lang, 5)
    q = len(pool) // 4
    top = set(pool[:q])
    bottom = set(pool[-q:])
    draws = [W.random_secret(lang, 5, rng) for _ in range(3000)]
    top_n = sum(d in top for d in draws)
    bottom_n = sum(d in bottom for d in draws)
    assert top_n > 1.5 * bottom_n, (top_n, bottom_n)
    # the tail must still be reachable
    assert bottom_n > 0


def test_daily_secret_weighted_and_deterministic():
    import datetime
    d = datetime.date(2026, 6, 14)
    for lang in W.LANGUAGES:
        for length in W.WORD_LENGTHS:
            s = W.daily_secret(lang, length, d)
            assert s == W.daily_secret(lang, length, d)
            assert s in W.answers(lang, length)


def test_best_safe_hint_is_safe_and_beats_random():
    from avoidle.analysis import best_safe_hint
    az = analyzer_for("en")
    g = AvoidleGame("crane", W.allowed_guesses(), PRESETS["classic"])
    g.submit("poise")
    pool = list(g.remaining_words)
    rng = random.Random(4)
    hint = best_safe_hint(az, pool, "crane", rng)
    assert hint in pool and hint != "crane"
    # the smart hint must retain at least as much as the average safe word
    safe = [w for w in pool if w != "crane"]
    sample = random.Random(9).sample(safe, 30)
    retained = az.retained_counts(sample + [hint], pool, "crane")
    assert retained[-1] >= retained[:-1].mean()
    # deterministic given the same rng seed
    assert hint == best_safe_hint(az, pool, "crane", random.Random(4))
    # pool of just the secret -> no hint
    assert best_safe_hint(az, ["crane"], "crane", rng) is None


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
