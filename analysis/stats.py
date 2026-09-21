"""Small, dependency-free statistics for reading experiment results.

Two tools, for two shapes of data (see docs/rl/03-evaluation.md):

* ``wilson_interval`` - for a count of successes out of independent trials,
  such as "seat 0 won 205 of 500 games".
* ``mean_interval`` - for a list of per-seed scores, such as a seat-swapped
  pair of games scored 0, 0.25, 0.5, 0.75 or 1. The seed is the independent
  unit there, not the game, because both games of a pair share the same luck.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

Z95 = 1.959963984540054  # two-sided 95% normal quantile


@dataclass(frozen=True)
class Estimate:
    value: float
    low: float
    high: float
    n: int

    def contains(self, x: float) -> bool:
        return self.low <= x <= self.high

    def __str__(self) -> str:
        return f"{self.value:.3f} [{self.low:.3f}, {self.high:.3f}] (n={self.n})"


def wilson_interval(successes: int, trials: int, z: float = Z95) -> Estimate:
    """Wilson score interval for a binomial proportion.

    Preferred over the textbook ``p +/- z*sqrt(p(1-p)/n)``: that one collapses to
    zero width at p = 0 or 1 and undercovers for small n.
    """
    if trials <= 0:
        return Estimate(0.0, 0.0, 1.0, 0)
    p = successes / trials
    denom = 1 + z * z / trials
    centre = (p + z * z / (2 * trials)) / denom
    half = z * math.sqrt(p * (1 - p) / trials + z * z / (4 * trials * trials)) / denom
    return Estimate(p, max(0.0, centre - half), min(1.0, centre + half), trials)


def mean_interval(values: Sequence[float], z: float = Z95) -> Estimate:
    """Mean with a normal-approximation interval from the sample spread.

    Fine for the sample sizes used here (hundreds of seeds). With fewer than
    about 30 values, prefer a t-interval.
    """
    n = len(values)
    if n == 0:
        return Estimate(0.0, 0.0, 0.0, 0)
    mean = sum(values) / n
    if n == 1:
        return Estimate(mean, mean, mean, 1)
    variance = sum((v - mean) ** 2 for v in values) / (n - 1)
    half = z * math.sqrt(variance / n)
    return Estimate(mean, mean - half, mean + half, n)


def games_for_margin(margin: float, z: float = Z95) -> int:
    """Games needed for a 95% interval of +/- ``margin`` on an even win rate.

    From n = (z * 0.5 / margin)^2. A 2-point margin needs about 2,400 games.
    """
    return math.ceil((z * 0.5 / margin) ** 2)
