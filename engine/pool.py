"""The shared unit pool.

Copies are shared across all players, which is what makes contesting real. A
purchase takes a copy; a sale returns one. A unit with no copies left cannot
appear in any shop.
"""

from __future__ import annotations

from typing import Mapping

from engine.config import Config
from engine.units import UnitTemplate


class Pool:
    def __init__(self, config: Config, templates: Mapping[str, UnitTemplate]) -> None:
        self._templates = templates
        self._remaining: dict[str, int] = {
            uid: config.copies_for_tier(t.tier) for uid, t in templates.items()
        }

    def remaining(self, template_id: str) -> int:
        return self._remaining[template_id]

    def take(self, template_id: str) -> None:
        """Remove one copy. Callers check availability first."""
        if self._remaining[template_id] <= 0:
            raise ValueError(f"pool exhausted for {template_id}")
        self._remaining[template_id] -= 1

    def give_back(self, template_id: str) -> None:
        self._remaining[template_id] += 1

    def available(self, tier: int) -> list[str]:
        """Sorted ids of a tier that still have copies left."""
        return sorted(
            uid for uid, t in self._templates.items()
            if t.tier == tier and self._remaining[uid] > 0
        )

    def total_remaining(self, tier: int) -> int:
        return sum(
            self._remaining[uid] for uid in sorted(self._templates)
            if self._templates[uid].tier == tier
        )

    def snapshot(self) -> dict[str, int]:
        return dict(sorted(self._remaining.items()))
