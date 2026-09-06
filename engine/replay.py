"""The replay format.

A replay is the whole artifact: seed, config hash, every action, every event.
Identical seed + config_hash + action sequence must serialise byte-identically,
which is why this module fixes key order and JSON separators rather than
leaving them to defaults.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

REPLAY_VERSION = "0.1.0"


@dataclass
class RoundRecord:
    round: int
    actions: list[tuple[int, dict]] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)

    def as_record(self) -> dict[str, Any]:
        return {
            "round": self.round,
            "actions": [[player, action] for player, action in self.actions],
            "events": self.events,
        }


@dataclass
class Replay:
    config_hash: str
    seed: int
    players: list[str]
    rounds: list[RoundRecord] = field(default_factory=list)
    result: dict[str, Any] = field(default_factory=dict)
    version: str = REPLAY_VERSION

    def as_record(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "config_hash": self.config_hash,
            "seed": self.seed,
            "players": list(self.players),
            "rounds": [r.as_record() for r in self.rounds],
            "result": self.result,
        }

    def to_json(self) -> str:
        """Serialise deterministically. Two equal runs produce equal bytes."""
        return json.dumps(
            self.as_record(),
            indent=2,
            separators=(",", ": "),
            ensure_ascii=True,
            sort_keys=False,
        )

    def action_sequence(self) -> list[list[tuple[int, dict]]]:
        """Per-round action lists, for replaying a recorded game."""
        return [list(r.actions) for r in self.rounds]
