"""The round loop, damage, placements, and config validation."""

from __future__ import annotations

import random

import pytest
from conftest import place, tweak

from agents import GreedyAgent, RandomAgent
from engine.config import Config, ConfigError, load_config
from engine.game import (
    apply_combat_result,
    combat_damage,
    game_over,
    placements,
    play_game,
    remove_dead_players,
    resolve,
)
from engine.combat import resolve_combat


def test_round_loop_pays_rolls_fights_and_damages(state):
    agents = [GreedyAgent("g"), GreedyAgent("g")]
    record = resolve(state, random.Random(3), agents, random.Random(3))

    assert record.round == 1
    assert record.actions, "planning must be recorded"
    assert record.events, "combat must emit events"
    assert sum(p.health for p in state.players) < 40, "someone must have taken damage"


def test_damage_is_base_plus_survivors(config):
    survivors = [object(), object(), object()]
    assert combat_damage(config, survivors, {}) == 1 + 3
    assert combat_damage(config, [], {}) == 1


def test_flat_plus_tiers_is_a_config_level_ablation(config):
    by_tiers = tweak(config, damage={"formula": "flat_plus_tiers"})

    class Fake:
        template_id = "warden"

    assert combat_damage(by_tiers, [Fake(), Fake()], {"warden": 3}) == 1 + 6


def test_a_draw_damages_nobody(state):
    result = resolve_combat(state, random.Random(0))  # two empty boards
    assert result.winner is None
    apply_combat_result(state, result, {})
    assert [p.health for p in state.players] == [20, 20]
    assert all(p.streak == 0 for p in state.players)


def test_losing_player_is_removed_at_zero(state):
    state.players[1].health = 1
    place(state, 0, "warden", 0, 1)
    result = resolve_combat(state, random.Random(0))
    apply_combat_result(state, result, {})
    remove_dead_players(state)

    assert state.players[1].health == 0
    assert not state.players[1].alive
    assert game_over(state)
    assert placements(state) == [0, 1]


def test_placements_tie_when_health_is_equal(state):
    assert placements(state) == [0, 0]


def test_game_stops_at_max_rounds(config):
    short = tweak(config, match={"max_rounds": 3})
    replay = play_game(short, 42, [RandomAgent("a"), RandomAgent("b")])
    assert replay.result["rounds_played"] <= 3
    assert len(replay.rounds) <= 3


def test_greedy_beats_random_over_a_seed_sweep(config):
    """Not a balance claim - a smoke test that decisions matter at all."""
    wins = 0
    for seed in range(20):
        replay = play_game(config, seed, [GreedyAgent("g"), RandomAgent("r")])
        if replay.result["placements"][0] == 0:
            wins += 1
    assert wins >= 15, f"greedy only won {wins}/20; economy or combat is off"


def test_every_round_records_actions_and_events(config):
    replay = play_game(config, 11, [RandomAgent("a"), RandomAgent("b")])
    for record in replay.rounds:
        assert record.actions
        assert record.events
        assert record.events[-1]["type"] == "combat_end"
        for event in record.events:
            assert set(event) == {"tick", "type", "actor", "target", "value"}


# -- config validation -----------------------------------------------------

def _broken(config: Config, **sections) -> dict:
    import copy
    raw = copy.deepcopy(dict(config.raw))
    for section, overrides in sections.items():
        raw[section] = {**raw[section], **overrides}
    return raw


def test_tier_odds_must_sum_to_one(config, tmp_path):
    import yaml
    from engine.config import _validate

    raw = _broken(config, shop={**config.shop, "tier_odds": {
        **config.shop["tier_odds"], 3: [0.5, 0.2, 0.1]}})
    with pytest.raises(ConfigError, match="tier_odds"):
        _validate(raw)


def test_missing_unit_cost_is_rejected(config):
    from engine.config import _validate
    raw = _broken(config, economy={"cost_by_tier": {1: 1, 2: 2}})
    with pytest.raises(ConfigError, match="unit cost"):
        _validate(raw)


def test_board_must_fit_the_max_level(config):
    from engine.config import _validate
    raw = _broken(config, board={"width": 1, "height": 1})
    with pytest.raises(ConfigError, match="board size"):
        _validate(raw)


def test_real_ruleset_loads_and_validates():
    config = load_config()
    assert config.version == "0.1.0"
    assert len(config.units) == 10
    assert config.board_size(5) == 5
    assert config.level_cost(5) is None
