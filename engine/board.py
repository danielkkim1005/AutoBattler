"""Board geometry and the merge into a single combat field.

Each player plans on their own ``width x height`` board. On contact the two
boards are merged: player 0 keeps its coordinates on the left half, player 1 is
mirrored onto the right half, so a unit on player 1's back line ends up
furthest from the fight.
"""

from __future__ import annotations

from engine.config import Config


def in_bounds(config: Config, x: int, y: int) -> bool:
    return 0 <= x < config.board["width"] and 0 <= y < config.board["height"]


def all_squares(config: Config) -> list[tuple[int, int]]:
    """Every square of one player's board, in deterministic (x, y) order."""
    return [
        (x, y)
        for x in range(config.board["width"])
        for y in range(config.board["height"])
    ]


def field_width(config: Config) -> int:
    return config.board["width"] * 2


def to_field(config: Config, owner: int, x: int, y: int) -> tuple[int, int]:
    """Map a player-local square onto the merged field."""
    if owner == 0:
        return (x, y)
    return (field_width(config) - 1 - x, y)


def field_in_bounds(config: Config, x: int, y: int) -> bool:
    return 0 <= x < field_width(config) and 0 <= y < config.board["height"]


def distance(metric: str, ax: int, ay: int, bx: int, by: int) -> int:
    dx = abs(ax - bx)
    dy = abs(ay - by)
    if metric == "chebyshev":
        return max(dx, dy)
    if metric == "manhattan":
        return dx + dy
    raise ValueError(f"unknown move_metric {metric!r}")
