"""Income, interest, and streaks.

Income is paid at the top of the round, before shops roll, so it can be spent
the same round.
"""

from __future__ import annotations

from engine.config import Config


def interest(config: Config, gold: int) -> int:
    per = config.economy["interest_per"]
    return min(gold // per, config.economy["interest_cap"])


def streak_bonus(config: Config, streak: int) -> int:
    """Bonus for the current win-or-loss streak: the largest threshold met."""
    bonus = 0
    for threshold in sorted(config.economy["streak"]):
        if streak >= threshold:
            bonus = config.economy["streak"][threshold]
    return bonus


def round_income(config: Config, gold: int, streak: int) -> int:
    return config.economy["base_income"] + interest(config, gold) + streak_bonus(config, streak)


def sell_refund(config: Config, tier: int) -> int:
    mode = config.economy["sell_refund"]
    cost = config.unit_cost(tier)
    if mode == "full":
        return cost
    if mode == "half":
        return cost // 2
    raise ValueError(f"unknown sell_refund {mode!r}")
