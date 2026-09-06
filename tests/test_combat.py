"""Combat resolution: targeting, movement, traits, and the tick cap."""

from __future__ import annotations

import random

from conftest import place, tweak
from engine import events
from engine.combat import build_combat_units, resolve_combat
from engine.events import EventLog
from engine.units import load_templates


def rng():
    return random.Random(0)


def test_lone_survivor_wins_uncontested(state):
    place(state, 0, "footman", 0, 0)
    result = resolve_combat(state, rng())
    assert result.winner == 0
    assert len(result.survivors[0]) == 1
    assert result.survivors[1] == []


def test_empty_boards_draw(state):
    result = resolve_combat(state, rng())
    assert result.winner is None
    assert result.ticks == 0


def test_footman_beats_scout_on_the_maths(state):
    """30hp/4dmg/cd10 out-trades 20hp/3dmg/cd7 given equal positioning."""
    place(state, 0, "footman", 0, 1)
    place(state, 1, "scout", 0, 1)
    result = resolve_combat(state, rng())
    assert result.winner == 0
    assert len(result.survivors[0]) == 1


def test_combat_is_repeatable(state, config):
    for owner, template in ((0, "knight"), (0, "ranger"), (1, "adept"), (1, "duelist")):
        place(state, owner, template, 0, 0 if template in ("knight", "adept") else 1)

    import copy
    first = resolve_combat(copy.deepcopy(state), rng())
    second = resolve_combat(copy.deepcopy(state), rng())
    assert first.log.records() == second.log.records()
    assert first.winner == second.winner


def test_units_close_the_distance(state):
    place(state, 0, "footman", 0, 0)
    place(state, 1, "footman", 0, 0)
    result = resolve_combat(state, rng())
    moves = result.log.of_type(events.MOVE)
    assert moves, "melee units on opposite back lines must walk toward each other"
    assert all(isinstance(m.value, list) and len(m.value) == 2 for m in moves)


def test_ranged_unit_stops_at_range(state):
    """An archmage (range 4) must not be standing on top of its target."""
    place(state, 0, "archmage", 0, 1)
    place(state, 1, "shieldman", 0, 1)
    result = resolve_combat(state, rng())
    assert result.winner == 0
    survivor = result.survivors[0][0]
    assert survivor.x <= 5, "archmage walked further than it needed to"


def test_tick_cap_ends_combat_and_timeout_decides(state, config):
    capped = tweak(config, combat={"tick_cap": 3})
    state.config = capped
    place(state, 0, "warden", 0, 1)     # 70 hp
    place(state, 1, "apprentice", 0, 1)  # 18 hp
    result = resolve_combat(state, rng())
    assert result.ticks == 3
    assert result.winner == 0, "most_total_health should favour the warden"
    end = result.log.of_type(events.COMBAT_END)[-1]
    assert end.value == 3 and end.actor == 0


def test_timeout_tie_is_a_draw(state, config):
    state.config = tweak(config, combat={"tick_cap": 1})
    place(state, 0, "footman", 0, 1)
    place(state, 1, "footman", 0, 1)
    result = resolve_combat(state, rng())
    assert result.winner is None


def test_trait_bonus_applies_at_breakpoint(state, config):
    """Two vanguards get +5 max health each; one gets nothing."""
    place(state, 0, "footman", 0, 0)
    log = EventLog()
    units = build_combat_units(state, log)
    assert units[0].max_health == 30
    assert log.of_type(events.TRAIT_APPLIED) == []

    place(state, 0, "shieldman", 0, 1)
    log = EventLog()
    units = build_combat_units(state, log)
    assert units[0].max_health == 35
    assert units[1].max_health == 41
    applied = log.of_type(events.TRAIT_APPLIED)
    assert len(applied) == 2
    assert {e.target for e in applied} == {"vanguard"}
    assert all(e.value == 5 for e in applied)


def test_trait_bonus_never_mutates_the_template(state, config):
    place(state, 0, "footman", 0, 0)
    place(state, 0, "shieldman", 0, 1)
    build_combat_units(state, EventLog())
    fresh = load_templates(config)
    assert state.templates["footman"] == fresh["footman"]
    assert state.templates["footman"].max_health == 30


def test_skirmisher_cooldown_floor(state, config):
    """A cooldown bonus can never drive a unit below one tick per attack."""
    fast = tweak(config, traits={
        **config.traits,
        "skirmisher": {"breakpoint": 2, "bonus": {"attack_cooldown": -99}},
    })
    state.config = fast
    place(state, 0, "scout", 0, 0)
    place(state, 0, "duelist", 0, 1)
    units = build_combat_units(state, EventLog())
    assert all(u.attack_cooldown >= 1 for u in units.values())


def test_health_bar_starts_full_and_only_health_moves(state):
    place(state, 0, "knight", 0, 0)
    place(state, 1, "knight", 0, 0)
    units = build_combat_units(state, EventLog())
    for unit in units.values():
        assert unit.health == unit.max_health

    result = resolve_combat(state, random.Random(0))
    for side in result.survivors.values():
        for unit in side:
            assert unit.max_health == 48, "max_health was written to during combat"
