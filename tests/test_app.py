"""End-to-end UI tests using Streamlit's AppTest harness.

These drive the real app.py: typing guesses, pressing buttons,
switching modes — and assert on the resulting session state.
"""

from pathlib import Path

from streamlit.testing.v1 import AppTest

from dontwordle.engine import GameStatus

APP = str(Path(__file__).parent.parent / "app.py")


def make_app() -> AppTest:
    """Boot the app and switch to typing mode (the historical default)
    so the text-input-driven test helpers keep working; the clickable
    keyboard is the product default and has its own dedicated tests."""
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    assert not at.exception
    at.session_state["input_mode"] = "type"
    at.run()
    assert not at.exception
    return at


def make_click_app() -> AppTest:
    """Boot with the product default (clickable keyboard)."""
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    assert not at.exception
    return at


def test_clickable_keyboard_is_the_default():
    at = make_click_app()
    assert at.session_state["input_mode"] == "click"
    assert at.button(key="kbd_q") is not None  # keyboard rendered
    from dontwordle import words as W
    assert W.LANGUAGES["en"].startswith("🇺🇸")  # American English


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
    button(at, "🎲 Random").click()
    at.run()
    assert not at.exception
    filled = at.session_state["guess_input"]
    game = at.session_state["game"]
    assert filled in game.remaining_words
    assert filled != game.secret  # must never hand the player the secret
    # after the first guess the random button must disappear
    game = at.session_state["game"]
    safe = next(w for w in game.remaining_words if w != game.secret)
    guess(at, safe)
    assert not [b for b in at.button if "🎲 Random" in b.label]


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
    assert any(b.label == "↩️ Undo ∞" for b in at.button)


def test_stats_export_import_roundtrip():
    import app as app_module
    exported = ('{"app": "dontwordle", "version": "x", '
                '"stats": {"daily": {"played": 3, "survived": 2, '
                '"streak": 2, "best_streak": 2, "best_score": 412}, '
                '"bogus_mode": {"played": 1}}, "survival_best": 777}')
    payload = app_module.parse_stats_json(exported)
    assert payload["survival_best"] == 777
    assert payload["stats"]["daily:en:5"]["best_score"] == 412
    assert "bogus_mode" not in payload["stats"]
    assert app_module.parse_stats_json("not json") is None
    assert app_module.parse_stats_json('{"stats": 7}') is None


def test_word_length_switch_starts_fresh_game():
    from dontwordle import words as W
    at = make_app()
    at.selectbox(key="len_select").set_value(6).run()
    assert not at.exception
    assert at.session_state["word_len"] == 6
    game = at.session_state["game"]
    assert game.word_length == 6
    assert game.secret in W.answers("en", 6)
    safe = next(w for w in game.remaining_words if w != game.secret)
    guess(at, safe)
    assert at.session_state["game"].guesses_made == 1
    # five-letter word rejected on a six-letter board
    guess(at, "crane")
    assert at.session_state["message"][0] == "error"
    # switching length again starts a fresh 4-letter board
    at.selectbox(key="len_select").set_value(4).run()
    assert at.session_state["game"].word_length == 4


def test_clickable_keyboard_full_flow():
    at = make_click_app()
    assert at.session_state["input_mode"] == "click"
    game = at.session_state["game"]
    game.secret = "crane"
    # click out 's','t','o','n','e' then submit with ⏎
    for letter in "stone":
        at.button(key=f"kbd_{letter}").click()
        at.run()
        assert not at.exception
    assert at.session_state["kbd_buffer"] == "stone"
    at.button(key="kbd_back").click()
    at.run()
    assert at.session_state["kbd_buffer"] == "ston"
    at.button(key="kbd_e").click()
    at.run()
    at.button(key="kbd_enter").click()
    at.run()
    assert not at.exception
    game = at.session_state["game"]
    assert game.guesses_made == 1
    assert game.history[0].guess == "stone"
    assert at.session_state["kbd_buffer"] == ""
    # eliminated letters become disabled keys
    know_gray = [l for l, c in zip("stone", game.history[0].feedback)
                 if c == "-"]
    if know_gray:
        assert at.button(key=f"kbd_{know_gray[0]}").disabled


def test_clickable_keyboard_rejects_and_keeps_buffer():
    at = make_click_app()
    for letter in "zzzzz":
        at.button(key="kbd_z").click()
        at.run()
    at.button(key="kbd_enter").click()
    at.run()
    assert not at.exception
    assert at.session_state["message"][0] == "error"
    assert at.session_state["kbd_buffer"] == "zzzzz"  # kept for editing


