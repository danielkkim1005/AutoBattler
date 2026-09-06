"""A uniformly random legal-move agent: the floor any real agent must beat."""

from __future__ import annotations

import random

from engine.actions import legal_actions
from engine.state import GameState, PlayerState


class RandomAgent:
    def __init__(self, name: str = "agent:random") -> None:
        self.name = name

    def choose(self, state: GameState, player: PlayerState,
               rng: random.Random) -> dict:
        options = legal_actions(state, player)
        return options[rng.randrange(len(options))]
