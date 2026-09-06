"""Planning-phase actions: legality, enumeration, and application.

Actions are plain dicts so they serialise straight into a replay. A player may
take any number of legal actions in any order before ending their turn.
"""

from __future__ import annotations

import random

from engine.board import all_squares, in_bounds
from engine.config import Config
from engine.economy import sell_refund
from engine.shop import roll_shop
from engine.state import GameState, PlayerState
from engine.units import BoardUnit

BUY = "buy"
SELL = "sell"
REROLL = "reroll"
BUY_LEVEL = "buy_level"
MOVE = "move"
SWAP = "swap"
END_TURN = "end_turn"


class IllegalAction(ValueError):
    """Raised when an action is not legal in the current state."""


def _placement_square(config: Config, player: PlayerState) -> tuple[int, int] | None:
    free = player.free_squares(config)
    return free[0] if free else None


def is_legal(state: GameState, player: PlayerState, action: dict) -> bool:
    try:
        _check(state, player, action)
    except IllegalAction:
        return False
    return True


def _check(state: GameState, player: PlayerState, action: dict) -> None:
    config = state.config
    kind = action.get("type")

    if kind == END_TURN:
        return

    if kind == BUY:
        slot = action["slot"]
        if not 0 <= slot < len(player.shop):
            raise IllegalAction("slot out of range")
        template_id = player.shop[slot]
        if template_id is None:
            raise IllegalAction("slot is empty")
        if player.gold < config.unit_cost(state.templates[template_id].tier):
            raise IllegalAction("cannot afford")
        if state.pool.remaining(template_id) <= 0:
            raise IllegalAction("pool exhausted")
        if player.board_full(config):
            # v0 config is "block"; a bench would be handled here instead.
            if config.purchase_when_board_full == "block":
                raise IllegalAction("board is full")
            raise IllegalAction("purchase_when_board_full mode not implemented")
        if _placement_square(config, player) is None:
            raise IllegalAction("no free square")
        return

    if kind == SELL:
        if action["uid"] not in player.board:
            raise IllegalAction("not your unit")
        return

    if kind == REROLL:
        if player.gold < config.economy["reroll_cost"]:
            raise IllegalAction("cannot afford reroll")
        return

    if kind == BUY_LEVEL:
        cost = config.level_cost(player.level)
        if cost is None:
            raise IllegalAction("already at max level")
        if player.gold < cost:
            raise IllegalAction("cannot afford level")
        return

    if kind == MOVE:
        uid = action["uid"]
        if uid not in player.board:
            raise IllegalAction("not your unit")
        x, y = action["x"], action["y"]
        if not in_bounds(config, x, y):
            raise IllegalAction("off the board")
        if (x, y) in player.occupied():
            raise IllegalAction("square occupied")
        return

    if kind == SWAP:
        if action["a"] not in player.board or action["b"] not in player.board:
            raise IllegalAction("not your unit")
        if action["a"] == action["b"]:
            raise IllegalAction("cannot swap a unit with itself")
        return

    raise IllegalAction("unknown action type")


def apply_action(state: GameState, player: PlayerState, action: dict,
                 rng: random.Random) -> None:
    """Apply one action, mutating state. Raises IllegalAction if not legal."""
    _check(state, player, action)
    config = state.config
    kind = action["type"]

    if kind == END_TURN:
        return

    if kind == BUY:
        template_id = player.shop[action["slot"]]
        state.pool.take(template_id)
        player.gold -= config.unit_cost(state.templates[template_id].tier)
        x, y = _placement_square(config, player)
        uid = state.new_uid()
        player.board[uid] = BoardUnit(uid, template_id, player.index, x, y)
        player.shop[action["slot"]] = None
        return

    if kind == SELL:
        unit = player.board.pop(action["uid"])
        state.pool.give_back(unit.template_id)
        player.gold += sell_refund(config, state.templates[unit.template_id].tier)
        return

    if kind == REROLL:
        player.gold -= config.economy["reroll_cost"]
        player.shop = roll_shop(config, state.pool, player.level, rng)
        return

    if kind == BUY_LEVEL:
        player.gold -= config.level_cost(player.level)
        player.level += 1
        return

    if kind == MOVE:
        unit = player.board[action["uid"]]
        unit.x, unit.y = action["x"], action["y"]
        return

    if kind == SWAP:
        a, b = player.board[action["a"]], player.board[action["b"]]
        a.x, b.x = b.x, a.x
        a.y, b.y = b.y, a.y
        return

    raise IllegalAction("unknown action type")


def legal_actions(state: GameState, player: PlayerState) -> list[dict]:
    """Every legal action, in a deterministic order. Ending the turn is first."""
    actions: list[dict] = [{"type": END_TURN}]

    for slot in range(len(player.shop)):
        candidate = {"type": BUY, "slot": slot}
        if is_legal(state, player, candidate):
            actions.append(candidate)

    for uid in sorted(player.board):
        candidate = {"type": SELL, "uid": uid}
        if is_legal(state, player, candidate):
            actions.append(candidate)

    for candidate in ({"type": REROLL}, {"type": BUY_LEVEL}):
        if is_legal(state, player, candidate):
            actions.append(candidate)

    for uid in sorted(player.board):
        for x, y in all_squares(state.config):
            candidate = {"type": MOVE, "uid": uid, "x": x, "y": y}
            if is_legal(state, player, candidate):
                actions.append(candidate)

    board_uids = sorted(player.board)
    for i, a in enumerate(board_uids):
        for b in board_uids[i + 1:]:
            actions.append({"type": SWAP, "a": a, "b": b})

    return actions
