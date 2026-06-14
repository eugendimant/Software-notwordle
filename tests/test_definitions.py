"""Tests for the best-effort, multilingual word-definition lookup.

The network is never touched: ``_http_get`` is monkeypatched so the
parsing, multilingual fallback, caching, and circuit-breaker logic are
exercised in isolation.
"""

import json
import urllib.error

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


def _rest_payload(lang="en", pos="Noun", definition="A wading bird."):
    return json.dumps({lang: [{
        "partOfSpeech": pos, "language": "English",
        "definitions": [{"definition": definition}],
    }]}).encode("utf-8")


def _wikitext_payload(wikitext):
    return json.dumps({"parse": {"wikitext": wikitext}}).encode("utf-8")


def _http_error(code=404):
    return urllib.error.HTTPError("http://x", code, "err", {}, None)


# ---------------------------------------------------------------------------
# cleaning / REST parsing
# ---------------------------------------------------------------------------
def test_clean_strips_markup_and_clamps_length():
    assert D._clean("  a <b>big</b>\n  bird ") == "a big bird"
    out = D._clean("word " * 100)
    assert len(out) <= D._MAX_LEN and out.endswith("…")


def test_clean_drops_inlined_templatestyles_css():
    # Wiktionary inlines a <style> block (e.g. from {{defdate}}); its CSS
    # must never bleed into the gloss (the "OVATE …{font-size:smaller}" bug)
    wrapped = ('Shaped like an egg<style data-mw-deduplicate="TS:r1">'
               '.mw-parser-output .defdate{font-size:smaller}</style>')
    assert D._clean(wrapped) == "Shaped like an egg"
    # even if the tags were stripped upstream, the bare rule still goes
    bare = "Shaped like an egg .mw-parser-output .defdate{font-size:smaller}"
    assert D._clean(bare) == "Shaped like an egg"


def test_parse_prefers_the_played_language_and_prepends_pos():
    out = D._parse(_rest_payload("de", "Substantiv", "Ein Apfel."), "de")
    assert out == "(substantiv) Ein Apfel."


def test_parse_falls_back_to_any_section_when_language_absent():
    out = D._parse(_rest_payload("en", "Verb", "to hurry"), "es")
    assert out == "(verb) to hurry"


def test_parse_skips_empty_definitions():
    blob = json.dumps({"en": [{"partOfSpeech": "Noun", "definitions": [
        {"definition": "   "}, {"definition": "<a>real</a> meaning"}]}]})
    assert D._parse(blob.encode(), "en") == "(noun) real meaning"


def test_parse_handles_junk_gracefully():
    assert D._parse(b"not json", "en") is None
    assert D._parse(b"{}", "en") is None
    assert D._parse(json.dumps({"en": "nope"}).encode(), "en") is None


# ---------------------------------------------------------------------------
# wikitext stripping
# ---------------------------------------------------------------------------
def test_strip_wikitext_unwraps_links_and_drops_templates():
    raw = "a [[wading]] [[bird|birds]] {{lb|en|zoology}} that '''wades'''"
    assert D._strip_wikitext(raw) == "a wading birds  that wades".replace(
        "  ", " ")


def test_strip_wikitext_clears_nested_templates_refs_and_entities():
    raw = "fruit {{a|{{b|c}}}} of the tree<ref>Smith 2020</ref> &amp; more"
    out = D._strip_wikitext(raw)
    assert "{{" not in out and "}}" not in out
    assert "<ref" not in out and "Smith" not in out
    assert "& more" in out and "fruit" in out


def test_strip_wikitext_takes_the_display_text_of_multi_pipe_links():
    assert D._strip_wikitext("see [[a|b|caption]] now") == "see caption now"
    assert "[[" not in D._strip_wikitext("[[File:x|thumb|left]] text")


def test_via_wikitext_survives_a_malformed_parse_payload(monkeypatch):
    monkeypatch.setattr(D, "_http_get",
                        lambda u: b'{"parse": null}')
    assert D._via_wikitext("x", "en") is None
    monkeypatch.setattr(D, "_http_get",
                        lambda u: b'{"error": {"code": "missingtitle"}}')
    assert D._via_wikitext("x", "en") is None


# ---------------------------------------------------------------------------
# first-definition extraction per language convention
# ---------------------------------------------------------------------------
def test_first_definition_english_hash_lines():
    wt = ("==English==\n===Noun===\n"
          "# A large [[wading]] [[bird]].\n"
          "#: {{ux|en|The crane stood still.}}\n"
          "# A lifting [[machine]].\n")
    assert D._first_definition(wt) == "A large wading bird."


