"""Shop rolling.

Tier is drawn from the level's odds row; the unit within that tier is drawn
weighted by copies remaining in the shared pool, so a contested unit gets
rarer as opponents buy it. A tier with nothing left yields an empty slot.

Rolling never reserves copies — only a purchase takes from the pool.
"""

from __future__ import annotations

import random

from engine.config import Config
from engine.pool import Pool


def _pick_tier(odds: list[float], rng: random.Random) -> int:
    roll = rng.random()
    cumulative = 0.0
    for index, weight in enumerate(odds):
        cumulative += weight
        if roll < cumulative:
            return index + 1
    return len(odds)  # float dust at the top of the range


def _pick_unit(pool: Pool, tier: int, rng: random.Random) -> str | None:
    total = pool.total_remaining(tier)
    if total <= 0:
        return None
    draw = rng.randrange(total)
    for template_id in pool.available(tier):
        draw -= pool.remaining(template_id)
        if draw < 0:
            return template_id
    return None  # unreachable while total_remaining agrees with available()


def roll_shop(config: Config, pool: Pool, level: int,
              rng: random.Random) -> list[str | None]:
    """Roll a fresh shop. Always consumes one tier draw per slot."""
    odds = config.tier_odds(level)
    return [
        _pick_unit(pool, _pick_tier(odds, rng), rng)
        for _ in range(config.shop["slots"])
    ]
