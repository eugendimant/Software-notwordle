"""DON'T Wordle — Streamlit app.

The anti-Wordle: six guesses, and your only job is to NOT say the word.
Run with:  streamlit run app.py
"""

from __future__ import annotations

import datetime
import json
import random

import streamlit as st

from dontwordle import __homepage__, __version__
from dontwordle import achievements as ACH
from dontwordle import analysis as A
from dontwordle import words as W
from dontwordle.engine import (
    GRAY,
    GREEN,
    PRESETS,
    UNLIMITED,
    YELLOW,
    DontWordleGame,
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
    "🔥 Hard": "hard",
    "💀 Impossible": "impossible",
    "⚔️ Survival": "survival",
    "🧘 Zen": "zen",
}

MODE_HELP = {
    "daily": "One shared puzzle per day — same secret word for everyone. "
             "6 guesses, 5 undos, 1 hint, 1 peek.",
    "classic": "Random word. 6 guesses, 5 undos, 1 hint, 1 peek.",
    "hard": "6 guesses, only 2 undos, no hints, 1 peek. 1.5× score.",
    "impossible": "SEVEN guesses to survive, zero undos, zero help. 2.5× score.",
    "survival": "Endless gauntlet: each round you lose one undo. "
                "Scores stack with a rising multiplier. One loss ends the run.",
    "zen": "Practice space — unlimited undos, hints and peeks. 0.25× score.",
}


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
def _new_game(mode: str) -> DontWordleGame:
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
    else:
        cfg = PRESETS[mode]
        secret = W.random_secret(lang, length, rng)
    return DontWordleGame(secret, W.allowed_guesses(lang, length), cfg, rng=rng)


def init_state() -> None:
    ss = st.session_state
    ss.setdefault("lang", "en")
    ss.setdefault("word_len", 5)
    ss.setdefault("input_mode", "type")  # "type" | "click"
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
    ss.setdefault("message", None)     # (kind, text)
    ss.setdefault("hint_word", None)
    ss.setdefault("peek_words", None)
    ss.setdefault("recorded", False)
    ss.setdefault("celebrated", False)
    ss.setdefault("daily_done", set())  # {"YYYY-MM-DD:lang:len"} counted
    if "game" not in ss:
        ss.game = _new_game(ss.mode)


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
    game: DontWordleGame = ss.game
    if ss.recorded or not game.is_over:
        return
    if game.status is GameStatus.WORDLED and game.can_undo() and not force:
        return
    ss.recorded = True
    if ss.mode == "daily":
        daily_key = ss.get("daily_key") or (
            f"{datetime.date.today().isoformat()}:{ss.lang}:{ss.word_len}")
        if daily_key in ss.daily_done:
            return  # practice replay of a known word: don't farm stats
        ss.daily_done.add(daily_key)
    ss.stats_upload_token = None  # stats changed; allow re-restoring a backup
    stats = mode_stats(ss.mode)
    stats["played"] += 1
    if game.status is GameStatus.SURVIVED:
        stats["survived"] += 1
        stats["streak"] += 1
        stats["best_streak"] = max(stats["best_streak"], stats["streak"])
        stats["best_score"] = max(stats["best_score"], game.score())
    else:
        stats["streak"] = 0
    if ss.mode == "survival":
        if game.status is GameStatus.SURVIVED:
            ss.survival_total += game.score()
            ss.survival_best = max(ss.survival_best, ss.survival_total)
        else:
            ss.survival_best = max(ss.survival_best, ss.survival_total)
    _award_progress(game, stats)


