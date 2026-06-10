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
    "hard": "6 guesses, only 2 undos, no hints. 1.5× score.",
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
    rng = random.Random()
    if mode == "daily":
        secret = W.daily_secret()
        cfg = PRESETS["classic"]
        # deterministic helper rng so daily hints/peeks match across players
        rng = random.Random(f"daily:{datetime.date.today().isoformat()}")
    elif mode == "survival":
        cfg = survival_config(st.session_state.survival_round)
        secret = W.random_secret(rng)
    else:
        cfg = PRESETS[mode]
        secret = W.random_secret(rng)
    return DontWordleGame(secret, W.allowed_guesses(), cfg, rng=rng)


def init_state() -> None:
    ss = st.session_state
    ss.setdefault("mode", "daily")
    ss.setdefault("survival_round", 1)
    ss.setdefault("survival_total", 0)
    ss.setdefault("survival_best", 0)
    ss.setdefault("stats", {})         # mode -> dict
    ss.setdefault("message", None)     # (kind, text)
    ss.setdefault("hint_word", None)
    ss.setdefault("peek_words", None)
    ss.setdefault("recorded", False)
    ss.setdefault("celebrated", False)
    ss.setdefault("daily_done", None)  # iso date of last finished daily
    if "game" not in ss:
        ss.game = _new_game(ss.mode)