def test_first_definition_german_bracket_lines():
    wt = ("== Apfel ({{Sprache|Deutsch}}) ==\n"
          "{{Aussprache}}\n:{{IPA}} {{Lautschrift|ˈapfl̩}}\n"
          "{{Bedeutungen}}\n"
          ":[1] runde [[Frucht]] des [[Apfelbaum]]s\n"
          ":[2] etwas Apfelförmiges\n")
    assert D._first_definition(wt) == "runde Frucht des Apfelbaums"


def test_first_definition_spanish_semicolon_lines():
    wt = ("== {{lengua|es}} ==\n=== {{sustantivo masculino|es}} ===\n"
          ";1 {{ámbito|Zoología}}: [[mamífero]] [[doméstico]] cánido\n"
          ";2: persona despreciable\n")
    assert D._first_definition(wt) == "mamífero doméstico cánido"


def test_first_definition_russian_hash_with_piped_link():
    wt = ("= {{-ru-}} =\n=== Значение ===\n"
          "# [[печатное]] [[издание]] из [[сшитый|сшитых]] листов\n"
          "#* ''цитата''\n")
    assert D._first_definition(wt) == "печатное издание из сшитых листов"


def test_first_definition_skips_empty_form_of_template_line():
    wt = "# {{plural of|en|cat}}\n# a small domesticated [[feline]]\n"
    assert D._first_definition(wt) == "a small domesticated feline"


def test_first_definition_returns_none_without_any_definition():
    assert D._first_definition("== Heading ==\nsome prose\n") is None


def test_first_definition_handles_german_inflected_form():
    # an inflected form (plural) carries no [1] definition — fall back to
    # the grammatical description under {{Grammatische Merkmale}}
    wt = ("== Fäden ({{Sprache|Deutsch}}) ==\n"
          "=== {{Wortart|Deklinierte Form|Deutsch}} ===\n"
          "{{Worttrennung}}\n:Fä·den\n"
          "{{Aussprache}}\n:{{IPA}} {{Lautschrift|ˈfɛːdn̩}}\n"
          "{{Grammatische Merkmale}}\n"
          "*Nominativ Plural des Substantivs '''[[Faden]]'''\n"
          "*Genitiv Plural des Substantivs '''[[Faden]]'''\n"
          "{{Grundformverweis Dekl|Faden}}\n")
    assert D._first_definition(wt) == "Nominativ Plural des Substantivs Faden"


def test_first_definition_falls_back_to_base_form_pointer():
    # a conjugated form with only a base-form template still points home
    wt = ("=== {{Wortart|Konjugierte Form|Deutsch}} ===\n"
          "{{Grundformverweis Konj|weggehen}}\n")
    assert D._first_definition(wt) == "→ weggehen"


def test_first_definition_renders_a_form_of_template():
    # "# {{plural of|...}}" reduces to nothing in pass 1, but pass 2 reads
    # the template and renders a readable gloss
    assert D._first_definition("# {{plural of|es|perro}}\n") == \
        "plural of perro"


def test_form_of_gloss_renders_or_ignores():
    assert D._form_of_gloss("# {{plural of|en|cat}}") == "plural of cat"
    assert D._form_of_gloss("{{Grundformverweis Dekl|Faden}}") == "→ Faden"
    assert D._form_of_gloss("a [[bird]] {{lb|en|zoology}}") is None  # not form-of


def test_numbered_definition_still_wins_over_form_fallback():
    # a normal entry with both a definition and a form template: the
    # definition (pass 1) must win, never the form fallback (pass 2)
    wt = ("# a small domesticated [[feline]]\n"
          "# {{plural of|en|cats}}\n"
          "*see also something\n")
    assert D._first_definition(wt) == "a small domesticated feline"


# ---------------------------------------------------------------------------
# define(): tiers, multilingual fallback, capitalisation, breaker
# ---------------------------------------------------------------------------
def test_define_uses_clean_rest_result_first(monkeypatch):
    calls = []

    def fake_get(url):
        calls.append(url)
        return _rest_payload("en", "Noun", "A tall lifting machine.")

    monkeypatch.setattr(D, "_http_get", fake_get)
    assert D.define("crane", "en") == "(noun) A tall lifting machine."
    assert D.define("crane", "en").startswith("(noun)")   # cached
    assert len(calls) == 1                                 # one round trip
    assert "en.wiktionary.org" in calls[0] and calls[0].endswith("crane")


def test_define_falls_back_to_wikitext_when_rest_is_unavailable(monkeypatch):
    seen = []

    def fake_get(url):
        seen.append(url)
        if "rest_v1" in url:
            raise _http_error(404)                 # endpoint not deployed
        return _wikitext_payload(
            ":[1] runde [[Frucht]] des [[Apfelbaum]]s\n")

    monkeypatch.setattr(D, "_http_get", fake_get)
    assert D.define("apfel", "de") == "runde Frucht des Apfelbaums"
    assert any("rest_v1" in u for u in seen)       # tried the clean path
    assert any("api.php" in u for u in seen)       # then the fallback
    assert all("de.wiktionary.org" in u for u in seen)  # in German