def _build_context(game: DontWordleGame, stats: dict) -> ACH.GameContext:
    ss = st.session_state
    won = game.status is GameStatus.SURVIVED
    if won:
        ss.wins_langs.add(ss.lang)
        ss.wins_lengths.add(ss.word_len)
    greens = sum(t.feedback.count(GREEN) for t in game.history)
    yellows = sum(t.feedback.count(YELLOW) for t in game.history)
    return ACH.GameContext(
        mode=ss.mode, lang=ss.lang, length=ss.word_len,
        won=won, score=game.score(),
        undos=game.undos_used, hints=game.hints_used, peeks=game.peeks_used,
        greens=greens, yellows=yellows,
        min_pool_seen=game.min_pool_seen, final_pool=game.remaining_count,
        was_trapped=game.was_ever_trapped,
        survival_round=ss.survival_round, streak=stats["streak"],
        total_wins=sum(s["survived"] for s in ss.stats.values()),
        rating_percentiles=[r.percentile for r in ss.ratings],
        langs_won=set(ss.wins_langs), lengths_won=set(ss.wins_lengths),
    )


def _award_progress(game: DontWordleGame, stats: dict) -> None:
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


# ----------------------------------------------------------------------
# Actions (widget callbacks)
# ----------------------------------------------------------------------
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
    ss.message = None
    ss.hint_word = None
    ss.peek_words = None
    ss.recorded = False
    ss.celebrated = False
    ss.ratings = []
    ss.review = None
    ss.kbd_buffer = ""
    ss.guess_input = ""  # don't carry a typed word into the new game
    ss.game_unlocks = []
    ss.last_action = "new"


def act_change_mode() -> None:
    _ensure_state()
    ss = st.session_state
    record_result_if_final(force=True)  # attribute result to the old mode
    ss.mode = MODES[ss.mode_label]
    ss.survival_round = 1
    ss.survival_total = 0
    act_new_game()


def act_change_lang() -> None:
    _ensure_state()
    ss = st.session_state
    record_result_if_final(force=True)  # attribute result to the old language
    ss.lang = ss.lang_select
    ss.survival_round = 1
    ss.survival_total = 0
    act_new_game()


def act_change_len() -> None:
    _ensure_state()
    ss = st.session_state
    record_result_if_final(force=True)  # attribute result to the old length
    ss.word_len = ss.len_select
    ss.survival_round = 1
    ss.survival_total = 0
    act_new_game()


def act_change_input() -> None:
    _ensure_state()
    ss = st.session_state
    ss.input_mode = "click" if "Click" in ss.input_select else "type"
    ss.kbd_buffer = ""


def act_submit() -> None:
    _ensure_state()
    word = st.session_state.get("guess_input", "").strip().lower()
    _process_guess(word, clear_input=True)


def act_key(letter: str) -> None:
    _ensure_state()
    ss = st.session_state
    if not ss.game.is_over and len(ss.kbd_buffer) < ss.game.word_length:
        ss.kbd_buffer += letter


def act_backspace() -> None:
    _ensure_state()
    ss = st.session_state
    ss.kbd_buffer = ss.kbd_buffer[:-1]


def act_kbd_enter() -> None:
    _ensure_state()
    ss = st.session_state
    _process_guess(ss.kbd_buffer)
    if ss.last_action == "guess":
        ss.kbd_buffer = ""


def act_accept_fate() -> None:
    """Trapped with no way out — play the only word left and take the L."""
    _ensure_state()
    _process_guess(st.session_state.game.secret)


def _process_guess(word: str, clear_input: bool = False) -> None:
    ss = st.session_state
    game: DontWordleGame = ss.game
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
    # rate the move: how well did it preserve the pool vs alternatives?
    # (same seed/sample as act_review so live and review grades agree)
    row = game.guesses_made - 1
    ss.ratings.append(A.rate_move(
        A.analyzer_for(ss.lang, game.word_length), word,
        game.pool_before(row), game.secret,
        rng=random.Random(f"{game.secret}:{row}"), sample_size=400,
        actual_retained=game.remaining_count))
    ss.hint_word = None
    ss.peek_words = None
    if game.is_over:
        ss.kbd_buffer = ""  # nothing left to type on a finished board
    if game.status is GameStatus.WORDLED:
        ss.message = ("loss", f"💀 You Wordled! “{word.upper()}” was the "
                              "hidden word." +
                      (" You can still UNDO it…" if game.can_undo() else ""))
    elif game.status is GameStatus.SURVIVED:
        ss.message = ("win", "🎉 You SURVIVED! You never said the word.")
    elif game.is_trapped:
        ss.message = ("warn", "⚠️ TRAPPED — only the hidden word is left. "
                              "Undo or face your fate!")
    else:
        greens = turn.feedback.count(GREEN)
        yellows = turn.feedback.count(YELLOW)
        if greens + yellows == 0:
            ss.message = ("ok", "Clean miss — nothing revealed. Nice.")
        else:
            ss.message = ("ok", f"Revealed {greens} green / {yellows} yellow. "
                                "Those clues now bind every future guess.")
    record_result_if_final()


