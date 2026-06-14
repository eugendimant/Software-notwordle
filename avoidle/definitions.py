"""Short, best-effort definitions for the words on the board.

Players (and the duel bot) sometimes put up a word nobody recognises.
This module turns a played word into a one-line gloss so a hover or tap
on its row can answer "…what does that even mean?".

The gloss is always returned **in the language being played** — German
words are defined in German, Spanish in Spanish, and so on — because the
lookup targets that language's own Wiktionary:

1. **Tier 1 — the REST ``definition`` endpoint**
   (``{lang}.wiktionary.org/api/rest_v1/page/definition/{word}``). Clean,
   structured glosses, but only fully deployed on a few Wiktionaries
   (English for sure), so it is just the fast path.
2. **Tier 2 — the MediaWiki action API's wikitext**
   (``{lang}.wiktionary.org/w/api.php?action=parse&prop=wikitext``). Every
   Wiktionary has this, and definitions are universally the lines that
   start with ``#`` — so this is the reliable multilingual fallback.

Because Wiktionary titles are case-sensitive and German nouns are
capitalised, each tier is tried on both the lower-case word and its
capitalised form.

Everything is *best-effort and never fatal*: a 404, junk, or no network
all resolve to ``None`` and the UI simply says it has no definition. A
small circuit breaker disables lookups after repeated *network* failures
(a 404 means the server is reachable and never trips it), so an offline
deployment never eats repeated timeouts.
"""

from __future__ import annotations

import html as _html
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from functools import lru_cache

# A descriptive User-Agent is required by Wikimedia policy; a generic one
# gets a hard 403. Keep a contact/url in it.
_UA = "Avoidle/1.5 (+https://notwordle.streamlit.app)"
_TIMEOUT = 2.5            # seconds per request — snappy, fails fast
_MAX_LEN = 180            # trim long entries to a single readable line

_TAG = re.compile(r"<[^>]+>")          # strip inline HTML
_WS = re.compile(r"\s+")

# Only *network* failures (no HTTP response at all) count toward the
# breaker; after a few in a row we stop trying for the process so an
# egress-less host stays instant.
_FAIL_CAP = 3
_consecutive_fails = 0
_circuit_open = False


def reset_circuit() -> None:
    """Re-arm the network (used by tests; harmless in production)."""
    global _consecutive_fails, _circuit_open
    _consecutive_fails = 0
    _circuit_open = False


