"""Avoidle — Streamlit app.

The anti-Wordle: six guesses, and your only job is to NOT say the word.
Run with:  streamlit run app.py
"""

from __future__ import annotations

import base64
import datetime
import functools
import json
import random
import re
import sys
import time
import zlib

import streamlit as st
import streamlit.components.v1 as components

# ----------------------------------------------------------------------
# Hot-redeploy guard: Streamlit Cloud re-runs THIS file on source
# updates but keeps previously imported modules cached. A new app.py
# calling an old avoidle module (mismatched signatures/classes) caused
# real production errors. If versions disagree, evict the cached
# package so the imports below load the matching code.
# ----------------------------------------------------------------------
_EXPECTED_CORE_VERSION = "1.5.1.0"
try:
    import avoidle as _core_probe
    if getattr(_core_probe, "__version__", None) != _EXPECTED_CORE_VERSION:
        for _name in [n for n in list(sys.modules)
                      if n == "avoidle" or n.startswith("avoidle.")]:
            del sys.modules[_name]
except Exception:
    pass

from avoidle import __homepage__, __version__
from avoidle import achievements as ACH
from avoidle import bot as BOT
from avoidle import analysis as A
from avoidle import words as W
from avoidle.engine import (
    GRAY,
    GREEN,
    PRESETS,
    UNLIMITED,
    YELLOW,
    AvoidleGame,
    GameConfig,
    GameStatus,
    InvalidGuess,
)

# ----------------------------------------------------------------------
# Modes
# ----------------------------------------------------------------------
MODES = {
    "📅 Daily Challenge": "daily",
    "🎲 Classic": "classic",
    "🆚 Duel": "duel",
    "🔥 Hard": "hard",
    "💀 Impossible": "impossible",
    "⚔️ Survival": "survival",
    "🧘 Zen": "zen",
}

DUEL_CONFIG = GameConfig("Duel", max_guesses=12, max_undos=0,
                         max_hints=0, max_peeks=1, score_multiplier=1.5)

MODE_HELP = {
    "daily": "One shared puzzle per day — same secret word for everyone. "
             "6 guesses, 5 undos, 1 hint, 1 peek.",
    "classic": "Random word. 6 guesses, 5 undos, 1 hint, 1 peek.",
    "duel": "Hot potato vs the bot: you alternate guesses — whoever says "
            "the hidden word LOSES. No undos, 1 peek. 12 rows, you go "
            "first. Pick the bot's strength below the mode selector.",
    "hard": "6 guesses, only 2 undos, no hints, 1 peek. 1.5× score.",
    "impossible": "SEVEN guesses to survive, zero undos, zero help. 2.5× score.",
    "survival": "Endless gauntlet: each round you lose one undo. "
                "Scores stack with a rising multiplier. One loss ends the run.",
    "zen": "Practice space — unlimited undos, hints and peeks. 0.25× score.",
}


HOW_TO_MD = (
    "- Guess words — but **never** the hidden word.\n"
    "- Every guess must obey all clues: 🟩 stays in its spot, 🟨 must be "
    "re-used (elsewhere), ⬜ is forbidden.\n"
    "- The clue rules shrink the pool of playable words, pushing you "
    "toward the answer. **Survive every guess to win.**\n"
    "- **↩️ Undo** takes back a guess — even a fatal one (no undos "
    "in 🆚 Duel). **💡 Hint** "
    "reveals a safe word. **👁️ Peek** shows remaining words (risky!).\n"
    "- Secrets are **frequency-weighted**: if the clues fit two words, "
    "suspect the common one.\n"
    "- More 🟩/🟨 on a winning board = higher score."
)


def survival_config(round_no: int) -> GameConfig:
    """Round 1 = 5 undos, each round one fewer; multiplier climbs 25%/round."""
    return GameConfig(
        label=f"Survival · Round {round_no}",
        max_guesses=6,
        max_undos=max(0, 6 - round_no),
        max_hints=1 if round_no <= 2 else 0,
        max_peeks=1,
        score_multiplier=1.0 + 0.25 * (round_no - 1),
    )


# ----------------------------------------------------------------------
# Session state
# ----------------------------------------------------------------------
def _new_game(mode: str) -> AvoidleGame:
    ss = st.session_state
    lang, length = ss.lang, ss.word_len
    rng = random.Random()
    if mode == "daily":
        import dataclasses
        today = datetime.date.today()
        secret = W.daily_secret(lang, length, today)
        cfg = dataclasses.replace(PRESETS["classic"], label="Daily")
        # pin the date at game creation so a session crossing midnight
        # stays attributed to the day it started
        ss.daily_key = f"{today.isoformat()}:{lang}:{length}"
        # deterministic helper rng so daily hints/peeks match across players
        rng = random.Random(f"daily:{lang}:{length}:{today.isoformat()}")
    elif mode == "survival":
        cfg = survival_config(ss.survival_round)
        secret = W.random_secret(lang, length, rng)
    elif mode == "duel":
        cfg = DUEL_CONFIG
        secret = W.random_secret(lang, length, rng)
    else:
        cfg = PRESETS[mode]
        secret = W.random_secret(lang, length, rng)
    return AvoidleGame(secret, W.allowed_guesses(lang, length), cfg, rng=rng)


def init_state() -> None:
    ss = st.session_state
    ss.setdefault("lang", "en")
    ss.setdefault("word_len", 5)
    ss.setdefault("input_mode", "click")  # clickable keyboard by default
    ss.setdefault("kbd_buffer", "")      # letters picked on the clickable kbd
    ss.setdefault("ratings", [])       # live MoveRating per row
    ss.setdefault("review", None)      # post-game best-move analysis
    ss.setdefault("last_action", None)  # drives reveal/shake animations
    ss.setdefault("mode", "daily")
    ss.setdefault("survival_round", 1)
    ss.setdefault("survival_total", 0)
    ss.setdefault("survival_best", 0)
    ss.setdefault("stats", {})         # mode -> dict
    ss.setdefault("xp", 0)
    ss.setdefault("achievements", set())   # unlocked achievement ids
    ss.setdefault("game_unlocks", [])      # banners for the end panel
    ss.setdefault("daily_streaks", {})     # "lang:len" -> {last, streak}
    ss.setdefault("wins_langs", set())
    ss.setdefault("wins_lengths", set())
    ss.setdefault("session_log", [])       # recap of finished games
    ss.setdefault("bot_level", "normal")   # duel opponent strength
    ss.setdefault("bot_pending", False)    # duel: bot replies next rerun
    ss.setdefault("duel_read", None)       # recursive endgame debrief
    ss.setdefault("message", None)     # (kind, text)
    ss.setdefault("hint_word", None)
    ss.setdefault("peek_words", None)
    ss.setdefault("recorded", False)
    ss.setdefault("celebrated", False)
    ss.setdefault("daily_done", set())  # {"YYYY-MM-DD:lang:len"} counted
    ss.setdefault("daily_win_dates", set())  # daily WINS, for the heatmap
    # self-heal after a redeploy: session objects created by an older
    # version of the code (different class identity) are rebuilt
    if "game" in ss and not isinstance(ss.game, AvoidleGame):
        del ss["game"]
        reset_game_view_state()
        ss.message = ("ok", "✨ Avoidle was updated — fresh board, "
                            "progress kept.")
    if any(not isinstance(r, A.MoveRating) for r in ss.get("ratings", [])):
        ss.ratings = []
    if ss.get("review") and any(not isinstance(r, A.MoveRating)
                                for r in ss.review):
        ss.review = None
    if not ss.get("_cookie_checked"):
        ss._cookie_checked = True
        if not ss.stats and ss.xp == 0:   # only a truly fresh session
            restore_progress_from_cookie()
    if "game" not in ss:
        ss.game = _new_game(ss.mode)


def reset_game_view_state() -> None:
    """Everything that belongs to ONE game's lifetime — used identically
    by new-game, redeploy healing and crash recovery, so the three
    safety layers can never disagree about what to reset."""
    ss = st.session_state
    ss.message = None
    ss.hint_word = None
    ss.peek_words = None
    ss.recorded = False
    ss.celebrated = False
    ss.ratings = []
    ss.review = None
    ss.duel_read = None
    ss.kbd_buffer = ""
    ss.game_unlocks = []
    ss.bot_pending = False
    ss.last_action = None


def player_won(game: AvoidleGame, mode: str) -> bool:
    """Did the human win? In Duel the fatal guess may be the bot's."""
    if game.status is GameStatus.SURVIVED:
        return True
    if mode == "duel" and game.status is GameStatus.WORDLED:
        # player rows are 0,2,4…; after the fatal row len(history) is
        # odd for a player blunder, even for a bot blunder
        return len(game.history) % 2 == 0
    return False


def duel_score(game: AvoidleGame) -> int:
    """Score for a duel won by the bot's blunder (engine score is 0
    because the game technically ended WORDLED). Tougher bots pay more."""
    mult = BOT.BOT_MULTIPLIER.get(st.session_state.get("bot_level",
                                                       "normal"), 1.5)
    return round((100 + 12 * game.guesses_made) * mult)


def game_score(game: AvoidleGame, mode: str) -> int:
    if mode == "duel":
        return duel_score(game) if player_won(game, mode) else 0
    return game.score()


def mode_stats(mode: str) -> dict:
    ss = st.session_state
    key = f"{mode}:{ss.lang}:{ss.word_len}"
    return ss.stats.setdefault(
        key, {"played": 0, "survived": 0, "streak": 0,
              "best_streak": 0, "best_score": 0})


