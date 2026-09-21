"""v0.2: simultaneous resolution, isolated round streams, spawn events, and
fail-fast config validation."""

from __future__ import annotations

import copy
import random

import pytest
import yaml
from conftest import place, tweak

from engine import __version__, events
from engine.combat import resolve_combat
from engine.config import DEFAULT_RULES_PATH, ConfigError, _validate
from engine.game import resolve
from engine.state import new_game

ALL_UNITS = ["footman", "scout", "apprentice", "shieldman", "knight",
             "duelist", "ranger", "adept", "warden", "archmage"]


def mirror(state, template, x=0, y=1):
    """The same unit on the same square of both boards."""
    place(state, 0, template, x, y)
    place(state, 1, template, x, y)
    return state


# -- the tick-order fix ------------------------------------------------------

@pytest.mark.parametrize("template", ALL_UNITS)
def test_a_perfect_mirror_is_a_draw(config, template):
    """Nothing distinguishes the sides, so nothing may decide the fight."""
    state = mirror(new_game(config, ["a", "b"]), template)
    result = resolve_combat(state, random.Random(0))
    assert result.winner is None, f"{template} mirror was won by p{result.winner}"


def test_sequential_mode_still_shows_the_v01_bias(config):
    """The ablation must keep reproducing the bias it exists to measure."""
    state = new_game(config, ["a", "b"])
    state.config = tweak(config, combat={"resolution": "sequential"})
    mirror(state, "footman")
    result = resolve_combat(state, random.Random(0))
    assert result.winner == 0, "sequential mirror should hand the lower uid the win"


def test_mutual_kill_is_a_draw_with_both_deaths_on_one_tick(config):
    state = mirror(new_game(config, ["a", "b"]), "footman")
    result = resolve_combat(state, random.Random(0))
    deaths = result.log.of_type(events.DEATH)
    assert len(deaths) == 2
    assert deaths[0].tick == deaths[1].tick
    assert result.log.of_type(events.COMBAT_END)[-1].actor is None


def _doomed_apprentice(config, resolution):
    """Two arcanists focus a lone apprentice that dies on tick 1 (24 >= 18)."""
    state = new_game(config, ["a", "b"])
    state.config = tweak(config, combat={"resolution": resolution})
    place(state, 0, "archmage", 4, 0)            # field (4, 0)
    place(state, 0, "apprentice", 4, 2)          # field (4, 2)
    doomed = place(state, 1, "apprentice", 4, 1)  # field (5, 1): both in range
    return state, doomed


def _tick_one(result, type):
    return [e for e in result.log.of_type(type) if e.tick == 1]


def test_a_unit_that_dies_this_tick_still_lands_its_attack(config):
    state, doomed = _doomed_apprentice(config, "simultaneous")
    result = resolve_combat(state, random.Random(0))
    assert doomed in [e.actor for e in _tick_one(result, events.DEATH)]
    # Its attack was decided at the start of the tick, so it lands.
    assert doomed in [e.actor for e in _tick_one(result, events.ATTACK)]


def test_sequential_mode_lets_the_first_mover_kill_before_the_swing(config):
    """The same setup under v0.1 rules: lower uids act first, so the doomed
    unit dies before its turn comes round and never swings. This is the bias."""
    state, doomed = _doomed_apprentice(config, "sequential")
    result = resolve_combat(state, random.Random(0))
    assert doomed in [e.actor for e in _tick_one(result, events.DEATH)]
    assert doomed not in [e.actor for e in _tick_one(result, events.ATTACK)]


def _contested(config, rule):
    """Two melee units two squares apart: both want the square between them."""
    state = new_game(config, ["a", "b"])
    state.config = tweak(config, combat={"move_conflict": rule})
    left = place(state, 0, "footman", 3, 1)    # field (3, 1)
    right = place(state, 1, "footman", 4, 1)   # field (5, 1)
    return state, left, right


def _first_tick_movers(result):
    return [e.actor for e in result.log.of_type(events.MOVE) if e.tick == 1]


def test_move_conflict_lowest_id(config):
    state, left, right = _contested(config, "lowest_id")
    result = resolve_combat(state, random.Random(0))
    assert _first_tick_movers(result) == [left]


def test_move_conflict_random_is_fair_and_repeatable(config):
    winners = set()
    for seed in range(20):
        state, _, _ = _contested(config, "random")
        movers = _first_tick_movers(resolve_combat(state, random.Random(seed)))
        assert len(movers) == 1, "exactly one claimant may take the square"
        winners.add(movers[0])

        again, _, _ = _contested(config, "random")
        assert _first_tick_movers(resolve_combat(again, random.Random(seed))) == movers
    assert len(winners) == 2, "over 20 seeds both sides should win the square"


def test_footman_still_beats_scout_on_the_maths(state):
    place(state, 0, "footman", 0, 1)
    place(state, 1, "scout", 0, 1)
    assert resolve_combat(state, random.Random(0)).winner == 0


# -- spawn events: the log alone must be enough to draw the fight -------------

