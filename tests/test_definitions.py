"""Tests for the best-effort word-definition lookup.

The network is never touched: ``_http_get`` is monkeypatched so the
parsing, caching, and circuit-breaker logic are exercised in isolation.
"""

import json

import pytest

from avoidle import definitions as D


@pytest.fixture(autouse=True)
def _clean_cache():
    """Each test starts with an empty cache and a re-armed circuit."""
    D.define.cache_clear()
    D.reset_circuit()
    yield
    D.define.cache_clear()
    D.reset_circuit()


def _payload(lang="en", pos="Noun", definition="A wading bird."):
    return json.dumps({lang: [{
        "partOfSpeech": pos, "language": "English",
        "definitions": [{"definition": definition}],
    }]}).encode("utf-8")


def test_clean_strips_markup_and_clamps_length():
    assert D._clean("  a <b>big</b>\n  bird ") == "a big bird"
    long = "word " * 100
    out = D._clean(long)
    assert len(out) <= D._MAX_LEN and out.endswith("…")


def test_parse_prefers_the_played_language_and_prepends_pos():
    out = D._parse(_payload("de", "Substantiv", "Ein Apfel."), "de")
    assert out == "substantiv — Ein Apfel."


def test_parse_falls_back_to_any_section_when_language_absent():
    # word only listed under a different code than the one requested
    out = D._parse(_payload("en", "Verb", "to hurry"), "es")
    assert out == "verb — to hurry"


def test_parse_skips_empty_definitions():
    blob = json.dumps({"en": [{"partOfSpeech": "Noun", "definitions": [
        {"definition": "   "}, {"definition": "<a>real</a> meaning"}]}]})
    assert D._parse(blob.encode(), "en") == "noun — real meaning"


def test_parse_handles_junk_gracefully():
    assert D._parse(b"not json", "en") is None
    assert D._parse(b"{}", "en") is None
    assert D._parse(json.dumps({"en": "nope"}).encode(), "en") is None


def test_define_fetches_parses_and_caches(monkeypatch):
    calls = []

    def fake_get(url):
        calls.append(url)
        return _payload("en", "Noun", "A tall machine for lifting.")

    monkeypatch.setattr(D, "_http_get", fake_get)
    assert D.define("crane", "en") == "noun — A tall machine for lifting."
    assert D.define("crane", "en").startswith("noun")   # second call cached
    assert len(calls) == 1                                # only one round trip
    assert "en.wiktionary.org" in calls[0] and calls[0].endswith("crane")


def test_define_rejects_non_words_without_network(monkeypatch):
    monkeypatch.setattr(D, "_http_get",
                        lambda u: pytest.fail("must not fetch"))
    assert D.define("", "en") is None
    assert D.define("ab-cd", "en") is None


def test_circuit_breaker_stops_hammering_an_offline_host(monkeypatch):
    attempts = {"n": 0}

    def boom(url):
        attempts["n"] += 1
        raise OSError("no network")

    monkeypatch.setattr(D, "_http_get", boom)
    # distinct alphabetic words so the lru_cache never short-circuits
    for w in ("alpha", "bravo", "charlie", "delta", "echo")[:D._FAIL_CAP]:
        assert D.define(w, "en") is None
    assert D._circuit_open
    before = attempts["n"]
    assert D.define("anotherword", "en") is None   # circuit open: no fetch
    assert attempts["n"] == before


def test_clean_round_trip_re_arms_after_a_failure(monkeypatch):
    seq = [OSError("blip")]

    def flaky(url):
        if seq:
            raise seq.pop()
        return _payload("en", "Noun", "ok now")

    monkeypatch.setattr(D, "_http_get", flaky)
    assert D.define("first", "en") is None       # one failure (not capped)
    assert D._consecutive_fails == 1
    assert D.define("second", "en") == "noun — ok now"
    assert D._consecutive_fails == 0             # success re-armed the count