def record_result_if_final(force: bool = False) -> None:
    """Count a finished game exactly once. A Wordled game with undos left
    is not final yet (the player may still take it back)."""
    ss = st.session_state
    game: AvoidleGame = ss.game
    if ss.recorded or not game.is_over:
        return
    if game.status is GameStatus.WORDLED and game.can_undo() and not force:
        return
    ss.recorded = True
    # the session recap lists every finished game (even daily practice
    # replays, which are excluded from stats/XP below)
    ss.session_log = (ss.session_log + [{
        "mode": ss.mode, "lang": ss.lang, "len": ss.word_len,
        "won": player_won(game, ss.mode),
        "score": game_score(game, ss.mode)}])[-20:]
    if ss.mode == "daily":
        daily_key = ss.get("daily_key") or (
            f"{datetime.date.today().isoformat()}:{ss.lang}:{ss.word_len}")
        if daily_key in ss.daily_done:
            return  # practice replay of a known word: don't farm stats
        ss.daily_done.add(daily_key)
    ss.stats_upload_token = None  # stats changed; allow re-restoring a backup
    stats = mode_stats(ss.mode)
    stats["played"] += 1
    if player_won(game, ss.mode):
        stats["survived"] += 1
        stats["streak"] += 1
        stats["best_streak"] = max(stats["best_streak"], stats["streak"])
        stats["best_score"] = max(stats["best_score"],
                                  game_score(game, ss.mode))
    else:
        stats["streak"] = 0
    if ss.mode == "survival":
        if game.status is GameStatus.SURVIVED:
            ss.survival_total += game.score()
            ss.survival_best = max(ss.survival_best, ss.survival_total)
        else:
            ss.survival_best = max(ss.survival_best, ss.survival_total)
    _award_progress(game, stats)
    ss.progress_dirty = True


def _build_context(game: AvoidleGame, stats: dict) -> ACH.GameContext:
    ss = st.session_state
    won = player_won(game, ss.mode)
    if won:
        ss.wins_langs.add(ss.lang)
        ss.wins_lengths.add(ss.word_len)
    # in duel, only the PLAYER's rows count toward achievements
    rows = game.history[0::2] if ss.mode == "duel" else game.history
    greens = sum(t.feedback.count(GREEN) for t in rows)
    yellows = sum(t.feedback.count(YELLOW) for t in rows)
    return ACH.GameContext(
        mode=ss.mode, lang=ss.lang, length=ss.word_len,
        won=won, score=game_score(game, ss.mode),
        undos=game.undos_used, hints=game.hints_used, peeks=game.peeks_used,
        greens=greens, yellows=yellows,
        min_pool_seen=game.min_pool_seen, final_pool=game.remaining_count,
        # in duel a winning trap was necessarily the BOT's, not yours
        was_trapped=game.was_ever_trapped and ss.mode != "duel",
        survival_round=ss.survival_round, streak=stats["streak"],
        total_wins=sum(s["survived"] for s in ss.stats.values()),
        rating_percentiles=[r.percentile for r in ss.ratings],
        langs_won=set(ss.wins_langs), lengths_won=set(ss.wins_lengths),
    )


def _award_progress(game: AvoidleGame, stats: dict) -> None:
    """XP, achievements, daily streaks and side-quests — recorded exactly
    once per game (guarded by the caller's `recorded` flag)."""
    ss = st.session_state
    ctx = _build_context(game, stats)
    before = ACH.level_for_xp(ss.xp)["level"]
    fresh = ACH.evaluate(ctx, ss.achievements)
    quest_bonus = 0
    if ss.mode == "daily" and ctx.won:
        date_iso = (ss.get("daily_key") or datetime.date.today().isoformat()
                    ).split(":")[0]
        quest = ACH.daily_quest(date_iso, ss.lang, ss.word_len)
        if ACH.quest_completed(quest.id, ctx):
            quest_bonus = quest.xp
            ss.game_unlocks.append(
                f"🎯 Side-quest complete: {quest.label} (+{quest.xp} XP)")
        ss.daily_win_dates.add(f"{date_iso}:{ss.lang}:{ss.word_len}")
        # daily streak: consecutive calendar days per language+length
        skey = f"{ss.lang}:{ss.word_len}"
        entry = ss.daily_streaks.get(skey, {"last": "", "streak": 0})
        today = datetime.date.fromisoformat(date_iso)
        prev = entry["last"]
        if prev == (today - datetime.timedelta(days=1)).isoformat():
            entry = {"last": date_iso, "streak": entry["streak"] + 1}
        elif prev != date_iso:
            entry = {"last": date_iso, "streak": 1}
        ss.daily_streaks[skey] = entry
    gained = ACH.xp_for_game(ctx, len(fresh)) + quest_bonus
    ss.xp += gained
    for ach in fresh:
        ss.achievements.add(ach.id)
        ss.game_unlocks.append(
            f"{ach.emoji} Achievement unlocked: **{ach.name}** — "
            f"{ach.description} (+{ACH.UNLOCK_XP} XP)")
        st.toast(f"{ach.emoji} {ach.name} unlocked!")
    after = ACH.level_for_xp(ss.xp)
    if after["level"] > before:
        ss.game_unlocks.append(
            f"⭐ Level up! You are now level {after['level']} — "
            f"*{after['title']}*")
        st.toast(f"⭐ Level {after['level']}: {after['title']}!")


def _ensure_state() -> None:
    """Callbacks can fire on a brand-new session (server restart, cache
    eviction) before the script body ran — never assume state exists."""
    if "game" not in st.session_state:
        init_state()


