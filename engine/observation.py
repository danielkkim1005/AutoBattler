"""What a player is allowed to know: observations for agents (v0.4).

Before v0.4, agents received the whole ``GameState``. Player 0 plans first, so
when player 1's agent was called it could see player 0's purchases and moves
from *this* round, and player 0's private shop. A hand-written agent that never
looks is harmless. A trained network will look at anything it is given, and
would learn to counter-position against moves its opponent has not revealed.

An observation fixes that. It is a plain, JSON-serialisable dict:

* **Your own state is live.** Gold, level, board, and shop reflect every action
  you have taken this round.
* **Everyone else is frozen at the start of planning.** Health, level, gold,
  streak, and board, as they stood after income and before anyone acted. That
  is what scouting would show; it is identical whichever seat plans first.
* **The pool is frozen too.** A live count would reveal what an opponent just
  bought.
* **Opponents' shops are never visible.**

One residual leak remains, and is documented rather than hidden: the legal
action list is computed from the live pool, so if an opponent buys the last
copy of a unit, the matching buy disappears from your legal actions. That is
the spec's "pool resolved on purchase in player-index order" showing through.

See docs/rl/04-observations.md.
"""

from __future__ import annotations

from typing import Any

from engine.actions import legal_actions
from engine.state import GameState, PlayerState
from engine.units import BoardUnit


def unit_view(state: GameState, unit: BoardUnit) -> dict[str, Any]:
    """A board unit with its template's (pre-trait) stats attached."""
    t = state.templates[unit.template_id]
    return {
        "uid": unit.uid,
        "unit": t.id,
        "tier": t.tier,
        "trait": t.trait,
        "x": unit.x,
        "y": unit.y,
        "max_health": t.max_health,
        "attack_damage": t.attack_damage,
        "attack_cooldown": t.attack_cooldown,
        "range": t.range,
    }


def shop_view(state: GameState, template_id: str | None) -> dict[str, Any] | None:
    if template_id is None:
        return None
    t = state.templates[template_id]
    return {
        "unit": t.id,
        "tier": t.tier,
        "trait": t.trait,
        "cost": state.config.unit_cost(t.tier),
        "max_health": t.max_health,
        "attack_damage": t.attack_damage,
        "attack_cooldown": t.attack_cooldown,
        "range": t.range,
    }


def _public_view(state: GameState, player: PlayerState) -> dict[str, Any]:
    return {
        "seat": player.index,
        "alive": player.alive,
        "health": player.health,
        "level": player.level,
        "gold": player.gold,
        "streak": player.streak,
        "streak_kind": player.streak_kind,
        "board": [unit_view(state, u) for u in player.units()],
    }


def snapshot_public(state: GameState) -> None:
    """Freeze what everyone may know about everyone for this round.

    Called once per round, after income and shops and before anyone acts.
    """
    state.public = {
        "players": [_public_view(state, p) for p in state.players],
        "pool": state.pool.snapshot(),
    }


def observe(state: GameState, seat: int) -> dict[str, Any]:
    """Everything seat ``seat`` may know right now, and nothing more."""
    if not state.public:
        raise RuntimeError("no public snapshot: observe() is only valid during "
                           "planning, after begin_round()")
    config = state.config
    me = state.players[seat]
    return {
        "round": state.round,
        "seat": seat,
        "board_shape": [config.board["width"], config.board["height"]],
        "self": {
            "health": me.health,
            "gold": me.gold,
            "level": me.level,
            "streak": me.streak,
            "streak_kind": me.streak_kind,
            "board_size": config.board_size(me.level),
            "level_cost": config.level_cost(me.level),
            "board": [unit_view(state, u) for u in me.units()],
            "shop": [shop_view(state, tid) for tid in me.shop],
        },
        "opponents": [view for view in state.public["players"]
                      if view["seat"] != seat],
        "pool": state.public["pool"],
        "legal_actions": legal_actions(state, me),
    }