def _http_get(url: str) -> bytes:
    """Fetch raw bytes. Isolated so tests can monkeypatch it. Raises
    ``urllib.error.HTTPError`` on a 4xx/5xx and ``URLError`` (or another
    ``OSError``) when the host cannot be reached at all."""
    req = urllib.request.Request(
        url, headers={"User-Agent": _UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        return resp.read()


def _clean(text: str) -> str:
    """Strip markup/whitespace and clamp to one readable line."""
    text = _WS.sub(" ", _TAG.sub("", text or "")).strip()
    if len(text) > _MAX_LEN:
        text = text[:_MAX_LEN - 1].rstrip(" ,;:.") + "…"
    return text


# ----------------------------------------------------------------------
# Tier 1: the structured REST definition endpoint
# ----------------------------------------------------------------------
def _parse(payload: bytes, lang: str) -> str | None:
    """Pull the first usable gloss out of a Wiktionary definition blob.

    The endpoint returns ``{lang_code: [ {partOfSpeech, definitions:[...]},
    ... ]}``. Prefer the section for the language being played; fall back
    to whatever section exists (some words are only listed once)."""
    try:
        data = json.loads(payload.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict) or not data:
        return None
    sections = data.get(lang) or next(iter(data.values()), None)
    if not isinstance(sections, list):
        return None
    for section in sections:
        if not isinstance(section, dict):
            continue
        pos = _clean(str(section.get("partOfSpeech", ""))).lower()
        for entry in section.get("definitions", []) or []:
            gloss = _clean(str((entry or {}).get("definition", "")))
            if gloss:
                return f"({pos}) {gloss}" if pos else gloss
    return None


def _via_rest(title: str, lang: str) -> str | None:
    url = (f"https://{lang}.wiktionary.org/api/rest_v1/page/definition/"
           + urllib.parse.quote(title))
    return _parse(_http_get(url), lang)


# ----------------------------------------------------------------------
# Tier 2: the universal wikitext fallback (definitions are the # lines)
# ----------------------------------------------------------------------
_WIKILINK = re.compile(r"\[\[(?:[^\[\]]*\|)?([^\[\]|]+)\]\]")   # [[a|b]]->b
_APOSTROPHES = re.compile(r"'{2,5}")          # ''italic'' / '''bold'''
_REF = re.compile(r"<ref[^>]*>.*?</ref>", re.S)
_REF_SELF = re.compile(r"<ref[^>]*/\s*>")
_COMMENT = re.compile(r"<!--.*?-->", re.S)


def _strip_templates(text: str) -> str:
    """Remove ``{{...}}`` templates, innermost first so nesting clears."""
    prev = None
    while prev != text:
        prev = text
        text = re.sub(r"\{\{[^{}]*\}\}", "", text)
    return text


def _strip_wikitext(text: str) -> str:
    """Turn one wikitext definition line into clean readable prose."""
    text = _COMMENT.sub("", text)
    text = _REF.sub("", text)
    text = _REF_SELF.sub("", text)
    text = _strip_templates(text)
    text = _WIKILINK.sub(r"\1", text)
    text = text.replace("[[", "").replace("]]", "")   # any odd leftovers
    text = _APOSTROPHES.sub("", text)
    text = _html.unescape(text)
    return _clean(text)


# Each Wiktionary marks up its definition lines differently; these cover
# the four interface languages (and most others). Each captures the
# definition text in group 1.
_DEF_LINE = (
    re.compile(r"^#+(?![:*#])\s*(.+)$"),                 # en / ru: "# def"
    re.compile(r"^:*\[(?=[^\]]*\d)[^\]]*\]\s*(.+)$"),    # de: ":[1] def"
    re.compile(r"^;\s*\d+[a-z]?[^:]*:\s*(.+)$"),         # es: ";1: def"
)

# a bullet line, optionally sense-numbered: German inflected forms list
# their grammar this way ("*Nominativ Plural des Substantivs [[Faden]]")
_BULLET = re.compile(r"^\*+\s*(?:\[[^\]]*\d[^\]]*\]\s*)?(.+)$")

# templates that mark an inflected / form-of entry, across editions
_FORMOF_KEYS = ("of", "form", "verweis", "grundform", "flex", "plural",
                "singular", "inflect", "particip", "konjug", "deklin",
                "nominativ", "genitiv", "dativ", "akkusativ", "forma")


def _form_of_gloss(line: str) -> str | None:
    """Render an inflection/form-of template into a short gloss, e.g.
    ``{{plural of|de|Faden}}`` -> "plural of Faden", or a bare base-form
    pointer (German ``{{Grundformverweis Dekl|Faden}}``) -> "→ Faden"."""
    m = re.search(r"\{\{\s*([^{}|]+?)\s*((?:\|[^{}]*)*)\}\}", line)
    if not m:
        return None
    name = m.group(1).strip()
    low = name.lower()
    if not any(k in low for k in _FORMOF_KEYS):
        return None
    pos = [p.strip() for p in m.group(2).split("|")[1:]
           if p.strip() and "=" not in p]      # positional params only
    if pos and re.fullmatch(r"[a-z]{2,3}", pos[0]):
        pos = pos[1:]                           # drop a leading language code
    # the lemma is the first positional that's an actual word
    lemma = next((p for p in pos if re.search(r"[^\W\d_]", p)), None)
    if not lemma:
        return None
    lemma = _strip_wikitext(lemma)
    if not lemma:
        return None
    if low.endswith(" of") or low == "of":
        return _clean(f"{name} {lemma}")
    return _clean(f"→ {lemma}")


def _first_definition(wikitext: str) -> str | None:
    """The first real definition line, in the page's own language.

    A word's own Wiktionary lists its primary-language entry first, so the
    first definition line is the gloss in that language. Examples
    (``#:``), quotations (``#*``), pronunciation/etymology lines, and
    lines that reduce to nothing (a bare form-of template) are all passed
    over. Inflected forms (e.g. a plural) carry no numbered definition, so
    a second pass falls back to their grammatical description or the base
    word they point to."""
    lines = [raw.strip() for raw in wikitext.splitlines()]
    for line in lines:                      # pass 1: a numbered definition
        for pattern in _DEF_LINE:
            m = pattern.match(line)
            if not m:
                continue
            gloss = _strip_wikitext(m.group(1))
            if gloss and re.search(r"\w", gloss):
                return gloss
            break          # matched a def marker but empty — next line
    for line in lines:                      # pass 2: an inflected form
        m = _BULLET.match(line)
        if m:
            gloss = _strip_wikitext(m.group(1))
            if gloss and re.search(r"\w", gloss):
                return gloss
        form = _form_of_gloss(line)
        if form:
            return form
    return None


def _via_wikitext(title: str, lang: str) -> str | None:
    url = (f"https://{lang}.wiktionary.org/w/api.php?action=parse"
           "&prop=wikitext&format=json&formatversion=2&redirects=1"
           "&page=" + urllib.parse.quote(title))
    data = json.loads(_http_get(url).decode("utf-8"))
    parse = data.get("parse") if isinstance(data, dict) else None
    wikitext = parse.get("wikitext") if isinstance(parse, dict) else None
    if not isinstance(wikitext, str):
        return None                        # missing page -> {"error": ...}
    return _first_definition(wikitext)


def _note_network_failure() -> None:
    global _consecutive_fails, _circuit_open
    _consecutive_fails += 1
    if _consecutive_fails >= _FAIL_CAP:
        _circuit_open = True               # give up on a no-egress host


@lru_cache(maxsize=4096)
def define(word: str, lang: str) -> str | None:
    """A one-line definition for ``word`` in ``lang``, or ``None``.

    Always glossed in ``lang`` (it queries that language's Wiktionary).
    Cached for the process; safe to call on every rerun."""
    global _consecutive_fails
    word = (word or "").strip().lower()
    if not word or not word.isalpha() or _circuit_open:
        return None
    # case-sensitive titles: try the word, then its capitalised form
    # (German nouns live under "Apfel", not "apfel")
    titles = [word]
    capitalised = word[:1].upper() + word[1:]
    if capitalised != word:
        titles.append(capitalised)
    for title in titles:
        for fetch in (_via_rest, _via_wikitext):
            try:
                gloss = fetch(title, lang)
            except urllib.error.HTTPError:
                _consecutive_fails = 0     # reachable, just no page/endpoint
                continue
            except Exception:
                _note_network_failure()    # genuinely offline: stop here
                return None
            _consecutive_fails = 0         # an HTTP response = we're online
            if gloss:
                return gloss
    return None