def _safe(fn):
    """No callback may ever crash the app. Catches everything our code
    can raise — including exceptions from STALE session objects created
    by a previous deploy, whose classes no longer match the freshly
    imported ones (the except-clause misses them by identity)."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            if type(e).__module__.startswith("streamlit"):
                raise  # never swallow Streamlit control flow
            ss = st.session_state
            if type(e).__name__ == "InvalidGuess":
                ss["message"] = ("error", getattr(e, "reason", str(e)))
                ss["last_action"] = "error"
            else:
                ss["message"] = ("error",
                                 "⚠️ That move hiccuped — your progress is "
                                 "safe. Try again or start a new game.")
    return wrapper


# ----------------------------------------------------------------------
# Actions (widget callbacks)
# ----------------------------------------------------------------------
@_safe
def act_new_game(next_round: bool = False) -> None:
    _ensure_state()
    ss = st.session_state
    record_result_if_final(force=True)
    if ss.mode == "survival":
        if next_round and ss.game.status is GameStatus.SURVIVED:
            ss.survival_round += 1
        else:
            ss.survival_round = 1
            ss.survival_total = 0
    ss.game = _new_game(ss.mode)
    reset_game_view_state()
    ss.guess_input = ""  # don't carry a typed word into the new game
    ss.last_action = "new"


def _switch(setting: str, new_value, reset_survival: bool = True) -> None:
    """Atomically change a game-defining setting: build the new board
    first conceptually — on any failure, roll the setting back so the
    UI never renders one mode's chrome over another mode's board."""
    ss = st.session_state
    record_result_if_final(force=True)
    prev = ss[setting]
    ss[setting] = new_value
    if reset_survival:
        ss.survival_round = 1
        ss.survival_total = 0
    try:
        act_new_game.__wrapped__()
    except Exception:
        ss[setting] = prev
        raise


@_safe
def act_change_bot() -> None:
    _ensure_state()
    _switch("bot_level", st.session_state.bot_select)


@_safe
def act_change_mode() -> None:
    _ensure_state()
    _switch("mode", MODES[st.session_state.mode_label])


@_safe
def act_change_lang() -> None:
    _ensure_state()
    _switch("lang", st.session_state.lang_select)


@_safe
def act_change_len() -> None:
    _ensure_state()
    _switch("word_len", st.session_state.len_select)


@_safe
def act_change_input() -> None:
    _ensure_state()
    ss = st.session_state
    ss.input_mode = "click" if "Click" in ss.input_select else "type"
    ss.kbd_buffer = ""


@_safe
def act_submit() -> None:
    _ensure_state()
    word = st.session_state.get("guess_input", "").strip().lower()
    _process_guess(word, clear_input=True)


@_safe
def act_key(letter: str) -> None:
    _ensure_state()
    ss = st.session_state
    if not ss.game.is_over and len(ss.kbd_buffer) < ss.game.word_length:
        ss.kbd_buffer += letter


@_safe
def act_backspace() -> None:
    _ensure_state()
    ss = st.session_state
    ss.kbd_buffer = ss.kbd_buffer[:-1]


@_safe
def act_kbd_enter() -> None:
    _ensure_state()
    ss = st.session_state
    _process_guess(ss.kbd_buffer)
    if ss.last_action == "guess":
        ss.kbd_buffer = ""


@_safe
def act_accept_fate() -> None:
    """Trapped with no way out — play the only word left and take the L."""
    _ensure_state()
    _process_guess(st.session_state.game.secret)


def _process_guess(word: str, clear_input: bool = False) -> None:
    ss = st.session_state
    game: AvoidleGame = ss.game
    if game.is_over:
        return
    word = W.normalize_guess(word, ss.lang)
    try:
        turn = game.submit(word)
    except InvalidGuess as e:
        # keep the typed word so the player can fix it instead of retyping
        ss.message = ("error", e.reason)
        ss.last_action = "error"
        return
    ss.last_action = "guess"
    if clear_input:
        ss.guess_input = ""
    # rate the player's move against the pool it was chosen from —
    # BEFORE any bot reply changes the board
    # (same seed/sample as act_review so live and review grades agree)
    row = game.guesses_made - 1
    try:
        rating = A.rate_move(
            A.analyzer_for(ss.lang, game.word_length), word,
            game.pool_before(row), game.secret,
            rng=random.Random(f"{game.secret}:{row}"), sample_size=400,
            actual_retained=game.remaining_count)
    except Exception:
        # the move already happened — never let analysis failure desync
        # ratings/history or block recording; degrade to a neutral rating
        rating = A.MoveRating(
            word=word, retained=game.remaining_count,
            pool_size=len(game.pool_before(row)), percentile=50.0,
            best_word=word, best_retained=game.remaining_count,
            exact=False)
    ss.ratings.append(rating)
    ss.hint_word = None
    ss.peek_words = None
    if game.status is GameStatus.WORDLED:
        ss.message = ("loss", f"💀 You said it! “{word.upper()}” was the "
                              "hidden word." +
                      (" You can still UNDO it…" if game.can_undo() else ""))
    elif game.status is GameStatus.SURVIVED:
        ss.message = ("win", "🎉 You SURVIVED! You never said the word.")
    elif ss.mode == "duel":
        # the bot replies on the NEXT rerun, after a visible thinking
        # beat — the player's tiles flip first, then the bot "decides"
        ss.bot_pending = True
        ss.message = None
    elif game.is_trapped:
        ss.message = ("warn", "Only the hidden word is left — undo, "
                              "or face your fate.")
    else:
        greens = turn.feedback.count(GREEN)
        yellows = turn.feedback.count(YELLOW)
        if greens + yellows == 0:
            ss.message = ("ok", "Clean miss — nothing revealed. Nice.")
        else:
            ss.message = ("ok", f"Revealed {greens} green / {yellows} yellow. "
                                "Those clues now bind every future guess.")
    if game.is_over:
        ss.kbd_buffer = ""  # nothing left to type on a finished board
    record_result_if_final()


def _bot_reply() -> None:
    """The duel bot's move, executed on the rerun after the player's
    tiles have rendered. Sets the follow-up message."""
    ss = st.session_state
    game: AvoidleGame = ss.game
    if game.is_over or ss.mode != "duel":
        return
    try:
        bot_word = BOT.bot_pick(ss.bot_level, game.remaining_words,
                                ss.lang, game.word_length, game.rng)
    except Exception:
        bot_word = game.rng.choice(game.remaining_words)
    game.submit(bot_word)
    ss.last_action = "guess"   # the bot's row gets its own flip
    if game.status is GameStatus.WORDLED:
        ss.message = ("win", f"👾 The bot said “{bot_word.upper()}” — "
                             "the hidden word. YOU WIN the duel!")
    elif game.status is GameStatus.SURVIVED:
        ss.message = ("win", "🏁 Twelve rows and nobody said it — "
                             "you outlasted the bot. You win!")
    else:
        # the meter and accept-fate button already explain a trap;
        # one short line is enough
        ss.message = ("ok", f"👾 played “{bot_word.upper()}”. Your turn.")
    record_result_if_final()


@_safe
def act_random_start() -> None:
    """Fill the box with a random opening word (first guess only, like the
    original's 'Random Starting Word'). Mid-game randomness could land on
    the secret itself, so it is deliberately unavailable after turn one."""
    _ensure_state()
    ss = st.session_state
    game: AvoidleGame = ss.game
    if not game.is_over and game.guesses_made == 0:
        _reseed_daily_rng("random-start")
        # never suggest the secret: with the deterministic daily seed it
        # would hand every player the losing word on unlucky dates
        word = game.rng.choice(game.safe_words())
        if ss.input_mode == "click":
            ss.kbd_buffer = word
        else:
            ss.guess_input = word


@_safe
def act_undo() -> None:
    _ensure_state()
    ss = st.session_state
    if ss.game.undo():
        ss.last_action = "undo"
        ss.message = ("ok", "↩️ Guess taken back. Choose more carefully…")
        if ss.ratings:
            ss.ratings.pop()
        ss.review = None  # any analysis refers to a board that no longer exists
        ss.hint_word = None
        ss.peek_words = None
    else:
        ss.message = ("error", "No undos available.")


@_safe
def act_review() -> None:
    """Post-game: find the best word for every row (exact where feasible)."""
    _ensure_state()
    ss = st.session_state
    game: AvoidleGame = ss.game
    az = A.analyzer_for(ss.lang, game.word_length)
    step = 2 if ss.mode == "duel" else 1   # skip bot rows in duel
    ss.review = [
        A.rate_move(az, t.guess, game.pool_before(i), game.secret,
                    rng=random.Random(f"{game.secret}:{i}"), sample_size=400,
                    actual_retained=len(game.pool_before(i + 1)))
        for i, t in list(enumerate(game.history))[::step]
    ]
    ss.duel_read = _duel_recursive_read(game) if ss.mode == "duel" else None


def _duel_recursive_read(game: AvoidleGame) -> str | None:
    """Backward-induction debrief: the earliest of YOUR moves from which
    the game was a provable forced win, per the recursive solver."""
    from avoidle.endgame import forced_win_plies
    for i in range(0, len(game.history), 2):        # player rows only
        plies = forced_win_plies(game.pool_before(i), game.secret)
        if plies is not None:
            return (f"♟️ Recursive read: from move {i // 2 + 1} the duel was "
                    f"a **forced win** — optimal play corners the bot in "
                    f"{plies // 2} of your move(s).")
    return None


def _reseed_daily_rng(facility: str) -> None:
    """Daily games must give every player identical hints/peeks/randoms,
    regardless of the order they use them in."""
    ss = st.session_state
    if ss.mode == "daily":
        # daily_key was pinned at game creation: stable across midnight
        ss.game.rng.seed(f"daily:{ss.get('daily_key')}"
                         f":{facility}:{ss.game.guesses_made}")


@_safe
def act_hint() -> None:
    _ensure_state()
    ss = st.session_state
    _reseed_daily_rng("hint")
    game: AvoidleGame = ss.game
    az = A.analyzer_for(ss.lang, game.word_length)

    def smart(safe, rng):  # safest sampled word, not just any safe word
        return A.best_safe_hint(az, game.remaining_words, game.secret, rng)

    h = game.hint(chooser=smart)
    if h:
        ss.hint_word = h
        ss.message = ("ok", "💡 The oracle whispers a *good* safe word — "
                            "it keeps your options wide open.")
    else:
        ss.message = ("error", "No hint available.")


@_safe
def act_peek() -> None:
    _ensure_state()
    ss = st.session_state
    _reseed_daily_rng("peek")
    sample = ss.game.peek()
    if sample:
        ss.peek_words = sample
        ss.message = ("warn", f"👁️ Peek: {len(sample)} of the remaining "
                              "words — the hidden word might be among them!")
    else:
        ss.message = ("error", "No peek available.")


# ----------------------------------------------------------------------
# Stats backup / restore
# ----------------------------------------------------------------------
STAT_KEYS = ("played", "survived", "streak", "best_streak", "best_score")


def export_stats_json(compact: bool = False) -> str:
    ss = st.session_state
    payload = {"app": "avoidle", "version": __version__,
               "stats": ss.stats, "survival_best": ss.survival_best,
               "xp": ss.xp,
               "achievements": sorted(ss.achievements),
               "daily_streaks": ss.daily_streaks,
               "daily_done": sorted(ss.daily_done),
               "daily_win_dates": sorted(ss.daily_win_dates)}
    if compact:
        return json.dumps(payload, separators=(",", ":"))
    return json.dumps(payload, indent=2)


def _recent(dated_keys: set, days: int) -> list:
    """Keep only entries whose date part is within the last ``days``."""
    floor = (datetime.date.today()
             - datetime.timedelta(days=days)).isoformat()
    return sorted(k for k in dated_keys if k.split(":")[0] >= floor)


def encode_progress() -> str:
    """Progress as a cookie-safe token (zlib + url-safe base64).
    Daily history is pruned to what the app actually needs (today's
    replay guard + the 28-day heatmap window) so the token stays well
    under the 4 KB cookie ceiling for years; the downloadable backup
    file keeps the full history."""
    ss = st.session_state
    payload = {"app": "avoidle", "version": __version__,
               "stats": ss.stats, "survival_best": ss.survival_best,
               "xp": ss.xp,
               "achievements": sorted(ss.achievements),
               "daily_streaks": ss.daily_streaks,
               "daily_done": _recent(ss.daily_done, 30),
               "daily_win_dates": _recent(ss.daily_win_dates, 56)}
    raw = json.dumps(payload, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(zlib.compress(raw, 9)).decode()


def decode_progress(token: str) -> dict | None:
    """Token -> validated payload (None on any tampering/corruption).
    Decompression is hard-capped at 1 MB via decompressobj — a zlib
    bomb stops mid-stream instead of ballooning into memory."""
    try:
        data = base64.urlsafe_b64decode(token.encode())
        d = zlib.decompressobj()
        raw = d.decompress(data, 1 << 20)
        if d.unconsumed_tail:   # output exceeded the cap: reject
            return None
    except Exception:
        return None
    return parse_stats_json(raw.decode("utf-8", errors="replace"))


def apply_progress(payload: dict) -> None:
    """Load a validated payload into the session (file or cookie)."""
    ss = st.session_state
    ss.stats = payload["stats"]
    ss.survival_best = payload["survival_best"]
    ss.xp = payload["xp"]
    ss.achievements = payload["achievements"]
    ss.daily_streaks = payload["daily_streaks"]
    ss.daily_done = payload["daily_done"]
    ss.daily_win_dates = payload["daily_win_dates"]
    ss.wins_langs, ss.wins_lengths = derive_session_wins(payload["stats"])


def save_progress_cookie() -> None:
    """Persist progress in the browser (1-year cookie, ~0.5 KB).
    Rendered as a zero-height component; runs once per change."""
    token = encode_progress()
    if len(token) > 3800:   # stay under the 4 KB cookie ceiling
        return
    try:
        # components.html is deprecated but its replacement (st.iframe)
        # cannot run inline scripts on the app origin; if a future
        # Streamlit removes it, persistence degrades gracefully instead
        # of crashing (the backup file always works).
        components.html(
            f"<script>document.cookie = '{PROGRESS_COOKIE}={token}; "
            "max-age=31536000; path=/; SameSite=Lax';</script>",
            height=0)
    except Exception:
        pass


def restore_progress_from_cookie() -> bool:
    """On a brand-new session, pull progress back from the cookie."""
    try:
        token = st.context.cookies.get(PROGRESS_COOKIE)
    except Exception:
        return False
    if not token:
        return False
    payload = decode_progress(token)
    if not payload:
        return False
    apply_progress(payload)
    return True


PROGRESS_COOKIE = "dw_progress"

NUM_CAP = 10**9  # ceiling for every numeric backup field


def _num(value, cap: int = NUM_CAP) -> int:
    """Clamp any user-supplied number: JSON big-ints are arbitrary
    precision in Python and would overflow float math downstream."""
    return min(max(0, int(value)), cap)


def parse_stats_json(text: str) -> dict | None:
    """Validate an exported stats file. Returns clean payload or None."""
    def valid_key(key: str) -> str | None:
        parts = key.split(":")
        if len(parts) > 3:
            return None
        # legacy exports: "mode" (≤1.3, English only) or "mode:lang" (1.4.0)
        mode = parts[0]
        lang = parts[1] if len(parts) > 1 else "en"
        length = parts[2] if len(parts) > 2 else "5"
        if (mode in MODES.values() and lang in W.LANGUAGES
                and length.isdigit() and int(length) in W.WORD_LENGTHS):
            return f"{mode}:{lang}:{int(length)}"
        return None

    try:
        data = json.loads(text)
        clean: dict[str, dict] = {}
        for key, s in data["stats"].items():
            norm = valid_key(key)
            if not norm or not isinstance(s, dict):
                continue
            incoming = {k: _num(s.get(k, 0)) for k in STAT_KEYS}
            if norm in clean:  # legacy + new key collided: keep the best
                incoming = {k: max(incoming[k], clean[norm][k])
                            for k in STAT_KEYS}
            clean[norm] = incoming
        achievements = {a for a in data.get("achievements", [])
                        if isinstance(a, str) and a in ACH.ACHIEVEMENTS}
        streaks = {}
        for key, e in (data.get("daily_streaks") or {}).items():
            lang, _, length = str(key).partition(":")
            if (lang in W.LANGUAGES and length.isdigit()
                    and int(length) in W.WORD_LENGTHS
                    and isinstance(e, dict)):
                streaks[f"{lang}:{int(length)}"] = {
                    "last": str(e.get("last", "")),
                    "streak": _num(e.get("streak", 0))}
        done = set()
        for key in data.get("daily_done", []):
            date_s, _, rest = str(key).partition(":")
            lang, _, length = rest.partition(":")
            try:
                datetime.date.fromisoformat(date_s)
            except ValueError:
                continue
            if (lang in W.LANGUAGES and length.isdigit()
                    and int(length) in W.WORD_LENGTHS and len(done) < 5000):
                done.add(f"{date_s}:{lang}:{int(length)}")
        win_dates = set()
        for key in data.get("daily_win_dates", []):
            date_s, _, rest = str(key).partition(":")
            lang, _, length = rest.partition(":")
            try:
                datetime.date.fromisoformat(date_s)
            except ValueError:
                continue
            if (lang in W.LANGUAGES and length.isdigit()
                    and int(length) in W.WORD_LENGTHS
                    and len(win_dates) < 5000):
                win_dates.add(f"{date_s}:{lang}:{int(length)}")
        return {"stats": clean,
                "survival_best": _num(data.get("survival_best", 0)),
                "xp": _num(data.get("xp", 0), ACH.XP_CAP),
                "achievements": achievements,
                "daily_streaks": streaks,
                "daily_done": done,
                "daily_win_dates": win_dates}
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
        return None


def derive_session_wins(stats: dict) -> tuple[set, set]:
    """Languages and lengths with at least one win, from stats keys."""
    langs, lengths = set(), set()
    for key, s in stats.items():
        if s.get("survived", 0) > 0:
            _, lang, length = key.split(":")
            langs.add(lang)
            lengths.add(int(length))
    return langs, lengths


def fmt(n: int) -> str:
    """Counter label; huge budgets render as infinity."""
    return "∞" if n >= UNLIMITED // 2 else str(n)


# ----------------------------------------------------------------------
# Rendering
# ----------------------------------------------------------------------
TILE_COLORS = {GREEN: "#538d4e", YELLOW: "#b59f3b", GRAY: "#3a3a3c"}

CSS = """
<style>
/* Windows ships no flag emojis (Chrome/Edge show bare country codes
   like "GB DE"). This web font supplies ONLY the regional-indicator
   codepoints (unicode-range), so every other character falls through
   to the normal fonts — icons and text are unaffected. */
@font-face {
  font-family: "Twemoji Country Flags";
  src: url("https://cdn.jsdelivr.net/npm/country-flag-emoji-polyfill@0.1.8/dist/TwemojiCountryFlags.woff2") format("woff2");
  unicode-range: U+1F1E6-1F1FF, U+1F3F4, U+E0062-E0063, U+E0065, U+E0067,
                 U+E006C, U+E006E, U+E0073-E0074, U+E0077, U+E007F;
  font-display: swap;
}
/* Sans text elements get the flag font FIRST in the stack — it only
   claims flag codepoints (unicode-range), everything else falls through
   to the app's normal sans font. Never list a monospace fallback here:
   Streamlit preloads Source Code Pro, and a wrong fallback order turns
   the whole UI into typewriter text. */
[data-baseweb="select"] div, [role="listbox"] li, [role="option"],
[data-testid="stMarkdownContainer"] p, [data-testid="stMarkdownContainer"] li,
[data-testid="stWidgetLabel"] p, [data-testid="stCaptionContainer"] p,
.dw-banner, .dw-footer {
  font-family: "Twemoji Country Flags", "Source Sans", "Source Sans Pro",
               "Source Sans 3", sans-serif;
}
pre, code {
  font-family: "Twemoji Country Flags", "Source Code Pro", monospace;
}
/* rules popover: a tiny centered chip under the header */
.st-key-rulesbar {margin:0;}
.st-key-rulesbar [data-testid="stHorizontalBlock"] {
  flex-wrap: nowrap !important; align-items: center;
}
.st-key-rulesbar [data-testid="stColumn"] {min-width: 0 !important;}
.st-key-rulesbar [data-testid="stColumn"]:last-child {
  display:flex; justify-content:flex-end;
}
.st-key-rulesbar [data-testid="stPopover"] {width:auto;}
.st-key-rulesbar .dw-banner {text-align:center; margin:0;}
.st-key-rulesbar [data-testid="stPopover"] button {
  font-size: 0.78rem;
  padding: 0.05rem 0.6rem;
  min-height: 1.6rem;
  border-radius: 999px;
  opacity: 0.85;
}
/* daily-wins heatmap: 4 weeks x 7 days */
.dw-heat {display:grid; grid-template-columns:repeat(7, 14px); gap:3px;
          justify-content:center; margin:4px 0 2px 0;}
.dw-heat div {width:14px; height:14px; border-radius:3px;
              background:#262628;}
.dw-heat .win {background:#538d4e;}
.dw-heat .today {outline:1.5px solid #b59f3b;}
.dw-heat-lab {text-align:center; font-size:0.72rem; opacity:0.7;
              letter-spacing:0.08em; text-transform:uppercase;}
/* sidebar stats: one tidy line instead of cramped metric tiles */
.dw-mini-stats {display:flex; justify-content:space-between; gap:8px;
                font-size:0.78rem; opacity:0.9; margin:2px 0 4px 0;}
.dw-mini-stats span {white-space:nowrap;}
.dw-mini-stats b {font-size:0.95rem;}
/* sidebar: tighter vertical rhythm */
section[data-testid="stSidebar"] [data-testid="stVerticalBlock"] {
  gap: 0.65rem;
}
section[data-testid="stSidebar"] h1 {
  font-size: 1.45rem; padding-bottom: 0;
}
/* one calm status zone under the keyboard */
.dw-status {max-width: 520px; margin: 6px auto 0 auto; padding: 5px 14px;
            border-radius: 8px; font-size: 0.85rem; text-align: center;
            border: 1px solid transparent;}
.dw-status.ok    {background: rgba(120,130,140,0.10);
                  border-color: rgba(120,130,140,0.25);}
.dw-status.win   {background: rgba(83,141,78,0.14);
                  border-color: rgba(83,141,78,0.40);}
.dw-status.warn  {background: rgba(181,159,59,0.12);
                  border-color: rgba(181,159,59,0.38);}
.dw-status.error, .dw-status.loss
                 {background: rgba(192,75,75,0.12);
                  border-color: rgba(192,75,75,0.40);}
.dw-substatus {text-align:center; font-size:0.73rem; opacity:0.55;
               margin-top:3px;}
.dw-think span {animation: dw-blink 1.2s infinite;}
.dw-think span:nth-child(2) {animation-delay: .2s;}
.dw-think span:nth-child(3) {animation-delay: .4s;}
@keyframes dw-blink {0%,100% {opacity:0.15;} 50% {opacity:1;}}
.st-key-fatebar {max-width: 420px; margin: 2px auto 0 auto;}
/* feedback alerts: compact single-line text */
[data-testid="stAlert"] [data-testid="stMarkdownContainer"] p {
  font-size: 0.88rem;
  line-height: 1.35;
}
.block-container {max-width: 760px; padding-top: 3.6rem;
                  padding-bottom: 1rem;}
/* tighter rhythm between main-page elements so board + keyboard fit
   one laptop screen without scrolling */
.block-container > div > [data-testid="stVerticalBlock"] {gap: 0.45rem;}
.dw-header {text-align:center; margin:0;}
/* the Avoidle wordmark: game tiles spelling the name — AVOID on dark
   slate, LE on brand green, a thin red "do not cross" bar beneath */
.dw-logo {display:inline-flex; gap:4px;}
.dw-logo .lt {width:29px; height:29px; display:flex; align-items:center;
              justify-content:center; border-radius:5px; font-weight:800;
              font-size:1.05rem; color:#fff;
              font-family:'Helvetica Neue',Arial,sans-serif;
              box-shadow:0 2px 5px rgba(0,0,0,0.45),
                         inset 0 1px 0 rgba(255,255,255,0.07);}
.dw-logo .lt.d {background:linear-gradient(180deg,#3f3f42,#2e2e30);}
.dw-logo .lt.g {background:linear-gradient(180deg,#62a35b,#4a7f44);}
.dw-logo-bar {width:152px; height:2px; margin:3px auto 1px auto;
              border-radius:2px;
              background:linear-gradient(90deg,transparent,#e74c3c 18%,
                                         #e74c3c 82%,transparent);}
.dw-header p {margin:0; opacity:0.55; font-size:0.68rem;
              letter-spacing:0.24em; text-transform:uppercase;}
.dw-banner {text-align:center; font-weight:700; font-size:1.0rem;
            margin:0 0 2px 0;}
.dw-banner .sub {opacity:0.7; font-weight:400; font-size:0.9rem;}
.dw-board {display:flex; flex-direction:column; gap:5px; align-items:center;
           margin: 2px 0 2px 0;}
.dw-row {display:flex; gap:5px;}
.dw-tile {width:44px; height:44px; display:flex; align-items:center;
          justify-content:center; font-size:1.45rem; font-weight:800;
          color:#fff; text-transform:uppercase; border-radius:6px;
          font-family:'Helvetica Neue',Arial,sans-serif;
          box-shadow:0 2px 6px rgba(0,0,0,0.35);}
.dw-empty {background:transparent; border:2px solid #3a3a3c;
           box-shadow:none;}
.dw-active {border-color:#5a5a5c; box-shadow:0 0 8px rgba(255,255,255,0.07);}
.dw-row.dw-reveal .dw-tile {animation: dw-flip .5s ease both;}
.dw-row.dw-reveal .dw-tile:nth-child(2) {animation-delay:.10s;}
.dw-row.dw-reveal .dw-tile:nth-child(3) {animation-delay:.20s;}
.dw-row.dw-reveal .dw-tile:nth-child(4) {animation-delay:.30s;}
.dw-row.dw-reveal .dw-tile:nth-child(5) {animation-delay:.40s;}
.dw-row.dw-reveal .dw-tile:nth-child(6) {animation-delay:.50s;}
@keyframes dw-flip {
  0%   {transform:rotateX(90deg); opacity:0.2;}
  100% {transform:rotateX(0deg); opacity:1;}
}
.dw-board.dw-shake {animation: dw-shake .4s ease;}
.dw-more {font-size:0.68rem; opacity:0.38; letter-spacing:0.06em;
          margin-top:2px;}
.dw-row.dw-bot {position: relative; opacity: 0.92;}
.dw-row.dw-bot::after {content: "👾"; position: absolute; right: -26px;
                       top: 50%; transform: translateY(-50%);
                       font-size: 0.85rem;}
@keyframes dw-shake {
  20% {transform:translateX(-7px);} 40% {transform:translateX(7px);}
  60% {transform:translateX(-4px);} 80% {transform:translateX(4px);}
}
.dw-kbd {display:flex; flex-direction:column; gap:5px; align-items:center;
         margin-top:8px;}
.dw-krow {display:flex; gap:4px;}
.dw-key {min-width:28px; height:38px; padding:0 5px; display:flex;
         align-items:center; justify-content:center; border-radius:5px;
         font-weight:700; font-size:0.95rem; color:#fff;
         background:#818384; text-transform:uppercase;
         box-shadow:0 1.5px 0 rgba(0,0,0,0.4);}
.dw-counts {display:flex; justify-content:center; gap:38px;
            text-align:center; font-weight:700; margin:0 0 2px 0;}
.dw-counts .lab {font-size:0.62rem; letter-spacing:0.09em; opacity:0.55;
                 text-transform:uppercase;}
.dw-counts .num {font-size:1.45rem; line-height:1.1;}
.dw-bar {height:5px; border-radius:3px; background:#262628;
         margin:0 auto 0 auto; max-width:300px; overflow:hidden;}
.dw-bar .dw-fill {height:100%; border-radius:4px;
                  transition:width .5s ease;}
.dw-trapped {animation: dw-pulse 1s ease infinite;}
@keyframes dw-pulse {50% {opacity:0.45;}}
.dw-footer {text-align:center; opacity:0.7; font-size:0.8rem;
            margin-top:28px;}
@media (max-width: 480px) {
  .dw-tile {width:38px; height:38px; font-size:1.25rem;}
  .dw-row {gap:4px;}
  .dw-key {min-width:24px; height:34px; font-size:0.85rem;}
  .dw-logo .lt {width:27px; height:27px; font-size:1.0rem;}
  .dw-logo-bar {width:142px;}
  .dw-header p {display:none;}   /* tagline: declutter small screens */
  .dw-banner {font-size:0.92rem; margin:0 0 4px 0;}
  .dw-counts {gap:22px;}
  .dw-counts .num {font-size:1.5rem;}
  .st-key-abilities .stButton > button {font-size:0.72rem;}
}
@media (max-width: 380px) {
  .dw-tile {width:38px; height:38px; font-size:1.2rem;}
}
/* Clickable keyboard: Streamlit stacks columns vertically on phones,
   which exploded the keyboard into 26 full-width rows. Force each
   keyboard row to stay a single horizontal flex line — and keep the
   whole keyboard compact and centered like a phone keyboard rather
   than sprawling across the desktop page. */
.st-key-clickkbd {max-width: 580px; margin: 0 auto;}
.st-key-clickkbd [data-testid="stVerticalBlock"] {gap: 0.22rem !important;}
.st-key-clickkbd [data-testid="stHorizontalBlock"] {
  flex-wrap: nowrap !important;
  gap: 5px !important;
  justify-content: center;   /* shorter rows center like a real keyboard */
  margin-bottom: 0;
}
.st-key-clickkbd [data-testid="stColumn"] {
  min-width: 0 !important;
  flex: 0 0 42px !important;  /* constant key size on every row */
  width: 42px !important;
}
.st-key-clickkbd .stButton > button {
  width: 42px !important;
  min-width: 0 !important;
  height: 2.3rem;
  min-height: 2.3rem;
  padding: 0 !important;
  font-weight: 600;
  font-size: 0.95rem;
  border-radius: 6px;
  text-transform: uppercase;
}
@media (max-width: 480px) {
  .st-key-clickkbd [data-testid="stColumn"] {
    flex: 0 0 7.6vw !important;
    width: 7.6vw !important;
  }
  .st-key-clickkbd .stButton > button {
    width: 7.6vw !important;
    height: 2.55rem;       /* thumb-sized on actual phones */
    min-height: 2.55rem;
    font-size: 0.9rem;
  }
}
/* ability buttons: one compact centered row, not a tall stack */
.st-key-abilities {max-width: 540px; margin: 0 auto;}
.st-key-abilities [data-testid="stHorizontalBlock"] {
  flex-wrap: nowrap !important;
  gap: 0.25rem !important;
}
.st-key-abilities [data-testid="stHorizontalBlock"] {justify-content:center;}
.st-key-abilities [data-testid="stColumn"] {
  min-width: 0 !important;
  flex: 0 1 170px !important;   /* lone buttons stay button-sized */
}
.st-key-abilities .stButton > button {
  width: 100% !important;
  min-width: 0 !important;
  padding: 0.25rem 0.1rem !important;
  font-size: 0.85rem;
  white-space: nowrap;
  min-height: 2.3rem;   /* same line weight as the keyboard keys */
}
/* keep the guess box and its button side by side on phones too */
.st-key-guessrow [data-testid="stHorizontalBlock"] {
  flex-wrap: nowrap !important;
}
.st-key-guessrow [data-testid="stColumn"] {
  min-width: 0 !important;
  flex: 1 1 0% !important;
}
.st-key-guessrow [data-testid="stColumn"]:last-child {
  flex: 0 0 5.5rem !important;
}
</style>
"""

HEADER = """
<div class="dw-header">
  <div class="dw-logo" role="img" aria-label="Avoidle">
    <span class="lt d">A</span><span class="lt d">V</span><span class="lt d">O</span><span class="lt d">I</span><span class="lt d">D</span><span class="lt g">L</span><span class="lt g">E</span>
  </div>
  <div class="dw-logo-bar"></div>
  <p>guess words — never the word</p>
</div>
"""


def render_board(game: AvoidleGame, buffer: str = "",
                 animate_last: bool = False, shake: bool = False,
                 duel: bool = False) -> str:
    rows = []
    last = len(game.history) - 1
    width = game.word_length
    for i, turn in enumerate(game.history):
        tiles = "".join(
            f'<div class="dw-tile" style="background:{TILE_COLORS[c]}">{l}</div>'
            for l, c in zip(turn.guess, turn.feedback)
        )
        cls = "dw-row dw-reveal" if (animate_last and i == last) else "dw-row"
        if duel and i % 2 == 1:
            cls += " dw-bot"
        rows.append(f'<div class="{cls}">{tiles}</div>')
    # duel boards are 12 rows deep — grow as played instead of pushing
    # the keyboard below the fold with a wall of empty tiles
    empty_to_show = min(game.guesses_left, 2) if duel else game.guesses_left
    for j in range(empty_to_show):
        cells = []
        for k in range(width):
            letter = buffer[k] if j == 0 and k < len(buffer) else ""
            cls = "dw-tile dw-empty" + (" dw-active" if j == 0 else "")
            cells.append(f'<div class="{cls}">{letter}</div>')
        rows.append(f'<div class="dw-row">{"".join(cells)}</div>')
    hidden = game.guesses_left - empty_to_show
    if hidden > 0:
        rows.append(f'<div class="dw-more">+ {hidden} rows in reserve</div>')
    board_cls = "dw-board dw-shake" if shake else "dw-board"
    return f'<div class="{board_cls}">{"".join(rows)}</div>'


def letter_knowledge(game: AvoidleGame) -> dict[str, str]:
    """Best-known status per letter: G > Y > gray(eliminated)."""
    rank = {GREEN: 3, YELLOW: 2, GRAY: 1}
    know: dict[str, str] = {}
    for turn in game.history:
        for l, c in zip(turn.guess, turn.feedback):
            if l not in know or rank[c] > rank[know[l]]:
                know[l] = c
    return know


def render_keyboard(game: AvoidleGame, lang: str) -> str:
    know = letter_knowledge(game)
    colors = {GREEN: "#538d4e", YELLOW: "#b59f3b", GRAY: "#2c2c2e"}
    rows_html = []
    for row in W.KEYBOARDS[lang]:
        keys = []
        for l in row:
            style = ""
            if l in know:
                extra = "opacity:0.45;" if know[l] == GRAY else ""
                style = f'style="background:{colors[know[l]]};{extra}"'
            keys.append(f'<div class="dw-key" {style}>{l}</div>')
        rows_html.append(f'<div class="dw-krow">{"".join(keys)}</div>')
    return f'<div class="dw-kbd">{"".join(rows_html)}</div>'


def render_meter(game: AvoidleGame) -> str:
    import math
    n = game.remaining_count
    total = len(game.dictionary)
    if game.is_trapped:
        color, label = "#e74c3c", "TRAPPED — only the hidden word remains!"
    elif n <= 20:
        color, label = "#e74c3c", "extreme danger"
    elif n <= 150:
        color, label = "#e67e22", "danger zone"
    elif n <= 1500:
        color, label = "#f1c40f", "getting risky"
    else:
        color, label = "#6aaa64", "plenty of room"
    # log scale: the pool collapses by orders of magnitude, not linearly
    pct = max(2.0, 100 * math.log(max(n, 1) + 1) / math.log(total + 1))
    danger_cls = "lab dw-trapped" if game.is_trapped else "lab"
    return (f'<div class="dw-counts">'
            f'<div><div class="lab">Valid words remaining</div>'
            f'<div class="num" style="color:{color}">{n:,}</div>'
            f'<div class="{danger_cls}" style="color:{color}">{label}</div></div>'
            f'<div><div class="lab">Undos remaining</div>'
            f'<div class="num">{fmt(game.undos_left)}</div>'
            f'<div class="lab">guesses left: {game.guesses_left}</div></div>'
            f'</div>'
            f'<div class="dw-bar"><div class="dw-fill" '
            f'style="width:{pct:.1f}%;background:{color}"></div></div>')


def render_click_keyboard(game: AvoidleGame, lang: str) -> None:
    """Clickable on-screen keyboard (st.buttons). Letters keep their clue
    color knowledge: eliminated letters are disabled, known letters green.
    Wrapped in a keyed container so CSS can pin rows horizontal on phones."""
    know = letter_knowledge(game)
    with st.container(key="clickkbd"):
        for r, row in enumerate(W.KEYBOARDS[lang]):
            extras = 2 if r == len(W.KEYBOARDS[lang]) - 1 else 0
            cols = st.columns(len(row) + extras, gap="small")
            offset = 0
            if extras:
                cols[0].button("⏎", key="kbd_enter", on_click=act_kbd_enter,
                               type="primary", width="stretch",
                               disabled=game.is_over,
                               help="Submit the word")
                offset = 1
            for i, letter in enumerate(row):
                status = know.get(letter)
                cols[i + offset].button(
                    letter.upper(), key=f"kbd_{letter}",
                    on_click=act_key, args=(letter,),
                    type="primary" if status in (GREEN, YELLOW)
                    else "secondary",
                    disabled=game.is_over or status == GRAY,
                    width="stretch")
            if extras:
                cols[-1].button("⌫", key="kbd_back", on_click=act_backspace,
                                width="stretch", disabled=game.is_over)


def render_streak_heatmap() -> str:
    """GitHub-style 28-day calendar of daily wins for the current
    language & length — the streak you don't want to break."""
    ss = st.session_state
    today = datetime.date.today()
    cells = []
    for offset in range(27, -1, -1):
        day = today - datetime.timedelta(days=offset)
        key = f"{day.isoformat()}:{ss.lang}:{ss.word_len}"
        cls = "win" if key in ss.daily_win_dates else ""
        if day == today:
            cls += " today"
        cells.append(f'<div class="{cls.strip()}" title="{day}"></div>')
    wins = sum("win" in c for c in cells)
    return (f'<div class="dw-heat-lab">daily wins · last 4 weeks '
            f'({wins}/28)</div><div class="dw-heat">{"".join(cells)}</div>')


def show_message() -> None:
    """In-game feedback as one compact, centered line — full-width alert
    boxes are reserved for the end-of-game panel."""
    msg = st.session_state.message
    if not msg:
        return
    kind, text = msg
    # the end-of-game panel already announces wins/losses
    if st.session_state.game.is_over and kind in ("win", "loss"):
        return
    if kind not in ("ok", "warn", "error", "win", "loss"):
        kind = "ok"
    html = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", str(text))
    st.markdown(f'<div class="dw-status {kind}">{html}</div>',
                unsafe_allow_html=True)


TRAP_FORECAST_LIMIT = 30


def trap_forecast(game: AvoidleGame) -> tuple[int, int] | None:
    """In the endgame, count how many playable words lead straight into a
    trap (their feedback would leave only the secret playable). Cheap to
    compute exactly once the pool is small. Returns (traps, safe_options)
    or None when not applicable."""
    ss = st.session_state
    safe = game.safe_words()
    if (game.is_over or not safe
            or game.guesses_left < 2  # last row: any safe word wins anyway
            or game.remaining_count > TRAP_FORECAST_LIMIT):
        return None
    az = A.analyzer_for(ss.lang, game.word_length)
    retained = az.retained_counts(safe, game.remaining_words, game.secret)
    traps = int((retained == 1).sum())
    return traps, len(safe)


def next_daily_in() -> str:
    """Human countdown to the next daily word (local midnight)."""
    now = datetime.datetime.now()
    tomorrow = datetime.datetime.combine(
        now.date() + datetime.timedelta(days=1), datetime.time.min)
    secs = int((tomorrow - now).total_seconds())
    return f"{secs // 3600}h {secs % 3600 // 60:02d}m"


def _secret_reveal(game: AvoidleGame) -> str:
    """Post-game reveal: the word plus how common it is — fuel for the
    'was that word likely?' debrief."""
    rank = W.frequency_rank(game.secret, st.session_state.lang,
                            game.word_length)
    total = len(W.answers(st.session_state.lang, game.word_length))
    if rank is None:
        return f"The hidden word was **{game.secret.upper()}**."
    pct = rank / total
    if pct <= 0.10:
        common = "a very common word"
    elif pct <= 0.35:
        common = "a fairly common word"
    elif pct <= 0.70:
        common = "a mid-frequency word"
    else:
        common = "a rare word"
    return (f"The hidden word was **{game.secret.upper()}** — {common} "
            f"(frequency rank #{rank:,} of {total:,}).")


def share_title() -> str:
    ss = st.session_state
    tag = "" if ss.lang == "en" else f" {W.LANGUAGES[ss.lang]}"
    if ss.word_len != 5:
        tag += f" ({ss.word_len} letters)"
    if ss.mode == "daily":
        day = (ss.get("daily_key") or datetime.date.today().isoformat()
               ).split(":")[0]
        return f"Avoidle Daily {day}{tag}"
    if ss.mode == "survival":
        return f"Avoidle Survival R{ss.survival_round}{tag}"
    return f"Avoidle {ss.game.config.label}{tag}"


# ----------------------------------------------------------------------
# Page
# ----------------------------------------------------------------------
def main() -> None:
    st.set_page_config(page_title="Avoidle", page_icon="🚫",
                       layout="centered")
    init_state()
    ss = st.session_state
    game: AvoidleGame = ss.game
    st.markdown(CSS, unsafe_allow_html=True)
    st.markdown(HEADER, unsafe_allow_html=True)

    # ----- sidebar ----------------------------------------------------
    with st.sidebar:
        st.title("🚫 Avoidle")
        st.caption("Whatever you do — don't say the word.")
        lv = ACH.level_for_xp(ss.xp)
        st.progress(lv["into"] / lv["needed"],
                    text=f"⭐ Level {lv['level']} · {lv['title']} · "
                         f"{ss.xp:,} XP")
        langs = list(W.LANGUAGES)
        c1, c2 = st.columns([3, 2])
        c1.selectbox("Language", langs,
                     index=langs.index(ss.lang), key="lang_select",
                     format_func=W.LANGUAGES.get, on_change=act_change_lang,
                     help="Word lists change; the interface stays English. "
                          "Changing language starts a fresh game.")
        lengths = list(W.WORD_LENGTHS)
        c2.selectbox("Letters", lengths,
                     index=lengths.index(ss.word_len), key="len_select",
                     on_change=act_change_len,
                     help="Word length: 4 = casual, 5 = classic, "
                          "6 = expert. Changing it starts a fresh game.")
        st.radio("Input method", ["🔠 Clickable letters", "⌨️ Typing"],
                 index=0 if ss.input_mode == "click" else 1,
                 key="input_select", on_change=act_change_input,
                 horizontal=True)
        labels = list(MODES)
        current = next(k for k, v in MODES.items() if v == ss.mode)
        st.radio("Game mode", labels, index=labels.index(current),
                 key="mode_label", on_change=act_change_mode,
                 help="Changing mode starts a fresh game.")
        st.caption(MODE_HELP[ss.mode])
        if ss.mode == "duel":
            levels = list(BOT.BOT_LEVELS)
            st.selectbox("Bot strength", levels,
                         index=levels.index(ss.bot_level), key="bot_select",
                         format_func=lambda k: BOT.BOT_LEVELS[k],
                         on_change=act_change_bot,
                         help="Hard solves the endgame by backward "
                              "induction (it reasons several moves ahead); "
                              "tougher bots pay a bigger multiplier.")
        st.button("🔄 New game", on_click=act_new_game, width="stretch")
        # retention nudge: today's daily for this combo is still unplayed
        today_key = (f"{datetime.date.today().isoformat()}:"
                     f"{ss.lang}:{ss.word_len}")
        if ss.mode != "daily" and today_key not in ss.daily_done:
            streak = ss.daily_streaks.get(
                f"{ss.lang}:{ss.word_len}", {}).get("streak", 0)
            if streak >= 1:
                st.warning(f"🔥 Your {streak}-day daily streak is on the "
                           "line — today's word is waiting!")
            else:
                st.caption("📅 Today's daily word is still waiting for you.")

        st.divider()
        st.subheader("📊 Your stats")
        stats = ss.stats.get(
            f"{ss.mode}:{ss.lang}:{ss.word_len}",
            {"played": 0, "survived": 0, "streak": 0,
             "best_streak": 0, "best_score": 0})
        rate = (stats["survived"] / stats["played"] * 100
                if stats["played"] else 0)
        st.markdown(
            f'<div class="dw-mini-stats">'
            f'<span><b>{stats["played"]}</b> played</span>'
            f'<span><b>{rate:.0f}%</b> wins</span>'
            f'<span><b>{stats["streak"]}</b> streak</span>'
            f'<span><b>{stats["best_score"]}</b> best</span></div>',
            unsafe_allow_html=True)
        st.markdown(render_streak_heatmap(), unsafe_allow_html=True)
        if ss.mode == "survival":
            st.metric("Best survival run", ss.survival_best)

        never_played = not any(s["played"] for s in ss.stats.values())
        with st.expander("📖 How to play", expanded=never_played):
            st.markdown(HOW_TO_MD)

        if ss.session_log:
            wins = sum(e["won"] for e in ss.session_log)
            with st.expander(f"🕑 This session ({wins}/"
                             f"{len(ss.session_log)} survived)"):
                label_of = {v: k for k, v in MODES.items()}
                for e in reversed(ss.session_log[-8:]):
                    icon = "✅" if e["won"] else "💀"
                    st.caption(f"{icon} {label_of[e['mode']]} · "
                               f"{e['lang']}·{e['len']} — "
                               f"{e['score']} pts")

        n_unlocked = len(ss.achievements)
        with st.expander(f"🏆 Trophy case ({n_unlocked}/"
                         f"{len(ACH.ACHIEVEMENTS)})"):
            for ach, _ in ACH.ACHIEVEMENTS.values():
                if ach.id in ss.achievements:
                    st.markdown(f"{ach.emoji} **{ach.name}** — "
                                f"{ach.description}")
                else:
                    st.caption(f"🔒 {ach.name} — {ach.description}")

        with st.expander("💾 Backup stats"):
            st.caption("Stats live in this browser session. Download them "
                       "to keep, re-upload to restore.")
            st.download_button("⬇️ Download stats", export_stats_json(),
                               file_name="avoidle_stats.json",
                               mime="application/json", width="stretch")
            up = st.file_uploader("Restore from file", type="json",
                                  key="stats_upload")
            if up is not None:
                content = up.getvalue().decode("utf-8", errors="replace")
                token = hash(content)
                if ss.get("stats_upload_token") != token:
                    ss.stats_upload_token = token  # import each file once
                    payload = parse_stats_json(content)
                    if payload:
                        apply_progress(payload)
                        ss.progress_dirty = True
                        st.success("Stats restored!")
                    else:
                        st.error("That doesn't look like a stats file.")
                else:
                    st.caption("✓ This backup is already loaded.")

        st.divider()
        st.markdown(
            f'<div class="dw-footer">v{__version__} · built by '
            f'<a href="{__homepage__}" target="_blank">Dr. Eugen Dimant</a>'
            "</div>",
            unsafe_allow_html=True,
        )

    # ----- top bar: rules chip + mode banner share one compact row ----
    with st.container(key="rulesbar"):
        c_left, c_banner, c_rules = st.columns([1.4, 7.2, 1.4])
        with c_rules:
            with st.popover("❓ Rules"):
                st.markdown(HOW_TO_MD)
    # ----- header / survival banner (centered like everything else) ----
    if ss.mode == "survival":
        c_banner.markdown(
            f'<div class="dw-banner">⚔️ Round {ss.survival_round} · '
            f'run score {ss.survival_total} <span class="sub">· '
            f'{game.config.max_undos} undo(s) this round</span></div>',
            unsafe_allow_html=True)
    elif ss.mode == "duel" and not game.is_over:
        level_icon = BOT.BOT_LEVELS[ss.bot_level].split(" ")[0]
        c_banner.markdown(f'<div class="dw-banner">🆚 Duel vs {level_icon} '
                    f'{ss.bot_level.title()} <span class="sub">— whoever '
                    f'says the word loses</span></div>',
                    unsafe_allow_html=True)
    elif ss.mode == "daily":
        streak = ss.daily_streaks.get(
            f"{ss.lang}:{ss.word_len}", {}).get("streak", 0)
        parts = [f'📅 Daily <span class="sub">'
                 f'{datetime.date.today():%b %d}</span>']
        if streak >= 2:
            parts.append(f'<span class="sub">🔥 {streak}-day streak</span>')
        if not game.is_over:
            # use the date pinned at game creation so the banner and the
            # award agree even across midnight
            quest_date = (ss.get("daily_key")
                          or datetime.date.today().isoformat()).split(":")[0]
            quest = ACH.daily_quest(quest_date, ss.lang, ss.word_len)
            parts.append(f'<span class="sub">🎯 {quest.label} '
                         f'(+{quest.xp} XP)</span>')
        c_banner.markdown(f'<div class="dw-banner">{" · ".join(parts)}</div>',
                          unsafe_allow_html=True)

    st.markdown(render_meter(game), unsafe_allow_html=True)
    buffer = ss.kbd_buffer if ss.input_mode == "click" else ""
    st.markdown(render_board(game, buffer=buffer,
                             animate_last=ss.last_action == "guess",
                             shake=ss.last_action == "error",
                             duel=ss.mode == "duel"),
                unsafe_allow_html=True)
    if ss.get("bot_pending") and ss.mode == "duel" and not game.is_over:
        # the player's row just rendered above; give the bot a visible
        # moment to "think", then let it reply and rerun
        from avoidle.endgame import MAX_SOLVE_POOL
        deep = (ss.bot_level == "hard"
                and game.remaining_count <= MAX_SOLVE_POOL)
        verb = "solving the endgame" if deep else "thinking"
        st.markdown(f'<div class="dw-status ok dw-think">👾 {verb}'
                    '<span>.</span><span>.</span><span>.</span></div>',
                    unsafe_allow_html=True)
        time.sleep(0.7 if deep else 0.5)
        ss.bot_pending = False
        _bot_reply()
        st.rerun()

    if ss.input_mode == "click":
        if not game.is_over:
            render_click_keyboard(game, ss.lang)
    else:
        st.markdown(render_keyboard(game, ss.lang), unsafe_allow_html=True)

    show_message()
    if ss.ratings and not game.is_over and not ss.get("bot_pending"):
        r = ss.ratings[-1]
        approx = "~" if not r.exact else ""
        st.markdown(
            f'<div class="dw-substatus">move {len(ss.ratings)}: {r.grade} · '
            f'kept {r.retained:,} of {r.pool_size:,} · beat '
            f'{approx}{r.percentile:.0f}% of options</div>',
            unsafe_allow_html=True)
    # endgame intel: shown in modes that allow help (hard keeps its peek;
    # impossible players are on their own)
    if (not game.is_over
            and game.config.max_hints + game.config.max_peeks > 0):
        forecast = trap_forecast(game)
        if forecast:
            traps, options = forecast
            if ss.mode == "duel":
                # a "trap" leaves only the secret — for the BOT, which
                # must then say it: those words are guaranteed wins
                if traps:
                    st.info(f"🎯 Endgame intel: **{traps} of your "
                            f"{options}** playable words corner the bot "
                            "into saying the word — guaranteed win!")
                else:
                    st.warning(f"💣 Endgame intel: none of your {options} "
                               "playable words corner the bot yet — "
                               "choose carefully.")
            elif traps == options:
                escape = (" Undo while you can!" if game.can_undo()
                          else " Choose your last words well…")
                st.warning(f"💣 Endgame intel: **every one** of your "
                           f"{options} playable words leads straight into "
                           f"a trap.{escape}")
            elif traps:
                st.warning(f"💣 Endgame intel: **{traps} of your {options}** "
                           "playable words lead straight into a trap.")
            else:
                st.info(f"🛡️ Endgame intel: none of your {options} playable "
                        "words trap you on the next row.")
    if ss.hint_word and not game.is_over:
        st.info(f"💡 Safe word: **{ss.hint_word.upper()}**")
    if ss.peek_words and not game.is_over:
        st.warning("👁️ " + " · ".join(w.upper() for w in ss.peek_words))

    # ----- zen practice: open book ------------------------------------
    if (ss.mode == "zen" and not game.is_over
            and game.remaining_count <= 500):
        with st.expander(f"🗒️ Browse all {game.remaining_count} remaining "
                         "words (Zen only)"):
            st.caption("One of these is the hidden word. Study how each "
                       "guess narrows the field.")
            st.markdown(" · ".join(w.upper() for w in game.remaining_words))

    # ----- controls ----------------------------------------------------
    if not game.is_over:
        if ss.input_mode == "type":
            with st.container(key="guessrow"):
                with st.form("guess_form", clear_on_submit=False,
                             border=False):
                    c1, c2 = st.columns([4, 1])
                    c1.text_input("Your guess", key="guess_input",
                                  max_chars=game.word_length,
                                  placeholder=f"type a {game.word_length}"
                                              "-letter word…",
                                  label_visibility="collapsed")
                    c2.form_submit_button("Guess", on_click=act_submit,
                                          type="primary", width="stretch")
        # only show abilities the current mode actually has
        actions = []
        if game.config.max_undos > 0:
            actions.append((f"↩️ Undo {fmt(game.undos_left)}", act_undo,
                            not game.can_undo()))
        if game.config.max_hints > 0:
            actions.append((f"💡 Hint {fmt(game.hints_left)}", act_hint,
                            game.hints_left <= 0))
        if game.config.max_peeks > 0:
            actions.append((f"👁️ Peek {fmt(game.peeks_left)}", act_peek,
                            game.peeks_left <= 0))
        if game.guesses_made == 0:
            actions.append(("🎲 Random", act_random_start, False))
        if actions:
            with st.container(key="abilities"):
                for col, (label, cb, off) in zip(st.columns(len(actions)),
                                                 actions):
                    col.button(label, on_click=cb, disabled=off,
                               width="stretch")
        if (game.is_trapped and not game.can_undo()
                and not ss.get("bot_pending")):
            with st.container(key="fatebar"):
                st.button(f"⚰️ Accept fate — play “{game.secret.upper()}”",
                          on_click=act_accept_fate, type="primary",
                          width="stretch")
    else:
        # ----- end of game panel ---------------------------------------
        won = player_won(game, ss.mode)
        if won:
            if not ss.celebrated:
                st.balloons()
                ss.celebrated = True
            if ss.mode == "duel":
                how = ("the bot said the word" if game.status is
                       GameStatus.WORDLED else "you outlasted it for 12 rows")
                st.success(f"👾💥 **You win the duel — {how}!** "
                           f"Score: **{game_score(game, ss.mode)}**")
                st.info(f"🔎 {_secret_reveal(game)}")
            elif game.status is GameStatus.SURVIVED:
                bd = game.score_breakdown()
                st.success(f"🎉 **You survived!** Score: **{bd['total']}**")
                st.info(f"🔎 {_secret_reveal(game)} You dodged it for "
                        f"{game.guesses_made} guesses.")
                floor_note = " — floored at the 10-point minimum" \
                    if bd["floored"] else ""
                st.caption(f"{bd['base']} survival + {bd['tiles']} tile "
                           f"points − {bd['penalties']} help penalties, "
                           f"× {bd['multiplier']:g} {game.config.label} "
                           f"bonus{floor_note}")
        else:
            st.error(f"💀 **You said the word.** {_secret_reveal(game)}")
            if ss.mode == "survival" and not game.can_undo():
                st.warning(f"⚔️ Run over at round {ss.survival_round}. "
                           f"Final run score: **{ss.survival_total}** · "
                           f"best ever: **{ss.survival_best}**")
            if game.can_undo():
                st.button("↩️ Undo that fatal guess!", on_click=act_undo,
                          type="primary")
        for note in ss.game_unlocks:
            st.success(note)
        lv = ACH.level_for_xp(ss.xp)
        player_rows = ((game.guesses_made + 1) // 2
                       if ss.mode == "duel" else None)
        share_block = (game.share_text(share_title(), won=won,
                                       score=game_score(game, ss.mode),
                                       guesses=player_rows)
                       + f"\n⭐ Level {lv['level']} {lv['title']} · "
                         f"🏆 {len(ss.achievements)}/{len(ACH.ACHIEVEMENTS)}")
        st.code(share_block, language=None)
        st.caption("Copy the block above to share your result.")

        with st.expander("🔬 Best-move review", expanded=ss.review is not None):
            if ss.review is None:
                st.caption("See, row by row, how many words your guess "
                           "kept alive — and which word would have kept "
                           "the most.")
                st.button("Analyze my game", on_click=act_review,
                          type="secondary")
            else:
                if ss.get("duel_read"):
                    st.markdown(ss.duel_read)
                rows = (game.history[0::2] if ss.mode == "duel"
                        else game.history)
                for i, (t, r) in enumerate(zip(rows, ss.review), 1):
                    approx = "" if r.exact else " (best found by sampling)"
                    if r.fatal and r.forced:
                        verdict = "**no way out — it was the only word left**"
                    elif r.fatal:
                        verdict = "**that was the hidden word**"
                    elif r.word == r.best_word and r.pool_size > 1:
                        verdict = ("**perfect — nothing kept more**"
                                   if r.exact else
                                   "**best of the sampled options**")
                    else:
                        verdict = (f"best: **{r.best_word.upper()}** "
                                   f"would have kept **{r.best_retained:,}**"
                                   f"{approx}")
                    st.markdown(
                        f"{i}. {r.grade} — **{r.word.upper()}** kept "
                        f"**{r.retained:,}** of {r.pool_size:,} · {verdict}")
        if ss.mode == "survival" and game.status is GameStatus.SURVIVED:
            st.button(f"⚔️ Next round ({ss.survival_round + 1}) →",
                      on_click=act_new_game, kwargs={"next_round": True},
                      type="primary")
            st.button("🏳️ End run", on_click=act_new_game)
        elif ss.mode == "daily":
            st.caption(f"That's today's puzzle — the next daily word "
                       f"drops in **{next_daily_in()}**. Or switch modes "
                       "to keep playing.")
            st.button("🔁 Replay today's word (practice)",
                      on_click=act_new_game)
        else:
            st.button("🔁 Play again", on_click=act_new_game, type="primary")

    # footer on the page itself — the sidebar is collapsed on phones
    st.markdown(
        f'<div class="dw-footer">v{__version__} · built by '
        f'<a href="{__homepage__}" target="_blank">Dr. Eugen Dimant</a>'
        '</div>',
        unsafe_allow_html=True)

    if ss.get("progress_dirty"):
        save_progress_cookie()
        ss.progress_dirty = False

    # animations are one-shot: replay only after the next qualifying action
    ss.last_action = None


def _run_protected() -> None:
    """Last line of defense: a render error shows a friendly recovery
    panel instead of Streamlit's crash page. Streamlit's own control-flow
    exceptions pass through untouched."""
    try:
        main()
    except Exception as e:
        if type(e).__module__.startswith("streamlit"):
            raise
        st.error("⚠️ Something went wrong while drawing the page — your "
                 "progress is safe.")
        ss = st.session_state
        ss.pop("game", None)
        try:
            reset_game_view_state()
        except Exception:
            pass
        if st.button("🔄 Restart the board", type="primary"):
            pass  # state cleared above; the rerun rebuilds everything


# run under `streamlit run` / AppTest, but stay importable for unit tests
if __name__ == "__main__" or st.runtime.exists():
    _run_protected()
