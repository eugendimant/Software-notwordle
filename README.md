# 🙅 DON'T Wordle

**The anti-Wordle.** Six guesses — and your only job is to *never* say the
hidden word. A fast, modern [Streamlit](https://streamlit.io) adaptation of
the cult classic [dontwordle.com](https://dontwordle.com), rebuilt from
scratch with extra game modes, abilities, move-quality analysis, four
dictionary languages, scoring and stats.

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
- **🎲 Random starting word** — a random opener, like the original
  (first guess only — mid-game randomness could land on the secret).
- **⚰️ Accept fate** — trapped with no undos? One click ends it with
  dignity.

Surviving with more 🟩/🟨 on the board scores higher; undos, hints and
peeks cost points. Copy-paste emoji share cards included.

## Languages & word lengths

Play with 🇬🇧 English, 🇩🇪 German, 🇷🇺 Russian or 🇪🇸 Spanish dictionaries —
the interface stays English — and pick your board size: **4 letters
(casual), 5 (classic) or 6 (expert)**. All twelve language×length
combinations have their own curated dictionaries (filtered against
native word lists, English loan-words, names and profanity), keyboard
layouts, daily words and stats. Input is normalized to dictionary
conventions (Russian ё→е, Spanish accents fold, ñ stays distinct).

## Input your way

Type your guess (Enter submits) or flip the sidebar switch to a fully
**clickable on-screen keyboard** — letters you've eliminated grey out
and lock, known letters glow green, and your picks preview live in the
grid.

## Progression & meta-game

- **⭐ XP and levels** — every game earns XP (score on wins, a little on
  losses); titles climb from *Word Novice* to *Grandmaster of Avoidance*.
- **🏆 15 achievements** — from First Dodge to the legendary 👻 Ghost
  (win revealing ≤8 clue tiles — simulation-tuned to ~1 in 20 sessions).
  Trophy case in the sidebar shows what's still locked.
- **🔥 Daily streaks** — consecutive daily wins per language & length,
  flaunted on the banner.
- **🎯 Daily side-quests** — one deterministic extra goal per day
  ("win without a single undo", +XP), same for every player.
- All progression travels with the stats backup file.

## Move analysis

- **Live safety rating** after every guess: a grade (🟢 brilliant → 🔴
  reckless), how many words your play kept alive, and the percentile of
  alternatives it beat.
- **🔬 Best-move review** after the game: row by row, the word that would
  have kept the most options open. Exact for pools ≤ 2,500 words,
  sampled above that — vectorized with numpy, so even the 14,855-word
  opening row is analyzed in well under a second.

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
  analysis.py   numpy-vectorized move-quality analyzer
  data/<lang>/  12 dictionaries: {en,de,ru,es} × {4,5,6}-letter words
app.py          Streamlit UI
tests/          120+ tests: engine, analysis, meta-game, self-play, AppTest UI
```

The engine was tuned with thousands of simulated self-play games per
language (`python -m dontwordle.simulate 300`): Classic lands near a
44–61% bot survival rate across languages, Impossible near 3–12% —
brutal but beatable.

```bash
python -m pytest
```

## Changelog

- **1.5.0.5** — double deep-check hardening (3 review agents): hostile
  backup files can no longer hang (unbounded XP → capped level math) or
  crash the app (float infinities and 400-digit JSON integers now
  rejected/clamped on every numeric field); daily XP/quests can't be
  re-farmed through backup restore (daily_done travels in the file);
  Polyglot/Triathlete progress survives restores; Houdini now requires
  actually *facing* the trap; quest banner and award agree across
  midnight; doc/desc accuracy pass. Plus docs/APP_STORE_GUIDE.md — the
  honest iPhone App Store playbook.
- **1.5.0.4** — engagement layer: XP & 10-title level ladder, 15
  achievements with sidebar trophy case and unlock toasts, per-language
  daily streaks with 🔥 banner, deterministic daily side-quests with XP
  bonuses, near-death drama tracking (Houdini/Daredevil unlocks);
  thresholds tuned via 40-session bot simulation; progression persists
  through stats backup (backward-compatible format).
- **1.5.0.3** — strategy intel: 🧨 endgame trap forecast (once ≤30 words
  remain, see how many of your playable words lead straight into a
  trap — hidden in Impossible, where you're on your own); 🗒️ Zen word
  browser (study the whole remaining pool while practicing); daily
  completion screen shows a countdown to the next word.
- **1.5.0.2** — frequency-weighted secrets: hidden words are drawn
  weighted by real spoken-language frequency (Zipf-style, 1/√rank — the
  common quartile supplies ~half of all games), so intuition about what
  people actually say becomes a strategy; all 12 answer lists reordered
  most-common-first; post-game reveal now appears after **wins** too,
  with the word's frequency rank ("a very common word, rank #123 of
  2,315"); how-to-play explains the weighting.
- **1.5.0.1** — mobile UX overhaul for the clickable keyboard: keyboard
  rows now stay horizontal on phones (previously Streamlit stacked every
  letter into a full-width row, forcing endless scrolling); compact
  evenly-stretched keys sized for thumbs; ability buttons collapse into
  one compact row; guess box and button stay side by side; shorter
  "Random start" label.
- **1.5.0.0** — word lengths 4/5/6 for every language (12 curated
  dictionaries); optional clickable on-screen keyboard with live grid
  preview, disabled eliminated letters and ⏎/⌫ keys; crash-proof widget
  callbacks on cold sessions (cloud cache restarts); centered banners
  and hardened header styling; move-rating pipeline capped-pool
  rescaling (6-letter openings rated in <1s); legacy stats keys
  auto-upgrade.
- **1.4.0.1** — dual independent review pass: de/es/ru secret lists
  rebuilt (native-dictionary ∩ frequency, minus English words, names and
  profanity; Russian pool rebuilt from curated nouns — no more word
  fragments); stale post-game analysis cleared on undo; daily practice
  replays no longer farm stats; daily hints/peeks deterministic per
  player order; fair mid-rank percentiles with 💀 fatal / ⚰️ forced
  grades; live and review ratings now always agree; one-shot animations;
  standard ЙЦУКЕН layout.
- **1.4.0.0** — four dictionary languages (🇬🇧🇩🇪🇷🇺🇪🇸) with per-language
  keyboards, dailies and stats; live move-safety ratings; post-game
  best-move review (numpy-vectorized); balance re-tuned per language with
  expanded dictionaries; UX overhaul: tile-flip reveals, error shake,
  pulsing trapped alert, log-scale danger gauge, refined header and
  keyboard. Version scheme extended to four digits.
- **1.3.0** — random word restricted to the opening guess (mid-game it
  could pre-fill the fatal word), typos no longer wipe your input,
  ⚰️ accept-fate button when trapped, itemized score breakdown,
  stats backup/restore (download + upload JSON), abilities hidden in
  modes that lack them, ∞ badges for Zen, win celebration fires once,
  rules auto-expanded for first-time players.
- **1.2.0** — six game modes, abilities (hint/peek/random word), survival
  gauntlet, per-mode stats & streaks, danger meter, emoji share cards,
  mode-scaled scoring, full test suite with self-play simulation.

## Credits

- Original concept: [dontwordle.com](https://dontwordle.com)
- Author: [Eugen Dimant](https://eugendimant.github.io)

## License

MIT — see [LICENSE](LICENSE).
