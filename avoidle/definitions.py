"""Short, best-effort definitions for the words on the board.

Players (and the duel bot) sometimes put up a word nobody recognises.
This module turns a played word into a one-line gloss so a hover or tap
on its row can answer "…what does that even mean?".

Source: Wiktionary's public REST ``definition`` endpoint, which covers
all four interface languages (en/de/es/ru) and returns the definition in
the word's own language. One network call per unique ``(word, lang)``,
cached process-wide for the life of the server.

Everything here is *best-effort and never fatal*: no network, a 404, a
slow endpoint, or junk JSON all resolve to ``None`` and the UI simply
says it has no definition. A misconfigured/offline deployment is capped
by a small circuit breaker so play never eats repeated timeouts.
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from functools import lru_cache

# A descriptive User-Agent is required by Wikimedia policy; a generic one
# gets a hard 403. Keep a contact/url in it.
_UA = "Avoidle/1.5 (+https://notwordle.streamlit.app)"
_TIMEOUT = 2.5            # seconds per request — snappy, fails fast
_MAX_LEN = 180            # trim long entries to a single readable line

_TAG = re.compile(r"<[^>]+>")          # strip Wiktionary's inline markup
_WS = re.compile(r"\s+")

# If the host has no outbound network every lookup would burn a full
# timeout; after a few consecutive failures we stop trying for the
# process so gameplay stays instant on offline deployments.
_FAIL_CAP = 3
_consecutive_fails = 0
_circuit_open = False


def reset_circuit() -> None:
    """Re-arm the network (used by tests; harmless in production)."""
    global _consecutive_fails, _circuit_open
    _consecutive_fails = 0
    _circuit_open = False


def _http_get(url: str) -> bytes:
    """Fetch raw bytes. Isolated so tests can monkeypatch it."""
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
                return f"{pos} — {gloss}" if pos else gloss
    return None


@lru_cache(maxsize=4096)
def define(word: str, lang: str) -> str | None:
    """A one-line definition for ``word`` in ``lang``, or ``None``.

    Cached for the process; safe to call on every rerun (a repeat is a
    dict hit). Any failure is swallowed and counts toward the circuit
    breaker that disables network lookups on offline hosts."""
    global _consecutive_fails, _circuit_open
    word = (word or "").strip().lower()
    if not word or not word.isalpha() or _circuit_open:
        return None
    url = (f"https://{lang}.wiktionary.org/api/rest_v1/page/definition/"
           + urllib.parse.quote(word))
    try:
        gloss = _parse(_http_get(url), lang)
        _consecutive_fails = 0          # a clean round trip re-arms us
        return gloss
    except Exception:
        _consecutive_fails += 1
        if _consecutive_fails >= _FAIL_CAP:
            _circuit_open = True        # give up on a no-egress host
        return None
