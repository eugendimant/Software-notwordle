"""Tests for the server-side store (global odometer + nickname slots)."""

import os
import tempfile
import threading

from avoidle.store import SqliteStore, get_store


def fresh_store() -> SqliteStore:
    return SqliteStore(os.path.join(
        tempfile.mkdtemp(prefix="avoidle-store-"), "s.db"))


def test_global_odometer_counts_and_never_goes_backward():
    s = fresh_store()
    assert s.games() == 0
    assert s.bump_games() == 1
    assert s.bump_games() == 2
    # the floor lifts a fresh/reset counter but never lowers a higher one
    assert s.raise_games_floor(10) == 10
    assert s.raise_games_floor(5) == 10
    assert s.bump_games() == 11


def test_profiles_roundtrip_and_guest_is_never_stored():
    s = fresh_store()
    assert s.load_profile("ben") is None
    s.save_profile("ben", "token-1")
    s.save_profile("ben", "token-2")        # upsert keeps the latest
    assert s.load_profile("ben") == "token-2"
    s.save_profile("", "guest-token")       # guest slot is cookie-only
    assert s.load_profile("") is None


def test_concurrent_bumps_lose_nothing():
    s = fresh_store()

    def worker():
        for _ in range(25):
            s.bump_games()

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert s.games() == 100


def test_get_store_uses_env_path_and_is_a_singleton():
    s1 = get_store()
    s2 = get_store()
    assert s1 is s2
    assert "avoidle-test" in getattr(s1, "path", "")  # conftest's tmp db


def test_duel_tally_counts_floors_and_never_lowers():
    s = fresh_store()
    assert s.duel_counts() == (0, 0)
    assert s.raise_duel_floor(32, 100) == (32, 100)    # seed near 32%
    assert s.bump_duel(True) == (33, 101)              # a human win
    assert s.bump_duel(False) == (33, 102)             # a human loss
    assert s.raise_duel_floor(10, 50) == (33, 102)     # never lowers a real count


def test_leaderboard_ranks_by_xp_then_wins():
    s = fresh_store()
    s.save_profile("amy", "t", xp=300, wins=3)
    s.save_profile("ben", "t", xp=900, wins=1)
    s.save_profile("cat", "t", xp=300, wins=9)
    s.save_profile("amy", "t2", xp=1200, wins=4)   # upsert re-ranks
    assert s.profile_count() == 3
    board = s.leaderboard()
    assert [n for n, _, _ in board] == ["amy", "ben", "cat"]
    assert board[0] == ("amy", 1200, 4)
