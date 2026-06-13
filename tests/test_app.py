"""End-to-end UI tests using Streamlit's AppTest harness.

These drive the real app.py: typing guesses, pressing buttons,
switching modes — and assert on the resulting session state.
"""

from pathlib import Path

from streamlit.testing.v1 import AppTest

from avoidle.engine import GameStatus

APP = str(Path(__file__).parent.parent / "app.py")


def make_app() -> AppTest:
    """Boot the app and switch to typing mode (the historical default)
    so the text-input-driven test helpers keep working; the clickable
    keyboard is the product default and has its own dedicated tests."""
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    assert not at.exception
    at.session_state["input_mode"] = "type"
    at.session_state["bot_pace"] = 0.0   # skip the duel thinking pause
    at.run()
    assert not at.exception
    return at


def make_click_app() -> AppTest:
    """Boot with the product default (clickable keyboard)."""
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    assert not at.exception
    at.session_state["bot_pace"] = 0.0   # skip the duel thinking pause
    return at


def test_clickable_keyboard_is_the_default():
    at = make_click_app()
    assert at.session_state["input_mode"] == "click"
    assert at.button(key="kbd_q") is not None  # keyboard rendered
    from avoidle import words as W
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
    button(at, "💡 Hint").click()
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
    assert not any(l.startswith(("↩️ Undo", "💡 Hint", "👁️ Peek"))
                   for l in labels)
    # zen shows infinite budgets
    at.radio(key="mode_label").set_value("🧘 Zen").run()
    assert not at.exception
    assert any(b.label == "↩️ Undo ∞" for b in at.button)


