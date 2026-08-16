from savox_giveaway.arena_state import ArenaStateStore


def test_arena_state_roundtrip_is_atomic(tmp_path):
    path = tmp_path / "arena-state.json"
    store = ArenaStateStore(path)
    state = {"phase": "battle", "combatants": [{"name": "Pilot", "hp": 42}]}

    store.save(state)

    assert store.load() == state


def test_invalid_arena_state_is_ignored(tmp_path):
    path = tmp_path / "arena-state.json"
    path.write_text("not-json", encoding="utf-8")

    assert ArenaStateStore(path).load() is None
