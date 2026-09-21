"""A greedy baseline: level when it can, buy the best unit it can afford.

Deliberately simple and fully deterministic given its observation - it draws
nothing from the rng. It exists to give the engine a non-degenerate opponent
and a fixed ruler to measure other agents against, not to play well.
"""

from __future__ import annotations

import random
from typing import Any

from engine.actions import BUY, BUY_LEVEL, END_TURN


class GreedyAgent:
    def __init__(self, name: str = "agent:greedy", level_first: bool = True) -> None:
        self.name = name
        self.level_first = level_first

    def choose(self, observation: dict[str, Any], rng: random.Random) -> dict:
        me = observation["self"]
        legal = observation["legal_actions"]

        if self.level_first:
            level_up = {"type": BUY_LEVEL}
            if len(me["board"]) >= me["board_size"] and level_up in legal:
                return level_up

        best_slot = None
        best_tier = 0
        for slot, item in enumerate(me["shop"]):
            if item is None or {"type": BUY, "slot": slot} not in legal:
                continue
            if item["tier"] > best_tier:
                best_tier, best_slot = item["tier"], slot

        if best_slot is not None:
            return {"type": BUY, "slot": best_slot}
        return {"type": END_TURN}
