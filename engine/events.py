"""The event log: the only output a renderer consumes.

Every mutation appends a record ``{tick, type, actor, target, value}``. The
schema is fixed at those five fields, which forces two conventions:

* ``trait_applied`` puts the unit uid in ``actor``, the trait name in
  ``target``, and the stat delta in ``value``. One event per unit per stat.
* ``combat_end`` puts the winning player index in ``actor`` (None on a draw)
  and the ending tick in ``value``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator

ATTACK = "attack"
DEATH = "death"
MOVE = "move"
TRAIT_APPLIED = "trait_applied"
COMBAT_END = "combat_end"

EVENT_TYPES = (ATTACK, DEATH, MOVE, TRAIT_APPLIED, COMBAT_END)


@dataclass(frozen=True)
class Event:
    tick: int
    type: str
    actor: Any = None
    target: Any = None
    value: Any = None

    def as_record(self) -> dict[str, Any]:
        """Serialise in the fixed field order the replay format documents."""
        return {
            "tick": self.tick,
            "type": self.type,
            "actor": self.actor,
            "target": self.target,
            "value": self.value,
        }


class EventLog:
    """An append-only list of events for a single combat."""

    def __init__(self) -> None:
        self._events: list[Event] = []

    def append(self, tick: int, type: str, actor: Any = None,
               target: Any = None, value: Any = None) -> None:
        if type not in EVENT_TYPES:
            raise ValueError(f"unknown event type {type!r}")
        self._events.append(Event(tick, type, actor, target, value))

    def records(self) -> list[dict[str, Any]]:
        return [e.as_record() for e in self._events]

    def of_type(self, type: str) -> list[Event]:
        return [e for e in self._events if e.type == type]

    def __len__(self) -> int:
        return len(self._events)

    def __iter__(self) -> Iterator[Event]:
        return iter(self._events)