def test_stats_key_collision_merges_not_clobbers():
    import app as app_module
    payload = app_module.parse_stats_json(
        '{"stats": {'
        '"classic:de": {"played": 100, "survived": 60, "streak": 1, '
        '"best_streak": 9, "best_score": 700}, '
        '"classic:de:5": {"played": 3, "survived": 2, "streak": 2, '
        '"best_streak": 2, "best_score": 300}, '
        '"classic:de:5:junk": {"played": 999}}, "survival_best": 1}')
    merged = payload["stats"]["classic:de:5"]
    assert merged["played"] == 100      # field-wise max, nothing lost
    assert merged["best_streak"] == 9
    assert merged["streak"] == 2
    assert len(payload["stats"]) == 1   # 4-part junk key rejected


def test_buffer_cleared_when_game_ends():
    at = make_click_app()
    game = at.session_state["game"]
    game.secret = "crane"
    at.button(key="kbd_s").click()
    at.run()
    game = at.session_state["game"]
    game._pools.append(["crane"])            # trapped...
    game.undos_used = game.config.max_undos  # ...with no undos
    at.run()
    button(at, "⚰️ Accept fate").click()
    at.run()
    assert not at.exception
    assert at.session_state["game"].is_over
    assert at.session_state["kbd_buffer"] == ""  # no ghost letters on board


def test_new_game_clears_typed_word():
    at = make_app()
    at.text_input(key="guess_input").input("apple")
    button(at, "🔄 New game").click()
    at.run()
    assert not at.exception
    assert at.session_state["guess_input"] == ""


def test_legacy_stats_keys_upgrade():
    import app as app_module  # noqa: import inside test for runtime guard
    payload = app_module.parse_stats_json(
        '{"stats": {"classic:de": {"played": 2, "survived": 1, "streak": 1, '
        '"best_streak": 1, "best_score": 200}}, "survival_best": 5}')
    assert payload["stats"]["classic:de:5"]["played"] == 2


def test_language_switch_starts_fresh_game_in_that_dictionary():
    from dontwordle import words as W  # noqa
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


def test_undo_clears_stale_review():
    at = make_app()
    secret = at.session_state["game"].secret
    guess(at, secret)  # lose (undoable)
    button(at, "Analyze my game").click()
    at.run()
    assert at.session_state["review"] is not None
    button(at, "↩️ Undo that fatal guess").click()
    at.run()
    assert not at.exception
    assert at.session_state["review"] is None


def test_daily_practice_replay_does_not_farm_stats():
    at = make_app()
    game = at.session_state["game"]
    game.secret = "crane"
    for word in ("aahed", "beaks", "clame", "coate", "crape", "crare"):
        guess(at, word)
    assert at.session_state["stats"]["daily:en:5"]["played"] == 1
    assert at.session_state["stats"]["daily:en:5"]["streak"] == 1
    button(at, "🔁 Replay today's word").click()
    at.run()
    game = at.session_state["game"]
    game.secret = "crane"
    for word in ("aahed", "beaks", "clame", "coate", "crape", "crare"):
        guess(at, word)
    # second (practice) completion must not inflate any stat
    assert at.session_state["stats"]["daily:en:5"]["played"] == 1
    assert at.session_state["stats"]["daily:en:5"]["survived"] == 1
    assert at.session_state["stats"]["daily:en:5"]["streak"] == 1


def test_fatal_and_forced_grades():
    import random as _random
    from dontwordle.analysis import analyzer_for, rate_move
    az = analyzer_for("en")
    # playing the secret is graded fatal, never 'brilliant'
    r = rate_move(az, "crane", az.words[:50] + ["crane"], "crane",
                  rng=_random.Random(0))
    assert r.fatal and r.grade == "💀 fatal"
    # a pool of one is a forced move, not a praised one
    r = rate_move(az, "crane", ["crane"], "crane", rng=_random.Random(0))
    assert r.forced and r.grade == "⚰️ forced"
    assert r.percentile == 100.0  # no alternatives existed


def test_live_and_review_ratings_agree():
    at = make_app()
    game = at.session_state["game"]
    game.secret = "crane"
    for word in ("aahed", "beaks", "clame", "coate", "crape", "crare"):
        guess(at, word)
    live = list(at.session_state["ratings"])
    button(at, "Analyze my game").click()
    at.run()
    review = at.session_state["review"]
    for lv, rv in zip(live, review):
        assert (lv.retained, lv.percentile, lv.grade) == \
               (rv.retained, rv.percentile, rv.grade)


def test_win_reveals_secret_and_frequency():
    at = make_app()
    game = at.session_state["game"]
    game.secret = "crane"
    for word in ("aahed", "beaks", "clame", "coate", "crape", "crare"):
        guess(at, word)
    assert at.session_state["game"].status is GameStatus.SURVIVED
    blob = " ".join(str(el.value) for el in at.info) + \
           " ".join(str(md.value) for md in at.markdown)
    assert "CRANE" in blob
    assert "frequency rank" in blob


