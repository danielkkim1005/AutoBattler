"""Unit templates and the two kinds of instance derived from them.

``UnitTemplate`` is frozen and shared. ``BoardUnit`` is what a player owns
between rounds — identity and a square, no stats. ``CombatUnit`` is built fresh
at the start of every combat with trait bonuses already baked into its stat
fields, so ``max_health`` is written once at construction and never again.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from engine.config import Config


@dataclass(frozen=True)
class UnitTemplate:
    id: str
    tier: int
    trait: str
    max_health: int
    attack_damage: int
    attack_cooldown: int
    range: int


def load_templates(config: Config) -> dict[str, UnitTemplate]:
    """Build the immutable template table, keyed by unit id."""
    templates: dict[str, UnitTemplate] = {}
    for row in config.units:
        templates[row["id"]] = UnitTemplate(
            id=row["id"],
            tier=int(row["tier"]),
            trait=row["trait"],
            max_health=int(row["max_health"]),
            attack_damage=int(row["attack_damage"]),
            attack_cooldown=int(row["attack_cooldown"]),
            range=int(row["range"]),
        )
    return templates


def templates_by_tier(templates: Mapping[str, UnitTemplate], tier: int) -> list[str]:
    """Unit ids of a tier, sorted — never iterate the template dict directly."""
    return sorted(uid for uid, t in templates.items() if t.tier == tier)


@dataclass
class BoardUnit:
    """A unit a player owns, sitting on a square of their own 3x5 board."""

    uid: int
    template_id: str
    owner: int
    x: int
    y: int

    def pos(self) -> tuple[int, int]:
        return (self.x, self.y)


@dataclass
class CombatUnit:
    """A unit inside a resolving combat.

    Stat fields are assigned at construction and treated as read-only for the
    rest of the combat. Only ``health``, ``x``, ``y``, ``target`` and
    ``ticks_until_attack`` mutate.
    """

    uid: int
    owner: int
    template_id: str
    max_health: int
    attack_damage: int
    attack_cooldown: int
    range: int
    x: int
    y: int
    health: int
    ticks_until_attack: int = 0
    target: int | None = None

    @property
    def alive(self) -> bool:
        return self.health > 0

    def pos(self) -> tuple[int, int]:
        return (self.x, self.y)
