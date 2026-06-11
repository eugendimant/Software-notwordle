"""Achievements, XP and levels — the meta-game that keeps players coming
back. Pure logic, no UI dependencies.

A finished game is summarized into a :class:`GameContext`; ``evaluate``
returns newly unlocked achievements, ``xp_for_game`` the XP earned, and
``level_for_xp`` the player's current level, title and progress.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Achievement:
    id: str
    emoji: str
    name: str
    description: str


@dataclass
class GameContext:
    """Everything needed to judge a finished game."""
    mode: str
    lang: str
    length: int
    won: bool
    score: int = 0
    undos: int = 0
    hints: int = 0
    peeks: int = 0
    greens: int = 0
    yellows: int = 0
    min_pool_seen: int = 10**9
    final_pool: int = 10**9
    was_trapped: bool = False        # actually faced a 1-word pool
    survival_round: int = 1
    streak: int = 0                  # mode streak after this game
    total_wins: int = 0              # across all modes/langs/lengths
    rating_percentiles: list = field(default_factory=list)
    langs_won: set = field(default_factory=set)     # incl. this game
    lengths_won: set = field(default_factory=set)   # incl. this game


def _won(ctx: GameContext) -> bool:
    return ctx.won


ACHIEVEMENTS: dict[str, tuple[Achievement, object]] = {
    a.id: (a, p) for a, p in [
        (Achievement("first_win", "🏆", "First Dodge",
                     "Survive your first game."),
         _won),
        (Achievement("purist", "🧘", "Purist",
                     "Win without undos, hints or peeks."),
         lambda c: c.won and c.undos + c.hints + c.peeks == 0),
        (Achievement("daredevil", "🪂", "Daredevil",
                     "Win a game where only 2 words were left standing."),
         lambda c: c.won and c.min_pool_seen == 2),
        (Achievement("houdini", "🪄", "Houdini",
                     "Get trapped — only the secret left — and still win."),
         lambda c: c.won and c.was_trapped),
        # thresholds tuned by simulation: Ghost ≈ 1% of wins ≈ 1 in 20
        # twelve-game sessions (the theoretical floor is 8 — full gray is
        # impossible under the consistency rule); Greenhouse ≈ 10% of wins
        (Achievement("ghost", "👻", "Ghost",
                     "Win revealing 8 clue tiles or fewer."),
         lambda c: c.won and c.greens + c.yellows <= 8),
        (Achievement("greenhouse", "🌿", "Greenhouse",
                     "Win with 18+ green tiles glowing on the board."),
         lambda c: c.won and c.greens >= 18),
        (Achievement("untouchable", "🛡️", "Untouchable",
                     "Win an Impossible game."),
         lambda c: c.won and c.mode == "impossible"),
        (Achievement("gauntlet5", "⚔️", "Gauntlet Veteran",
                     "Reach round 5 of Survival and win it."),
         lambda c: c.won and c.mode == "survival" and c.survival_round >= 5),
        (Achievement("calculated", "🎓", "Calculated",
                     "Win with every move rated above the 60th percentile "
                     "(4+ moves)."),
         lambda c: c.won and len(c.rating_percentiles) >= 4
         and min(c.rating_percentiles) >= 60),
        (Achievement("high_roller", "💎", "High Roller",
                     "Score 400+ in a single game."),
         lambda c: c.won and c.score >= 400),
        (Achievement("polyglot", "🌍", "Polyglot",
                     "Win games in two different languages."),
         lambda c: c.won and len(c.langs_won) >= 2),
        (Achievement("triathlete", "📏", "Triathlete",
                     "Win at all three word lengths."),
         lambda c: c.won and c.lengths_won >= {4, 5, 6}),
        (Achievement("streak3", "🔥", "On Fire",
                     "Win 3 in a row in the same mode "
                     "(per language & length)."),
         lambda c: c.won and c.streak >= 3),
        (Achievement("streak7", "🌋", "Unstoppable",
                     "Win 7 in a row in the same mode "
                     "(per language & length)."),
         lambda c: c.won and c.streak >= 7),
        (Achievement("veteran25", "🎖️", "Veteran",
                     "Survive 25 games in total."),
         lambda c: c.won and c.total_wins >= 25),
    ]
}


def evaluate(ctx: GameContext, unlocked: set[str]) -> list[Achievement]:
    """Newly unlocked achievements for a finished game."""
    fresh = []
    for aid, (ach, predicate) in ACHIEVEMENTS.items():
        if aid not in unlocked and predicate(ctx):
            fresh.append(ach)
    return fresh


# ----------------------------------------------------------------------
# XP & levels
# ----------------------------------------------------------------------
LOSS_XP = 10           # participation; losing still teaches you something
UNLOCK_XP = 50         # per fresh achievement


def xp_for_game(ctx: GameContext, fresh_unlocks: int = 0) -> int:
    base = ctx.score if ctx.won else LOSS_XP
    return base + UNLOCK_XP * fresh_unlocks


TITLES = (
    "Word Novice", "Dodge Apprentice", "Evasion Adept", "Trap Dancer",
    "Clue Juggler", "Pool Shark", "Risk Architect", "Word Phantom",
    "Anti-Wordle Sage", "Grandmaster of Avoidance",
)


XP_CAP = 10**9         # sanity ceiling (also enforced on backup import)


def _xp_to_advance(level: int) -> int:
    """XP needed to go from ``level`` to ``level + 1`` (gentle ramp)."""
    return 250 + 150 * (level - 1)


def level_for_xp(xp: int) -> dict:
    """Level, title, and progress toward the next level."""
    level = 1
    remaining = min(max(0, int(xp)), XP_CAP)  # capped: O(√cap) worst case
    while remaining >= _xp_to_advance(level):
        remaining -= _xp_to_advance(level)
        level += 1
    title = (TITLES[level - 1] if level <= len(TITLES)
             else f"Avoidance Legend {level - len(TITLES)}")
    return {"level": level, "title": title, "into": remaining,
            "needed": _xp_to_advance(level)}


# ----------------------------------------------------------------------
# Daily side-quests: one deterministic extra goal per daily puzzle
# ----------------------------------------------------------------------
@dataclass(frozen=True)
class Quest:
    id: str
    label: str
    xp: int


QUESTS: dict[str, tuple[Quest, object]] = {
    q.id: (q, p) for q, p in [
        (Quest("no_undo", "win without a single undo", 150),
         lambda c: c.won and c.undos == 0),
        (Quest("ghostly", "win revealing at most 12 clue tiles", 200),
         lambda c: c.won and c.greens + c.yellows <= 12),
        (Quest("wide_open", "win with 100+ words still alive", 150),
         lambda c: c.won and c.final_pool >= 100),
        (Quest("greenery", "win with 14+ green tiles showing", 200),
         lambda c: c.won and c.greens >= 14),
        (Quest("no_help", "win without hints or peeks", 100),
         lambda c: c.won and c.hints + c.peeks == 0),
    ]
}


def daily_quest(date_iso: str, lang: str, length: int) -> Quest:
    """Deterministic side-quest of the day (same for every player)."""
    import zlib
    ids = sorted(QUESTS)
    key = f"quest:{date_iso}:{lang}:{length}"
    return QUESTS[ids[zlib.crc32(key.encode()) % len(ids)]][0]


def quest_completed(quest_id: str, ctx: GameContext) -> bool:
    return QUESTS[quest_id][1](ctx)
