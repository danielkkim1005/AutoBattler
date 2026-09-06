"""Baseline agents.

Agents live outside engine/ but obey the same rule: every random choice comes
from the rng handed to them, never from a module-level generator.
"""

from agents.greedy import GreedyAgent
from agents.random_agent import RandomAgent

__all__ = ["GreedyAgent", "RandomAgent"]
