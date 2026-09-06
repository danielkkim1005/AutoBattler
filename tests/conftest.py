"""Shared fixtures and helpers for the engine tests."""

from __future__ import annotations

import copy
import sys
from pathlib import Path
from typing import Any, Mapping

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.config import Config, load_config  # noqa: E402
from engine.state import GameState, new_game  # noqa: E402
from engine.units import BoardUnit  # noqa: E402


@pytest.fixture(scope="session")
def config() -> Config:
    return load_config()


@pytest.fixture
def state(config: Config) -> GameState:
    return new_game(config, ["p0", "p1"])


def tweak(config: Config, **sections: Mapping[str, Any]) -> Config:
    """A config with some sections overridden, for ablations in tests.

    The hash is left alone: these are throwaway configs that never reach a
    replay, and a test that cares about hashing should load the real file.
    """
    raw = copy.deepcopy(dict(config.raw))
    for section, overrides in sections.items():
        raw[section] = {**raw[section], **overrides}
    return Config(raw=raw, config_hash=config.config_hash)


def place(state: GameState, player_index: int, template_id: str,
          x: int, y: int) -> int:
    """Drop a unit straight onto a board, bypassing the shop."""
    uid = state.new_uid()
    state.players[player_index].board[uid] = BoardUnit(
        uid, template_id, player_index, x, y
    )
    return uid
