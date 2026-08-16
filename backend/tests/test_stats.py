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


def test_participations_are_counted_once_per_round(tmp_path):
    store = WinnerStatsStore(tmp_path / "winner-stats.json")

    store.record_participants(["Pilot", "Wingman"], "round-1")
    store.record_participants(["pilot"], "round-1")
    store.record_participants(["Pilot"], "round-2")

    assert store.lookup("PILOT")["participations"] == 2
    assert store.lookup("Wingman")["participations"] == 1
    assert store.lookup("Unknown")["wins"] == 0