def test_trap_forecast_matches_brute_force():
    from dontwordle.engine import score_guess
    at = make_app()
    game = at.session_state["game"]
    game.secret = "crane"
    for word in ("aahed", "beaks", "clame", "coate"):
        guess(at, word)
    game = at.session_state["game"]
    pool = game.remaining_words
    assert 2 <= len(pool) <= 30 and game.guesses_left >= 2
    expected_traps = sum(
        1 for w in pool if w != "crane"
        and sum(score_guess(w, v) == score_guess(w, "crane")
                for v in pool) == 1)
    blob = " ".join(str(el.value) for el in at.warning) + \
           " ".join(str(el.value) for el in at.info)
    assert "Endgame intel" in blob
    if expected_traps:
        assert f"{expected_traps} of your" in blob or "every one" in blob
    else:
        assert "none of your" in blob


def test_no_trap_forecast_in_impossible_mode():
    at = make_app()
    at.radio(key="mode_label").set_value("💀 Impossible").run()
    game = at.session_state["game"]
    game.secret = "crane"
    game._pools.append(["crane", "crape", "crare"])  # tiny endgame pool
    at.run()
    assert not at.exception
    blob = " ".join(str(el.value) for el in at.warning) + \
           " ".join(str(el.value) for el in at.info)
    assert "Endgame intel" not in blob


def test_zen_word_browser_lists_pool():
    at = make_app()
    at.radio(key="mode_label").set_value("🧘 Zen").run()
    game = at.session_state["game"]
    game.secret = "crane"
    game._pools.append(["crane", "crape", "crare"])
    at.run()
    assert not at.exception
    blob = " ".join(str(el.value) for el in at.expander[-1].markdown) \
        if at.expander else ""
    page = blob + " ".join(str(md.value) for md in at.markdown)
    assert "CRAPE" in page and "CRARE" in page
    # the browser is a zen perk: classic must not show it
    at.radio(key="mode_label").set_value("🎲 Classic").run()
    game = at.session_state["game"]
    game._pools.append([game.secret])
    at.run()
    page = " ".join(str(md.value) for md in at.markdown)
    assert "Browse all" not in page


def test_next_daily_countdown_format():
    import re
    import app as app_module
    assert re.fullmatch(r"\d{1,2}h \d{2}m", app_module.next_daily_in())


def test_win_awards_xp_and_achievements():
    at = make_app()
    game = at.session_state["game"]
    game.secret = "crane"
    for word in ("aahed", "beaks", "clame", "coate", "crape", "crare"):
        guess(at, word)
    assert at.session_state["game"].status is GameStatus.SURVIVED
    assert "first_win" in at.session_state["achievements"]
    assert at.session_state["xp"] >= at.session_state["game"].score()
    blob = " ".join(str(el.value) for el in at.success)
    assert "Achievement unlocked" in blob
    # trophy case reflects the unlock
    labels = " ".join(str(md.value) for md in at.sidebar.markdown)
    assert "First Dodge" in labels


def test_loss_gives_participation_xp_only():
    from dontwordle import achievements as ACH
    at = make_app()
    game = at.session_state["game"]
    game.undos_used = game.config.max_undos  # make the loss final
    guess(at, game.secret)
    assert at.session_state["game"].status is GameStatus.WORDLED
    assert at.session_state["xp"] == ACH.LOSS_XP
    assert "first_win" not in at.session_state["achievements"]


def test_daily_streak_and_quest_banner():
    at = make_app()
    # quest banner shows while playing the daily (merged into one line)
    page = " ".join(str(md.value) for md in at.markdown)
    assert "🎯" in page and "XP)" in page
    game = at.session_state["game"]
    game.secret = "crane"
    for word in ("aahed", "beaks", "clame", "coate", "crape", "crare"):
        guess(at, word)
    streaks = at.session_state["daily_streaks"]
    assert streaks["en:5"]["streak"] == 1


def test_backup_roundtrip_with_progress_fields():
    import app as app_module
    payload = app_module.parse_stats_json(
        '{"stats": {}, "survival_best": 0, "xp": 1234, '
        '"achievements": ["purist", "not_a_real_one"], '
        '"daily_streaks": {"en:5": {"last": "2026-06-10", "streak": 4}, '
        '"xx:9": {"last": "x", "streak": 1}}}')
    assert payload["xp"] == 1234
    assert payload["achievements"] == {"purist"}
    assert payload["daily_streaks"] == {
        "en:5": {"last": "2026-06-10", "streak": 4}}
    # legacy files without the new fields still parse
    legacy = app_module.parse_stats_json('{"stats": {}, "survival_best": 2}')
    assert legacy["xp"] == 0 and legacy["achievements"] == set()


