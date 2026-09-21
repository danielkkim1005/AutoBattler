"""Greedy buying plus a formation: melee in front, ranged behind.

The point of this agent is measurement, not strength. GreedyAgent never moves a
unit - everything it buys lands on the first free square, which is the back
line - and RandomAgent moves units at random. Neither says anything about
whether positioning matters. This agent buys exactly like GreedyAgent, so any
difference between the two in a seat-swapped match is the value of its
formation and nothing else.

The formation, in the player's own frame (``x = width - 1`` faces the enemy
for both seats, because player 1's board is mirrored):

* melee units (range 1) take the front columns, toughest first, centre rows
  first;
* ranged units take the back columns, longest range first.
"""

from __future__ import annotations

import random

from agents.greedy import GreedyAgent
from engine.actions import END_TURN, MOVE, SWAP
from engine.config import Config
from engine.state import GameState, PlayerState
from engine.units import BoardUnit, UnitTemplate


def _rows_centre_first(height: int) -> list[int]:
    middle = (height - 1) / 2
    return sorted(range(height), key=lambda y: (abs(y - middle), y))


def formation(config: Config, templates: dict[str, UnitTemplate],
              units: list[BoardUnit]) -> dict[int, tuple[int, int]]:
    """Target square for every unit. Injective: no two units share a square."""
    width, height = config.board["width"], config.board["height"]
    rows = _rows_centre_first(height)
    front_to_back = [(x, y) for x in range(width - 1, -1, -1) for y in rows]
    back_to_front = [(x, y) for x in range(width) for y in rows]

    def stats(unit: BoardUnit) -> UnitTemplate:
        return templates[unit.template_id]

    melee = sorted((u for u in units if stats(u).range <= 1),
                   key=lambda u: (-stats(u).max_health, u.uid))
    ranged = sorted((u for u in units if stats(u).range > 1),
                    key=lambda u: (-stats(u).range, u.uid))

    taken: set[tuple[int, int]] = set()
    plan: dict[int, tuple[int, int]] = {}
    for group, squares in ((melee, front_to_back), (ranged, back_to_front)):
        for unit in group:
            square = next(sq for sq in squares if sq not in taken)
            taken.add(square)
            plan[unit.uid] = square
    return plan


class PositionalAgent(GreedyAgent):
    def __init__(self, name: str = "agent:positional") -> None:
        super().__init__(name)

    def choose(self, state: GameState, player: PlayerState,
               rng: random.Random) -> dict:
        action = super().choose(state, player, rng)
        if action["type"] != END_TURN:
            return action
        return self._next_formation_step(state, player) or action

    @staticmethod
    def _next_formation_step(state: GameState, player: PlayerState) -> dict | None:
        """One move or swap toward the formation, or None when it is in place.

        Each step puts one unit on its target square for good: a unit already
        in place is never touched, and no other unit targets its square. So the
        formation completes in at most one step per unit.
        """
        plan = formation(state.config, state.templates, player.units())
        occupied = player.occupied()
        for uid in sorted(plan):
            square = plan[uid]
            if player.board[uid].pos() == square:
                continue
            other = occupied.get(square)
            if other is None:
                return {"type": MOVE, "uid": uid, "x": square[0], "y": square[1]}
            return {"type": SWAP, "a": uid, "b": other}
        return None
