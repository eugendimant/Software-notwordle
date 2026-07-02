"""GitHub-backed durable counter for the worldwide games total.

Streamlit Cloud runs the app on ephemeral disk that is wiped whenever the
app sleeps/wakes or redeploys, so the default SQLite odometer keeps
resetting. This module keeps the true total in a file **in the repo
itself** (``games_count.txt`` on a side branch), so it survives every
restart:

* **read** — the raw file is public, so any run can fetch the latest
  count with no credentials (GitHub's CDN caches it ~5 min, which is fine
  for a floor that only ever rises);
* **write** — publishing a new count needs a ``GITHUB_TOKEN`` secret with
  ``contents: write`` on the repo. Writes go to the ``game-stats`` side
  branch, NOT the deployment branch, so they never trigger a redeploy.

Everything is best-effort and never raises to the caller: no token, no
network, or an API hiccup simply means the count isn't published this
tick — the game is never affected.
"""

from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.parse
import urllib.request

_DEFAULT_REPO = "eugendimant/Software-notwordle"
_DEFAULT_BRANCH = "game-stats"
_PATH = "games_count.txt"
_UA = "Avoidle/1.5 (+https://notwordle.streamlit.app)"
_TIMEOUT = 4.0


def _cfg(key: str, default: str = "") -> str:
    """An env var or Streamlit secret (both survive redeploys)."""
    val = os.environ.get(key, "").strip()
    if not val:
        try:
            import streamlit as st
            val = str(st.secrets.get(key, "")).strip()
        except Exception:
            val = ""
    return val or default


def _repo() -> str:
    return _cfg("AVOIDLE_STATS_REPO", _DEFAULT_REPO)


def _branch() -> str:
    return _cfg("AVOIDLE_STATS_BRANCH", _DEFAULT_BRANCH)


def _token() -> str:
    return _cfg("GITHUB_TOKEN")


def _http(url: str, headers: dict, data: bytes | None = None,
          method: str | None = None) -> bytes:
    """Isolated network primitive (tests monkeypatch this)."""
    req = urllib.request.Request(url, data=data, headers=headers,
                                 method=method)
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        return resp.read()


def _parse_count(text: str) -> int:
    try:
        return max(0, int(text.strip().split()[0]))
    except (ValueError, IndexError):
        return 0


def read_count() -> int:
    """The published total from the raw file, or 0 if unavailable."""
    url = (f"https://raw.githubusercontent.com/{_repo()}/{_branch()}/"
           + urllib.parse.quote(_PATH))
    try:
        raw = _http(url, {"User-Agent": _UA, "Cache-Control": "no-cache"})
        return _parse_count(raw.decode("utf-8", "replace"))
    except Exception:
        return 0


def publish(count: int) -> bool:
    """Commit ``count`` to the side branch, but only if it RAISES the
    stored value. Needs a ``GITHUB_TOKEN`` with contents:write. Returns
    True when the repo already holds >= count or the write succeeded."""
    token = _token()
    if not token or not isinstance(count, int) or count <= 0:
        return False
    api = (f"https://api.github.com/repos/{_repo()}/contents/"
           + urllib.parse.quote(_PATH))
    hdr = {"User-Agent": _UA, "Authorization": f"Bearer {token}",
           "Accept": "application/vnd.github+json",
           "X-GitHub-Api-Version": "2022-11-28"}
    ref = urllib.parse.quote(_branch())
    try:
        sha = None
        try:
            meta = json.loads(_http(api + f"?ref={ref}", hdr))
            sha = meta.get("sha")
            existing = _parse_count(
                base64.b64decode(meta.get("content", "")).decode("utf-8"))
            if existing >= count:
                return True                 # already current — nothing to do
        except urllib.error.HTTPError as e:
            if e.code != 404:               # 404 => file not created yet
                return False
        body = {
            "message": f"games played: {count}",
            "branch": _branch(),
            "content": base64.b64encode(f"{count}\n".encode()).decode(),
        }
        if sha:
            body["sha"] = sha
        _http(api, {**hdr, "Content-Type": "application/json"},
              data=json.dumps(body).encode(), method="PUT")
        return True
    except Exception:
        return False