def act_random_start() -> None:
    """Fill the box with a random opening word (first guess only, like the
    original's 'Random Starting Word'). Mid-game randomness could land on
    the secret itself, so it is deliberately unavailable after turn one."""
    _ensure_state()
    ss = st.session_state
    game: DontWordleGame = ss.game
    if not game.is_over and game.guesses_made == 0:
        _reseed_daily_rng("random-start")
        # never suggest the secret: with the deterministic daily seed it
        # would hand every player the losing word on unlucky dates
        word = game.rng.choice(game.safe_words())
        if ss.input_mode == "click":
            ss.kbd_buffer = word
        else:
            ss.guess_input = word


def act_undo() -> None:
    _ensure_state()
    ss = st.session_state
    ss.last_action = "undo"
    if ss.game.undo():
        ss.message = ("ok", "↩️ Guess taken back. Choose more carefully…")
        if ss.ratings:
            ss.ratings.pop()
        ss.review = None  # any analysis refers to a board that no longer exists
        ss.hint_word = None
        ss.peek_words = None
    else:
        ss.message = ("error", "No undos available.")


def act_review() -> None:
    """Post-game: find the best word for every row (exact where feasible)."""
    _ensure_state()
    ss = st.session_state
    game: DontWordleGame = ss.game
    az = A.analyzer_for(ss.lang, game.word_length)
    ss.review = [
        A.rate_move(az, t.guess, game.pool_before(i), game.secret,
                    rng=random.Random(f"{game.secret}:{i}"), sample_size=400,
                    actual_retained=len(game.pool_before(i + 1)))
        for i, t in enumerate(game.history)
    ]


def _reseed_daily_rng(facility: str) -> None:
    """Daily games must give every player identical hints/peeks/randoms,
    regardless of the order they use them in."""
    ss = st.session_state
    if ss.mode == "daily":
        # daily_key was pinned at game creation: stable across midnight
        ss.game.rng.seed(f"daily:{ss.get('daily_key')}"
                         f":{facility}:{ss.game.guesses_made}")


def act_hint() -> None:
    _ensure_state()
    ss = st.session_state
    _reseed_daily_rng("hint")
    game: DontWordleGame = ss.game
    az = A.analyzer_for(ss.lang, game.word_length)

    def smart(safe, rng):  # safest sampled word, not just any safe word
        return A.best_safe_hint(az, game.remaining_words, game.secret, rng)

    h = game.hint(chooser=smart)
    if h:
        ss.hint_word = h
        ss.message = ("ok", "🛟 The oracle whispers a *good* safe word — "
                            "it keeps your options wide open.")
    else:
        ss.message = ("error", "No hint available.")


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


def export_stats_json() -> str:
    ss = st.session_state
    return json.dumps({"app": "dontwordle", "version": __version__,
                       "stats": ss.stats, "survival_best": ss.survival_best,
                       "xp": ss.xp,
                       "achievements": sorted(ss.achievements),
                       "daily_streaks": ss.daily_streaks,
                       "daily_done": sorted(ss.daily_done)},
                      indent=2)


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
        return {"stats": clean,
                "survival_best": _num(data.get("survival_best", 0)),
                "xp": _num(data.get("xp", 0), ACH.XP_CAP),
                "achievements": achievements,
                "daily_streaks": streaks,
                "daily_done": done}
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
.block-container {max-width: 720px;}
.dw-header {text-align:center; margin:-12px 0 2px 0;}
.dw-title {font-family:'Helvetica Neue',Arial,sans-serif; font-weight:900;
           letter-spacing:0.16em; font-size:2.0rem; line-height:1.2;}
