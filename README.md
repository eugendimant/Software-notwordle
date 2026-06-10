# 🙅 DON'T Wordle

**The anti-Wordle.** Six guesses — and your only job is to *never* say the
hidden word. A fast, modern [Streamlit](https://streamlit.io) adaptation of
the cult classic [dontwordle.com](https://dontwordle.com), rebuilt from
scratch with extra game modes, abilities, scoring and stats.

> Built by [Eugen Dimant](https://eugendimant.github.io) · current version
> in [`dontwordle/__init__.py`](dontwordle/__init__.py)

## Why it's hard (and fun)

Every guess must be a real word **and** obey every clue revealed so far:

| Clue | Rule it imposes on all future guesses |
|------|----------------------------------------|
| 🟩 green | that letter is locked into that exact spot |
| 🟨 yellow | that letter must be re-used (somewhere else) |
| ⬜ gray | that letter is forbidden |

So each guess shrinks the pool of *valid words remaining* — squeezing you
toward the one word you must not say. Survive all your guesses and you win.

## Game modes

| Mode | Guesses | Undos | Hints | Peeks | Score |
|------|--------:|------:|------:|------:|------:|
| 📅 Daily Challenge | 6 | 5 | 1 | 1 | 1× |
| 🎲 Classic | 6 | 5 | 1 | 1 | 1× |
| 🔥 Hard | 6 | 2 | 0 | 1 | 1.5× |
| 💀 Impossible | **7** | 0 | 0 | 0 | 2.5× |
| ⚔️ Survival | 6/round | 5 → 0 | early rounds | 1 | climbs +25%/round |
| 🧘 Zen | 6 | ∞ | ∞ | ∞ | 0.25× |

**Daily Challenge** uses a deterministic word-of-the-day, so everyone on
the planet fights the same word. **Survival** is an endless gauntlet:
every round costs you an undo and raises the score multiplier — one loss
ends the run.

## Abilities

- **↩️ Undo** — take back your last guess, *even a fatal one*.
- **🛟 Hint** — the oracle reveals a guaranteed-safe playable word.
- **👁️ Peek** — gamble: see 5 of the remaining words… the hidden word may
  be among them.
- **🎲 Random word** — fills the box with a random playable word, like the
  original's *Random Starting Word*.

Surviving with more 🟩/🟨 on the board scores higher; undos, hints and
peeks cost points. Copy-paste emoji share cards included.

## Run it

```bash
pip install -r requirements.txt
streamlit run app.py
```

Deploy free on [Streamlit Community Cloud](https://streamlit.io/cloud):
point it at this repo, main file `app.py`. Done.

## Architecture & testing

```
dontwordle/
  engine.py     pure game logic (zero UI deps)
  words.py      word lists, daily/random secrets
  simulate.py   self-play balance harness (python -m dontwordle.simulate)
  data/         2,315 secrets · 14,855 playable words
app.py          Streamlit UI
tests/          50 tests: engine units, self-play invariants, AppTest UI
```

The engine was tuned with thousands of simulated self-play games
(`python -m dontwordle.simulate 300`): Classic lands near a 25–45% bot
survival rate, Impossible near 3–5% — brutal but beatable.

```bash
python -m pytest
```

## Changelog

- **1.2.0** — six game modes, abilities (hint/peek/random word), survival
  gauntlet, per-mode stats & streaks, danger meter, emoji share cards,
  mode-scaled scoring, full test suite with self-play simulation.

## Credits

- Original concept: [dontwordle.com](https://dontwordle.com)
- Author: [Eugen Dimant](https://eugendimant.github.io)

## License

MIT — see [LICENSE](LICENSE).
