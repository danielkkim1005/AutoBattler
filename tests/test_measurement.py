"""v0.3: statistics, telemetry, seat-swapped evaluation, PositionalAgent,
brawl mode, and config overlays."""

from __future__ import annotations

import random
from pathlib import Path

import pytest
from conftest import place, tweak

from agents import GreedyAgent, PositionalAgent, RandomAgent
from agents.positional import formation
from analysis.evaluate import compare_rulesets, run_matchup
from analysis.stats import games_for_margin, mean_interval, wilson_interval
from analysis.telemetry import game_stats
from engine import events
from engine.actions import MOVE, SWAP, apply_action
from engine.combat import resolve_combat
from engine.config import DEFAULT_RULES_PATH, ConfigError, load_config
from engine.game import play_game
from engine.state import new_game

ABLATIONS_DIR = Path(__file__).resolve().parent.parent / "configs" / "ablations"
ABLATIONS = sorted(ABLATIONS_DIR.glob("*.yaml"))


# -- statistics --------------------------------------------------------------

def test_wilson_matches_the_published_bias_numbers():
    """The v0.1 seat-bias figure quoted in the docs: 205 of 500."""
    e = wilson_interval(205, 500)
    assert (round(e.low, 3), round(e.high, 3)) == (0.368, 0.454)
    assert not e.contains(0.5)


def test_wilson_never_collapses_at_the_extremes():
    e = wilson_interval(0, 10)
    assert e.low == 0.0 and e.high > 0.2, "0/10 must not mean 'certainly 0%'"


def test_mean_interval_and_sample_size_rule():
    e = mean_interval([0.0, 1.0] * 50)
    assert e.value == 0.5 and e.low < 0.5 < e.high
    assert games_for_margin(0.02) == 2401


# -- telemetry ---------------------------------------------------------------

def test_telemetry_reads_everything_from_the_replay(config):
    replay = play_game(config, 3, [GreedyAgent("a"), GreedyAgent("b")])
    stats = game_stats(replay)
    assert stats.rounds_played == len(replay.rounds) == len(stats.combats)
    assert stats.level == replay.result["level"]
    spawns = sum(1 for r in replay.rounds for e in r.events if e["type"] == "spawn")
    assert sum(sum(c.values()) for c in stats.fielded) == spawns
    for combat in stats.combats:
        if combat.winner is not None and not combat.timeout:
            assert combat.survivors[1 - combat.winner] == 0, "a wipe leaves nobody"


def test_telemetry_works_on_a_replay_loaded_from_json(config):
    import json
    replay = play_game(config, 3, [GreedyAgent("a"), RandomAgent("b")])
    from_disk = json.loads(replay.to_json())
    assert game_stats(from_disk) == game_stats(replay)


def test_timeouts_are_detected(config):
    capped = tweak(config, combat={"tick_cap": 2})
    replay = play_game(capped, 3, [GreedyAgent("a"), GreedyAgent("b")])
    stats = game_stats(replay)
    assert any(c.timeout for c in stats.combats)
    assert all(c.ticks <= 2 for c in stats.combats)


# -- evaluation --------------------------------------------------------------

def test_seat_swapping_scores_identical_agents_at_exactly_one_half(config):
    """Greedy is deterministic, so both games of a pair are the same game with
    the labels exchanged. Every seed must score 0.5 - no noise at all."""
    report = run_matchup(config, GreedyAgent, GreedyAgent, range(10))
    assert report.per_seed(lambda r: r.a_score) == [0.5] * 10
    assert report.a_score.low == report.a_score.high == 0.5


def test_brawl_is_a_perfect_control_for_positioning(config):
    """With positioning off, squares stop mattering, so PositionalAgent and
    GreedyAgent - which buy identically - are indistinguishable. If this ever
    fails, something other than positioning separates them."""
    brawl = tweak(config, board={"positioning": False})
    report = run_matchup(brawl, PositionalAgent, GreedyAgent, range(10))
    assert report.per_seed(lambda r: r.a_score) == [0.5] * 10


def test_compare_rulesets_pairs_by_seed(config):
    longer = tweak(config, match={"starting_health": 40})
    report = compare_rulesets(config, longer, GreedyAgent, GreedyAgent, range(15))
    rounds = report.paired(lambda r: r.stats.rounds_played)
    assert rounds.low > 0, "doubling health must lengthen games, visibly"


