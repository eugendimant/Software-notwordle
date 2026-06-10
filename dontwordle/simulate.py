"""Self-play simulation harness — used for balance tuning and testing.

Run directly for a difficulty report:

    python -m dontwordle.simulate [games_per_preset]
"""

from __future__ import annotations

import random
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass

from . import words
from .engine import PRESETS, DontWordleGame, GameConfig, GameStatus


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
             use_undo: bool = True) -> DontWordleGame:
    """Play one full game, backtracking with undos like a careful human.

    Keeps a per-depth memory of words already tried so undos explore new
    branches instead of looping on a doomed one.
    """
    game = DontWordleGame(secret, words.allowed_guesses(), config, rng=rng)
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


def run(config: GameConfig, policy_name: str, n: int, seed: int = 0) -> SimResult:
    rng = random.Random(seed)
    policy = POLICIES[policy_name]
    res = SimResult()
    pool = words.answers()
    for _ in range(n):
        game = play_one(rng.choice(pool), config, policy, rng)
        res.played += 1
        res.survived += game.status is GameStatus.SURVIVED
        res.wordled += game.status is GameStatus.WORDLED
        res.undos += game.undos_used
        res.total_score += game.score()
    return res


def main() -> None:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    print(f"{'preset':<12}{'policy':<10}{'win rate':>9}{'avg undos':>11}"
          f"{'avg score':>11}")
    for key, cfg in PRESETS.items():
        for pname in POLICIES:
            r = run(cfg, pname, n, seed=42)
            print(f"{key:<12}{pname:<10}{r.win_rate:>8.1%}"
                  f"{r.undos / r.played:>11.2f}"
                  f"{r.total_score / max(1, r.survived):>11.1f}")


if __name__ == "__main__":
    main()
