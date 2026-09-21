"""Per-game metrics, derived from a replay alone.

Everything here reads a replay's event log and result block, never the
engine's live state. So it works equally on a game that just finished and on a
replay file saved months ago. It needs ``spawn`` events (v0.2+) and the
``level``/``gold`` result fields (v0.3+).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

from engine.replay import Replay

SEATS = 2


@dataclass(frozen=True)
class CombatStats:
    round: int
    ticks: int
    winner: int | None          # seat, or None for a draw
    survivors: tuple[int, int]  # living units per seat at the end
    timeout: bool               # both sides still standing: the tick cap ended it


@dataclass(frozen=True)
class GameStats:
    rounds_played: int
    placements: list[int]
    winner: int | None          # seat with sole first place, else None
    health: list[int]
    level: list[int]
    gold: list[int]
    combats: list[CombatStats]
    fielded: list[Counter]      # per seat: unit id -> rounds it was on the board
    traits: list[Counter]       # per seat: trait -> rounds it was active


def _record(replay: Replay | dict[str, Any]) -> dict[str, Any]:
    return replay.as_record() if isinstance(replay, Replay) else replay


def combat_stats(round_record: dict[str, Any]) -> CombatStats:
    owner: dict[int, int] = {}
    alive = [0] * SEATS
    ticks, winner = 0, None
    for event in round_record["events"]:
        kind = event["type"]
        if kind == "spawn":
            owner[event["actor"]] = event["target"]
            alive[event["target"]] += 1
        elif kind == "death":
            alive[owner[event["actor"]]] -= 1
        elif kind == "combat_end":
            ticks, winner = event["value"], event["actor"]
    return CombatStats(
        round=round_record["round"],
        ticks=ticks,
        winner=winner,
        survivors=(alive[0], alive[1]),
        timeout=all(n > 0 for n in alive),
    )


def game_stats(replay: Replay | dict[str, Any]) -> GameStats:
    record = _record(replay)
    result = record["result"]

    fielded = [Counter() for _ in range(SEATS)]
    traits = [Counter() for _ in range(SEATS)]
    for round_record in record["rounds"]:
        owner: dict[int, int] = {}
        for event in round_record["events"]:
            if event["type"] == "spawn":
                owner[event["actor"]] = event["target"]
                fielded[event["target"]][event["value"]["unit"]] += 1
        # trait_applied precedes its unit's spawn, hence the second pass.
        active = sorted({(owner[e["actor"]], e["target"])
                         for e in round_record["events"]
                         if e["type"] == "trait_applied"})
        for seat, trait in active:
            traits[seat][trait] += 1

    placements = result["placements"]
    firsts = [seat for seat, place in enumerate(placements) if place == 0]
    return GameStats(
        rounds_played=result["rounds_played"],
        placements=placements,
        winner=firsts[0] if len(firsts) == 1 else None,
        health=result["health"],
        level=result["level"],
        gold=result["gold"],
        combats=[combat_stats(r) for r in record["rounds"]],
        fielded=fielded,
        traits=traits,
    )
