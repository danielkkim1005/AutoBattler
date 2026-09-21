"""Evaluating agents and rulesets, with honest error bars.

``run_matchup`` plays agent A against agent B over a list of seeds. By default
every seed is played twice with the seats swapped, so any seat advantage hits
both agents equally and cancels out. The seed, not the game, is the unit of
independence: both games of a pair share the same luck (docs/rl/03-evaluation.md).

``compare_rulesets`` plays the same matchup under two configs on the same
seeds and reports per-seed *paired* differences. Pairing lets shared luck
cancel, so a real change shows up with fewer games.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

from analysis.stats import Estimate, mean_interval, wilson_interval
from analysis.telemetry import GameStats, game_stats
from engine.config import Config
from engine.game import play_game

AgentFactory = Callable[[], Any]


@dataclass(frozen=True)
class GameRow:
    seed: int
    a_seat: int
    stats: GameStats

    @property
    def a_score(self) -> float:
        """1 for an A win, 0.5 for a draw, 0 for a loss."""
        if self.stats.winner is None:
            return 0.5
        return 1.0 if self.stats.winner == self.a_seat else 0.0


@dataclass
class MatchupReport:
    label_a: str
    label_b: str
    config_hash: str
    swapped: bool
    rows: list[GameRow] = field(default_factory=list)

    # -- outcome ------------------------------------------------------------
    def per_seed(self, metric: Callable[[GameRow], float]) -> list[float]:
        """Average a per-game metric over each seed's games (one or two)."""
        by_seed: dict[int, list[float]] = {}
        for row in self.rows:
            by_seed.setdefault(row.seed, []).append(metric(row))
        return [sum(v) / len(v) for _, v in sorted(by_seed.items())]

    @property
    def a_score(self) -> Estimate:
        """A's expected score per game, from per-seed averages."""
        return mean_interval(self.per_seed(lambda r: r.a_score))

    def counts(self) -> dict[str, int]:
        a = sum(1 for r in self.rows if r.stats.winner == r.a_seat)
        draws = sum(1 for r in self.rows if r.stats.winner is None)
        return {"games": len(self.rows), "a_wins": a,
                "b_wins": len(self.rows) - a - draws, "draws": draws}

    @property
    def seat0(self) -> Estimate:
        """Seat 0's share of decided games. Near 0.5 means no seat bias."""
        decided = [r for r in self.rows if r.stats.winner is not None]
        wins = sum(1 for r in decided if r.stats.winner == 0)
        return wilson_interval(wins, len(decided))

    # -- telemetry ----------------------------------------------------------
    @property
    def rounds(self) -> Estimate:
        return mean_interval(self.per_seed(lambda r: r.stats.rounds_played))

    def combat_summary(self) -> dict[str, float]:
        combats = [c for r in self.rows for c in r.stats.combats]
        n = len(combats) or 1
        return {
            "combats": len(combats),
            "mean_ticks": sum(c.ticks for c in combats) / n,
            "timeout_rate": sum(c.timeout for c in combats) / n,
            "draw_rate": sum(c.winner is None for c in combats) / n,
        }

    def agent_summary(self, which: str) -> dict[str, Any]:
        """Level, unit mix, and trait uptime for agent 'a' or 'b'."""
        seat_of = (lambda r: r.a_seat) if which == "a" else (lambda r: 1 - r.a_seat)
        rows = self.rows
        levels = [r.stats.level[seat_of(r)] for r in rows]
        fielded: Counter = Counter()
        traits: Counter = Counter()
        rounds = 0
        for r in rows:
            fielded.update(r.stats.fielded[seat_of(r)])
            traits.update(r.stats.traits[seat_of(r)])
            rounds += r.stats.rounds_played
        total_units = sum(fielded.values()) or 1
        return {
            "mean_final_level": sum(levels) / (len(levels) or 1),
            "unit_share": {u: round(n / total_units, 3)
                           for u, n in sorted(fielded.items())},
            "trait_uptime": {t: round(n / (rounds or 1), 3)
                             for t, n in sorted(traits.items())},
        }

    def as_dict(self) -> dict[str, Any]:
        def est(e: Estimate) -> dict[str, float]:
            return {"value": round(e.value, 4), "low": round(e.low, 4),
                    "high": round(e.high, 4), "n": e.n}
        return {
            "a": self.label_a,
            "b": self.label_b,
            "config_hash": self.config_hash,
            "seat_swapped": self.swapped,
            **self.counts(),
            "a_score": est(self.a_score),
            "seat0_share": est(self.seat0),
            "rounds": est(self.rounds),
            "combat": {k: round(v, 4) for k, v in self.combat_summary().items()},
            "agent_a": self.agent_summary("a"),
            "agent_b": self.agent_summary("b"),
        }


