"""Tests for the GitHub-backed durable games counter (network mocked)."""

import base64
import json
import urllib.error

import pytest

from avoidle import ghcount as GH


def test_read_count_parses_the_raw_file(monkeypatch):
    monkeypatch.setattr(GH, "_http", lambda url, headers, **k: b"137\n")
    assert GH.read_count() == 137


def test_read_count_is_zero_when_offline(monkeypatch):
    def boom(*a, **k):
        raise OSError("offline")
    monkeypatch.setattr(GH, "_http", boom)
    assert GH.read_count() == 0


def test_publish_needs_a_token(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setattr(GH, "_token", lambda: "")
    monkeypatch.setattr(GH, "_http",
                        lambda *a, **k: pytest.fail("must not hit the network"))
    assert GH.publish(100) is False


def test_publish_commits_when_it_raises_the_count(monkeypatch):
    monkeypatch.setattr(GH, "_token", lambda: "tok")
    calls = []

    def fake_http(url, headers, data=None, method=None):
        calls.append(method)
        if method is None:            # GET the current file
            return json.dumps({"sha": "abc",
                "content": base64.b64encode(b"90\n").decode()}).encode()
        return b"{}"                  # PUT

    monkeypatch.setattr(GH, "_http", fake_http)
    assert GH.publish(100) is True
    assert "PUT" in calls             # actually committed the new value


def test_publish_skips_when_repo_already_higher(monkeypatch):
    monkeypatch.setattr(GH, "_token", lambda: "tok")

    def fake_http(url, headers, data=None, method=None):
        if method is None:
            return json.dumps({"sha": "abc",
                "content": base64.b64encode(b"150\n").decode()}).encode()
        pytest.fail("must not PUT when the repo already holds a higher count")

    monkeypatch.setattr(GH, "_http", fake_http)
    assert GH.publish(100) is True    # already current — no write needed


def test_publish_creates_the_file_when_missing(monkeypatch):
    monkeypatch.setattr(GH, "_token", lambda: "tok")
    seen = []

    def fake_http(url, headers, data=None, method=None):
        if method is None:            # file doesn't exist yet
            raise urllib.error.HTTPError(url, 404, "nf", {}, None)
        seen.append(json.loads(data))
        return b"{}"

    monkeypatch.setattr(GH, "_http", fake_http)
    assert GH.publish(42) is True
    assert seen and seen[0]["branch"] and "sha" not in seen[0]   # a create
