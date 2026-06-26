# 🚫 Avoidle

**Avoidle** — the word game where guessing the answer means you LOSE.
Six guesses, and your only job is to *never* say the hidden word. A fast, modern [Streamlit](https://streamlit.io) adaptation of
the cult classic [dontwordle.com](https://dontwordle.com), rebuilt from
scratch with extra game modes, abilities, move-quality analysis, four
dictionary languages, scoring and stats.

> Built by [Eugen Dimant](https://eugendimant.github.io) · current version
> in [`avoidle/__init__.py`](avoidle/__init__.py)

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
| 🧘 Zen | 6 | ∞ | ∞ | ∞ | 0.25× |
| 🔥 Hard | 6 | 2 | 0 | 1 | 1.5× |
| 💀 Impossible | **7** | 0 | 0 | 0 | 2.5× |
| ⚔️ Survival | 6/round | 5 → 0 | early rounds | 1 | climbs +25%/round |
| 🆚 Duel | 12 rows | 0 | 0 | 1 | 1×–2.5× by bot |

The mode menu follows that progression — the everyday puzzles, the
no-pressure practice room, the solo difficulty ladder, the endless run,
and the bot showdown — with a one-glance blurb under every option.

**Daily Challenge** uses a deterministic word-of-the-day, so everyone on
the planet fights the same word. **Survival** is an endless gauntlet:
every round costs you an undo and raises the score multiplier — one loss
ends the run. **🆚 Duel** is hot potato against a fair bot at three
strengths — 😴 Easy, 🤖 Normal, ♟️ Hard. Every bot plays with public
information only (it can genuinely blunder into the secret), but **Hard
reasons recursively**: once the playable pool is small it *solves* the
duel by backward induction — "if I play X, you're forced to play Y, so
I play Z…" — searching the full alternating game tree to find a move
that corners you. It doesn't know the secret, so it runs that minimax
across its belief about which word is hidden. Measured over 24,000
simulated duels: a skilled player who broke even against the old
heuristic Hard bot (50%) now wins just **40%** against the recursive
one (naive players 36% → 30%); tougher bots pay bigger multipliers.

## Abilities

- **↩️ Undo** — take back your last guess, *even a fatal one*.
- **💡 Hint** — the oracle reveals a guaranteed-safe playable word.
- **👁️ Peek** — gamble: see 5 of the remaining words… the hidden word may
  be among them.
- **🎲 Random starting word** — a random opener, like the original
  (first guess only — mid-game randomness could land on the secret).
- **⚰️ Accept fate** — trapped with no undos? One click ends it with
  dignity.

Surviving with more 🟩/🟨 on the board scores higher; undos, hints and
peeks cost points. Copy-paste emoji share cards included.

## Languages & word lengths

Play with 🇺🇸 English, 🇩🇪 German, 🇷🇺 Russian or 🇪🇸 Spanish dictionaries —
the interface stays English — and pick your board size: **4 letters
(casual), 5 (classic) or 6 (expert)**. All twelve language×length
combinations have their own curated dictionaries (filtered against
native word lists, English loan-words, names and profanity), keyboard
layouts, daily words and stats. Input is normalized to dictionary
conventions (Russian ё→е, Spanish accents fold, ñ stays distinct).

## Input your way

A compact, phone-style **clickable keyboard** is the default — letters
you've eliminated grey out and lock, known letters glow green, and your
picks preview live in the grid. Prefer typing? Flip the sidebar switch
(Enter submits).

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
- **💾 Progress persists automatically** — XP, trophies, streaks and
  daily history are saved in a browser cookie and restored on your next
  visit; the backup file remains for moving between devices.
- **📆 Streak heatmap** — a 28-day calendar of your daily wins in the
  sidebar.

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
avoidle/
  engine.py     pure game logic (zero UI deps)
  words.py      word lists, daily/random secrets
  simulate.py   self-play balance harness (python -m avoidle.simulate)
  analysis.py   numpy-vectorized move-quality analyzer
  endgame.py    recursive backward-induction duel solver
  data/<lang>/  12 dictionaries: {en,de,ru,es} × {4,5,6}-letter words
app.py          Streamlit UI
tests/          120+ tests: engine, analysis, meta-game, self-play, AppTest UI
```

The engine was tuned with thousands of simulated self-play games per
language (`python -m avoidle.simulate 300`): Classic lands near a
44–61% bot survival rate across languages, Impossible near 3–12% —
brutal but beatable.

```bash
python -m pytest
```

## Changelog

- **1.5.3.2** — **⚔️ worldwide duel win-rate**: under the games odometer
  the sidebar now shows what share of duels humans win against the AI, as
  a single percentage (no counts). It starts near **32%** and every
  finished duel nudges it. Same durable-floor design as the odometer
  (monotonic cookie + heal-on-read; seed overridable with
  `AVOIDLE_DUEL_SEED="wins/total"`).
- **1.5.3.1** — **the worldwide counter never resets again**: the default
  SQLite file lives on ephemeral disk and is wiped on every redeploy, and
  a stale save could overwrite the browser's remembered count with a low
  value — so the odometer occasionally fell back to 0. The remembered
  floor is now strictly **monotonic** (never saved lower than seen),
  **healed on every read** (a wiped file is lifted straight back), and
  anchored by an optional **`AVOIDLE_GAMES_FLOOR`** env var / Streamlit
  secret (secrets survive redeploys). For *full* permanence set
  **`DATABASE_URL`** to a free external Postgres (Neon/Supabase) — the
  store switches to it automatically. *(To restore your ~70: set
  `AVOIDLE_GAMES_FLOOR = "70"` in Streamlit secrets.)*
- **1.5.3.0** — **real words only**: every playable guess across all four
  languages is now a genuine, definable word. The allowed-guess lists were
  scrubbed of corpus-absent non-words (e.g. English "efits") using word
  frequencies, so the duel bot can never put up a fake word and a typed
  guess always has a meaning to look up. Secrets are untouched and the bot
  keeps its full unpredictable strategy — it just can't reach a non-word.
  (Offline cleaner: `tools/clean_wordlists.py`.)
- **1.5.2.3** — definitions now speak your language: a **📖 row
  definition is glossed in whichever language you're playing** (German
  words explained in German, Spanish in Spanish, Russian in Russian),
  because the lookup targets that language's own Wiktionary — with a
  universal fallback that reads each Wiktionary's own definition markup,
  and a capitalised-title retry so German nouns resolve. New title-page
  and sidebar line: **"whatever you do: don't say the word."** Game modes
  are now listed **alphabetically**. (Hardened along the way: the
  definition circuit-breaker no longer trips on plain 404s, only on real
  network failures.)
- **1.5.2.2** — know your words, mind the clock: **📖 row definitions**
  — hover or tap any played row (yours *or* the duel bot's) to see a
  one-line gloss of what that word means, pulled best-effort from
  Wiktionary in all four languages and cached per word (offline-safe: a
  no-network host degrades to a quiet "no definition found" and never
  stalls play). And the timer is now a flexible **⏱️ Time crunch**: still
  off by default and lockable before your first word, but you pick the
  pace — **⚡30s / 🏃1m / 🚶2m / 🧘3m / 🐢5m** per move — instead of a
  fixed three minutes. Plus a desktop comfort: your **physical keyboard
  now works in either input mode** — in clickable mode real keystrokes
  drive the on-screen keys (Enter submits, Backspace deletes), and in
  typing mode the box auto-focuses so you can just start typing.
- **1.5.2.1** — the world plays together: a **server-side database**
  (self-creating SQLite, zero setup; auto-upgrades to any external DB if
  a `DATABASE_URL` secret ever exists) now holds a **🌍 worldwide
  games odometer** counting every finished game by every visitor — it
  self-heals from returning players' cookies and never goes backward —
  plus **cross-device nickname slots** (type your name on any device to
  continue; freshest copy of cookie vs. server wins) and a
  **🏅 leaderboard** (top names by XP and wins) that appears once a
  critical mass of 5 named players exists. Roulette got richer too:
  💰 a growing points pot paid out on survival, a rare 🌟 jackpot, and
  the wheel never lands on the same twist twice in a row. Hardened:
  junk cookie values can never mint a save slot.
- **1.5.2.0** — the wheel, the clock and the name: new **🎰 Roulette**
  mode (after every guess the wheel spins a twist — bonus undos, oracle
  clues, imp thefts, a forced letter, or the hidden word itself secretly
  re-rolled among the words that still fit every clue); optional
  **⏱️ turn timer** in every mode (3:00 per play, lock it in before the
  first word — overruns cost a hint, then a peek, then an undo, then the
  game, with a live client-side countdown); optional **👤 nicknames** as
  save slots so several players can keep separate stats/XP/streaks in
  one browser; an all-time **games-played odometer** that never resets;
  a 💬 suggest-a-feature button; the duel bot now takes a properly
  human 2–4½ s to "think"; the Rules chip no longer wraps mid-word on
  phones; the best-move review names the safe alternative even on the
  fatal row; and the mode selector can never again disagree with the
  board (widget state self-heals to the actual game).
- **1.5.1.1** — the verdict rail: every played row now shows its grade,
  kept-count and percentile in the space right of the tiles (phones keep
  the compact line under the keyboard); more breathing room between the
  board and the keyboard; the duel bot "thinks" for a variable, human
  beat with a visible progress bar (longer when it's solving the
  endgame); the Game-mode ? and the menu itself now carry one-glance
  blurbs for every mode, ordered as a progression (everyday → practice →
  difficulty ladder → survival → duel).
- **1.5.1.0** — recursive reasoning: the Hard duel bot now *solves*
  the endgame by backward induction (minimax over the full alternating
  game tree) instead of a one-step heuristic — it reasons several moves
  ahead ("if I play X you're forced to Y…") across its belief about the
  hidden word, staying fair (it never sees the secret). New
  `avoidle/endgame.py`, cross-checked against an independent naive
  minimax on 511 positions; the bot got measurably stronger (skilled
  players 50% → 40%, naive 36% → 30% over 24k duels) at 1–2 ms per move,
  with a wall-clock deadline bounding pathological positions (5.4s →
  0.4s, clean heuristic fallback). Surfaced in-game: Hard "solves the
  endgame…" while thinking, and the post-game review shows the
  recursive "forced win" debrief.
- **1.5.0.19** — front-page alignment round (3 iterations): the
  keyboard now behaves like a real keyboard — constant 42px keys with
  shorter rows centered and indented, instead of every row stretching
  to equal width (keys used to get visibly wider on 9-key rows);
  geometry verified for all four layouts incl. Russian's 12-key row;
  the topbar is symmetric (banner truly centered, Rules chip balancing
  on the right); the danger gauge no longer outweighs the board;
  sidebar stats are one tidy line instead of cramped metric tiles;
  control heights unified with the keyboard's line weight.
- **1.5.0.18** — professional UX calm pass: one compact centered status
  line under the keyboard replaces stacked full-width alert boxes (the
  trapped state was being announced three times at once); move ratings
  become a muted sub-line; ability and accept-fate buttons are
  button-sized and centered instead of page-wide; quieter meter labels
  and reserve note; duel banner slimmed. The duel bot now visibly
  "thinks" — your tiles flip first, an animated 👾 thinking… beat plays
  (~0.5s), then the bot's row lands with its own flip. Footer reads
  "built by Dr. Eugen Dimant" (research site only).
- **1.5.0.17** — front-page fit & compatibility round: title no longer
  clipped under Streamlit's toolbar; board, keyboard and abilities all
  fit one laptop screen (compact 44px tiles, tighter rhythm, slimmer
  counters/gauge, Rules chip shares a row with the mode banner); duel
  boards grow as you play (2 upcoming rows + "+N in reserve") instead
  of stacking 12 empty rows above the keyboard; emoji compatibility
  sweep for older Windows fonts (🆚 Duel, 👾 bot, 💡 hint, ♟️ hard,
  🎩/🎢 trophies, 💣 intel); and the hot-redeploy error class is closed
  for good — app.py now version-checks the cached game modules and
  evicts them on mismatch, so a cloud source update can never again mix
  new app code with old module signatures.
- **1.5.0.16** — three deep review rounds (2 agents + perf/simulation
  matrices + failure-injection chaos): the three crash-safety layers
  now share ONE reset helper (a render crash could permanently block
  the next game's stats; redeploy healing leaked the old game's
  hint/peek/banners); duel endgame intel was giving exactly inverted
  advice (in duel, "trap" words corner the BOT — they're guaranteed
  wins, now said so) and told undo-less modes to undo; duel share cards
  showed score 0 and counted bot rows as your guesses (engine
  share_text gained score/guesses overrides); mode/language/length
  switches are atomic with rollback (a failed board build could leave
  duel chrome — and bot replies! — on a daily board); analysis failures
  degrade to a neutral rating instead of desyncing history; viewing
  stats no longer creates empty entries; perf re-profiled (boot 0.2s,
  guess 0.8s, 12 analyzers = 30MB) and balance matrices re-validated.
- **1.5.0.15** — crash-proofing after a production incident (a redeploy
  left live sessions holding old-module game objects whose exceptions
  the new code couldn't catch by class identity): every callback is now
  wrapped in a safety net that converts any exception into a friendly
  message, stale session objects are detected and healed on rerun, and
  a recovery shell replaces the crash page as a last resort — verified
  by a 220-action chaos simulation injecting corrupt objects and
  exploding internals (zero crashes). Also: fixed the accidental
  monospace look (a wrong font fallback), tightened header/sidebar
  spacing and centered the Rules chip.
- **1.5.0.14** — 🚫 the game is now **AVOIDLE**: full rebrand (package,
  class names, UI, share cards, docs) with a professional tile wordmark
  (AVOID on slate, LE on green, red "do not cross" bar); loss verb is
  now "you said the word"; App Store guide locked to the Avoidle name
  and bundle id. Daily-word seeds and saved progress are untouched —
  existing players keep their words, streaks and cookies.
- **1.5.0.13** — thorough review round (2 agents): real zlib-bomb cap
  on backup/cookie decoding (the old guard was ineffective — a 3KB
  upload could balloon to 200MB); duel fairness fixes: the bot's tiles
  no longer count toward your achievements/score, the best-move review
  covers only your rows, 12-row outlast wins now pay the bot-level
  multiplier, and Houdini can't unlock off the bot's trap; cookie
  history pruned to what the app needs so persistence never silently
  stops for long-term players; duel balance reproducible via
  `python -m avoidle.simulate duel`; rules text notes Duel has no
  undos.
- **1.5.0.12** — duel bots got a difficulty ladder: 😴 Easy (reckless,
  gravitates toward likely secrets), 🤖 Normal (dodges the likeliest
  quartile), ♟️ Hard (plays provably-safe non-answer words while they
  exist); all fair — public info only. Balance validated over 24,000
  simulated duels (4,000 per cell, naive and skilled players); Easy
  re-tuned from 51% to 59% beginner win rate; win multipliers 1×/1.5×/
  2.5× by strength; selector in the sidebar restarts the duel fairly.
- **1.5.0.11** — top-3 improvement round: 💾 automatic progress
  persistence (compressed browser cookie, auto-restored on fresh
  sessions — streaks finally survive a page refresh); 🆚 Duel mode
  (alternate guesses vs a fair bot, whoever says the word loses;
  simulated 52% baseline player win rate, ~5 rows per duel); 📆 28-day
  daily-wins heatmap in the sidebar.
- **1.5.0.10** — mobile polish round: ability buttons no longer
  overflow (compact labels + smaller phone font); the ⏎ submit key is
  now green so it's unmissable; author + GitHub links in a footer on
  the page itself (the sidebar is collapsed on phones); decluttered
  top-of-page (tagline hidden on small screens, smaller title, daily
  date/streak/quest merged into one line); ❓ Rules popover under the
  header toggles the rules on/off anywhere.
- **1.5.0.9** — clue-violation errors now name the exact rule you broke
  ("E can't sit in spot 3 again — it was yellow there" / "spot 4 is
  locked to N (green)" / "T was ruled out — it's gray" / "must use E")
  instead of a generic catch-all; alert text compacted to fit one line.
- **1.5.0.8** — flags render everywhere: Windows ships no flag emojis
  (browsers showed bare "GB DE" codes), so a Twemoji country-flag web
  font now covers exactly the flag codepoints on every OS; 🇺🇸 American
  English label; clickable keyboard is the default input (typing is the
  toggle); keyboard restyled compact and centered like a phone keyboard
  instead of sprawling across desktop.
- **1.5.0.7** — 🕑 session recap in the sidebar (last games with
  outcome and score, practice replays included); share cards now carry
  your level and trophy count for extra bragging rights.
- **1.5.0.6** — the oracle got smart: 💡 hints now suggest the safest
  sampled word (keeps ~3.6× more words alive than a random safe word,
  measured over 25 positions); 🔥 streak-at-risk nudge in the sidebar
  when today's daily is still unplayed.
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
- **1.5.0.3** — strategy intel: 💣 endgame trap forecast (once ≤30 words
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
