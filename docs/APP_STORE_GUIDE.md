# 📱 Taking DON'T Wordle to the iPhone App Store — The Complete Playbook

*Prepared for Eugen Dimant · v2.0 (updated for game v1.5.0.13) · honest edition*

---

## 0. Read this first: three facts that decide everything

### Fact 1 — A Streamlit app cannot be submitted to the App Store
What runs at `*.streamlit.app` is a **server-rendered website**. Apple's
**Guideline 4.2 (Minimum Functionality)** explicitly rejects apps that
"are simply a website bundled as an app" — a WebView wrapper pointed at
the Streamlit URL is the single most common rejection in the store.
It would also die without internet and lag on every tap (every
interaction round-trips to a Python server). **Nobody can wrap this
repo and get accepted.** A real client build is required (Section 2).

### Fact 2 — The name "DON'T Wordle" is a trademark problem
**WORDLE® is a registered trademark of The New York Times** (acquired
January 2022, USPTO Reg. No. 97184961 family). The NYT has actively
issued takedowns against Wordle-named clones since 2022. Submitting
under this name risks:
- rejection under **Guideline 5.2 (Intellectual Property)** and
  **4.1 (Copycats)**;
- a trademark complaint *after* approval, which can nuke the listing
  and strike your developer account.

**Action: rename for the store.** The *mechanic* (colored letter tiles)
is not protectable and dozens of approved games use it — only the name
and trade dress are the issue. Candidates that keep the hook (see Section 11 for the full
brainstorm): **Avoidle**, **Don't Say It!**, **DodgeWord**.
⚠️ **Avoid any name *containing* the string "Wordle"** — including
"UnWordle" or "NotWordle": the mark is inside the name, which is
exactly what NYT's takedowns target. The "-dle" *suffix* on its own
has proven safe (Quordle, Nerdle, Heardle all lived on the store).
Also: never mention "Wordle" in the app name, subtitle, keywords or
screenshots (**Guideline 2.3.7** bans referencing other brands in
metadata). You *may* describe it as "the anti word-guessing game."

### Fact 3 — Nobody can guarantee instant acceptance
Average review time is 24–48 h and ~40 % of first submissions get at
least one rejection. What you *can* do is eliminate every known
rejection cause before submitting — that is what the checklist in
Section 5 is for. Plan for one rejection-and-resubmit cycle in your
launch timeline anyway.

---

## 1. Choose your path

| Path | Effort | Store? | Verdict |
|------|--------|--------|---------|
| **A. PWA** — host the Streamlit app, players "Add to Home Screen" | hours | ❌ | Do this **today** to validate virality while building B/C |
| **B. Capacitor + offline JS port** | 2–4 weeks | ✅ | **Recommended.** Port the engine to TypeScript, ship a fully offline hybrid app with native juice |
| **C. Native SwiftUI rebuild** | 4–8 weeks | ✅ | Best feel/performance; do later if the game takes off |

Why B works where wrappers fail: the game runs **100 % on-device**
(offline play), and you add genuinely native capabilities — haptics on
tile flips, the iOS share sheet for result cards, **daily-word push
notifications**, Game Center leaderboards/achievements, a home-screen
widget showing today's streak. That package comfortably clears 4.2.

**This repo is the spec.** The port is mechanical because the game is
already isolated from the UI:
- `dontwordle/engine.py` (pure logic incl. trap tracking) → TypeScript 1:1
- `dontwordle/analysis.py` (move ratings, best-move review, trap
  forecast, smart hints) → TypeScript; ship in v1 — it's a signature
  feature
- `dontwordle/achievements.py` (15 achievements, XP/levels, daily
  side-quests) → map 1:1 to **Game Center achievements** + a Game
  Center leaderboard on total XP
