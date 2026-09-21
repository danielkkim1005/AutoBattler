"""Fixed-size action and observation spaces for learning agents.

The engine speaks in dicts: ``{"type": "move", "uid": 17, "x": 3, "y": 1}``.
A neural network needs a fixed number of outputs and a fixed-length input
vector. This module is the translation layer, and nothing else.

Action space
------------
One flat discrete space. Board units are addressed by **board index**: your
i-th unit in uid order (oldest first), not by uid, because uids grow without
bound. Blocks, in order:

    end_turn                       1
    buy shop slot s                slots
    sell board index i             max_board
    reroll                         1
    buy_level                      1
    move board index i -> square j max_board * width * height
    swap board index i <-> j       max_board * (max_board - 1) / 2

With the default rules that is 1 + 5 + 5 + 1 + 1 + 75 + 10 = 98 actions. Most
are illegal at any given moment, which is what the mask is for.

Observation vector
------------------
Scalars for you and your opponent, then one-hot unit grids for both boards,
the shop, and the pool. ``ObservationEncoder.names()`` labels every position,
so a vector can always be read back.

The normalising constants below (``GOLD_SCALE``, ``STREAK_SCALE``) shape the
network's input, not the game, which is why they live here and not in
rules.yaml.
"""

from __future__ import annotations

from typing import Any

from engine.actions import BUY, BUY_LEVEL, END_TURN, MOVE, REROLL, SELL, SWAP
from engine.board import all_squares
from engine.config import Config

GOLD_SCALE = 50.0
STREAK_SCALE = 5.0


class ActionSpace:
    def __init__(self, config: Config) -> None:
        self.slots = config.shop["slots"]
        self.max_board = config.board_size(config.level["max"])
        self.squares = all_squares(config)
        self.pairs = [(i, j) for i in range(self.max_board)
                      for j in range(i + 1, self.max_board)]
        self._pair_index = {pair: k for k, pair in enumerate(self.pairs)}

        blocks = [
            (END_TURN, 1),
            (BUY, self.slots),
            (SELL, self.max_board),
            (REROLL, 1),
            (BUY_LEVEL, 1),
            (MOVE, self.max_board * len(self.squares)),
            (SWAP, len(self.pairs)),
        ]
        self.offsets: dict[str, int] = {}
        self._blocks: list[tuple[str, int, int]] = []  # (kind, start, length)
        start = 0
        for kind, length in blocks:
            self.offsets[kind] = start
            self._blocks.append((kind, start, length))
            start += length
        self.size = start

    def _locate(self, index: int) -> tuple[str, int]:
        if not 0 <= index < self.size:
            raise IndexError(f"action index {index} outside 0..{self.size - 1}")
        for kind, start, length in self._blocks:
            if index < start + length:
                return kind, index - start
        raise AssertionError("unreachable")

    def decode(self, index: int, board_uids: list[int]) -> dict | None:
        """The engine action for ``index``, or None if it names an empty board
        slot. ``board_uids`` is your board in uid order."""
        kind, k = self._locate(index)
        if kind in (END_TURN, REROLL, BUY_LEVEL):
            return {"type": kind}
        if kind == BUY:
            return {"type": BUY, "slot": k}
        if kind == SELL:
            return {"type": SELL, "uid": board_uids[k]} if k < len(board_uids) else None
        if kind == MOVE:
            i, j = divmod(k, len(self.squares))
            if i >= len(board_uids):
                return None
            x, y = self.squares[j]
            return {"type": MOVE, "uid": board_uids[i], "x": x, "y": y}
        i, j = self.pairs[k]  # SWAP
        if j >= len(board_uids):
            return None
        return {"type": SWAP, "a": board_uids[i], "b": board_uids[j]}

    def encode(self, action: dict, board_uids: list[int]) -> int:
        """The index of an engine action. Inverse of ``decode``."""
        kind = action["type"]
        base = self.offsets[kind]
        if kind in (END_TURN, REROLL, BUY_LEVEL):
            return base
        if kind == BUY:
            return base + action["slot"]
        position = {uid: i for i, uid in enumerate(board_uids)}
        if kind == SELL:
            return base + position[action["uid"]]
        if kind == MOVE:
            square = self.squares.index((action["x"], action["y"]))
            return base + position[action["uid"]] * len(self.squares) + square
        pair = tuple(sorted((position[action["a"]], position[action["b"]])))
        return base + self._pair_index[pair]  # SWAP

    def mask(self, legal_actions: list[dict], board_uids: list[int]) -> list[bool]:
        """True exactly at the indices of legal actions."""
        allowed = [False] * self.size
        for action in legal_actions:
            allowed[self.encode(action, board_uids)] = True
        return allowed

    def describe(self, index: int) -> str:
        kind, k = self._locate(index)
        if kind == MOVE:
            i, j = divmod(k, len(self.squares))
            return f"move board[{i}] -> {self.squares[j]}"
        if kind == SWAP:
            i, j = self.pairs[k]
            return f"swap board[{i}] <-> board[{j}]"
        if kind in (BUY, SELL):
            return f"{kind} {'slot' if kind == BUY else 'board'}[{k}]"
        return kind


