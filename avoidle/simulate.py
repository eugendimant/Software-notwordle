"""Self-play simulation harness — used for balance tuning and testing.

Run directly for a difficulty report:

    python -m avoidle.simulate [games_per_preset]
"""

from __future__ import annotations

import random
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass

from . import words
from .engine import PRESETS, AvoidleGame, GameConfig, GameStatus


def policy_random(pool: list[str], rng: random.Random) -> str:
    """Naive player: any playable word (might be the secret — bad luck)."""
    return rng.choice(pool)


def policy_common_letters(pool: list[str], rng: random.Random) -> str:
    """Greedy survivor: prefer words with frequent letters so clues stay
    vague; mimics the 'common words' strategy from the official site."""
    freq = Counter(c for w in pool for c in set(w))
    sample = rng.sample(pool, min(200, len(pool)))
    return max(sample, key=lambda w: sum(freq[c] for c in set(w)))


POLICIES = {
    "random": policy_random,
    "common": policy_common_letters,
}


@dataclass
class SimResult:
    played: int = 0
    survived: int = 0
    wordled: int = 0
    undos: int = 0
    total_score: int = 0

    @property
    def win_rate(self) -> float:
        return self.survived / self.played if self.played else 0.0


def play_one(secret: str, config: GameConfig, policy, rng: random.Random,
             use_undo: bool = True, lang: str = "en") -> AvoidleGame:
    """Play one full game, backtracking with undos like a careful human.

    Keeps a per-depth memory of words already tried so undos explore new
    branches instead of looping on a doomed one.
    """
    game = AvoidleGame(secret, words.allowed_guesses(lang), config, rng=rng)
    tried: dict[int, set[str]] = defaultdict(set)
    while not game.is_over:
        depth = game.guesses_made
        options = [w for w in game.remaining_words if w not in tried[depth]]
        if not options:
            if use_undo and game.can_undo():
                # dead branch: back up and forget deeper exploration
                for d in [d for d in tried if d >= depth]:
                    del tried[d]
                game.undo()
                continue
            options = game.remaining_words  # cornered — play out the hand
        word = policy(options, rng)
        tried[depth].add(word)
        game.submit(word)
        if game.status is GameStatus.WORDLED and use_undo and game.can_undo():
            game.undo()  # same depth; the secret stays in tried[depth]
    return game


def run(config: GameConfig, policy_name: str, n: int, seed: int = 0,
        lang: str = "en") -> SimResult:
    rng = random.Random(seed)
    policy = POLICIES[policy_name]
    res = SimResult()
    pool = words.answers(lang)
    for _ in range(n):
        game = play_one(rng.choice(pool), config, policy, rng, lang=lang)
        res.played += 1
        res.survived += game.status is GameStatus.SURVIVED
        res.wordled += game.status is GameStatus.WORDLED
        res.undos += game.undos_used
        res.total_score += game.score()
    return res


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "duel":
        duel_main(int(sys.argv[2]) if len(sys.argv) > 2 else 1000)
        return
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    print(f"{'lang':<6}{'preset':<12}{'policy':<10}{'win rate':>9}"
          f"{'avg undos':>11}{'avg score':>11}")
    for lang in words.LANGUAGES:
        for key, cfg in PRESETS.items():
            for pname in POLICIES:
                r = run(cfg, pname, n, seed=42, lang=lang)
                print(f"{lang:<6}{key:<12}{pname:<10}{r.win_rate:>8.1%}"
                      f"{r.undos / r.played:>11.2f}"
                      f"{r.total_score / max(1, r.survived):>11.1f}")


# ----------------------------------------------------------------------
# Duel balance: python -m avoidle.simulate duel [n]
# ----------------------------------------------------------------------
def run_duels(level: str, n: int, player: str = "random", seed: int = 99,
              lang: str = "en", length: int = 5) -> float:
    """Player win rate over n duels against the given bot level.
    ``player``: 'random' (naive) or 'smart' (plays the answer-list meta)."""
    from .bot import bot_pick, _answer_rank
    rng = random.Random(seed)
    cfg = GameConfig("Duel", max_guesses=12, max_undos=0, max_hints=0,
                     max_peeks=1, score_multiplier=1.5)
    allowed = words.allowed_guesses(lang, length)
    ranks = _answer_rank(lang, length)
    wins = 0
    for _ in range(n):
        g = AvoidleGame(words.random_secret(lang, length, rng), allowed,
                           cfg, rng=rng)
        while not g.is_over:
            pool = g.remaining_words
            if g.guesses_made % 2 == 0:      # player's turn
                if player == "smart":
                    safe = [w for w in pool if w not in ranks]
                    word = (rng.choice(safe) if safe
                            else max(pool, key=lambda w: ranks.get(w, 0)))
                else:
                    word = rng.choice(pool)
            else:                            # bot's turn
                word = bot_pick(level, pool, lang, length, rng)
            g.submit(word)
        wins += (g.status is GameStatus.SURVIVED
                 or len(g.history) % 2 == 0)
    return wins / n


def duel_main(n: int) -> None:
    from .bot import BOT_LEVELS
    print(f"{'bot':<8}{'player':<8}{'player win rate':>16}")
    for level in BOT_LEVELS:
        for player in ("random", "smart"):
            rate = run_duels(level, n, player)
            print(f"{level:<8}{player:<8}{rate:>15.1%}")


if __name__ == "__main__":
    main()