.dw-title .no {color:#e74c3c;}
.dw-title .word {color:#6aaa64;}
.dw-header p {margin:0; opacity:0.65; font-size:0.85rem;
              letter-spacing:0.28em; text-transform:uppercase;}
.dw-banner {text-align:center; font-weight:700; font-size:1.05rem;
            margin:2px 0 6px 0;}
.dw-banner .sub {opacity:0.7; font-weight:400; font-size:0.9rem;}
.dw-board {display:flex; flex-direction:column; gap:6px; align-items:center;
           margin: 10px 0 4px 0;}
.dw-row {display:flex; gap:6px;}
.dw-tile {width:52px; height:52px; display:flex; align-items:center;
          justify-content:center; font-size:1.7rem; font-weight:800;
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
.dw-counts {display:flex; justify-content:center; gap:34px;
            text-align:center; font-weight:700; margin-bottom:4px;}
.dw-counts .lab {font-size:0.75rem; letter-spacing:0.1em; opacity:0.75;
                 text-transform:uppercase;}
.dw-counts .num {font-size:1.9rem; line-height:1.15;}
.dw-bar {height:7px; border-radius:4px; background:#262628;
         margin:0 auto 2px auto; max-width:440px; overflow:hidden;}
.dw-bar .dw-fill {height:100%; border-radius:4px;
                  transition:width .5s ease;}
.dw-trapped {animation: dw-pulse 1s ease infinite;}
@keyframes dw-pulse {50% {opacity:0.45;}}
.dw-footer {text-align:center; opacity:0.8; font-size:0.85rem;
            margin-top:18px;}
@media (max-width: 480px) {
  .dw-tile {width:44px; height:44px; font-size:1.4rem;}
  .dw-row {gap:4px;}
  .dw-key {min-width:24px; height:34px; font-size:0.85rem;}
}
@media (max-width: 380px) {
  .dw-tile {width:38px; height:38px; font-size:1.2rem;}
}
/* Clickable keyboard: Streamlit stacks columns vertically on phones,
   which exploded the keyboard into 26 full-width rows. Force each
   keyboard row to stay a single horizontal flex line with compact,
   evenly stretched keys at every viewport width. */
.st-key-clickkbd [data-testid="stHorizontalBlock"] {
  flex-wrap: nowrap !important;
  gap: 0.22rem !important;
  margin-bottom: 0.22rem;
}
.st-key-clickkbd [data-testid="stColumn"] {
  min-width: 0 !important;
  flex: 1 1 0% !important;
  width: auto !important;
}
.st-key-clickkbd .stButton > button {
  width: 100% !important;
  min-width: 0 !important;
  height: 2.9rem;
  padding: 0 !important;
  font-weight: 700;
  font-size: 1rem;
  border-radius: 6px;
  text-transform: uppercase;
}
@media (max-width: 480px) {
  .st-key-clickkbd .stButton > button {
    height: 2.6rem;
    font-size: 0.9rem;
  }
}
/* ability buttons: one compact row on phones instead of a tall stack */
.st-key-abilities [data-testid="stHorizontalBlock"] {
  flex-wrap: nowrap !important;
  gap: 0.25rem !important;
}
.st-key-abilities [data-testid="stColumn"] {
  min-width: 0 !important;
  flex: 1 1 0% !important;
}
.st-key-abilities .stButton > button {
  width: 100% !important;
  min-width: 0 !important;
  padding: 0.25rem 0.1rem !important;
  font-size: 0.85rem;
  white-space: nowrap;
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
  <div class="dw-title"><span class="no">DON'T</span> <span class="word">WORDLE</span></div>
  <p>guess words — never the word</p>
</div>
"""


def render_board(game: DontWordleGame, buffer: str = "",
                 animate_last: bool = False, shake: bool = False) -> str:
    rows = []
    last = len(game.history) - 1
    width = game.word_length
    for i, turn in enumerate(game.history):
        tiles = "".join(
            f'<div class="dw-tile" style="background:{TILE_COLORS[c]}">{l}</div>'
            for l, c in zip(turn.guess, turn.feedback)
        )
        cls = "dw-row dw-reveal" if (animate_last and i == last) else "dw-row"
        rows.append(f'<div class="{cls}">{tiles}</div>')
    for j in range(game.guesses_left):
        cells = []
        for k in range(width):
            letter = buffer[k] if j == 0 and k < len(buffer) else ""
            cls = "dw-tile dw-empty" + (" dw-active" if j == 0 else "")
            cells.append(f'<div class="{cls}">{letter}</div>')
        rows.append(f'<div class="dw-row">{"".join(cells)}</div>')
    board_cls = "dw-board dw-shake" if shake else "dw-board"
    return f'<div class="{board_cls}">{"".join(rows)}</div>'


def letter_knowledge(game: DontWordleGame) -> dict[str, str]:
    """Best-known status per letter: G > Y > gray(eliminated)."""
    rank = {GREEN: 3, YELLOW: 2, GRAY: 1}
    know: dict[str, str] = {}
    for turn in game.history:
        for l, c in zip(turn.guess, turn.feedback):
            if l not in know or rank[c] > rank[know[l]]:
                know[l] = c
    return know


def render_keyboard(game: DontWordleGame, lang: str) -> str:
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


def render_meter(game: DontWordleGame) -> str:
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


def render_click_keyboard(game: DontWordleGame, lang: str) -> None:
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
                               width="stretch", disabled=game.is_over,
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


def show_message() -> None:
    msg = st.session_state.message
    if not msg:
        return
    kind, text = msg
    # the end-of-game panel already announces wins/losses
    if st.session_state.game.is_over and kind in ("win", "loss"):
        return
    {"error": st.error, "warn": st.warning, "win": st.success,
     "loss": st.error, "ok": st.info}[kind](text)


TRAP_FORECAST_LIMIT = 30


def trap_forecast(game: DontWordleGame) -> tuple[int, int] | None:
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


def _secret_reveal(game: DontWordleGame) -> str:
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
        return f"Don't Wordle Daily {datetime.date.today().isoformat()}{tag}"
    if ss.mode == "survival":
        return f"Don't Wordle Survival R{ss.survival_round}{tag}"
    return f"Don't Wordle {ss.game.config.label}{tag}"


# ----------------------------------------------------------------------
# Page
# ----------------------------------------------------------------------
def main() -> None:
    st.set_page_config(page_title="DON'T Wordle", page_icon="🙅",
                       layout="centered")
    init_state()
    ss = st.session_state
    game: DontWordleGame = ss.game
    st.markdown(CSS, unsafe_allow_html=True)
    st.markdown(HEADER, unsafe_allow_html=True)

    # ----- sidebar ----------------------------------------------------
    with st.sidebar:
        st.title("🙅 DON'T Wordle")
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
        st.radio("Input method", ["⌨️ Typing", "🔠 Clickable letters"],
                 index=0 if ss.input_mode == "type" else 1,
                 key="input_select", on_change=act_change_input,
                 horizontal=True)
        labels = list(MODES)
        current = next(k for k, v in MODES.items() if v == ss.mode)
        st.radio("Game mode", labels, index=labels.index(current),
                 key="mode_label", on_change=act_change_mode,
                 help="Changing mode starts a fresh game.")
        st.caption(MODE_HELP[ss.mode])
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
        stats = mode_stats(ss.mode)
        c1, c2 = st.columns(2)
        c1.metric("Played", stats["played"])
        rate = (stats["survived"] / stats["played"] * 100
                if stats["played"] else 0)
        c2.metric("Survival %", f"{rate:.0f}%")
        c1.metric("Streak", stats["streak"])
        c2.metric("Best score", stats["best_score"])
        if ss.mode == "survival":
            st.metric("Best survival run", ss.survival_best)

        never_played = not any(s["played"] for s in ss.stats.values())
        with st.expander("📖 How to play", expanded=never_played):
            st.markdown(
                f"- Guess {ss.word_len}-letter words — but **never** the "
                "hidden word.\n"
                "- Every guess must obey all clues so far: 🟩 greens stay "
                "in place, 🟨 yellows must be re-used, ⬜ grays are "
                "forbidden.\n"
                "- The clue rules shrink the pool of playable words and "
                "push you toward the answer. **Survive every guess to "
                "win.**\n"
                "- **↩️ Undo** takes back a guess — even a fatal one.\n"
                "- **🛟 Hint** reveals a guaranteed-safe word.\n"
                "- **👁️ Peek** shows some remaining words… one might be "
                "the answer.\n"
                "- Secrets are **weighted by real-world frequency**: "
                "everyday words are several times likelier than obscure "
                "ones. If the clues fit two words, suspect the common "
                "one!\n"
                "- Surviving with more 🟩/🟨 on the board scores higher."
            )

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
                               file_name="dontwordle_stats.json",
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
                        ss.stats = payload["stats"]
                        ss.survival_best = payload["survival_best"]
                        ss.xp = payload["xp"]
                        ss.achievements = payload["achievements"]
                        ss.daily_streaks = payload["daily_streaks"]
                        ss.daily_done = payload["daily_done"]
                        # rebuild session win sets so Polyglot/Triathlete
                        # progress survives the restore
                        ss.wins_langs, ss.wins_lengths = \
                            derive_session_wins(payload["stats"])
                        st.success("Stats restored!")
                    else:
                        st.error("That doesn't look like a stats file.")
                else:
                    st.caption("✓ This backup is already loaded.")

        st.divider()
        st.markdown(
            f'<div class="dw-footer">v{__version__} · built by '
            f'<a href="{__homepage__}" target="_blank">Eugen Dimant</a>'
            "</div>",
            unsafe_allow_html=True,
        )

    # ----- header / survival banner (centered like everything else) ----
    if ss.mode == "survival":
        st.markdown(
            f'<div class="dw-banner">⚔️ Round {ss.survival_round} · '
            f'run score {ss.survival_total} <span class="sub">· '
            f'{game.config.max_undos} undo(s) this round</span></div>',
            unsafe_allow_html=True)
    elif ss.mode == "daily":
        streak = ss.daily_streaks.get(
            f"{ss.lang}:{ss.word_len}", {}).get("streak", 0)
        flame = f' · <span class="sub">🔥 {streak}-day streak</span>' \
            if streak >= 2 else ""
        st.markdown(
            f'<div class="dw-banner">📅 Daily Challenge '
            f'<span class="sub">— {datetime.date.today():%B %d, %Y}'
            f'</span>{flame}</div>', unsafe_allow_html=True)
        if not game.is_over:
            # use the date pinned at game creation so the banner and the
            # award agree even across midnight
            quest_date = (ss.get("daily_key")
                          or datetime.date.today().isoformat()).split(":")[0]
            quest = ACH.daily_quest(quest_date, ss.lang, ss.word_len)
            st.markdown(
                f'<div class="dw-banner"><span class="sub">🎯 Side-quest: '
                f'{quest.label} (+{quest.xp} XP)</span></div>',
                unsafe_allow_html=True)

    st.markdown(render_meter(game), unsafe_allow_html=True)
    buffer = ss.kbd_buffer if ss.input_mode == "click" else ""
    st.markdown(render_board(game, buffer=buffer,
                             animate_last=ss.last_action == "guess",
                             shake=ss.last_action == "error"),
                unsafe_allow_html=True)
    if ss.input_mode == "click":
        if not game.is_over:
            render_click_keyboard(game, ss.lang)
    else:
        st.markdown(render_keyboard(game, ss.lang), unsafe_allow_html=True)

    show_message()
    if ss.ratings and not game.is_over:
        r = ss.ratings[-1]
        st.caption(
            f"Move {len(ss.ratings)} safety: **{r.grade}** — kept "
            f"**{r.retained:,}** of {r.pool_size:,} words, outperformed "
            f"{'~' if not r.exact else ''}{r.percentile:.0f}% of your options")
    # endgame intel: shown in modes that allow help (hard keeps its peek;
    # impossible players are on their own)
    if (not game.is_over
            and game.config.max_hints + game.config.max_peeks > 0):
        forecast = trap_forecast(game)
        if forecast:
            traps, options = forecast
            if traps == options:
                st.warning(f"🧨 Endgame intel: **every one** of your "
                           f"{options} playable words leads straight into "
                           "a trap. Undo while you can!")
            elif traps:
                st.warning(f"🧨 Endgame intel: **{traps} of your {options}** "
                           "playable words lead straight into a trap.")
            else:
                st.info(f"🛡️ Endgame intel: none of your {options} playable "
                        "words trap you on the next row.")
    if ss.hint_word and not game.is_over:
        st.info(f"🛟 Safe word: **{ss.hint_word.upper()}**")
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
            actions.append((f"↩️ Undo ({fmt(game.undos_left)})", act_undo,
                            not game.can_undo()))
        if game.config.max_hints > 0:
            actions.append((f"🛟 Hint ({fmt(game.hints_left)})", act_hint,
                            game.hints_left <= 0))
        if game.config.max_peeks > 0:
            actions.append((f"👁️ Peek ({fmt(game.peeks_left)})", act_peek,
                            game.peeks_left <= 0))
        if game.guesses_made == 0:
            actions.append(("🎲 Random start", act_random_start, False))
        if actions:
            with st.container(key="abilities"):
                for col, (label, cb, off) in zip(st.columns(len(actions)),
                                                 actions):
                    col.button(label, on_click=cb, disabled=off,
                               width="stretch")
        if game.is_trapped and not game.can_undo():
            st.button(f"⚰️ Accept fate — play “{game.secret.upper()}”",
                      on_click=act_accept_fate, type="primary",
                      width="stretch")
    else:
        # ----- end of game panel ---------------------------------------
        if game.status is GameStatus.SURVIVED:
            if not ss.celebrated:
                st.balloons()
                ss.celebrated = True
            bd = game.score_breakdown()
            st.success(f"🎉 **You survived!** Score: **{bd['total']}**")
            st.info(f"🔎 {_secret_reveal(game)} You dodged it for "
                    f"{game.guesses_made} guesses.")
            floor_note = " — floored at the 10-point minimum" \
                if bd["floored"] else ""
            st.caption(f"{bd['base']} survival + {bd['tiles']} tile points "
                       f"− {bd['penalties']} help penalties, "
                       f"× {bd['multiplier']:g} {game.config.label} bonus"
                       f"{floor_note}")
        else:
            st.error(f"💀 **You Wordled.** {_secret_reveal(game)}")
            if ss.mode == "survival" and not game.can_undo():
                st.warning(f"⚔️ Run over at round {ss.survival_round}. "
                           f"Final run score: **{ss.survival_total}** · "
                           f"best ever: **{ss.survival_best}**")
            if game.can_undo():
                st.button("↩️ Undo that fatal guess!", on_click=act_undo,
                          type="primary")
        for note in ss.game_unlocks:
            st.success(note)
        st.code(game.share_text(share_title()), language=None)
        st.caption("Copy the block above to share your result.")

        with st.expander("🔬 Best-move review", expanded=ss.review is not None):
            if ss.review is None:
                st.caption("See, row by row, how many words your guess "
                           "kept alive — and which word would have kept "
                           "the most.")
                st.button("Analyze my game", on_click=act_review,
                          type="secondary")
            else:
                for i, (t, r) in enumerate(zip(game.history, ss.review), 1):
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

    # animations are one-shot: replay only after the next qualifying action
    ss.last_action = None


# run under `streamlit run` / AppTest, but stay importable for unit tests
if __name__ == "__main__" or st.runtime.exists():
    main()