def run_matchup(config: Config, make_a: AgentFactory, make_b: AgentFactory,
                seeds: Sequence[int], swap_seats: bool = True,
                label_a: str = "A", label_b: str = "B") -> MatchupReport:
    report = MatchupReport(label_a, label_b, config.config_hash, swap_seats)
    for seed in seeds:
        for a_seat in ((0, 1) if swap_seats else (0,)):
            agents = [make_a(), make_b()] if a_seat == 0 else [make_b(), make_a()]
            replay = play_game(config, seed, agents)
            report.rows.append(GameRow(seed, a_seat, game_stats(replay)))
    return report


@dataclass
class ComparisonReport:
    x: MatchupReport
    y: MatchupReport

    def paired(self, metric: Callable[[GameRow], float]) -> Estimate:
        """Mean per-seed difference y - x. Pairing cancels shared luck."""
        xs = self.x.per_seed(metric)
        ys = self.y.per_seed(metric)
        return mean_interval([b - a for a, b in zip(xs, ys)])

    def as_dict(self) -> dict[str, Any]:
        def est(e: Estimate) -> dict[str, float]:
            return {"value": round(e.value, 4), "low": round(e.low, 4),
                    "high": round(e.high, 4), "n": e.n}
        return {
            "x": self.x.as_dict(),
            "y": self.y.as_dict(),
            "diff_a_score": est(self.paired(lambda r: r.a_score)),
            "diff_rounds": est(self.paired(lambda r: r.stats.rounds_played)),
        }


def compare_rulesets(config_x: Config, config_y: Config,
                     make_a: AgentFactory, make_b: AgentFactory,
                     seeds: Sequence[int], swap_seats: bool = True,
                     label_a: str = "A", label_b: str = "B") -> ComparisonReport:
    return ComparisonReport(
        run_matchup(config_x, make_a, make_b, seeds, swap_seats, label_a, label_b),
        run_matchup(config_y, make_a, make_b, seeds, swap_seats, label_a, label_b),
    )


# -- text output -------------------------------------------------------------

def _pct(e: Estimate) -> str:
    return f"{100 * e.value:5.1f}%  [{100 * e.low:5.1f}, {100 * e.high:5.1f}]"


def format_matchup(report: MatchupReport) -> str:
    c = report.counts()
    combat = report.combat_summary()
    lines = [
        f"{report.label_a} (A) vs {report.label_b} (B)  "
        f"config {report.config_hash[:12]}  "
        f"{'seat-swapped' if report.swapped else 'A always seat 0'}",
        f"  games {c['games']}  A wins {c['a_wins']}  B wins {c['b_wins']}  "
        f"draws {c['draws']}",
        f"  A score      {_pct(report.a_score)}   95% CI, per-seed",
        f"  seat 0 share {_pct(report.seat0)}   near 50% = no seat bias",
        f"  rounds       {report.rounds.value:5.2f}  "
        f"[{report.rounds.low:.2f}, {report.rounds.high:.2f}]",
        f"  combat       {combat['mean_ticks']:.1f} ticks avg, "
        f"{100 * combat['timeout_rate']:.1f}% timeouts, "
        f"{100 * combat['draw_rate']:.1f}% draws",
    ]
    for which, label in (("a", report.label_a), ("b", report.label_b)):
        s = report.agent_summary(which)
        top = sorted(s["unit_share"].items(), key=lambda kv: (-kv[1], kv[0]))[:4]
        lines.append(
            f"  {label:<10s} level {s['mean_final_level']:.2f}  "
            f"units {', '.join(f'{u} {v:.0%}' for u, v in top)}  "
            f"traits {', '.join(f'{t} {v:.0%}' for t, v in s['trait_uptime'].items())}"
        )
    return "\n".join(lines)


def format_comparison(comparison: ComparisonReport, name_x: str, name_y: str) -> str:
    score = comparison.paired(lambda r: r.a_score)
    rounds = comparison.paired(lambda r: r.stats.rounds_played)
    return "\n".join([
        f"[{name_x}]",
        format_matchup(comparison.x),
        f"[{name_y}]",
        format_matchup(comparison.y),
        f"[paired difference, {name_y} minus {name_x}, per seed]",
        f"  A score  {100 * score.value:+5.1f} pts  "
        f"[{100 * score.low:+.1f}, {100 * score.high:+.1f}]",
        f"  rounds   {rounds.value:+5.2f}      [{rounds.low:+.2f}, {rounds.high:+.2f}]",
        "  An interval that excludes 0 is a real difference at 95% confidence.",
    ])
