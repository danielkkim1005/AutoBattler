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
from typing import Any

from agents.greedy import GreedyAgent
from engine.actions import END_TURN, MOVE, SWAP


def _rows_centre_first(height: int) -> list[int]:
    middle = (height - 1) / 2
    return sorted(range(height), key=lambda y: (abs(y - middle), y))


def formation(board_shape: list[int],
              units: list[dict[str, Any]]) -> dict[int, tuple[int, int]]:
    """Target square for every unit view. Injective: no two share a square."""
    width, height = board_shape
    rows = _rows_centre_first(height)
    front_to_back = [(x, y) for x in range(width - 1, -1, -1) for y in rows]
    back_to_front = [(x, y) for x in range(width) for y in rows]

    melee = sorted((u for u in units if u["range"] <= 1),
                   key=lambda u: (-u["max_health"], u["uid"]))
    ranged = sorted((u for u in units if u["range"] > 1),
                    key=lambda u: (-u["range"], u["uid"]))

    taken: set[tuple[int, int]] = set()
    plan: dict[int, tuple[int, int]] = {}
    for group, squares in ((melee, front_to_back), (ranged, back_to_front)):
        for unit in group:
            square = next(sq for sq in squares if sq not in taken)
            taken.add(square)
            plan[unit["uid"]] = square
    return plan


def next_formation_step(observation: dict[str, Any]) -> dict | None:
    """One move or swap toward the formation, or None when it is in place.

    Each step puts one unit on its target square for good: a unit already in
    place is never touched, and no other unit targets its square. So the
    formation completes in at most one step per unit.
    """
    board = observation["self"]["board"]
    plan = formation(observation["board_shape"], board)
    where = {u["uid"]: (u["x"], u["y"]) for u in board}
    occupant = {square: uid for uid, square in where.items()}
    for uid in sorted(plan):
        square = plan[uid]
        if where[uid] == square:
            continue
        other = occupant.get(square)
        if other is None:
            return {"type": MOVE, "uid": uid, "x": square[0], "y": square[1]}
        return {"type": SWAP, "a": uid, "b": other}
    return None


class PositionalAgent(GreedyAgent):
    def __init__(self, name: str = "agent:positional") -> None:
        super().__init__(name)

    def choose(self, observation: dict[str, Any], rng: random.Random) -> dict:
        action = super().choose(observation, rng)
        if action["type"] != END_TURN:
            return action
        return next_formation_step(observation) or action
