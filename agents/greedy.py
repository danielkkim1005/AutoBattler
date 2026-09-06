"""A greedy baseline: level when it can, buy the best unit it can afford.

Deliberately simple and fully deterministic given the state - it draws nothing
from the rng. It exists to give the engine a non-degenerate opponent and to
make economy tuning visible, not to play well.
"""

from __future__ import annotations

import random

from engine.actions import BUY, BUY_LEVEL, END_TURN, is_legal
from engine.state import GameState, PlayerState


class GreedyAgent:
    def __init__(self, name: str = "agent:greedy", level_first: bool = True) -> None:
        self.name = name
        self.level_first = level_first

    def choose(self, state: GameState, player: PlayerState,
               rng: random.Random) -> dict:
        if self.level_first:
            level_up = {"type": BUY_LEVEL}
            if player.board_full(state.config) and is_legal(state, player, level_up):
                return level_up

        best_slot = None
        best_tier = 0
        for slot, template_id in enumerate(player.shop):
            if template_id is None:
                continue
            if not is_legal(state, player, {"type": BUY, "slot": slot}):
                continue
            tier = state.templates[template_id].tier
            if tier > best_tier:
                best_tier, best_slot = tier, slot

        if best_slot is not None:
            return {"type": BUY, "slot": best_slot}

        return {"type": END_TURN}