def test_every_unit_spawns_once_with_final_stats(state):
    footman = place(state, 0, "footman", 0, 0)
    place(state, 0, "shieldman", 0, 1)      # activates vanguard
    archmage = place(state, 1, "archmage", 2, 2)

    result = resolve_combat(state, random.Random(0))
    spawns = {e.actor: e for e in result.log.of_type(events.SPAWN)}
    assert set(spawns) == {footman, footman + 1, archmage}
    assert all(e.tick == 0 for e in spawns.values())

    assert spawns[footman].target == 0
    assert spawns[footman].value["unit"] == "footman"
    assert spawns[footman].value["max_health"] == 35, "spawn carries post-trait stats"
    assert spawns[archmage].target == 1
    assert (spawns[archmage].value["x"], spawns[archmage].value["y"]) == (7, 2), \
        "spawn carries field coordinates, mirrored for player 1"


def replay_log(records):
    """A minimal renderer: rebuild every unit's position and health from events."""
    units = {}
    for e in records:
        if e["type"] == "spawn":
            units[e["actor"]] = {"x": e["value"]["x"], "y": e["value"]["y"],
                                 "hp": e["value"]["max_health"], "owner": e["target"]}
        elif e["type"] == "move":
            units[e["actor"]]["x"], units[e["actor"]]["y"] = e["value"]
        elif e["type"] == "attack":
            units[e["target"]]["hp"] -= e["value"]
    return units


@pytest.mark.parametrize("resolution", ["simultaneous", "sequential"])
def test_the_event_log_reconstructs_the_fight(config, resolution):
    state = new_game(config, ["a", "b"])
    state.config = tweak(config, combat={"resolution": resolution})
    for owner, template, x, y in [(0, "knight", 4, 1), (0, "ranger", 1, 0),
                                  (0, "adept", 0, 2), (1, "warden", 3, 1),
                                  (1, "duelist", 4, 0), (1, "archmage", 0, 1)]:
        place(state, owner, template, x, y)

    result = resolve_combat(state, random.Random(3))
    rebuilt = replay_log(result.log.records())
    for side in result.survivors.values():
        for unit in side:
            assert (rebuilt[unit.uid]["x"], rebuilt[unit.uid]["y"]) == unit.pos()
            assert rebuilt[unit.uid]["hp"] == unit.health
    for event in result.log.of_type(events.DEATH):
        assert rebuilt[event.actor]["hp"] <= 0


# -- per-round random streams ---------------------------------------------

END_TURNS = [(0, {"type": "end_turn"}), (1, {"type": "end_turn"})]


def test_rerolls_do_not_shift_the_next_rounds_shops(config):
    """Round 2's opening shops depend on the seed, not on round 1's rerolls."""
    def round_two_shops(round_one_actions):
        state = new_game(config, ["a", "b"])
        rng = random.Random(42)
        resolve(state, rng, [], recorded=round_one_actions)
        # Ending the turn at once leaves round 2's shops exactly as rolled.
        resolve(state, rng, [], recorded=END_TURNS)
        return [list(p.shop) for p in state.players]

    busy = [(0, {"type": "reroll"}), (0, {"type": "reroll"})] + END_TURNS
    assert round_two_shops(END_TURNS) == round_two_shops(busy)


def test_each_round_takes_exactly_one_draw_from_the_master_stream(config):
    """Rerolls, a contested square, a fight: none of it reaches the master rng."""
    for rule in ("random", "lowest_id"):
        state = new_game(config, ["a", "b"])
        state.config = tweak(config, combat={"move_conflict": rule})
        place(state, 0, "footman", 3, 1)    # contests field (4, 1) ...
        place(state, 1, "footman", 4, 1)    # ... with this unit at (5, 1)

        master = random.Random(42)
        resolve(state, master, [], recorded=[(0, {"type": "reroll"})] + END_TURNS)

        reference = random.Random(42)
        reference.getrandbits(64)
        assert master.getstate() == reference.getstate(), rule


# -- versioning and fail-fast validation ------------------------------------

def test_rules_version_matches_the_engine_release():
    raw = yaml.safe_load(DEFAULT_RULES_PATH.read_text(encoding="utf-8"))
    assert raw["version"] == __version__, \
        "bump rules.yaml version and engine/version.py together"


def test_an_unquoted_version_is_rejected(config):
    raw = copy.deepcopy(dict(config.raw))
    raw["version"] = 0.1  # what YAML makes of an unquoted 0.10
    with pytest.raises(ConfigError, match="quoted"):
        _validate(raw)


@pytest.mark.parametrize("section, key, value", [
    ("combat", "resolution", "turn_based"),
    ("combat", "move_conflict", "coin"),
    ("combat", "target_rule", "furthest"),
    ("damage", "formula", "flat"),
    ("board", "positioning", False),
])
def test_unsupported_options_fail_at_load(config, section, key, value):
    raw = copy.deepcopy(dict(config.raw))
    raw[section] = {**raw[section], key: value}
    with pytest.raises(ConfigError, match=f"{section}.{key}"):
        _validate(raw)


def test_bench_fails_at_load_not_mid_game(config):
    raw = copy.deepcopy(dict(config.raw))
    raw["purchase_when_board_full"] = "bench"
    with pytest.raises(ConfigError, match="purchase_when_board_full"):
        _validate(raw)


def test_only_two_players_are_supported(config):
    raw = copy.deepcopy(dict(config.raw))
    raw["match"] = {**raw["match"], "players": 3}
    with pytest.raises(ConfigError, match="2 players"):
        _validate(raw)
