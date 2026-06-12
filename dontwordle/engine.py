"""Pure game logic for Don't Wordle. No UI dependencies — fully testable.

Rules (mirroring dontwordle.com):
  * The player makes up to ``max_guesses`` guesses and must NEVER guess
    the hidden secret word.
  * Every guess must be a real word AND consistent with every clue
    revealed so far (greens stay in place, yellows must be re-used,
    grays are forbidden) — i.e. the guess must still be a *possible*
    secret. The pool of such words is ``remaining_words``.
  * The secret is always inside ``remaining_words``; when the pool
    shrinks to 1 the player is trapped and must guess the secret
    (or spend an undo).
  * Undos take back the latest guess — including a losing one.
  * Survive all guesses without naming the secret to win.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import Enum

GREEN = "G"
YELLOW = "Y"
GRAY = "-"


def score_guess(guess: str, secret: str) -> str:
    """Standard Wordle feedback with correct duplicate handling.

    Returns a 5-char string of G (green), Y (yellow), - (gray).
    """
    if len(guess) != len(secret):
        raise ValueError("guess and secret must have equal length")
    guess = guess.lower()
    secret = secret.lower()
    feedback = [GRAY] * len(guess)
    available: dict[str, int] = {}
    for i, (g, s) in enumerate(zip(guess, secret)):
        if g == s:
            feedback[i] = GREEN
        else:
            available[s] = available.get(s, 0) + 1
    for i, g in enumerate(guess):
        if feedback[i] == GRAY and available.get(g, 0) > 0:
            feedback[i] = YELLOW
            available[g] -= 1
    return "".join(feedback)


def is_consistent(word: str, guess: str, feedback: str) -> bool:
    """Would ``word`` (as secret) have produced ``feedback`` for ``guess``?"""
    return score_guess(guess, word) == feedback


class GameStatus(Enum):
    PLAYING = "playing"
    SURVIVED = "survived"  # win
    WORDLED = "wordled"    # loss — the player guessed the secret


class InvalidGuess(Exception):
    """Raised by submit() for unplayable guesses; .reason explains why."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class GameConfig:
    label: str = "Classic"
    max_guesses: int = 6
    max_undos: int = 5
    max_hints: int = 1
    max_peeks: int = 1
    score_multiplier: float = 1.0

    def __post_init__(self) -> None:
        if self.max_guesses < 1:
            raise ValueError("max_guesses must be >= 1")
        if self.score_multiplier <= 0:
            raise ValueError("score_multiplier must be > 0")
        for name in ("max_undos", "max_hints", "max_peeks"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be >= 0")


# "Unlimited" budgets are a huge-but-finite number so the engine needs
# no special cases; the UI renders anything this large as ∞.
UNLIMITED = 10_000

PRESETS: dict[str, GameConfig] = {
    "zen": GameConfig("Zen", max_guesses=6, max_undos=UNLIMITED,
                      max_hints=UNLIMITED, max_peeks=UNLIMITED,
                      score_multiplier=0.25),
    "classic": GameConfig("Classic", max_guesses=6, max_undos=5,
                          max_hints=1, max_peeks=1),
    "hard": GameConfig("Hard", max_guesses=6, max_undos=2,
                       max_hints=0, max_peeks=1, score_multiplier=1.5),
    "impossible": GameConfig("Impossible", max_guesses=7, max_undos=0,
                             max_hints=0, max_peeks=0, score_multiplier=2.5),
}


@dataclass
class TurnRecord:
    guess: str
    feedback: str


@dataclass
class DontWordleGame:
    secret: str
    dictionary: frozenset[str]
    config: GameConfig = field(default_factory=GameConfig)
    rng: random.Random = field(default_factory=random.Random)

    def __post_init__(self) -> None:
        self.secret = self.secret.lower()
        self.word_length = len(self.secret)
        if self.secret not in self.dictionary:
            raise ValueError(f"secret {self.secret!r} must be a playable word")
        self.history: list[TurnRecord] = []
        self.status = GameStatus.PLAYING
        self.undos_used = 0
        self.hints_used = 0
        self.peeks_used = 0
        # Stack of remaining playable pools, one entry per turn played,
        # so undo is O(1). Element 0 is the full dictionary.
        self._pools: list[list[str]] = [sorted(self.dictionary)]
        # drama bookkeeping: the smallest pool ever reached this game
        # (deliberately NOT reverted by undo — a near-death stays lived)
        self.min_pool_seen = len(self._pools[0])
        self._trap_faced = False  # player acted while only the secret remained

    # ------------------------------------------------------------------
    # State inspection
    # ------------------------------------------------------------------
    @property
    def remaining_words(self) -> list[str]:
        """Words still playable (consistent with all clues so far)."""
        return self._pools[-1]

    @property
    def remaining_count(self) -> int:
        return len(self._pools[-1])

    @property
    def guesses_made(self) -> int:
        return len(self.history)

    @property
    def guesses_left(self) -> int:
        return self.config.max_guesses - len(self.history)

    @property
    def undos_left(self) -> int:
        return self.config.max_undos - self.undos_used

    @property
    def hints_left(self) -> int:
        return self.config.max_hints - self.hints_used

    @property
    def peeks_left(self) -> int:
        return self.config.max_peeks - self.peeks_used

    @property
    def is_over(self) -> bool:
        return self.status is not GameStatus.PLAYING

    @property
    def is_trapped(self) -> bool:
        """Only the secret itself remains playable. Undo or lose."""
        return (self.status is GameStatus.PLAYING
                and self._pools[-1] == [self.secret])

    @property
    def was_ever_trapped(self) -> bool:
        """Did the player ever have to act while trapped? (A final winning
        guess that merely collapses the pool to the secret doesn't count —
        no trap was actually faced.)"""
        return self._trap_faced

    def safe_words(self) -> list[str]:
        return [w for w in self._pools[-1] if w != self.secret]

    def pool_before(self, turn: int) -> list[str]:
        """The playable pool as it was before guess number ``turn`` (0-based).
        Useful for post-hoc move analysis."""
        return self._pools[turn]

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def validate(self, word: str) -> str | None:
        """Return a human-readable rejection reason, or None if playable."""
        word = word.strip().lower()
        if len(word) != self.word_length or not word.isalpha():
            return f"Enter a {self.word_length}-letter word."
        if word not in self.dictionary:
            return f"“{word.upper()}” is not in the dictionary."
        if any(t.guess == word for t in self.history):
            return f"You already played “{word.upper()}”."
        if word not in self._pools[-1]:
            return f"“{word.upper()}”: {self._diagnose_violation(word)}"
        return None

    def _diagnose_violation(self, word: str) -> str:
        """Pinpoint WHICH revealed clue the word breaks, most specific
        first, so the player learns the rule they tripped on."""
        from collections import Counter
        wc = Counter(word)
        for t in self.history:
            colored = Counter()
            for i, (gl, fl) in enumerate(zip(t.guess, t.feedback)):
                if fl == GREEN and word[i] != gl:
                    return (f"spot {i + 1} is locked to {gl.upper()} "
                            "(green).")
                if fl == YELLOW and word[i] == gl:
                    return (f"{gl.upper()} can't sit in spot {i + 1} again "
                            "— it was yellow there.")
                if fl != GRAY:
                    colored[gl] += 1
            for letter, need in colored.items():
                if wc[letter] < need:
                    return f"must use {letter.upper()} — it's a known letter."
            for gl, fl in zip(t.guess, t.feedback):
                if fl == GRAY and wc[gl] > colored.get(gl, 0):
                    return f"{gl.upper()} was ruled out — it's gray."
        return "it breaks the revealed clues."

    def submit(self, word: str) -> TurnRecord:
        if self.is_over:
            raise InvalidGuess("The game is over.")
        if self.is_trapped:
            self._trap_faced = True
        word = word.strip().lower()
        reason = self.validate(word)
        if reason:
            raise InvalidGuess(reason)
        feedback = score_guess(word, self.secret)
        turn = TurnRecord(word, feedback)
        self.history.append(turn)
        self._pools.append(
            [w for w in self._pools[-1] if is_consistent(w, word, feedback)]
        )
        self.min_pool_seen = min(self.min_pool_seen, len(self._pools[-1]))
        if word == self.secret:
            self.status = GameStatus.WORDLED
        elif len(self.history) >= self.config.max_guesses:
            self.status = GameStatus.SURVIVED
        return turn

    def can_undo(self) -> bool:
        return (bool(self.history)
                and self.undos_left > 0
                and self.status is not GameStatus.SURVIVED)

    def undo(self) -> bool:
        """Take back the latest guess (allowed even after losing)."""
        if not self.can_undo():
            return False
        if self.is_trapped:
            self._trap_faced = True  # undoing out of a trap = facing it
        self.history.pop()
        self._pools.pop()
        self.undos_used += 1
        self.status = GameStatus.PLAYING
        return True

    def hint(self, chooser=None) -> str | None:
        """Reveal a guaranteed-safe playable word (never the secret).
        ``chooser(safe_words, rng)`` may pick smartly; default is random."""
        if self.hints_left <= 0 or self.is_over:
            return None
        safe = self.safe_words()
        if not safe:
            return None
        self.hints_used += 1
        if chooser is not None:
            return chooser(safe, self.rng)
        return self.rng.choice(safe)

    def peek(self, k: int = 5) -> list[str]:
        """Gamble: sample up to k remaining words — may include the secret."""
        if self.peeks_left <= 0 or self.is_over:
            return []
        pool = self._pools[-1]
        self.peeks_used += 1
        return sorted(self.rng.sample(pool, min(k, len(pool))))

    # ------------------------------------------------------------------
    # Scoring & sharing
    # ------------------------------------------------------------------
    TILE_POINTS = {GREEN: 15, YELLOW: 8, GRAY: 2}
    SURVIVAL_BONUS = 100
    UNDO_COST = 10
    HINT_COST = 30
    PEEK_COST = 15

    def score(self) -> int:
        """Final score; surviving with more revealed clues scores higher."""
        return self.score_breakdown()["total"]

    def score_breakdown(self) -> dict[str, float]:
        """Itemized scoring, for display. All zeros unless the player won."""
        if self.status is not GameStatus.SURVIVED:
            return {"base": 0, "tiles": 0, "penalties": 0,
                    "multiplier": self.config.score_multiplier, "total": 0,
                    "floored": False}
        tiles = sum(self.TILE_POINTS[c] for t in self.history for c in t.feedback)
        penalties = (self.undos_used * self.UNDO_COST
                     + self.hints_used * self.HINT_COST
                     + self.peeks_used * self.PEEK_COST)
        raw = round((self.SURVIVAL_BONUS + tiles - penalties)
                    * self.config.score_multiplier)
        return {"base": self.SURVIVAL_BONUS, "tiles": tiles,
                "penalties": penalties,
                "multiplier": self.config.score_multiplier,
                "total": max(10, raw), "floored": raw < 10}

    EMOJI = {GREEN: "🟩", YELLOW: "🟨", GRAY: "⬜"}

    def share_text(self, title: str = "Don't Wordle",
                   won: bool | None = None) -> str:
        """Emoji result card. ``won`` overrides the outcome line for modes
        with their own win semantics (e.g. duels won by the opponent's
        blunder)."""
        if won is None:
            won = self.status is GameStatus.SURVIVED
        outcome = "I SURVIVED 🎉" if won else "I Wordled 💀"
        undo_word = "undo" if self.undos_used == 1 else "undos"
        lines = [f"{title} — {outcome}",
                 f"{self.guesses_made}/{self.config.max_guesses} guesses · "
                 f"{self.undos_used} {undo_word} · score {self.score()}"]
        lines += ["".join(self.EMOJI[c] for c in t.feedback) for t in self.history]
        return "\n".join(lines)
