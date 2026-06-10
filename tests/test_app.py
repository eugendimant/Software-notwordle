"""End-to-end UI tests using Streamlit's AppTest harness.

These drive the real app.py: typing guesses, pressing buttons,
switching modes — and assert on the resulting session state.
"""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from dontwordle.engine import GameStatus

APP = str(Path(__file__).parent.parent / "app.py")


def make_app() -> AppTest:
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    assert not at.exception
    return at


def button(at: AppTest, prefix: str):
    matches = [b for b in at.button if b.label.startswith(prefix)]
    assert matches, f"no button starting with {prefix!r}: " \
                    f"{[b.label for b in at.button]}"
    return matches[0]


def guess(at: AppTest, word: str) -> AppTest:
    at.text_input(key="guess_input").input(word)
    button(at, "Guess").click()
    at.run()
    assert not at.exception
    return at


def test_app_boots_with_daily_mode():
    at = make_app()
    assert at.session_state["mode"] == "daily"
    game = at.session_state["game"]
    assert game.status is GameStatus.PLAYING
    assert game.remaining_count > 10_000


def test_valid_guess_updates_board_and_meter():
    at = make_app()
    game = at.session_state["game"]
    safe = next(w for w in game.remaining_words if w != game.secret)
    before = game.remaining_count
    guess(at, safe)
    game = at.session_state["game"]
    assert game.guesses_made == 1
    assert game.remaining_count < before


def test_invalid_guess_shows_error_and_costs_nothing():
    at = make_app()
    guess(at, "zzzzz")
    game = at.session_state["game"]
    assert game.guesses_made == 0
    assert at.session_state["message"][0] == "error"


def test_undo_button_roundtrip():
    at = make_app()
    game = at.session_state["game"]
    safe = next(w for w in game.remaining_words if w != game.secret)
    guess(at, safe)
    button(at, "↩️ Undo").click()
    at.run()
    assert not at.exception
    game = at.session_state["game"]
    assert game.guesses_made == 0
    assert game.undos_used == 1


def test_hint_is_safe_and_displayed():
    at = make_app()
    button(at, "🛟 Hint").click()
    at.run()
    assert not at.exception
    game = at.session_state["game"]
    h = at.session_state["hint_word"]
    assert h is not None and h != game.secret and h in game.remaining_words


def test_peek_shows_words():
    at = make_app()
    button(at, "👁️ Peek").click()
    at.run()
    assert not at.exception
    assert 1 <= len(at.session_state["peek_words"]) <= 5


def test_random_starting_word_first_turn_only():
    at = make_app()
    button(at, "🎲 Random starting word").click()
    at.run()
    assert not at.exception
    filled = at.session_state["guess_input"]
    assert filled in at.session_state["game"].remaining_words
    # after the first guess the random button must disappear
    game = at.session_state["game"]
    safe = next(w for w in game.remaining_words if w != game.secret)
    guess(at, safe)
    assert not [b for b in at.button if "Random starting" in b.label]


def test_invalid_guess_preserves_typed_word():
    at = make_app()
    at.text_input(key="guess_input").input("zzzzz")
    button(at, "Guess").click()
    at.run()
    assert not at.exception
    assert at.session_state["message"][0] == "error"
    assert at.session_state["guess_input"] == "zzzzz"


def test_accept_fate_button_when_trapped_without_undos():
    at = make_app()
    game = at.session_state["game"]
    game.secret = "crane"
    game._pools.append(["crane"])          # force a trapped position
    game.undos_used = game.config.max_undos  # ...with no undos left
    at.run()
    assert not at.exception
    assert at.session_state["game"].is_trapped
    button(at, "⚰️ Accept fate").click()
    at.run()
    assert not at.exception
    assert at.session_state["game"].status is GameStatus.WORDLED


def test_modes_hide_unavailable_abilities():
    at = make_app()
    at.radio(key="mode_label").set_value("💀 Impossible").run()
    assert not at.exception
    labels = [b.label for b in at.button]
    assert not any(l.startswith(("↩️ Undo", "🛟 Hint", "👁️ Peek"))
                   for l in labels)
    # zen shows infinite budgets
    at.radio(key="mode_label").set_value("🧘 Zen").run()
    assert not at.exception
    assert any(b.label == "↩️ Undo (∞)" for b in at.button)


def test_stats_export_import_roundtrip():
    import app as app_module
    exported = ('{"app": "dontwordle", "version": "x", '
                '"stats": {"daily": {"played": 3, "survived": 2, '
                '"streak": 2, "best_streak": 2, "best_score": 412}, '
                '"bogus_mode": {"played": 1}}, "survival_best": 777}')
    payload = app_module.parse_stats_json(exported)
    assert payload["survival_best"] == 777
    assert payload["stats"]["daily:en"]["best_score"] == 412
    assert "bogus_mode" not in payload["stats"]
    assert app_module.parse_stats_json("not json") is None
    assert app_module.parse_stats_json('{"stats": 7}') is None


