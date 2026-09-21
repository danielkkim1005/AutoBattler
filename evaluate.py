"""Evaluate agents and rulesets from the command line.

Every seed is played twice with the seats swapped unless --no-swap is given,
and every number comes with a 95% interval. See docs/rl/03-evaluation.md.

    python evaluate.py --agents positional greedy --seeds 300
    python evaluate.py --agents greedy greedy --ablate configs/ablations/rich.yaml
    python evaluate.py --agents greedy greedy --against path/to/other_rules.yaml
    python evaluate.py --agents greedy random --seeds 100 --json out.json

--ablate takes an overlay: a small YAML holding only the keys it changes. The
run compares the base ruleset against base-plus-overlay on the same seeds.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from agents import REGISTRY
from analysis.evaluate import (
    compare_rulesets,
    format_comparison,
    format_matchup,
    run_matchup,
)
from engine.config import DEFAULT_RULES_PATH, load_config


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--agents", nargs=2, default=["greedy", "greedy"],
                        choices=sorted(REGISTRY), metavar=("A", "B"))
    parser.add_argument("--seeds", type=int, default=200,
                        help="number of seeds; each is played twice when swapping")
    parser.add_argument("--first-seed", type=int, default=0)
    parser.add_argument("--rules", type=Path, default=DEFAULT_RULES_PATH)
    arms = parser.add_mutually_exclusive_group()
    arms.add_argument("--against", type=Path,
                      help="a second full ruleset: compare the two on the same seeds")
    arms.add_argument("--ablate", type=Path, action="append",
                      help="an overlay applied on top of --rules; repeatable. "
                           "Compares base against base + overlays")
    parser.add_argument("--no-swap", action="store_true",
                        help="keep A in seat 0 (only for measuring seat bias)")
    parser.add_argument("--json", type=Path, help="also write the report here")
    args = parser.parse_args()

    name_a, name_b = args.agents
    make_a, make_b = REGISTRY[name_a], REGISTRY[name_b]
    seeds = range(args.first_seed, args.first_seed + args.seeds)
    swap = not args.no_swap

    config = load_config(args.rules)
    if args.against or args.ablate:
        if args.against:
            other, other_name = load_config(args.against), args.against.name
        else:
            other = load_config(args.rules, tuple(args.ablate))
            other_name = " + ".join(p.stem for p in args.ablate)
        report = compare_rulesets(config, other, make_a, make_b, seeds, swap,
                                  name_a, name_b)
        print(format_comparison(report, args.rules.name, other_name))
    else:
        report = run_matchup(config, make_a, make_b, seeds, swap, name_a, name_b)
        print(format_matchup(report))

    if args.json:
        args.json.write_text(json.dumps(report.as_dict(), indent=2) + "\n",
                             encoding="utf-8")
        print(f"wrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
