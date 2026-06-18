"""Offline word-list hygiene for Avoidle.

Drops allowed-*guess* words that appear in no large corpus (wordfreq
``zipf == 0``) — the non-words with no real definition, e.g. English
"efits". Answers (the curated secrets) are always kept, so no secret can
become unplayable. The bot's strategy is unchanged; it simply can no
longer reach a fake word.

    pip install wordfreq && python3 tools/clean_wordlists.py

Rewrites avoidle/data/<lang>/allowed_<len>.txt in place (sorted, unique).
"""
from pathlib import Path

from wordfreq import zipf_frequency

from avoidle import words as W

DATA = Path(__file__).resolve().parent.parent / "avoidle" / "data"


def main() -> None:
    for lang in W.LANGUAGES:
        for length in W.WORD_LENGTHS:
            path = DATA / lang / f"allowed_{length}.txt"
            words = [w for w in path.read_text(encoding="utf-8").split()
                     if len(w) == length and w.isalpha()]
            answers = set(W.answers(lang, length))
            kept = sorted({w for w in words
                           if w in answers or zipf_frequency(w, lang) > 0})
            path.write_text("\n".join(kept) + "\n", encoding="utf-8")
            print(f"{lang}/{length}: {len(words)} -> {len(kept)} "
                  f"({len(words) - len(kept)} non-words removed)")


if __name__ == "__main__":
    main()
