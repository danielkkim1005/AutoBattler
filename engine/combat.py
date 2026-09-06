"""Combat resolution.

Boards are merged into a single field, player 0 on the left half and player 1
mirrored onto the right. Combat then advances in integer ticks until one side
is wiped or the tick cap is reached.

Two readings of the spec are pinned down here, because the prose leaves them
open and the outcome depends on both:

* A unit that is in range but still on cooldown holds its ground. It does not
  advance. Otherwise a ranged unit would walk into melee while waiting, which
  would make range meaningless.
* Trait bonuses are baked into a fresh CombatUnit at construction rather than
  written onto an existing unit, which is what keeps the "max_health is never
  written to" invariant true.

Combat consumes no randomness. The rng is threaded through anyway so the
signature stays honest if a future rule needs it.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from engine import events
from engine.board import distance, field_in_bounds, to_field
from engine.config import Config
from engine.events import EventLog
from engine.state import GameState
from engine.traits import active_bonuses
from engine.units import CombatUnit

MIN_ATTACK_COOLDOWN = 1  # a cooldown reduced past this would mean free attacks


@dataclass
class CombatResult:
    winner: int | None  # player index, or None for a draw
    ticks: int
    log: EventLog
    survivors: dict[int, list[CombatUnit]]  # player index -> living units


def _sign(n: int) -> int:
    return (n > 0) - (n < 0)


def build_combat_units(state: GameState, log: EventLog) -> dict[int, CombatUnit]:
    """Merge both boards into one field, applying trait bonuses on the way."""
    units: dict[int, CombatUnit] = {}

    for player in state.players:
        bonuses = active_bonuses(state.config, player.units(), state.templates)
        for unit in player.units():
            template = state.templates[unit.template_id]
            stats = {
                "max_health": template.max_health,
                "attack_damage": template.attack_damage,
                "attack_cooldown": template.attack_cooldown,
                "range": template.range,
            }
            trait = template.trait
            for stat, delta in bonuses.get(trait, {}).items():
                stats[stat] += delta
                log.append(0, events.TRAIT_APPLIED, actor=unit.uid,
                           target=trait, value=delta)
            stats["attack_cooldown"] = max(MIN_ATTACK_COOLDOWN,
                                           stats["attack_cooldown"])

            x, y = to_field(state.config, player.index, unit.x, unit.y)
            units[unit.uid] = CombatUnit(
                uid=unit.uid,
                owner=player.index,
                template_id=unit.template_id,
                max_health=stats["max_health"],
                attack_damage=stats["attack_damage"],
                attack_cooldown=stats["attack_cooldown"],
                range=stats["range"],
                x=x,
                y=y,
                health=stats["max_health"],
            )
    return units


def _living(units: dict[int, CombatUnit], owner: int | None = None) -> list[CombatUnit]:
    """Living units in sorted-uid order, optionally filtered to one side."""
    return [
        units[uid] for uid in sorted(units)
        if units[uid].alive and (owner is None or units[uid].owner == owner)
    ]


def _acquire_target(config: Config, unit: CombatUnit,
                    units: dict[int, CombatUnit]) -> int | None:
    """Pick a target by target_rule, breaking ties on lowest uid."""
    if config.combat["target_tiebreak"] != "lowest_id":
        raise ValueError("only lowest_id tiebreak is implemented")

    rule = config.combat["target_rule"]
    metric = config.combat["move_metric"]
    enemies = [u for u in _living(units) if u.owner != unit.owner]
    if not enemies:
        return None

    if rule == "nearest":
        def key(enemy: CombatUnit) -> tuple[int, int]:
            return (distance(metric, unit.x, unit.y, enemy.x, enemy.y), enemy.uid)
    elif rule == "lowest_health":
        def key(enemy: CombatUnit) -> tuple[int, int]:
            return (enemy.health, enemy.uid)
    else:
        raise ValueError("unknown target_rule: " + str(rule))

    return min(enemies, key=key).uid


def _step_toward(config: Config, unit: CombatUnit, target: CombatUnit,
                 occupied: dict[tuple[int, int], int]) -> tuple[int, int] | None:
    """One axis-aligned step that most reduces distance; x wins ties.

    Returns the destination, or None when the unit does not move - either it is
    already stacked on the target or the chosen square is taken.
    """
    metric = config.combat["move_metric"]
    step = config.combat["move_per_tick"]

    candidates: list[tuple[int, int, int]] = []  # (priority, x, y); 0 = x-axis
    if target.x != unit.x:
        candidates.append((0, unit.x + _sign(target.x - unit.x) * step, unit.y))
    if target.y != unit.y:
        candidates.append((1, unit.x, unit.y + _sign(target.y - unit.y) * step))
    if not candidates:
        return None

    def rank(candidate: tuple[int, int, int]) -> tuple[int, int]:
        priority, x, y = candidate
        return (distance(metric, x, y, target.x, target.y), priority)

    _, x, y = min(candidates, key=rank)
    if not field_in_bounds(config, x, y) or (x, y) in occupied:
        return None
    return (x, y)


def _side_wiped(state: GameState, units: dict[int, CombatUnit]) -> int | None:
    """Winner if exactly one side still has units, else None.

    A double wipe, or two empty boards, leaves no winner and returns None.
    """
    alive_sides = [p.index for p in state.players if _living(units, p.index)]
    if len(alive_sides) == 1:
        return alive_sides[0]
    return None


def _timeout_winner(state: GameState, units: dict[int, CombatUnit]) -> int | None:
    rule = state.config.combat["timeout_result"]
    if rule != "most_total_health":
        raise ValueError("unknown timeout_result: " + str(rule))

    totals = {
        p.index: sum(u.health for u in _living(units, p.index))
        for p in state.players
    }
    best = max(totals.values())
    leaders = sorted(i for i, total in totals.items() if total == best)
    return leaders[0] if len(leaders) == 1 else None


def resolve_combat(state: GameState, rng: random.Random) -> CombatResult:
    """Run one combat to completion and return the result plus its event log."""
    config = state.config
    log = EventLog()
    units = build_combat_units(state, log)
    metric = config.combat["move_metric"]
    tick_cap = config.combat["tick_cap"]

    occupied: dict[tuple[int, int], int] = {u.pos(): u.uid for u in _living(units)}

    tick = 0
    winner = _side_wiped(state, units)
    # An empty field - two bare boards, or a double wipe - is over at once.
    # Without the _living guard it would grind out the full tick cap doing
    # nothing before timing out to the same draw.
    while winner is None and _living(units) and tick < tick_cap:
        tick += 1
        for unit in _living(units):
            if not unit.alive:  # killed earlier in this same tick
                continue

            target_uid = unit.target
            if target_uid is None or not units[target_uid].alive:
                target_uid = _acquire_target(config, unit, units)
                unit.target = target_uid
            if target_uid is None:
                break  # no enemies left; the tick is over

            target = units[target_uid]
            if distance(metric, unit.x, unit.y, target.x, target.y) <= unit.range:
                if unit.ticks_until_attack == 0:
                    target.health -= unit.attack_damage
                    log.append(tick, events.ATTACK, actor=unit.uid,
                               target=target.uid, value=unit.attack_damage)
                    unit.ticks_until_attack = unit.attack_cooldown
                    if not target.alive:
                        log.append(tick, events.DEATH, actor=target.uid,
                                   target=unit.uid, value=target.health)
                        del occupied[target.pos()]
                # In range but on cooldown: hold position.
            else:
                destination = _step_toward(config, unit, target, occupied)
                if destination is not None:
                    del occupied[unit.pos()]
                    unit.x, unit.y = destination
                    occupied[destination] = unit.uid
                    log.append(tick, events.MOVE, actor=unit.uid,
                               target=target.uid, value=list(destination))

        for unit in _living(units):
            if unit.ticks_until_attack > 0:
                unit.ticks_until_attack -= 1

        winner = _side_wiped(state, units)

    if winner is None:
        winner = _timeout_winner(state, units)

    log.append(tick, events.COMBAT_END, actor=winner, value=tick)
    survivors = {p.index: _living(units, p.index) for p in state.players}
    return CombatResult(winner=winner, ticks=tick, log=log, survivors=survivors)