def test_language_switch_starts_fresh_game_in_that_dictionary():
    from dontwordle import words as W
    at = make_app()
    at.selectbox(key="lang_select").set_value("de").run()
    assert not at.exception
    assert at.session_state["lang"] == "de"
    game = at.session_state["game"]
    assert game.secret in W.answers("de")
    assert game.guesses_made == 0
    # play a German word; stats land under the German key
    safe = next(w for w in game.remaining_words if w != game.secret)
    guess(at, safe)
    assert at.session_state["game"].guesses_made == 1
    # English word rejected by the German dictionary
    guess(at, "crane")
    assert at.session_state["message"][0] == "error"
    assert at.session_state["game"].guesses_made == 1


def test_spanish_accents_fold_to_dictionary_form():
    at = make_app()
    at.selectbox(key="lang_select").set_value("es").run()
    assert not at.exception
    game = at.session_state["game"]
    game.secret = "salsa" if game.secret == "comun" else game.secret
    if "comun" in game.remaining_words and game.secret != "comun":
        guess(at, "común")  # typed with accent, dictionary stores 'comun'
        assert at.session_state["game"].history[-1].guess == "comun"


def test_live_rating_appears_and_tracks_undo():
    at = make_app()
    game = at.session_state["game"]
    safe = next(w for w in game.remaining_words if w != game.secret)
    guess(at, safe)
    ratings = at.session_state["ratings"]
    assert len(ratings) == 1
    assert ratings[0].word == safe
    assert ratings[0].retained == at.session_state["game"].remaining_count
    assert 0 <= ratings[0].percentile <= 100
    button(at, "↩️ Undo").click()
    at.run()
    assert not at.exception
    assert at.session_state["ratings"] == []


def test_post_game_review_lists_best_words():
    at = make_app()
    game = at.session_state["game"]
    game.secret = "crane"
    for word in ("aahed", "beaks", "clame", "coate", "crape", "crare"):
        guess(at, word)
    assert at.session_state["game"].status is GameStatus.SURVIVED
    button(at, "Analyze my game").click()
    at.run()
    assert not at.exception
    review = at.session_state["review"]
    assert len(review) == 6
    for r in review:
        assert r.best_retained >= r.retained
        assert r.best_word in at.session_state["game"].dictionary
    blob = " ".join(str(md.value) for md in at.markdown)
    assert "Best-move" in blob or "kept" in blob


def test_losing_by_guessing_secret_then_undo_rescue():
    at = make_app()
    secret = at.session_state["game"].secret
    guess(at, secret)
    game = at.session_state["game"]
    assert game.status is GameStatus.WORDLED
    # loss with undos left must NOT be recorded yet
    assert at.session_state["stats"]["daily:en"]["played"] == 0
    button(at, "↩️ Undo that fatal guess").click()
    at.run()
    assert not at.exception
    game = at.session_state["game"]
    assert game.status is GameStatus.PLAYING
    assert game.undos_used == 1


def test_full_survival_win_flow():
    at = make_app()
    # switch to survival mode
    at.radio(key="mode_label").set_value("⚔️ Survival").run()
    assert not at.exception
    assert at.session_state["mode"] == "survival"
    game = at.session_state["game"]
    assert game.config.max_undos == 5  # round 1
    # pin the secret on the fresh game so the test is fully deterministic
    game.secret = "crane"
    for word in ("aahed", "beaks", "clame", "coate", "crape", "crare"):
        guess(at, word)  # known-good surviving line against CRANE
    game = at.session_state["game"]
    assert game.status is GameStatus.SURVIVED
    assert at.session_state["stats"]["survival:en"]["survived"] == 1
    assert at.session_state["survival_total"] == game.score()
    # advance to round 2: one fewer undo
    button(at, "⚔️ Next round").click()
    at.run()
    assert not at.exception
    assert at.session_state["survival_round"] == 2
    assert at.session_state["game"].config.max_undos == 4


def test_mode_switch_resets_game_and_attributes_stats_to_old_mode():
    at = make_app()
    secret = at.session_state["game"].secret
    guess(at, secret)  # lose the daily (undoable, so not yet recorded)
    at.radio(key="mode_label").set_value("💀 Impossible").run()
    assert not at.exception
    # the abandoned daily loss must be recorded under 'daily'
    assert at.session_state["stats"]["daily:en"]["played"] == 1
    assert at.session_state["stats"]["daily:en"]["survived"] == 0
    game = at.session_state["game"]
    assert game.config.label == "Impossible"
    assert game.config.max_undos == 0
    assert game.guesses_made == 0


def test_new_game_button():
    at = make_app()
    game_before = at.session_state["game"]
    safe = next(w for w in game_before.remaining_words
                if w != game_before.secret)
    guess(at, safe)
    button(at, "🔄 New game").click()
    at.run()
    assert not at.exception
    assert at.session_state["game"].guesses_made == 0


def test_version_and_homepage_in_sidebar():
    from dontwordle import __homepage__, __version__
    at = make_app()
    rendered = " ".join(str(md.value) for md in at.markdown)
    sidebar_md = " ".join(str(md.value) for md in at.sidebar.markdown)
    blob = rendered + sidebar_md
    assert __version__ in blob
    assert __homepage__ in blob