class ObservationEncoder:
    def __init__(self, config: Config) -> None:
        self.units = sorted(u["id"] for u in config.units)
        self._unit_index = {unit: i for i, unit in enumerate(self.units)}
        self.squares = all_squares(config)
        self.slots = config.shop["slots"]
        self.start_health = config.match["starting_health"]
        self.max_level = config.level["max"]
        self.max_rounds = config.match["max_rounds"]
        self.copies = {u["id"]: config.copies_for_tier(u["tier"]) for u in config.units}
        self._names = self._build_names()
        self.size = len(self._names)

    def _build_names(self) -> list[str]:
        names = ["round", "self.health", "self.gold", "self.level", "self.streak",
                 "self.board_fill", "opp.health", "opp.gold", "opp.level",
                 "opp.streak", "opp.alive"]
        for who in ("self", "opp"):
            names += [f"{who}.board.{x},{y}.{unit}"
                      for x, y in self.squares for unit in self.units]
        names += [f"shop{s}.{unit}" for s in range(self.slots) for unit in self.units]
        names += [f"pool.{unit}" for unit in self.units]
        return names

    def names(self) -> list[str]:
        return list(self._names)

    @staticmethod
    def _streak(view: dict[str, Any]) -> float:
        sign = {"win": 1.0, "loss": -1.0}.get(view["streak_kind"], 0.0)
        return sign * min(view["streak"], STREAK_SCALE) / STREAK_SCALE

    def _grid(self, board: list[dict[str, Any]]) -> list[float]:
        cells = [0.0] * (len(self.squares) * len(self.units))
        for unit in board:
            square = self.squares.index((unit["x"], unit["y"]))
            cells[square * len(self.units) + self._unit_index[unit["unit"]]] = 1.0
        return cells

    def encode(self, observation: dict[str, Any]) -> list[float]:
        me = observation["self"]
        opp = observation["opponents"][0]
        vector = [
            observation["round"] / self.max_rounds,
            me["health"] / self.start_health,
            me["gold"] / GOLD_SCALE,
            me["level"] / self.max_level,
            self._streak(me),
            len(me["board"]) / me["board_size"],
            opp["health"] / self.start_health,
            opp["gold"] / GOLD_SCALE,
            opp["level"] / self.max_level,
            self._streak(opp),
            1.0 if opp["alive"] else 0.0,
        ]
        vector += self._grid(me["board"])
        vector += self._grid(opp["board"])
        shop = [0.0] * (self.slots * len(self.units))
        for slot, item in enumerate(me["shop"]):
            if item is not None:
                shop[slot * len(self.units) + self._unit_index[item["unit"]]] = 1.0
        vector += shop
        vector += [observation["pool"][unit] / self.copies[unit] for unit in self.units]
        return vector
