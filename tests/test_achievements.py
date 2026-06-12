"""Tests for the achievements / XP / quest meta-game."""

from avoidle import achievements as ACH


def ctx(**kw) -> ACH.GameContext:
    base = dict(mode="classic", lang="en", length=5, won=True, score=300,
                min_pool_seen=500, final_pool=200, streak=1, total_wins=1,
                langs_won={"en"}, lengths_won={5})
    base.update(kw)
    return ACH.GameContext(**base)


def test_first_win_and_no_reunlock():
    fresh = ACH.evaluate(ctx(), set())
    ids = {a.id for a in fresh}
    assert "first_win" in ids
    assert not any(a.id == "first_win"
                   for a in ACH.evaluate(ctx(), {"first_win"}))


def test_loss_unlocks_nothing():
    assert ACH.evaluate(ctx(won=False, score=0), set()) == []


def test_skill_achievements():
    ids = {a.id for a in ACH.evaluate(
        ctx(undos=0, hints=0, peeks=0, min_pool_seen=1, was_trapped=True,
            greens=18, score=450, streak=3), set())}
    assert {"purist", "houdini", "greenhouse", "high_roller",
            "streak3"} <= ids
    assert "daredevil" not in ids        # trapped (1) is houdini, not 2
    assert "streak7" not in ids
    ids = {a.id for a in ACH.evaluate(ctx(min_pool_seen=2), set())}
    assert "daredevil" in ids and "houdini" not in ids
    # a final winning guess collapsing the pool to 1 is NOT houdini:
    # the trap was never actually faced
    ids = {a.id for a in ACH.evaluate(
        ctx(min_pool_seen=1, was_trapped=False), set())}
    assert "houdini" not in ids


def test_level_for_xp_bounded_against_hostile_values():
    import time
    t0 = time.perf_counter()
    huge = ACH.level_for_xp(10**300)
    assert time.perf_counter() - t0 < 0.5
    assert huge == ACH.level_for_xp(ACH.XP_CAP)


def test_ghost_and_calculated():
    ids = {a.id for a in ACH.evaluate(ctx(greens=4, yellows=4), set())}
    assert "ghost" in ids
    ids = {a.id for a in ACH.evaluate(ctx(greens=5, yellows=4), set())}
    assert "ghost" not in ids
    ids = {a.id for a in ACH.evaluate(
        ctx(rating_percentiles=[88, 71, 65, 92, 60, 77]), set())}
    assert "calculated" in ids
    ids = {a.id for a in ACH.evaluate(
        ctx(rating_percentiles=[88, 30, 65, 92]), set())}
    assert "calculated" not in ids


def test_meta_achievements():
    ids = {a.id for a in ACH.evaluate(
        ctx(mode="impossible", langs_won={"en", "de"},
            lengths_won={4, 5, 6}, total_wins=25), set())}
    assert {"untouchable", "polyglot", "triathlete", "veteran25"} <= ids
    ids = {a.id for a in ACH.evaluate(
        ctx(mode="survival", survival_round=5), set())}
    assert "gauntlet5" in ids


def test_xp_and_levels():
    assert ACH.xp_for_game(ctx(won=False, score=0)) == ACH.LOSS_XP
    assert ACH.xp_for_game(ctx(score=300), fresh_unlocks=2) == 400
    lv1 = ACH.level_for_xp(0)
    assert lv1["level"] == 1 and lv1["title"] == ACH.TITLES[0]
    assert ACH.level_for_xp(250)["level"] == 2
    # strictly monotonic, progress always within bounds
    prev = 1
    for xp in range(0, 20000, 500):
        lv = ACH.level_for_xp(xp)
        assert lv["level"] >= prev
        assert 0 <= lv["into"] < lv["needed"]
        prev = lv["level"]
    deep = ACH.level_for_xp(10**6)
    assert deep["title"].startswith("Avoidance Legend")


def test_daily_quest_deterministic_and_completable():
    q1 = ACH.daily_quest("2026-06-11", "en", 5)
    assert q1 == ACH.daily_quest("2026-06-11", "en", 5)
    assert q1.id in ACH.QUESTS and q1.xp > 0
    # over a month every quest id should appear at least once somewhere
    seen = {ACH.daily_quest(f"2026-07-{d:02d}", lang, 5).id
            for d in range(1, 29) for lang in ("en", "de", "ru", "es")}
    assert seen == set(ACH.QUESTS)
    full_clear = ctx(undos=0, hints=0, peeks=0, greens=6, yellows=0,
                     final_pool=150)
    for qid in ACH.QUESTS:
        assert isinstance(ACH.quest_completed(qid, full_clear), bool)
    assert ACH.quest_completed("no_undo", full_clear)
    assert not ACH.quest_completed("no_undo", ctx(undos=2))