def test_define_tries_the_capitalised_title_for_german_nouns(monkeypatch):
    def fake_get(url):
        if "rest_v1" in url:
            raise _http_error(404)
        if "page=Apfel" in url:                    # only the capitalised page
            return _wikitext_payload(
                ":[1] runde [[Frucht]] des [[Apfelbaum]]s\n")
        return json.dumps({"error": {"code": "missingtitle"}}).encode()

    monkeypatch.setattr(D, "_http_get", fake_get)
    assert D.define("apfel", "de") == "runde Frucht des Apfelbaums"


def test_define_queries_the_native_wiktionary_first_then_english(monkeypatch):
    hosts = []

    def fake_get(url):
        hosts.append(url)
        raise _http_error(404)

    monkeypatch.setattr(D, "_http_get", fake_get)
    D.define("perro", "es")
    # the word's own Wiktionary is exhausted before the English fallback
    assert "es.wiktionary.org" in hosts[0]
    first_en = next(i for i, u in enumerate(hosts) if "en.wiktionary.org" in u)
    assert all("es.wiktionary.org" in u for u in hosts[:first_en])


def test_via_english_rest_picks_the_played_language_section(monkeypatch):
    blob = json.dumps({"other": [
        {"language": "Italian", "partOfSpeech": "Noun",
         "definitions": [{"definition": "wrong language"}]},
        {"language": "Spanish", "partOfSpeech": "Noun",
         "definitions": [{"definition": "dog"}]},
    ]}).encode()
    monkeypatch.setattr(D, "_http_get", lambda url: blob)
    assert D._via_english_rest("perro", "es") == "(noun) dog"


def test_via_english_rest_ignores_other_languages(monkeypatch):
    only_de = json.dumps({"other": [{"language": "German",
        "partOfSpeech": "Noun",
        "definitions": [{"definition": "Hund"}]}]}).encode()
    monkeypatch.setattr(D, "_http_get", lambda url: only_de)
    assert D._via_english_rest("perro", "es") is None   # never wrong-language


def test_define_falls_back_to_english_when_native_is_empty(monkeypatch):
    def fake_get(url):
        if "en.wiktionary.org" in url:
            return json.dumps({"other": [{"language": "German",
                "partOfSpeech": "Noun",
                "definitions": [{"definition": "plural of Faden"}]}]}).encode()
        raise _http_error(404)               # native de wiki: nothing

    monkeypatch.setattr(D, "_http_get", fake_get)
    assert D.define("fäden", "de") == "(noun) plural of Faden"


def test_define_prefers_a_native_gloss_over_english(monkeypatch):
    seen = []

    def fake_get(url):
        seen.append(url)
        if "api.php" in url:                 # native de wikitext succeeds
            return _wikitext_payload(":[1] runde [[Frucht]]\n")
        raise _http_error(404)

    monkeypatch.setattr(D, "_http_get", fake_get)
    assert D.define("apfel", "de") == "runde Frucht"
    assert not any("en.wiktionary.org" in u for u in seen)   # never reached


def test_define_rejects_non_words_without_network(monkeypatch):
    monkeypatch.setattr(D, "_http_get",
                        lambda u: pytest.fail("must not fetch"))
    assert D.define("", "en") is None
    assert D.define("ab-cd", "en") is None


def test_http_404_never_trips_the_circuit_breaker(monkeypatch):
    monkeypatch.setattr(D, "_http_get", lambda u: (_ for _ in ()).throw(
        _http_error(404)))
    for w in ("alpha", "bravo", "charlie", "delta", "echo"):
        assert D.define(w, "en") is None
    assert not D._circuit_open               # 404 == server reachable
    assert D._consecutive_fails == 0


def test_circuit_breaker_stops_hammering_an_offline_host(monkeypatch):
    attempts = {"n": 0}

    def boom(url):
        attempts["n"] += 1
        raise OSError("no network")

    monkeypatch.setattr(D, "_http_get", boom)
    for w in ("alpha", "bravo", "charlie", "delta", "echo")[:D._FAIL_CAP]:
        assert D.define(w, "en") is None
    assert D._circuit_open
    before = attempts["n"]
    assert D.define("another", "en") is None     # circuit open: no fetch
    assert attempts["n"] == before


def test_a_clean_round_trip_re_arms_after_a_network_failure(monkeypatch):
    seq = [OSError("blip")]

    def flaky(url):
        if seq:
            raise seq.pop()
        return _rest_payload("en", "Noun", "ok now")

    monkeypatch.setattr(D, "_http_get", flaky)
    assert D.define("first", "en") is None
    assert D._consecutive_fails == 1
    assert D.define("second", "en") == "(noun) ok now"
    assert D._consecutive_fails == 0