- `dontwordle/bot.py` (3 fair duel opponents, balance validated over
  24,000 simulated duels) → TypeScript; Duel is the headline mode for
  the store listing ("play AGAINST the bot — whoever says the word
  loses")
- `dontwordle/words.py` + `dontwordle/data/**` → ship as JSON assets
  (12 dictionaries: en/de/es/ru × 4/5/6 letters, frequency-ordered,
  profanity-filtered — the filtering matters for the 4+ age rating)
- `tests/` (145 tests) → port the engine/bot/achievement suites as the
  conformance suite; if the TS engine passes, the game is identical

### Feature inventory the iOS build must include (game v1.5.0.13)
- 7 modes: Daily, Classic, 🤖 Duel (3 bot strengths), Hard, Impossible,
  Survival gauntlet, Zen
- 4 languages × 3 word lengths, per-combo daily words (crc32 scheme —
  keep identical so web + iOS players share the same daily)
- Abilities: undo, smart hint, peek, random start, accept-fate
- Live move-safety ratings + post-game best-move review + endgame trap
  forecast
- XP/levels (10 titles), 15 achievements, daily streaks + 28-day
  heatmap, daily side-quests
- Persistence: replace the web cookie with native storage (UserDefaults
  / Capacitor Preferences) — strictly better, no 4 KB ceiling
- Share cards (emoji grid + level/trophy line) → iOS share sheet

---

## 2. Build plan (Path B)

1. **Port the engine** to TypeScript: `scoreGuess`, consistency filter,
   pool stack, undo, scoring, frequency-weighted secret selection
   (answers files are already frequency-ordered; daily word = same
   crc32 scheme so web and iOS players share the daily).
2. **Build the UI** in React/Vue/Svelte (Capacitor wraps any of them):
   board, flip animations, clickable keyboard (layouts in `words.py`),
   danger meter, trap forecast, achievements, share cards. Reuse the
   visual design — dark theme, #538d4e/#b59f3b/#3a3a3c tiles.
3. **Persistence**: `localStorage`/Capacitor Preferences replaces the
   backup-file dance — streaks and XP simply persist. (This alone is a
   big UX upgrade over the web version.)
4. **Native layer** (Capacitor plugins): Haptics, Share, Local
   Notifications ("Your daily word is ready — protect the 🔥 streak"),
   Game Center (leaderboard: total XP, weekly score; achievements:
   the 15 from `achievements.py`).
5. **Test on real devices** via TestFlight (Section 4): iPhone SE
   (smallest screen — the 6-letter board must fit), iPhone Pro Max,
   iPad if you ship universal.

---

## 3. Apple accounts & certificates (one-time, ~1 day)

1. **Apple Developer Program** — enroll at developer.apple.com with
   your Apple ID ($99/year). Individual enrollment is fine (your name
   shows as seller; an LLC needs a D-U-N-S number).
2. **Xcode** (Mac required) — latest version from the App Store.
3. **Bundle ID** — e.g. `io.github.eugendimant.dontsayit` (Certificates,
   Identifiers & Profiles → Identifiers → +). Enable capabilities:
   Push Notifications, Game Center.
4. **Signing** — in Xcode: Settings → Accounts → your team →
   "Automatically manage signing." Don't fight certificates manually.
5. **App Store Connect** — appstoreconnect.apple.com → My Apps → + →
   New App: platform iOS, your bundle ID, SKU (any string), name.

---

## 4. TestFlight before review (do not skip)

1. Xcode → Product → Archive → Distribute → App Store Connect.
2. In App Store Connect → TestFlight: add internal testers (you, 2–3
   friends with iPhones).
3. **Soak for a week.** Apple reviewers do exactly what testers do in
   the first 90 seconds: launch, rotate, background the app, kill it
   mid-game, replay, tap everything. Crashes in the first session are
   rejection 2.1 — the #1 cause.
4. Fix, re-archive, repeat until a full week is crash-free.

---

## 5. The listing (this is where acceptance is won)

### Metadata
- **Name** (30 chars): `Don't Say It! — Anti Word Game` *(no "Wordle")*
- **Subtitle** (30 chars): `Dodge the hidden word & win`
- **Keywords** (100 chars, comma-separated, no brand names):
  `word,game,puzzle,daily,anti,avoid,letters,brain,streak,vocabulary,german,spanish,russian`
- **Description**: lead with the twist ("The word game where guessing
  the answer means you LOSE"), then modes, languages, achievements.
  No competitor names, no "#1", no unverifiable claims (2.3.1).
- **Promotional text** (170 chars, updatable without review): use for
  event hooks ("New: 6-letter expert boards!").
- **Category**: Games → Word. Secondary: Games → Puzzle.
- **Age rating questionnaire**: everything "No" → **4+** (the word
  lists are already profanity-filtered — done in v1.4.0.1, keep it that
  way; a single vulgar solution word found by a reviewer is a rejection).

### Screenshots (required sizes, no device frames needed)
- 6.9" (iPhone 16 Pro Max) and 6.5" (11 Pro Max) — mandatory.
- 5–8 images, first two do all the work: ① mid-game board with the
  danger meter screaming "5 WORDS REMAINING", ② the win screen with
  confetti + score, ③ trophy case, ④ languages/lengths picker,
  ⑤ share card. Add one-line captions in the images.
- Record a 15–30 s **app preview video** of a dramatic endgame.

### Privacy (Guideline 5.1 — huge rejection source, easy for you)
- The game stores everything on-device and collects **nothing**.
- App Privacy section → "Data Not Collected" (only valid if you add
  **no** analytics/ads SDK — keep it that way for v1; it's also a
  marketing asset: "No ads. No tracking. Just the game.").
- Still required: a **privacy policy URL** — add a one-page
  `privacy.html` to eugendimant.github.io stating no data is collected.

### Review information
- Fill "Notes for Review": "Fully offline word game. No account needed.
  To see a full game quickly: play any 4-letter casual game. Daily
  notification is optional and asks permission in-app."
- Demo account: N/A (no login — say so explicitly).

---

## 6. Pre-submission checklist (every known rejection cause)

- [ ] **2.1 Completeness**: no crashes (week of TestFlight), no
      placeholder text, all links work, notification permission asked
      *in context* (after first daily, not at launch).
- [ ] **4.2 Minimum functionality**: fully offline ✓, haptics ✓,
      share sheet ✓, notifications ✓, Game Center ✓ — list these in
      review notes.
- [ ] **5.2 IP / 4.1 Copycat**: renamed ✓, no "Wordle" anywhere in
      binary or metadata ✓, original icon/branding (do NOT imitate the
      NYT tile logo) ✓.
- [ ] **2.3 Metadata**: screenshots show real gameplay only, age
      rating honest, no brand references.
- [ ] **5.1 Privacy**: policy URL live, nutrition label "Data Not
      Collected", no third-party SDKs.
- [ ] **4.0 Design**: respects safe areas/notch, dark mode native,
      supports iPhone SE screen, no broken rotation (lock portrait —
      acceptable and simpler).
- [ ] **3.1 Payments**: v1 is free with no purchases = nothing to
      review. (Add IAP "tip jar"/themes later via a normal update.)
- [ ] Version 1.0.0, build number incremented per upload.

Submit → "Automatically release after approval" OFF for v1 (release
manually so launch day is yours).

---

## 7. The viral playbook (what actually makes word games spread)

1. **The share card is the product.** The emoji grid + "I SURVIVED 🎉"
   already exists — in the app make it one tap → iOS share sheet, and
   append the App Store link. Wordle grew 90→300k users on this alone.
2. **One shared daily word per language** (already deterministic in the
   engine) → people compare. Push notification at 9:00 local: "today's
   word has 14,855 ways to dodge it."
3. **Streak protection = retention.** The 🔥 streak is built; surface it
   in the app icon badge and the widget.
4. **Launch sequence**: PWA live first (Path A) → collect a waitlist on
   eugendimant.github.io → TestFlight link to the first 100 (TestFlight
   scarcity is its own marketing) → App Store release + Product Hunt +
   r/wordgames + the original dontwordle community → ASO iterate on
   keywords every 2 weeks.
5. **Game Center leaderboards** give the competitive loop without
   building a backend.

---

## 8. What you pay Apple (exact numbers)

| Item | Cost | Mandatory? |
|---|---|---|
| Apple Developer Program | **$99/year** (≈€99) | Yes — the only mandatory fee |
| App review, hosting, TestFlight, Game Center | $0 | included |
| Revenue cut on a **free app with no purchases** | **$0 — Apple takes nothing** | n/a |
| If you later add purchases (tip jar, themes) | 15% of revenue (Small Business Program, under $1M/yr); 30% above | only if you sell |
| A Mac to build with | you need access to macOS + Xcode | borrow, or rent a cloud Mac (MacStadium/Scaleway ~$20–50/mo for the build weeks) |

So: **$99/year, full stop**, for a free app — and the first year is the only certain cost.

## 9. Honest acceptance-risk assessment

| Approach | Rejection risk |
|---|---|
| WebView wrapper around the Streamlit site | **~certain rejection** (Guideline 4.2) — don't try |
| Proper offline port, but named with "Wordle" in it | **High** — 5.2 IP / 4.1 copycat, plus NYT takedown exposure even post-approval |
| Proper offline port, original name, checklist followed | **Good odds.** Industry-wide ~60% of first submissions pass; with the Section 6 checklist (the known rejection causes) you're well above that. Realistic worst case: one rejection for something cosmetic → fix → resubmit → approved within days |

What could still trip you despite everything: a reviewer hitting a crash you never saw (mitigate: the TestFlight soak week), a metadata nit (screenshot shows UI not in the binary), or a subjective 4.3 "spam/saturated category" call — rare for games with this much original mechanics (Duel mode is your strongest differentiation argument; mention it in Review Notes). **Nobody can guarantee first-pass approval; plan the launch date with one review cycle of slack.**

## 10. Timeline & budget

| Week | Milestone |
|------|-----------|
| 0 | PWA live (Path A) · Developer Program enrollment · rename decided |
| 1–2 | TypeScript engine port, passes ported test suite |
| 2–3 | UI + native plugins, runs on device |
| 4 | TestFlight soak, screenshots, listing, privacy page |
| 5 | Submit → review (1–2 days) → manual release 🚀 |

Costs: $99/yr developer program. Everything else is free.

---

*The Python repo remains the source of truth for game rules, balance
numbers and word lists. Any behavior question during the port is
answered by `tests/` — if the TS engine passes the ported suite, it IS
the game.*