def test_hostile_backup_files_rejected_or_clamped():
    import app as app_module
    from dontwordle import achievements as ACH
    # absurd-but-finite xp is clamped, not allowed to hang the session
    p = app_module.parse_stats_json('{"stats": {}, "xp": 1e300}')
    assert p["xp"] == ACH.XP_CAP
    # infinities used to raise OverflowError and crash the app
    assert app_module.parse_stats_json('{"stats": {}, "xp": 1e999}') is None
    assert app_module.parse_stats_json(
        '{"stats": {}, "survival_best": 1e999}') is None
    assert app_module.parse_stats_json(
        '{"stats": {}, "daily_streaks": {"en:5": '
        '{"last": "x", "streak": 1e999}}}') is None
    # JSON *big integers* are arbitrary precision in Python — they used
    # to sail through validation and crash the stats display later
    big = "9" * 400
    p = app_module.parse_stats_json(
        '{"stats": {"daily:en:5": {"played": 1, "survived": ' + big +
        '}}, "survival_best": ' + big + '}')
    assert p["stats"]["daily:en:5"]["survived"] == app_module.NUM_CAP
    assert p["survival_best"] == app_module.NUM_CAP


def test_daily_done_travels_in_backup():
    import app as app_module
    p = app_module.parse_stats_json(
        '{"stats": {}, "daily_done": ["2026-06-10:en:5", "garbage", '
        '"2026-06-11:xx:5", "2026-06-11:de:9", "not-a-date:de:5"]}')
    assert p["daily_done"] == {"2026-06-10:en:5"}


def test_restored_daily_done_blocks_refarming():
    import datetime
    at = make_app()
    today = datetime.date.today().isoformat()
    at.session_state["daily_done"].add(f"{today}:en:5")  # as if restored
    game = at.session_state["game"]
    game.secret = "crane"
    for word in ("aahed", "beaks", "clame", "coate", "crape", "crare"):
        guess(at, word)
    assert at.session_state["game"].status is GameStatus.SURVIVED
    assert at.session_state["xp"] == 0
    assert at.session_state["stats"].get(
        "daily:en:5", {}).get("played", 0) == 0


def test_derive_session_wins_from_stats():
    import app as app_module
    langs, lengths = app_module.derive_session_wins({
        "classic:de:5": {"survived": 2}, "daily:en:6": {"survived": 1},
        "hard:ru:4": {"survived": 0}})
    assert langs == {"de", "en"} and lengths == {5, 6}


def test_daily_streak_nudge_in_sidebar():
    import datetime
    at = make_app()
    at.radio(key="mode_label").set_value("🎲 Classic").run()
    at.session_state["daily_streaks"]["en:5"] = {
        "last": (datetime.date.today()
                 - datetime.timedelta(days=1)).isoformat(), "streak": 4}
    at.run()
    blob = " ".join(str(el.value) for el in at.sidebar.warning)
    assert "4-day daily streak is on the line" in blob
    # once today's daily is done, the nudge disappears
    at.session_state["daily_done"].add(
        f"{datetime.date.today().isoformat()}:en:5")
    at.run()
    blob = " ".join(str(el.value) for el in at.sidebar.warning)
    assert "on the line" not in blob


def test_session_log_and_share_card_meta():
    at = make_app()
    game = at.session_state["game"]
    game.secret = "crane"
    for word in ("aahed", "beaks", "clame", "coate", "crape", "crare"):
        guess(at, word)
    # share card now carries level + trophy count
    blob = " ".join(str(el.value) for el in at.code)
    assert "⭐ Level" in blob and "🏆" in blob
    log = at.session_state["session_log"]
    assert len(log) == 1 and log[0]["won"] and log[0]["mode"] == "daily"
    # a loss is logged too
    button(at, "🔁 Replay today's word").click()
    at.run()
    game = at.session_state["game"]
    game.undos_used = game.config.max_undos
    guess(at, game.secret)
    log = at.session_state["session_log"]
    assert len(log) == 2 and not log[1]["won"]
    side = " ".join(str(md.value) for md in at.sidebar.caption)
    assert "pts" in side  # recap rendered


def test_losing_by_guessing_secret_then_undo_rescue():
    at = make_app()
    secret = at.session_state["game"].secret
    guess(at, secret)
    game = at.session_state["game"]
    assert game.status is GameStatus.WORDLED
    # loss with undos left must NOT be recorded yet
    assert at.session_state["stats"]["daily:en:5"]["played"] == 0
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
    assert at.session_state["stats"]["survival:en:5"]["survived"] == 1
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
    assert at.session_state["stats"]["daily:en:5"]["played"] == 1
    assert at.session_state["stats"]["daily:en:5"]["survived"] == 0
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
