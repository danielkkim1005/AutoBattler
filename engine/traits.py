"""Trait breakpoints.

A trait is active for a player when the number of units on their board carrying
it reaches the breakpoint. v0 counts copies, not distinct unit ids: two
footmen activate vanguard. One breakpoint per trait.
"""

from __future__ import annotations

from typing import Iterable, Mapping

from engine.config import Config
from engine.units import BoardUnit, UnitTemplate


def trait_counts(units: Iterable[BoardUnit],
                 templates: Mapping[str, UnitTemplate]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for unit in units:
        trait = templates[unit.template_id].trait
        counts[trait] = counts.get(trait, 0) + 1
    return counts


def active_bonuses(config: Config, units: Iterable[BoardUnit],
                   templates: Mapping[str, UnitTemplate]) -> dict[str, dict[str, int]]:
    """Map trait name -> stat deltas, for traits that hit their breakpoint.

    Returned in sorted trait order so downstream event logging is stable.
    """
    counts = trait_counts(units, templates)
    active: dict[str, dict[str, int]] = {}
    for trait in sorted(config.traits):
        spec = config.traits[trait]
        if counts.get(trait, 0) >= spec["breakpoint"]:
            active[trait] = {k: int(v) for k, v in sorted(spec["bonus"].items())}
    return active