def mode_stats(mode: str) -> dict:
    return st.session_state.stats.setdefault(
        mode, {"played": 0, "survived": 0, "streak": 0,
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
    stats = mode_stats(ss.mode)
    stats["played"] += 1
    if game.status is GameStatus.SURVIVED:
        stats["survived"] += 1
        stats["streak"] += 1
        stats["best_streak"] = max(stats["best_streak"], stats["streak"])
        stats["best_score"] = max(stats["best_score"], game.score())
    else:
        stats["streak"] = 0
    if ss.mode == "daily":
        ss.daily_done = datetime.date.today().isoformat()
    if ss.mode == "survival":
        if game.status is GameStatus.SURVIVED:
            ss.survival_total += game.score()
            ss.survival_best = max(ss.survival_best, ss.survival_total)
        else:
            ss.survival_best = max(ss.survival_best, ss.survival_total)


# ----------------------------------------------------------------------
# Actions (widget callbacks)
# ----------------------------------------------------------------------
def act_new_game(next_round: bool = False) -> None:
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


def act_change_mode() -> None:
    ss = st.session_state
    record_result_if_final(force=True)  # attribute result to the old mode
    ss.mode = MODES[ss.mode_label]
    ss.survival_round = 1
    ss.survival_total = 0
    act_new_game()


def act_submit() -> None:
    word = st.session_state.get("guess_input", "").strip().lower()
    _process_guess(word, clear_input=True)


def act_accept_fate() -> None:
    """Trapped with no way out — play the only word left and take the L."""
    _process_guess(st.session_state.game.secret)


def _process_guess(word: str, clear_input: bool = False) -> None:
    ss = st.session_state
    game: DontWordleGame = ss.game
    if game.is_over:
        return
    try:
        turn = game.submit(word)
    except InvalidGuess as e:
        # keep the typed word so the player can fix it instead of retyping
        ss.message = ("error", e.reason)
        return
    if clear_input:
        ss.guess_input = ""
    ss.hint_word = None
    ss.peek_words = None
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
    ss = st.session_state
    game: DontWordleGame = ss.game
    if not game.is_over and game.guesses_made == 0:
        ss.guess_input = game.rng.choice(game.remaining_words)


def act_undo() -> None:
    ss = st.session_state
    if ss.game.undo():
        ss.message = ("ok", "↩️ Guess taken back. Choose more carefully…")
        ss.hint_word = None
        ss.peek_words = None
    else:
        ss.message = ("error", "No undos available.")


def act_hint() -> None:
    ss = st.session_state
    h = ss.game.hint()
    if h:
        ss.hint_word = h
        ss.message = ("ok", "🛟 The oracle whispers a guaranteed-safe word.")
    else:
        ss.message = ("error", "No hint available.")


def act_peek() -> None:
    ss = st.session_state
    sample = ss.game.peek()
    if sample:
        ss.peek_words = sample
        ss.message = ("warn", "👁️ Peek: 5 of the remaining words — "
                              "the hidden word might be among them!")
    else:
        ss.message = ("error", "No peek available.")


# ----------------------------------------------------------------------
# Stats backup / restore
# ----------------------------------------------------------------------
STAT_KEYS = ("played", "survived", "streak", "best_streak", "best_score")


def export_stats_json() -> str:
    ss = st.session_state
    return json.dumps({"app": "dontwordle", "version": __version__,
                       "stats": ss.stats, "survival_best": ss.survival_best},
                      indent=2)


def parse_stats_json(text: str) -> dict | None:
    """Validate an exported stats file. Returns clean payload or None."""
    try:
        data = json.loads(text)
        clean = {
            mode: {k: max(0, int(s.get(k, 0))) for k in STAT_KEYS}
            for mode, s in data["stats"].items()
            if mode in MODES.values() and isinstance(s, dict)
        }
        return {"stats": clean,
                "survival_best": max(0, int(data.get("survival_best", 0)))}
    except (ValueError, TypeError, KeyError, AttributeError):
        return None


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
.dw-board {display:flex; flex-direction:column; gap:6px; align-items:center;
           margin: 10px 0 4px 0;}
.dw-row {display:flex; gap:6px;}
.dw-tile {width:52px; height:52px; display:flex; align-items:center;
          justify-content:center; font-size:1.7rem; font-weight:800;
          color:#fff; text-transform:uppercase; border-radius:6px;
          font-family:'Helvetica Neue',Arial,sans-serif;}
.dw-empty {background:transparent; border:2px solid #3a3a3c;}
.dw-kbd {display:flex; flex-direction:column; gap:5px; align-items:center;
         margin-top:6px;}
.dw-krow {display:flex; gap:4px;}
.dw-key {min-width:30px; height:38px; padding:0 6px; display:flex;
         align-items:center; justify-content:center; border-radius:4px;
         font-weight:700; font-size:0.95rem; color:#fff;
         background:#818384; text-transform:uppercase;}
.dw-meter {text-align:center; margin:2px 0 8px 0; font-weight:700;}
.dw-meter .num {font-size:1.9rem;}
.dw-counts {display:flex; justify-content:center; gap:34px;
            text-align:center; font-weight:700; margin-bottom:2px;}
.dw-counts .lab {font-size:0.75rem; letter-spacing:0.1em; opacity:0.75;
                 text-transform:uppercase;}
.dw-footer {text-align:center; opacity:0.8; font-size:0.85rem;
            margin-top:18px;}
</style>
"""


def render_board(game: DontWordleGame) -> str:
    rows = []
    for turn in game.history:
        tiles = "".join(
            f'<div class="dw-tile" style="background:{TILE_COLORS[c]}">{l}</div>'
            for l, c in zip(turn.guess, turn.feedback)
        )
        rows.append(f'<div class="dw-row">{tiles}</div>')
    for _ in range(game.guesses_left):
        tiles = '<div class="dw-tile dw-empty"></div>' * 5
        rows.append(f'<div class="dw-row">{tiles}</div>')
    return f'<div class="dw-board">{"".join(rows)}</div>'


def letter_knowledge(game: DontWordleGame) -> dict[str, str]:
    """Best-known status per letter: G > Y > gray(eliminated)."""
    rank = {GREEN: 3, YELLOW: 2, GRAY: 1}
    know: dict[str, str] = {}
    for turn in game.history:
        for l, c in zip(turn.guess, turn.feedback):
            if l not in know or rank[c] > rank[know[l]]:
                know[l] = c
    return know


def render_keyboard(game: DontWordleGame) -> str:
    know = letter_knowledge(game)
    colors = {GREEN: "#538d4e", YELLOW: "#b59f3b", GRAY: "#2c2c2e"}
    rows_html = []
    for row in ("qwertyuiop", "asdfghjkl", "zxcvbnm"):
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
    n = game.remaining_count
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
    return (f'<div class="dw-counts">'
            f'<div><div class="lab">Valid words remaining</div>'
            f'<div class="num" style="color:{color};font-size:1.9rem">{n:,}</div>'
            f'<div class="lab" style="color:{color}">{label}</div></div>'
            f'<div><div class="lab">Undos remaining</div>'
            f'<div class="num" style="font-size:1.9rem">'
            f'{fmt(game.undos_left)}</div>'
            f'<div class="lab">guesses left: {game.guesses_left}</div></div>'
            f'</div>')


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


def share_title() -> str:
    ss = st.session_state
    if ss.mode == "daily":
        return f"Don't Wordle Daily {datetime.date.today().isoformat()}"
    if ss.mode == "survival":
        return f"Don't Wordle Survival R{ss.survival_round}"
    return f"Don't Wordle {ss.game.config.label}"


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

    # ----- sidebar ----------------------------------------------------
    with st.sidebar:
        st.title("🙅 DON'T Wordle")
        st.caption("Six guesses. Don't say the word.")
        labels = list(MODES)
        current = next(k for k, v in MODES.items() if v == ss.mode)
        st.radio("Game mode", labels, index=labels.index(current),
                 key="mode_label", on_change=act_change_mode,
                 help="Changing mode starts a fresh game.")
        st.caption(MODE_HELP[ss.mode])
        st.button("🔄 New game", on_click=act_new_game, width="stretch")

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
                "- Guess five-letter words — but **never** the hidden word.\n"
                "- Every guess must obey all clues so far: 🟩 greens stay "
                "in place, 🟨 yellows must be re-used, ⬜ grays are "
                "forbidden.\n"
                "- The clue rules shrink the pool of playable words and "
                "push you toward the answer. **Survive every guess to "
                "win.**\n"
                "- **↩️ Undo** takes back a guess — even a fatal one.\n"
                "- **🛟 Hint** reveals a guaranteed-safe word.\n"
                "- **👁️ Peek** shows 5 remaining words… one might be the "
                "answer.\n"
                "- Surviving with more 🟩/🟨 on the board scores higher."
            )

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
                        st.success("Stats restored!")
                    else:
                        st.error("That doesn't look like a stats file.")

        st.divider()
        st.markdown(
            f'<div class="dw-footer">v{__version__} · built by '
            f'<a href="{__homepage__}" target="_blank">Eugen Dimant</a>'
            "</div>",
            unsafe_allow_html=True,
        )

    # ----- header / survival banner -----------------------------------
    if ss.mode == "survival":
        st.markdown(
            f"#### ⚔️ Round {ss.survival_round} · run score "
            f"**{ss.survival_total}** · "
            f"{game.config.max_undos} undo(s) this round"
        )
    elif ss.mode == "daily":
        st.markdown(f"#### 📅 Daily Challenge — "
                    f"{datetime.date.today():%B %d, %Y}")

    st.markdown(render_meter(game), unsafe_allow_html=True)
    st.markdown(render_board(game), unsafe_allow_html=True)
    st.markdown(render_keyboard(game), unsafe_allow_html=True)

    show_message()
    if ss.hint_word and not game.is_over:
        st.info(f"🛟 Safe word: **{ss.hint_word.upper()}**")
    if ss.peek_words and not game.is_over:
        st.warning("👁️ " + " · ".join(w.upper() for w in ss.peek_words))

    # ----- controls ----------------------------------------------------
    if not game.is_over:
        with st.form("guess_form", clear_on_submit=False, border=False):
            c1, c2 = st.columns([4, 1])
            c1.text_input("Your guess", key="guess_input", max_chars=5,
                          placeholder="type a five-letter word…",
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
            actions.append(("🎲 Random starting word", act_random_start,
                            False))
        if actions:
            for col, (label, cb, off) in zip(st.columns(len(actions)),
                                             actions):
                col.button(label, on_click=cb, disabled=off, width="stretch")
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
            st.caption(f"{bd['base']} survival + {bd['tiles']} tile points "
                       f"− {bd['penalties']} help penalties, "
                       f"× {bd['multiplier']:g} {game.config.label} bonus")
        else:
            st.error(f"💀 **You Wordled.** The hidden word was "
                     f"**{game.secret.upper()}**.")
            if ss.mode == "survival" and not game.can_undo():
                st.warning(f"⚔️ Run over at round {ss.survival_round}. "
                           f"Final run score: **{ss.survival_total}** · "
                           f"best ever: **{ss.survival_best}**")
            if game.can_undo():
                st.button("↩️ Undo that fatal guess!", on_click=act_undo,
                          type="primary")
        record_result_if_final(force=not game.can_undo())
        st.code(game.share_text(share_title()), language=None)
        st.caption("Copy the block above to share your result.")
        if ss.mode == "survival" and game.status is GameStatus.SURVIVED:
            st.button(f"⚔️ Next round ({ss.survival_round + 1}) →",
                      on_click=act_new_game, kwargs={"next_round": True},
                      type="primary")
            st.button("🏳️ End run", on_click=act_new_game)
        elif ss.mode == "daily":
            st.caption("That's today's puzzle — come back tomorrow! "
                       "Or switch modes to keep playing.")
            st.button("🔁 Replay today's word (practice)",
                      on_click=act_new_game)
        else:
            st.button("🔁 Play again", on_click=act_new_game, type="primary")


# run under `streamlit run` / AppTest, but stay importable for unit tests
if __name__ == "__main__" or st.runtime.exists():
    main()