# -- PositionalAgent ---------------------------------------------------------

def test_formation_puts_melee_in_front_and_ranged_behind(state, config):
    melee = place(state, 0, "warden", 0, 0)
    ranged = place(state, 0, "archmage", 4, 1)
    plan = formation(config, state.templates, state.players[0].units())
    width = config.board["width"]
    assert plan[melee][0] == width - 1, "melee faces the enemy"
    assert plan[ranged][0] == 0, "ranged holds the back line"
    assert len(set(plan.values())) == len(plan), "no two units share a square"


def test_formation_converges_in_one_step_per_unit(state, config):
    rng = random.Random(0)
    layout = [("warden", 4, 0), ("archmage", 4, 1), ("knight", 0, 2),
              ("ranger", 2, 1), ("footman", 3, 2)]
    for template, x, y in layout:
        place(state, 0, template, x, y)
    player = state.players[0]
    steps = 0
    while (step := PositionalAgent._next_formation_step(state, player)) is not None:
        assert step["type"] in (MOVE, SWAP)
        apply_action(state, player, step, rng)
        steps += 1
        assert steps <= len(layout)
    plan = formation(config, state.templates, player.units())
    assert all(player.board[uid].pos() == sq for uid, sq in plan.items())


def test_positional_buys_exactly_like_greedy(config):
    """Round 1 shops are identical, so the non-positioning actions must be too."""
    def buys(agent):
        replay = play_game(config, 11, [agent, GreedyAgent("opponent")])
        return [a for seat, a in replay.rounds[0].actions
                if seat == 0 and a["type"] not in (MOVE, SWAP)]
    assert buys(PositionalAgent("p")) == buys(GreedyAgent("g"))


# -- brawl mode ---------------------------------------------------------------

def test_brawl_has_no_movement_and_everyone_swings_at_once(config):
    state = new_game(config, ["a", "b"])
    state.config = tweak(config, board={"positioning": False})
    place(state, 0, "footman", 0, 0)
    place(state, 1, "scout", 0, 2)
    result = resolve_combat(state, random.Random(0))
    assert result.log.of_type(events.MOVE) == []
    assert {e.actor for e in result.log.of_type(events.ATTACK) if e.tick == 1} == {0, 1}


# -- overlays ---------------------------------------------------------------

@pytest.mark.parametrize("overlay", ABLATIONS, ids=lambda p: p.stem)
def test_every_shipped_ablation_loads(overlay, config):
    ablated = load_config(DEFAULT_RULES_PATH, (overlay,))
    assert ablated.config_hash != config.config_hash
    assert ablated.raw != config.raw, "an ablation that changes nothing is a bug"


def test_an_overlay_changes_only_what_it_names(config):
    rich = load_config(DEFAULT_RULES_PATH, (ABLATIONS_DIR / "rich.yaml",))
    assert rich.economy["base_income"] == 7
    assert {k: v for k, v in rich.economy.items() if k != "base_income"} == \
        {k: v for k, v in config.economy.items() if k != "base_income"}
    assert {k: v for k, v in rich.raw.items() if k != "economy"} == \
        {k: v for k, v in config.raw.items() if k != "economy"}


def test_a_typo_in_an_overlay_is_rejected(tmp_path):
    typo = tmp_path / "typo.yaml"
    typo.write_text("damge:\n  formula: flat_plus_tiers\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="damge"):
        load_config(DEFAULT_RULES_PATH, (typo,))


def test_an_overlay_is_still_validated(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("combat:\n  resolution: turn_based\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="combat.resolution"):
        load_config(DEFAULT_RULES_PATH, (bad,))


def test_overlay_order_is_part_of_the_hash():
    a, b = ABLATIONS_DIR / "rich.yaml", ABLATIONS_DIR / "long_game.yaml"
    ab = load_config(DEFAULT_RULES_PATH, (a, b))
    ba = load_config(DEFAULT_RULES_PATH, (b, a))
    assert ab.raw == ba.raw
    assert ab.config_hash != ba.config_hash, "the recipe, not just the result"
