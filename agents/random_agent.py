"""A uniformly random legal-move agent: the floor any real agent must beat."""

from __future__ import annotations

import random
from typing import Any


class RandomAgent:
    def __init__(self, name: str = "agent:random") -> None:
        self.name = name

    def choose(self, observation: dict[str, Any], rng: random.Random) -> dict:
        options = observation["legal_actions"]
        return options[rng.randrange(len(options))]
