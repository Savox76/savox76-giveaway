from savox_giveaway.stats import WinnerStatsStore


def test_winner_stats_are_persistent_and_case_insensitive(tmp_path):
    path = tmp_path / "winner-stats.json"
    store = WinnerStatsStore(path)

    assert store.record("LongPilotName", "round-1")["wins"] == 1
    assert store.record("longpilotname", "round-2")["wins"] == 2

    reloaded = WinnerStatsStore(path)
    assert reloaded.leaders()[0]["wins"] == 2
    assert reloaded.leaders()[0]["name"] == "longpilotname"


def test_winner_record_is_idempotent(tmp_path):
    store = WinnerStatsStore(tmp_path / "winner-stats.json")

    assert store.record("Pilot", "same-round")["wins"] == 1
    assert store.record("Pilot", "same-round")["wins"] == 1
