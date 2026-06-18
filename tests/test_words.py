"""Word-list hygiene: every playable guess is a real (corpus-present)
word, and every secret stays a legal guess in every language."""

from avoidle import words as W


def test_reported_non_word_is_purged_but_real_words_remain():
    allowed = W.allowed_guesses("en", 5)
    assert "efits" not in allowed                 # the reported non-word
    # real words (common and obscure-but-genuine) are kept
    for real in ("crane", "vroom", "fjord", "plumb", "blurb"):
        assert real in allowed


def test_every_secret_is_still_a_legal_guess():
    for lang in W.LANGUAGES:
        for length in W.WORD_LENGTHS:
            allowed = W.allowed_guesses(lang, length)
            # secrets are drawn from answers — they must stay playable
            assert set(W.answers(lang, length)) <= allowed
            assert len(allowed) > 2_000           # still a deep guess pool
