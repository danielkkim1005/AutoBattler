"""Combat resolution.

Boards are merged into a single field, player 0 on the left half and player 1
mirrored onto the right. Combat then advances in integer ticks until one side
is wiped or the tick cap is reached.

Two resolution modes, chosen by ``combat.resolution``:

* ``simultaneous`` (default since v0.2). Every unit decides what to do from the
  field as it stood at the start of the tick. Then every attack lands at once,
  including attacks from units that die this tick. Then the survivors move.
  No unit sees another unit's action from the same tick, so unit ids carry no
  advantage and a perfect mirror match is a draw.
* ``sequential`` (the v0.1 behaviour). Units act one at a time in uid order,
  each seeing everything lower uids did this tick. That hands a structural
  edge to one side. It is kept only so the bias can be measured; see
  docs/rl/02-environment-bias.md.

In both modes a unit in range but on cooldown holds its ground rather than
advancing, which keeps ``range`` meaningful.

``board.positioning: false`` (v0.3) turns the fight into a brawl: every unit is
in range of every enemy, nobody moves, and ``nearest`` targeting collapses to
the tiebreak. Squares still exist - they just stop mattering - which is what
makes it a clean control for measuring what positioning is worth. Trait bonuses are baked into a
fresh ``CombatUnit`` at construction, so ``max_health`` is never written to.

Randomness: only ``simultaneous`` with ``move_conflict: random`` draws from the
rng, to settle two units claiming the same square. The rng passed in is the
round's own combat stream, isolated from the shop stream, so a change in how a
fight plays out never shifts a later shop roll.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Callable

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
    """Merge both boards into one field, applying trait bonuses on the way.

    Emits ``trait_applied`` then ``spawn`` for each unit at tick 0, in sorted-uid
    order across both players. The spawn event carries final, post-trait stats
    and field coordinates: everything a renderer needs to draw the opening.
    """
    config = state.config
    bonuses = {
        player.index: active_bonuses(config, player.units(), state.templates)
        for player in state.players
    }
    board_units = {unit.uid: unit for player in state.players for unit in player.units()}

    units: dict[int, CombatUnit] = {}
    for uid in sorted(board_units):
        unit = board_units[uid]
        template = state.templates[unit.template_id]
        stats = {
            "max_health": template.max_health,
            "attack_damage": template.attack_damage,
            "attack_cooldown": template.attack_cooldown,
            "range": template.range,
        }
        for stat, delta in bonuses[unit.owner].get(template.trait, {}).items():
            stats[stat] += delta
            log.append(0, events.TRAIT_APPLIED, actor=uid,
                       target=template.trait, value=delta)
        stats["attack_cooldown"] = max(MIN_ATTACK_COOLDOWN, stats["attack_cooldown"])

        x, y = to_field(config, unit.owner, unit.x, unit.y)
        units[uid] = CombatUnit(
            uid=uid,
            owner=unit.owner,
            template_id=unit.template_id,
            max_health=stats["max_health"],
            attack_damage=stats["attack_damage"],
            attack_cooldown=stats["attack_cooldown"],
            range=stats["range"],
            x=x,
            y=y,
            health=stats["max_health"],
        )
        log.append(0, events.SPAWN, actor=uid, target=unit.owner, value={
            "unit": unit.template_id,
            "x": x,
            "y": y,
            "max_health": stats["max_health"],
            "attack_damage": stats["attack_damage"],
            "attack_cooldown": stats["attack_cooldown"],
            "range": stats["range"],
        })
    return units


def _living(units: dict[int, CombatUnit], owner: int | None = None) -> list[CombatUnit]:
    """Living units in sorted-uid order, optionally filtered to one side."""
    return [
        units[uid] for uid in sorted(units)
        if units[uid].alive and (owner is None or units[uid].owner == owner)
    ]


def _acquire_target(config: Config, unit: CombatUnit,
                    units: dict[int, CombatUnit]) -> int | None:
    """Pick a target by target_rule, breaking ties on lowest uid.

    In a brawl (``board.positioning: false``) there is no distance, so
    ``nearest`` has nothing to measure and falls through to the tiebreak.
    """
    rule = config.combat["target_rule"]
    metric = config.combat["move_metric"]
    enemies = [u for u in _living(units) if u.owner != unit.owner]
    if not enemies:
        return None

    if rule == "nearest" and not config.board["positioning"]:
        def key(enemy: CombatUnit) -> tuple[int, int]:
            return (0, enemy.uid)
    elif rule == "nearest":
        def key(enemy: CombatUnit) -> tuple[int, int]:
            return (distance(metric, unit.x, unit.y, enemy.x, enemy.y), enemy.uid)
    else:  # lowest_health; config validation rules out anything else
        def key(enemy: CombatUnit) -> tuple[int, int]:
            return (enemy.health, enemy.uid)

    return min(enemies, key=key).uid


def _current_target(config: Config, unit: CombatUnit,
                    units: dict[int, CombatUnit]) -> CombatUnit | None:
    """Keep the current target while it lives; otherwise acquire a new one."""
    if unit.target is None or not units[unit.target].alive:
        unit.target = _acquire_target(config, unit, units)
    return None if unit.target is None else units[unit.target]


def _in_range(config: Config, unit: CombatUnit, target: CombatUnit) -> bool:
    """Within range on the grid. In a brawl, everyone reaches everyone."""
    if not config.board["positioning"]:
        return True
    metric = config.combat["move_metric"]
    return distance(metric, unit.x, unit.y, target.x, target.y) <= unit.range


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


def _strike(attacker: CombatUnit, target: CombatUnit, log: EventLog, tick: int) -> None:
    target.health -= attacker.attack_damage
    log.append(tick, events.ATTACK, actor=attacker.uid, target=target.uid,
               value=attacker.attack_damage)
    attacker.ticks_until_attack = attacker.attack_cooldown


def _relocate(unit: CombatUnit, destination: tuple[int, int], chasing: int,
              occupied: dict[tuple[int, int], int], log: EventLog, tick: int) -> None:
    del occupied[unit.pos()]
    unit.x, unit.y = destination
    occupied[destination] = unit.uid
    log.append(tick, events.MOVE, actor=unit.uid, target=chasing,
               value=list(destination))


def _tick_sequential(config: Config, units: dict[int, CombatUnit],
                     occupied: dict[tuple[int, int], int], log: EventLog,
                     tick: int, rng: random.Random) -> None:
    """v0.1 semantics: each unit acts in uid order on a field already changed
    by every lower uid this tick. Kept as an ablation of the side bias."""
    for unit in _living(units):
        if not unit.alive:  # killed earlier in this same tick
            continue
        target = _current_target(config, unit, units)
        if target is None:
            break  # no enemies left; the tick is over

        if _in_range(config, unit, target):
            if unit.ticks_until_attack == 0:
                _strike(unit, target, log, tick)
                if not target.alive:
                    log.append(tick, events.DEATH, actor=target.uid,
                               target=unit.uid, value=target.health)
                    del occupied[target.pos()]
            # In range but on cooldown: hold position.
        else:
            destination = _step_toward(config, unit, target, occupied)
            if destination is not None:
                _relocate(unit, destination, target.uid, occupied, log, tick)


def _settle_claim(config: Config, claimants: list[int], rng: random.Random) -> int:
    """Pick which of several units claiming one square gets it."""
    if len(claimants) == 1:
        return claimants[0]
    if config.combat["move_conflict"] == "lowest_id":
        return min(claimants)
    return claimants[rng.randrange(len(claimants))]


def _tick_simultaneous(config: Config, units: dict[int, CombatUnit],
                       occupied: dict[tuple[int, int], int], log: EventLog,
                       tick: int, rng: random.Random) -> None:
    """Decide from a snapshot, then land every attack, then move survivors."""
    # 1. Decide. Nothing on the field changes during this loop - only each
    #    unit's own choice of target - so every unit sees the same snapshot.
    strikes: list[tuple[CombatUnit, CombatUnit]] = []
    wanted: dict[int, tuple[int, int]] = {}
    for unit in _living(units):
        target = _current_target(config, unit, units)
        if target is None:
            continue
        if _in_range(config, unit, target):
            if unit.ticks_until_attack == 0:
                strikes.append((unit, target))
            # In range but on cooldown: hold position.
        else:
            destination = _step_toward(config, unit, target, occupied)
            if destination is not None:
                wanted[unit.uid] = destination

    # 2. Every decided attack lands, including those from units that are about
    #    to die. Deaths are only settled once all damage is in.
    hit_by: dict[int, list[int]] = {}
    for attacker, target in strikes:
        _strike(attacker, target, log, tick)
        hit_by.setdefault(target.uid, []).append(attacker.uid)
    for uid in sorted(hit_by):
        victim = units[uid]
        if not victim.alive:
            log.append(tick, events.DEATH, actor=uid, target=min(hit_by[uid]),
                       value=victim.health)
            del occupied[victim.pos()]

    # 3. Survivors move. Every destination was empty at the start of the tick,
    #    so the only conflict is two units claiming the same square.
    claims: dict[tuple[int, int], list[int]] = {}
    for uid in sorted(wanted):
        if units[uid].alive:
            claims.setdefault(wanted[uid], []).append(uid)
    movers = [_settle_claim(config, claims[square], rng) for square in sorted(claims)]
    for uid in sorted(movers):
        unit = units[uid]
        _relocate(unit, wanted[uid], unit.target, occupied, log, tick)


TickFn = Callable[[Config, dict[int, CombatUnit], dict[tuple[int, int], int],
                   EventLog, int, random.Random], None]
_TICKS: dict[str, TickFn] = {
    "simultaneous": _tick_simultaneous,
    "sequential": _tick_sequential,
}


def _side_wiped(state: GameState, units: dict[int, CombatUnit]) -> int | None:
    """Winner if exactly one side still has units, else None.

    A double wipe, or two empty boards, leaves no winner and returns None.
    """
    alive_sides = [p.index for p in state.players if _living(units, p.index)]
    if len(alive_sides) == 1:
        return alive_sides[0]
    return None


def _timeout_winner(state: GameState, units: dict[int, CombatUnit]) -> int | None:
    """most_total_health; config validation rules out anything else."""
    totals = {
        p.index: sum(u.health for u in _living(units, p.index))
        for p in state.players
    }
    best = max(totals.values())
    leaders = sorted(i for i, total in totals.items() if total == best)
    return leaders[0] if len(leaders) == 1 else None


def resolve_combat(state: GameState, rng: random.Random) -> CombatResult:
    """Run one combat to completion and return the result plus its event log.

    ``rng`` should be the round's combat stream (see engine.game.resolve), not
    the stream that rolls shops.
    """
    config = state.config
    log = EventLog()
    units = build_combat_units(state, log)
    tick_cap = config.combat["tick_cap"]
    tick_fn = _TICKS[config.combat["resolution"]]

    occupied: dict[tuple[int, int], int] = {u.pos(): u.uid for u in _living(units)}

    tick = 0
    winner = _side_wiped(state, units)
    # An empty field - two bare boards, or a double wipe - is over at once.
    # Without the _living guard it would grind out the full tick cap doing
    # nothing before timing out to the same draw.
    while winner is None and _living(units) and tick < tick_cap:
        tick += 1
        tick_fn(config, units, occupied, log, tick, rng)

        for unit in _living(units):
            if unit.ticks_until_attack > 0:
                unit.ticks_until_attack -= 1

        winner = _side_wiped(state, units)

    if winner is None:
        winner = _timeout_winner(state, units)

    log.append(tick, events.COMBAT_END, actor=winner, value=tick)
    survivors = {p.index: _living(units, p.index) for p in state.players}
    return CombatResult(winner=winner, ticks=tick, log=log, survivors=survivors)
