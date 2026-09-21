"""The invariant the whole project rests on.

Identical seed + config_hash + action sequence must produce a byte-identical
replay. Asserted, not assumed.
"""

from __future__ import annotations

import hashlib
import random

from agents import GreedyAgent, RandomAgent
from engine import __version__
from engine.config import DEFAULT_RULES_PATH, load_config
from engine.game import play_game, replay_game

SEEDS = [0, 1, 42, 1337, 99991]


def _agents():
    return [RandomAgent("agent:r0"), RandomAgent("agent:r1")]


def test_same_seed_is_byte_identical(config):
    for seed in SEEDS:
        first = play_game(config, seed, _agents()).to_json()
        second = play_game(config, seed, _agents()).to_json()
        assert first == second, f"seed {seed} diverged between runs"


def test_recorded_actions_reproduce_the_replay(config):
    for seed in SEEDS:
        original = play_game(config, seed, _agents())
        reproduced = replay_game(config, original)
        assert reproduced.to_json() == original.to_json(), f"seed {seed} did not replay"


def test_different_seeds_diverge(config):
    a = play_game(config, 42, _agents()).to_json()
    b = play_game(config, 43, _agents()).to_json()
    assert a != b


def test_agent_randomness_is_off_the_engine_stream(config):
    """Burning agent rng must not shift the engine's shop rolls.

    This is what lets a recorded action list stand in for the agents that
    produced it.
    """

    class Chatty(RandomAgent):
        def choose(self, state, player, rng):
            for _ in range(7):
                rng.random()
            return super().choose(state, player, rng)

    quiet = play_game(config, 42, [RandomAgent("a"), RandomAgent("b")])
    noisy = play_game(config, 42, [Chatty("a"), Chatty("b")])

    # The games differ (different decisions) but each still replays exactly.
    assert replay_game(config, noisy).to_json() == noisy.to_json()
    assert replay_game(config, quiet).to_json() == quiet.to_json()


def test_config_hash_matches_the_file(config):
    content = DEFAULT_RULES_PATH.read_bytes().replace(b"\r\n", b"\n")
    expected = hashlib.sha256(content).hexdigest()
    assert config.config_hash == expected
    assert load_config().config_hash == expected


def test_config_hash_ignores_line_endings(config, tmp_path):
    """A CRLF checkout of the same rules must not orphan existing replays."""
    lf = DEFAULT_RULES_PATH.read_bytes().replace(b"\r\n", b"\n")
    crlf = tmp_path / "rules_crlf.yaml"
    crlf.write_bytes(lf.replace(b"\n", b"\r\n"))
    assert load_config(crlf).config_hash == config.config_hash


def test_config_hash_still_sees_real_edits(config, tmp_path):
    edited = tmp_path / "rules_edited.yaml"
    edited.write_bytes(DEFAULT_RULES_PATH.read_bytes() + b"# a comment\n")
    assert load_config(edited).config_hash != config.config_hash


def test_replay_header_carries_seed_and_hash(config):
    replay = play_game(config, 42, _agents())
    record = replay.as_record()
    assert record["seed"] == 42
    assert record["config_hash"] == config.config_hash
    assert record["version"] == __version__
    assert list(record) == ["version", "config_hash", "seed", "players",
                            "rounds", "result"]


def test_greedy_is_deterministic_without_rng(config):
    """GreedyAgent draws nothing, so an unrelated rng must not change the game."""
    a = play_game(config, 7, [GreedyAgent("g0"), GreedyAgent("g1")])
    random.Random(999).random()
    b = play_game(config, 7, [GreedyAgent("g0"), GreedyAgent("g1")])
    assert a.to_json() == b.to_json()


def test_engine_never_touches_the_module_level_random():
    """Static guard on the invariant: engine/ may build a Random, not call one.

    ``random.Random(seed)`` is fine. ``random.random()``, ``random.choice(...)``
    and friends read the process-wide generator and would make a run
    irreproducible, so they are banned outright rather than reviewed for.
    """
    import ast
    from pathlib import Path

    engine_dir = Path(__file__).resolve().parent.parent / "engine"
    offenders = []
    for path in sorted(engine_dir.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute):
                continue
            if isinstance(node.value, ast.Name) and node.value.id == "random":
                if node.attr != "Random":
                    offenders.append(f"{path.name}:{node.lineno} random.{node.attr}")
    assert not offenders, "unseeded randomness in engine/: " + ", ".join(offenders)