def test_stats_export_import_roundtrip():
    import app as app_module
    exported = ('{"app": "avoidle", "version": "x", '
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
    from avoidle import words as W
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
    from avoidle import words as W  # noqa
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
    from avoidle.analysis import analyzer_for, rate_move
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
    from avoidle.engine import score_guess
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
    from avoidle import achievements as ACH
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
    from avoidle import achievements as ACH
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


def test_progress_cookie_roundtrip():
    import app as app_module
    at = make_app()
    game = at.session_state["game"]
    game.secret = "crane"
    for word in ("aahed", "beaks", "clame", "coate", "crape", "crare"):
        guess(at, word)
    assert at.session_state["xp"] > 0
    # encode within the live session, decode outside it
    at.session_state["_token"] = None
    # exercise the codec directly on an export-shaped payload
    exported = (
        '{"stats": {"daily:en:5": {"played": 1, "survived": 1, "streak": 1,'
        ' "best_streak": 1, "best_score": 373}}, "survival_best": 0,'
        ' "xp": 473, "achievements": ["first_win"],'
        ' "daily_streaks": {"en:5": {"last": "2026-06-12", "streak": 1}},'
        ' "daily_done": ["2026-06-12:en:5"],'
        ' "daily_win_dates": ["2026-06-12:en:5"]}')
    import base64
    import zlib
    token = base64.urlsafe_b64encode(
        zlib.compress(exported.encode())).decode()
    payload = app_module.decode_progress(token)
    assert payload["xp"] == 473
    assert payload["achievements"] == {"first_win"}
    assert payload["daily_win_dates"] == {"2026-06-12:en:5"}
    # tampered tokens are rejected, never raise
    assert app_module.decode_progress("not-a-token!!") is None
    assert app_module.decode_progress(token[:-10]) is None


def test_duel_mode_full_flow():
    import random as _random
    at = make_app()
    at.radio(key="mode_label").set_value("🆚 Duel").run()
    assert not at.exception
    game = at.session_state["game"]
    assert game.config.label == "Duel"
    assert game.config.max_undos == 0 and game.config.max_guesses == 12
    game.secret = "crane"
    game.rng = _random.Random(7)  # deterministic bot
    safe = next(w for w in game.remaining_words if w != "crane")
    guess(at, safe)
    game = at.session_state["game"]
    if not game.is_over:
        # the bot answered: two rows on the board after one player move
        assert game.guesses_made == 2
        # exactly one live rating (the player's move only)
        assert len(at.session_state["ratings"]) == 1
    # play on until the duel ends
    for _ in range(8):
        game = at.session_state["game"]
        if game.is_over:
            break
        safe = next((w for w in game.remaining_words if w != game.secret),
                    game.secret)
        guess(at, safe)
    game = at.session_state["game"]
    assert game.is_over
    import app as app_module
    won = app_module.player_won(game, "duel")
    stats = at.session_state["stats"]["duel:en:5"]
    assert stats["played"] == 1
    assert stats["survived"] == (1 if won else 0)
    if won and game.status is GameStatus.WORDLED:
        # bot blunder win: fatal row count is even, score comes from app
        assert len(game.history) % 2 == 0
        assert stats["best_score"] == app_module.duel_score(game)


def test_bot_levels_play_fair_and_differ():
    import random as _random
    from avoidle import words as W
    from avoidle.bot import bot_pick, _answer_rank, BOT_LEVELS
    ranks = _answer_rank("en", 5)
    pool = list(W.allowed_guesses())[:400] + list(W.answers())[:50]
    rng = _random.Random(1)
    for level in BOT_LEVELS:
        pick = bot_pick(level, pool, "en", 5, rng)
        assert pick in pool
    # hard always plays a provably-safe non-answer word when one exists
    for seed in range(20):
        pick = bot_pick("hard", pool, "en", 5, _random.Random(seed))
        assert pick not in ranks
    # cornered among answers only with a pool too large to solve: the
    # heuristic fallback gambles on the rarest answer (small all-answer
    # pools are handled by the recursive solver instead — see
    # tests/test_endgame.py)
    answers_only = list(W.answers())[:19] + [list(W.answers())[-1]]
    pick = bot_pick("hard", answers_only, "en", 5, rng)
    assert pick == max(answers_only, key=lambda w: ranks[w])
    # trapped pool: every level is forced, like a human
    for level in BOT_LEVELS:
        assert bot_pick(level, ["crane"], "en", 5, rng) == "crane"


def test_duel_bot_strength_selector():
    from avoidle.bot import BOT_MULTIPLIER
    at = make_app()
    at.radio(key="mode_label").set_value("🆚 Duel").run()
    assert not at.exception
    assert at.session_state["bot_level"] == "normal"
    at.selectbox(key="bot_select").set_value("hard").run()
    assert not at.exception
    assert at.session_state["bot_level"] == "hard"
    assert at.session_state["game"].guesses_made == 0  # fresh duel
    # harder bots pay more when beaten
    assert BOT_MULTIPLIER["hard"] > BOT_MULTIPLIER["normal"] \
        > BOT_MULTIPLIER["easy"]


def test_duel_player_blunder_is_a_loss():
    import app as app_module
    at = make_app()
    at.radio(key="mode_label").set_value("🆚 Duel").run()
    game = at.session_state["game"]
    guess(at, game.secret)  # player says the word -> instant loss
    game = at.session_state["game"]
    assert game.status is GameStatus.WORDLED
    assert not app_module.player_won(game, "duel")
    assert at.session_state["stats"]["duel:en:5"]["survived"] == 0


def test_streak_heatmap_renders_wins():
    import datetime
    at = make_app()
    today = datetime.date.today().isoformat()
    at.session_state["daily_win_dates"].add(f"{today}:en:5")
    at.run()
    blob = " ".join(str(md.value) for md in at.sidebar.markdown)
    assert "dw-heat" in blob and 'class="win today"' in blob


def test_zlib_bomb_rejected_without_ballooning():
    import app as app_module
    import base64
    import time
    import zlib
    bomb = base64.urlsafe_b64encode(
        zlib.compress(b"0" * (50 * 1024 * 1024), 9)).decode()
    t0 = time.perf_counter()
    assert app_module.decode_progress(bomb) is None
    assert time.perf_counter() - t0 < 1.0  # stopped at the 1MB cap


def test_cookie_prunes_history_but_export_keeps_it():
    import datetime
    import app as app_module
    at = make_app()
    old = (datetime.date.today()
           - datetime.timedelta(days=400)).isoformat()
    today = datetime.date.today().isoformat()
    at.session_state["daily_done"].update({f"{old}:en:5", f"{today}:en:5"})
    at.session_state["daily_win_dates"].add(f"{old}:en:5")
    # drive the codec on a synthetic session via the pure helper
    recent = app_module._recent({f"{old}:en:5", f"{today}:en:5"}, 30)
    assert recent == [f"{today}:en:5"]  # the stale entry is pruned
    assert app_module._recent({f"{old}:en:5"}, 100000) == [f"{old}:en:5"]


def test_duel_context_counts_player_tiles_only():
    import app as app_module
    at = make_app()
    at.radio(key="mode_label").set_value("🆚 Duel").run()
    import random as _random
    game = at.session_state["game"]
    game.secret = "crane"
    game.rng = _random.Random(7)
    for _ in range(6):
        game = at.session_state["game"]
        if game.is_over:
            break
        safe = next((w for w in game.remaining_words if w != game.secret),
                    game.secret)
        guess(at, safe)
    game = at.session_state["game"]
    assert game.is_over
    # the recorded best score (if won) must use the level multiplier
    won = app_module.player_won(game, "duel")
    stats = at.session_state["stats"]["duel:en:5"]
    if won:
        assert stats["best_score"] == app_module.duel_score(game)
    # review covers player rows only
    if at.session_state["review"] is None:
        btns = [b for b in at.button if b.label.startswith("Analyze")]
        if btns:
            btns[0].click()
            at.run()
    review = at.session_state["review"]
    if review is not None:
        player_rows = (len(game.history) + 1) // 2
        assert len(review) == player_rows


def test_callbacks_never_crash_even_on_foreign_exceptions():
    """Reproduces the production crash: after a redeploy, the session's
    game object raises an InvalidGuess from the OLD module — a class the
    new except-clause can't catch by identity. No callback may ever let
    any exception escape."""
    at = make_app()
    game = at.session_state["game"]

    class LegacyInvalidGuess(Exception):  # foreign exception class
        def __init__(self, reason):
            super().__init__(reason)
            self.reason = reason
    LegacyInvalidGuess.__name__ = "InvalidGuess"

    def exploding_submit(word):
        raise LegacyInvalidGuess("legacy reason text")
    game.submit = exploding_submit
    guess(at, "stone")  # asserts not at.exception internally
    assert at.session_state["message"][0] == "error"
    assert "legacy reason" in at.session_state["message"][1]

    def truly_broken(word):
        raise RuntimeError("totally unexpected")
    at.session_state["game"].submit = truly_broken
    at.text_input(key="guess_input").input("brick")
    button(at, "Guess").click()
    at.run()
    assert not at.exception            # survived an arbitrary explosion
    assert "hiccuped" in at.session_state["message"][1]


def test_stale_game_object_is_healed_on_rerun():
    """A session that survived a redeploy may hold a game whose class no
    longer exists — the app must rebuild it instead of crashing."""
    at = make_app()

    class NotAGame:                     # simulates an old-module instance
        status = None
    at.session_state["game"] = NotAGame()
    at.session_state["ratings"] = [object()]   # stale ratings too
    at.run()
    assert not at.exception
    from avoidle.engine import AvoidleGame
    assert isinstance(at.session_state["game"], AvoidleGame)
    assert at.session_state["ratings"] == []
    # and the rebuilt board is playable immediately
    game = at.session_state["game"]
    safe = next(w for w in game.remaining_words if w != game.secret)
    guess(at, safe)
    assert at.session_state["game"].guesses_made == 1


def test_rating_failure_never_desyncs_or_blocks_recording():
    """If move analysis explodes AFTER a successful submit, the move must
    still count fully: ratings aligned, buffer cleared, game recorded."""
    import avoidle.analysis as analysis
    at = make_app()
    game = at.session_state["game"]
    game.secret = "crane"
    orig = analysis.rate_move

    def boom(*a, **k):
        raise RuntimeError("rating exploded")
    try:
        analysis.rate_move = boom
        guess(at, "aahed")
    finally:
        analysis.rate_move = orig
    game = at.session_state["game"]
    assert game.guesses_made == 1
    assert len(at.session_state["ratings"]) == 1     # fallback rating kept
    assert at.session_state["ratings"][0].retained == game.remaining_count
    # and a game-ending guess under failure still records stats + XP
    try:
        analysis.rate_move = boom
        for word in ("beaks", "clame", "coate", "crape", "crare"):
            guess(at, word)
    finally:
        analysis.rate_move = orig
    assert at.session_state["game"].status is GameStatus.SURVIVED
    assert at.session_state["stats"]["daily:en:5"]["played"] == 1
    assert at.session_state["xp"] > 0
    blob = " ".join(str(el.value) for el in at.success)
    assert "Achievement unlocked" in blob            # banners not wiped


def test_mode_switch_rolls_back_on_failure():
    """A failed board build must never leave one mode's setting pointing
    at another mode's game (duel chrome over a daily board)."""
    import avoidle.words as words
    at = make_app()
    assert at.session_state["mode"] == "daily"
    orig = words.random_secret

    def boom(*a, **k):
        raise RuntimeError("word list hiccup")
    try:
        words.random_secret = boom
        at.radio(key="mode_label").set_value("🆚 Duel").run()
    finally:
        words.random_secret = orig
    assert not at.exception
    ss = at.session_state
    assert ss["mode"] == "daily"                     # rolled back
    assert ss["game"].config.label == "Daily"        # consistent pair
    # and the next guess plays as a daily — no bot reply appears
    game = ss["game"]
    safe = next(w for w in game.remaining_words if w != game.secret)
    guess(at, safe)
    assert at.session_state["game"].guesses_made == 1


def test_app_and_core_versions_locked_together():
    """The hot-redeploy guard only works if app.py's expected version
    string is bumped in lockstep with avoidle.__version__."""
    import app as app_module
    from avoidle import __version__
    assert app_module._EXPECTED_CORE_VERSION == __version__


def test_stale_core_module_is_evicted_on_app_run():
    """Simulates a Streamlit Cloud hot-update: the cached avoidle module
    reports an old version; running app.py must evict and reload it so
    mixed-version signature errors can never reach the player."""
    import sys
    import avoidle
    real = avoidle.__version__
    snapshot = {n: m for n, m in sys.modules.items()
                if n == "avoidle" or n.startswith("avoidle.")}
    try:
        avoidle.__version__ = "0.0.0.0"   # pretend the cache is stale
        at = AppTest.from_file(APP, default_timeout=30)
        at.run()
        assert not at.exception
        import avoidle as reloaded
        assert reloaded.__version__ == real
    finally:
        # restore the ORIGINAL module objects so later tests keep
        # consistent class identities
        for n in [n for n in list(sys.modules)
                  if n == "avoidle" or n.startswith("avoidle.")]:
            del sys.modules[n]
        sys.modules.update(snapshot)
        avoidle.__version__ = real


def test_duel_board_grows_instead_of_stacking_empty_rows():
    at = make_app()
    at.radio(key="mode_label").set_value("🆚 Duel").run()
    assert not at.exception
    boards = [str(md.value) for md in at.markdown
              if 'class="dw-board' in str(md.value)]
    assert boards and "rows in reserve" in boards[0]
    assert boards[0].count("dw-empty") <= \
        2 * at.session_state["game"].word_length


def test_move_feedback_rail_renders_right_of_board():
    """Every played row carries its verdict in the rail next to the
    tiles (grade + kept-count), so feedback never gets lost below."""
    at = make_app()
    game = at.session_state["game"]
    safe = next(w for w in game.remaining_words if w != game.secret)
    guess(at, safe)
    boards = [str(md.value) for md in at.markdown
              if 'class="dw-board' in str(md.value)]
    assert boards and "dw-rail" in boards[0] and "kept" in boards[0]
    # one rail per played row
    assert boards[0].count("dw-rail") >= 1


def test_duel_rail_marks_player_rows_only():
    import random as _random
    at = make_app()
    at.radio(key="mode_label").set_value("🆚 Duel").run()
    game = at.session_state["game"]
    game.rng = _random.Random(5)
    safe = next(w for w in game.remaining_words if w != game.secret)
    guess(at, safe)
    boards = [str(md.value) for md in at.markdown
              if 'class="dw-board' in str(md.value)]
    # after player move + bot reply: exactly one rail (the player's)
    n_rails = boards[0].count('class="dw-rail')
    assert n_rails == len(at.session_state["ratings"]) == 1


def test_mode_radio_carries_blurbs_and_thinking_css_present():
    import app as app_module
    # every mode has a one-glance blurb, shown as radio captions and in
    # the ? tooltip
    assert set(app_module.MODE_BLURBS) == set(app_module.MODES.values())
    assert all(app_module.MODE_BLURBS[m] for m in app_module.MODES.values())
    # the bot's visible thinking progress bar + the rail styles ship in
    # the stylesheet, and the board keeps its keyboard breathing room
    assert "dw-think-track" in app_module.CSS
    assert "dw-rail" in app_module.CSS
    assert "margin: 2px 0 14px 0" in app_module.CSS


def test_duel_recursive_read_after_endgame():
    """The Hard duel reaches an endgame and the post-game review surfaces
    the backward-induction 'forced win' debrief when one existed."""
    at = make_app()
    at.radio(key="mode_label").set_value("🆚 Duel").run()
    at.selectbox(key="bot_select").set_value("hard").run()
    assert not at.exception
    assert at.session_state["bot_level"] == "hard"
    # drive a duel to its conclusion (bot replies via deferred rerun)
    import random as _random
    game = at.session_state["game"]
    game.rng = _random.Random(3)
    for _ in range(12):
        game = at.session_state["game"]
        if game.is_over:
            break
        safe = next((w for w in game.remaining_words if w != game.secret),
                    game.secret)
        guess(at, safe)
    assert at.session_state["game"].is_over
    btns = [b for b in at.button if b.label.startswith("Analyze")]
    if btns:
        btns[0].click()
        at.run()
        assert not at.exception
        # review covers player rows only; recursive read is a str or None
        assert at.session_state["duel_read"] is None or \
            "Recursive read" in at.session_state["duel_read"]


def test_losing_by_guessing_secret_then_undo_rescue():
    at = make_app()
    secret = at.session_state["game"].secret
    guess(at, secret)
    game = at.session_state["game"]
    assert game.status is GameStatus.WORDLED
    # loss with undos left must NOT be recorded yet (key may not even
    # exist — viewing stats no longer creates zero entries)
    assert at.session_state["stats"].get(
        "daily:en:5", {}).get("played", 0) == 0
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
    from avoidle import __homepage__, __version__
    at = make_app()
    rendered = " ".join(str(md.value) for md in at.markdown)
    sidebar_md = " ".join(str(md.value) for md in at.sidebar.markdown)
    blob = rendered + sidebar_md
    assert __version__ in blob
    assert __homepage__ in blob


# ----------------------------------------------------------------------
# v1.5.2.0: turn timer, roulette mode, nickname slots, odometer
# ----------------------------------------------------------------------
def test_turn_timer_penalty_ladder_and_reset():
    import time as _time
    at = make_app()
    at.toggle(key="timer_toggle").set_value(True).run()
    assert not at.exception
    assert at.session_state["timer_on"] is True
    assert at.session_state["turn_deadline"] is not None
    # a play arriving past the deadline costs an ability (daily: the hint)
    at.session_state["turn_deadline"] = _time.time() - 5
    game = at.session_state["game"]
    safe = next(w for w in game.remaining_words if w != game.secret)
    guess(at, safe)
    game = at.session_state["game"]
    assert game.guesses_made == 1            # the late play still counts
    assert game.config.max_hints == 0        # ...but the clock ate the hint
    assert "clock ate" in at.session_state["message"][1]
    assert at.session_state["turn_deadline"] > _time.time()  # clock restarted


def test_turn_timer_locks_once_the_game_has_begun():
    at = make_app()
    game = at.session_state["game"]
    safe = next(w for w in game.remaining_words if w != game.secret)
    guess(at, safe)
    at.toggle(key="timer_toggle").set_value(True).run()
    assert not at.exception
    assert at.session_state["timer_on"] is False   # change rejected


def test_turn_timer_forfeits_with_nothing_left_to_take():
    import time as _time
    import app as app_module
    at = make_app()
    at.radio(key="mode_label").set_value("💀 Impossible").run()
    at.toggle(key="timer_toggle").set_value(True).run()
    at.session_state["turn_deadline"] = _time.time() - 5
    game = at.session_state["game"]
    safe = next(w for w in game.remaining_words if w != game.secret)
    guess(at, safe)
    game = at.session_state["game"]
    assert game.is_over and game.forfeited
    assert not app_module.player_won(game, "impossible")
    assert at.session_state["stats"]["impossible:en:5"]["played"] == 1
    assert at.session_state["stats"]["impossible:en:5"]["survived"] == 0


def _fake_wiktionary(definition="A tall lifting machine.", pos="Noun"):
    import json

    def fake_get(url):
        return json.dumps({"en": [{
            "partOfSpeech": pos,
            "definitions": [{"definition": definition}]}]}).encode("utf-8")
    return fake_get


def _board_html(at):
    return next(m.value for m in at.markdown
                if 'class="dw-board' in (m.value or ""))


def test_played_row_shows_a_word_definition(monkeypatch):
    from avoidle import definitions as D
    D.define.cache_clear()
    D.reset_circuit()
    monkeypatch.setattr(D, "_http_get", _fake_wiktionary())
    at = make_app()
    game = at.session_state["game"]
    safe = next(w for w in game.remaining_words if w != game.secret)
    guess(at, safe)
    # the gloss was looked up once and memoised in the session
    assert at.session_state["defs"][safe] == "(noun) A tall lifting machine."
    # ...and embedded in the board for hover (title) and tap (the card)
    board = _board_html(at)
    assert "dw-defbox" in board and "tabindex" in board
    assert "A tall lifting machine." in board
    assert safe.upper() in board


def test_render_board_definition_states():
    import app as app_module
    at = make_app()
    game = at.session_state["game"]
    safe = next(w for w in game.remaining_words if w != game.secret)
    guess(at, safe)
    game = at.session_state["game"]
    # a real gloss: interactive row + populated card
    known = app_module.render_board(game, defs={safe: "(noun) a thing"})
    assert "dw-def" in known and "a thing" in known
    assert "dw-defbox-empty" not in known
    # looked up but nothing found: still interactive, but a muted note
    missing = app_module.render_board(game, defs={safe: None})
    assert "dw-defbox-empty" in missing and "no definition found" in missing
    # definitions disabled: no affordance at all
    off = app_module.render_board(game, defs=None)
    assert "dw-def" not in off and "tabindex" not in off


def test_definitions_cover_the_duel_bots_word(monkeypatch):
    from avoidle import definitions as D
    D.define.cache_clear()
    D.reset_circuit()
    monkeypatch.setattr(D, "_http_get",
                        _fake_wiktionary("An imaginary opponent.", "Noun"))
    at = make_app()
    at.radio(key="mode_label").set_value("🆚 Duel").run()
    game = at.session_state["game"]
    safe = next(w for w in game.remaining_words if w != game.secret)
    guess(at, safe)                       # player plays, bot replies
    game = at.session_state["game"]
    if game.guesses_made >= 2:            # the bot has put up a word
        bot_word = game.history[1].guess
        assert bot_word in at.session_state["defs"]
        assert bot_word.upper() in _board_html(at)


def test_definitions_are_in_the_language_being_played(monkeypatch):
    import json
    import urllib.error
    from avoidle import definitions as D
    D.define.cache_clear()
    D.reset_circuit()
    seen = []

    def fake_get(url):
        seen.append(url)
        if "rest_v1" in url:                       # endpoint is en-only
            raise urllib.error.HTTPError(url, 404, "x", {}, None)
        return json.dumps({"parse": {"wikitext":
                           ":[1] runde [[Frucht]] des [[Apfelbaum]]s\n"}}
                          ).encode("utf-8")

    monkeypatch.setattr(D, "_http_get", fake_get)
    at = make_app()
    at.selectbox(key="lang_select").set_value("de").run()
    assert at.session_state["lang"] == "de"
    game = at.session_state["game"]
    safe = next(w for w in game.remaining_words if w != game.secret)
    guess(at, safe)
    # the gloss is the German one, and every lookup hit the German wiki
    assert at.session_state["defs"][safe] == "runde Frucht des Apfelbaums"
    assert seen and all("de.wiktionary.org" in u for u in seen)


def test_header_tagline_tells_you_not_to_say_the_word():
    import app as app_module
    assert "don't say the word" in app_module.HEADER
    assert "never the word" not in app_module.HEADER


def test_game_modes_are_listed_alphabetically():
    import app as app_module
    names = [label.split(" ", 1)[1] for label in app_module.MODES]
    assert names == sorted(names)
    # every mode kept its internal key and blurb through the reorder
    assert set(app_module.MODES.values()) == set(app_module.MODE_BLURBS)


def test_time_crunch_offers_selectable_lengths_with_sensible_default():
    import time as _t
    import app as app_module
    at = make_app()
    assert at.session_state["turn_seconds"] == app_module.TURN_SECONDS == 120
    at.toggle(key="timer_toggle").set_value(True).run()
    sel = at.selectbox(key="turn_seconds_select")    # appears only when on
    assert sel is not None
    assert list(app_module.TIMER_CHOICES) == [30, 60, 120, 180, 300]
    sel.set_value(30).run()
    assert at.session_state["turn_seconds"] == 30
    # the live deadline reflects the shorter crunch, not the old 3:00
    assert at.session_state["turn_deadline"] - _t.time() <= 31


def test_time_crunch_length_locks_once_the_game_has_begun():
    at = make_app()
    at.toggle(key="timer_toggle").set_value(True).run()
    at.selectbox(key="turn_seconds_select").set_value(60).run()
    assert at.session_state["turn_seconds"] == 60
    game = at.session_state["game"]
    safe = next(w for w in game.remaining_words if w != game.secret)
    guess(at, safe)
    locked = at.selectbox(key="turn_seconds_select")
    assert locked.disabled                       # cannot be changed mid-game
    locked.set_value(300).run()
    assert at.session_state["turn_seconds"] == 60   # change rejected


def test_keyboard_bridge_routes_real_keys_in_click_mode():
    import app as app_module
    js = app_module._keyboard_bridge_js("click", is_over=False)
    # routes physical keys onto the on-screen keyboard buttons
    assert ".st-key-clickkbd" in js
    assert "'Enter'" in js and "'Backspace'" in js
    assert "addEventListener('keydown'" in js
    # exactly one handler ever lives on the parent (no stacked listeners)
    assert "removeEventListener('keydown'" in js
    assert "__avoidleKey" in js
    # never hijacks typing into a real text field
    assert "isContentEditable" in js


def test_keyboard_bridge_autofocuses_the_text_box_in_type_mode():
    import app as app_module
    js = app_module._keyboard_bridge_js("type", is_over=False)
    assert ".st-key-guessrow input" in js and ".focus()" in js
    # the runtime branch is selected by the mode flag baked into the script
    assert "MODE='type'" in js
    assert "MODE='click'" not in js


def test_keyboard_bridge_is_inert_once_the_game_is_over():
    import app as app_module
    js = app_module._keyboard_bridge_js("click", is_over=True)
    assert "OVER=true" in js


def test_keyboard_bridge_renders_without_error():
    # the bridge is injected on a normal click-mode board
    at = make_click_app()
    assert not at.exception
    assert at.session_state["input_mode"] == "click"


def test_roulette_wheel_spins_and_keeps_the_game_fair():
    import random as _random
    at = make_app()
    at.radio(key="mode_label").set_value("🎰 Roulette").run()
    assert not at.exception
    game = at.session_state["game"]
    assert game.config.label == "Roulette"
    game.rng = _random.Random(42)
    for _ in range(4):
        game = at.session_state["game"]
        if game.is_over:
            break
        demanded = at.session_state["spin_letter"]
        if demanded:
            safe = next((w for w in game.remaining_words
                         if w != game.secret and demanded in w), None)
        else:
            safe = next((w for w in game.remaining_words
                         if w != game.secret), None)
        if safe is None:        # trapped or no word satisfies the demand
            break
        guess(at, safe)
        game = at.session_state["game"]
        # invariants the wheel must never break
        assert game.secret in game.remaining_words
        assert game.config.max_undos >= game.undos_used
        assert game.config.max_hints >= game.hints_used
        assert game.config.max_peeks >= game.peeks_used
        if not game.is_over:
            note = at.session_state["spin_note"]
            assert note and note.startswith("🎰")


def test_roulette_handcuff_blocks_words_without_the_letter():
    at = make_app()
    at.radio(key="mode_label").set_value("🎰 Roulette").run()
    game = at.session_state["game"]
    at.session_state["spin_letter"] = "z"
    safe = next(w for w in game.remaining_words
                if w != game.secret and "z" not in w)
    guess(at, safe)
    game = at.session_state["game"]
    assert game.guesses_made == 0
    assert at.session_state["message"][0] == "error"
    withz = next((w for w in game.remaining_words
                  if w != game.secret and "z" in w), None)
    if withz:
        guess(at, withz)
        assert at.session_state["game"].guesses_made == 1


def _roulette_seed_for(event, last=None):
    """A seed whose first wheel spin lands on ``event`` (deterministic)."""
    import random as _random
    from app import WHEEL
    opts = [(w, e) for w, e in WHEEL if e != last]
    weights = [w for w, _ in opts]
    events = [e for _, e in opts]
    for s in range(50000):
        if _random.Random(s).choices(events, weights=weights, k=1)[0] == event:
            return s
    raise AssertionError(f"no seed found for {event!r}")


def _roulette_app():
    import random as _random
    at = make_app()
    at.radio(key="mode_label").set_value("🎰 Roulette").run()
    assert not at.exception
    return at, _random


def test_roulette_undo_reverts_a_wheel_gift_so_it_cant_be_farmed():
    at, _random = _roulette_app()
    game = at.session_state["game"]
    base_undos = game.config.max_undos
    game.rng = _random.Random(_roulette_seed_for("lucky_undo"))
    safe = next(w for w in game.remaining_words if w != game.secret)
    guess(at, safe)
    game = at.session_state["game"]
    assert game.config.max_undos == base_undos + 1     # the wheel gifted one
    button(at, "↩️ Undo").click()
    at.run()
    assert not at.exception
    game = at.session_state["game"]
    assert game.config.max_undos == base_undos         # undo took the gift back
    assert at.session_state["spin_undo_stack"] == []   # stack stays aligned


def test_roulette_undo_clears_a_taken_back_handcuff_demand():
    at, _random = _roulette_app()
    game = at.session_state["game"]
    assert at.session_state["spin_letter"] is None
    game.rng = _random.Random(_roulette_seed_for("handcuff"))
    safe = next(w for w in game.remaining_words if w != game.secret)
    guess(at, safe)
    demand = at.session_state["spin_letter"]
    assert demand                                      # a demand was imposed
    button(at, "↩️ Undo").click()
    at.run()
    assert not at.exception
    assert at.session_state["spin_letter"] is None     # demand rolled back
    # the stale demand must not lock the replacement guess
    game = at.session_state["game"]
    nomatch = next((w for w in game.remaining_words
                    if w != game.secret and demand not in w), None)
    if nomatch:
        guess(at, nomatch)
        assert at.session_state["game"].guesses_made == 1


def test_roulette_undo_restores_a_reshuffled_secret():
    at, _random = _roulette_app()
    game = at.session_state["game"]
    pre_secret = game.secret
    game.rng = _random.Random(_roulette_seed_for("shuffle"))
    safe = next(w for w in game.remaining_words if w != game.secret)
    guess(at, safe)
    button(at, "↩️ Undo").click()
    at.run()
    assert not at.exception
    assert at.session_state["game"].secret == pre_secret   # reroll undone


def test_nickname_slug_and_cookie_names():
    import app as app_module
    assert app_module._slug("Eugen! 23") == "eugen23"
    assert app_module._slug("x" * 40) == "x" * 16
    assert app_module._slug(None) == ""        # junk never mints a slot
    assert app_module._slug(12345) == ""
    assert app_module.profile_cookie("") == "dw_progress"   # legacy guest
    assert app_module.profile_cookie("Ben") == "dw_p_ben"


def test_nickname_switch_starts_a_fresh_slot():
    at = make_app()
    at.session_state["xp"] = 750
    at.session_state["games_total"] = 9
    at.text_input(key="nick_input").input("Ben")
    at.run()
    assert not at.exception
    assert at.session_state["nickname"] == "ben"
    # no cookie exists for "ben" in the test harness -> fresh slot
    assert at.session_state["xp"] == 0
    assert at.session_state["games_total"] == 0


def test_games_total_odometer_counts_and_survives_roundtrip():
    import app as app_module
    at = make_app()
    at.radio(key="mode_label").set_value("💀 Impossible").run()
    guess(at, at.session_state["game"].secret)   # instant final loss
    assert at.session_state["games_total"] == 1
    # the odometer survives the backup-file roundtrip, clamped like
    # every numeric field
    payload = app_module.parse_stats_json(
        '{"stats": {}, "games_total": 7}')
    assert payload["games_total"] == 7


def test_review_shows_safe_alternative_for_fatal_move():
    at = make_app()
    at.radio(key="mode_label").set_value("💀 Impossible").run()
    guess(at, at.session_state["game"].secret)
    assert at.session_state["game"].is_over
    btns = [b for b in at.button if b.label.startswith("Analyze")]
    assert btns
    btns[0].click()
    at.run()
    assert not at.exception
    blob = " ".join(str(md.value) for md in at.markdown)
    assert "safe instead" in blob


# ----------------------------------------------------------------------
# v1.5.2.1: worldwide odometer + roulette wheel upgrades
# ----------------------------------------------------------------------
def test_global_counter_counts_across_everyone():
    from avoidle.store import get_store
    at = make_app()
    before = get_store().games()
    at.radio(key="mode_label").set_value("💀 Impossible").run()
    guess(at, at.session_state["game"].secret)   # finished game
    assert at.session_state["global_games"] == before + 1
    assert get_store().games() == before + 1     # server-side, shared
    blob = " ".join(str(md.value) for md in at.sidebar.markdown)
    assert "by everyone, ever" in blob


def test_global_floor_heals_after_a_wiped_store():
    from avoidle.store import SqliteStore
    import os
    import tempfile
    s = SqliteStore(os.path.join(
        tempfile.mkdtemp(prefix="avoidle-floor-"), "s.db"))
    # a returning visitor's cookie remembers 500 games; the fresh file
    # resumes from there instead of embarrassing everyone with a zero
    assert s.raise_games_floor(500) == 500
    assert s.bump_games() == 501


def test_roulette_wheel_never_repeats_back_to_back():
    import random as _random
    at = make_app()
    at.radio(key="mode_label").set_value("🎰 Roulette").run()
    game = at.session_state["game"]
    game.rng = _random.Random(7)
    prev = None
    for _ in range(5):
        game = at.session_state["game"]
        if game.is_over:
            break
        demanded = at.session_state["spin_letter"]
        pool = [w for w in game.remaining_words
                if w != game.secret and (not demanded or demanded in w)]
        if not pool:
            break
        guess(at, pool[0])
        if at.session_state["game"].is_over:
            break
        ev = at.session_state["last_spin"]
        assert ev is not None
        if prev is not None:
            assert ev != prev          # the wheel never repeats itself
        prev = ev
        assert at.session_state["spin_pot"] >= 0


def test_roulette_pot_pays_out_only_on_survival():
    import random as _random
    at = make_app()
    at.radio(key="mode_label").set_value("🎰 Roulette").run()
    game = at.session_state["game"]
    game.rng = _random.Random(11)
    for _ in range(6):
        game = at.session_state["game"]
        if game.is_over:
            break
        demanded = at.session_state["spin_letter"]
        pool = [w for w in game.remaining_words
                if w != game.secret and (not demanded or demanded in w)]
        if not pool:
            break
        guess(at, pool[0])
    game = at.session_state["game"]
    if game.status is GameStatus.SURVIVED:
        pot = at.session_state["spin_pot"]
        recorded = at.session_state["stats"]["roulette:en:5"]["best_score"]
        assert recorded == game.score() + pot


def test_leaderboard_appears_once_critical_mass_is_reached():
    import app as app_module
    from avoidle.store import get_store
    s = get_store()
    for i in range(app_module.LEADERBOARD_MIN):
        s.save_profile(f"player{i}", "x", xp=1000 + i, wins=i)
    at = make_app()
    blob = " ".join(str(md.value) for md in at.sidebar.markdown)
    assert "👑" in blob            # the board rendered, leader crowned
    assert "player" in blob and "XP" in blob
