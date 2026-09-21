"""Play one game and optionally write or verify its replay.

Printing lives here, outside engine/, because the engine is headless by
contract. For sweeps over many seeds, with error bars, use evaluate.py.

    python run_game.py --seed 42 --verify
    python run_game.py --agents positional greedy --seed 7 --out replay.json
"""

from __future__ import annotations

import argparse
from pathlib import Path

from agents import REGISTRY
from engine.config import DEFAULT_RULES_PATH, load_config
from engine.game import play_game, replay_game


def main() -> int:
    parser = argparse.ArgumentParser(description="Play one autobattler game.")
    parser.add_argument("--rules", type=Path, default=DEFAULT_RULES_PATH)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--agents", nargs=2, default=["greedy", "random"],
                        choices=sorted(REGISTRY), metavar=("SEAT0", "SEAT1"))
    parser.add_argument("--out", type=Path, help="write the replay JSON here")
    parser.add_argument("--verify", action="store_true",
                        help="re-run the replay and check it is byte-identical")
    args = parser.parse_args()

    config = load_config(args.rules)
    agents = [REGISTRY[name](f"agent:{name}-{seat}")
              for seat, name in enumerate(args.agents)]
    replay = play_game(config, args.seed, agents)

    result = replay.result
    print(f"version     {replay.version}  config {replay.config_hash[:16]}  "
          f"seed {replay.seed}")
    print(f"rounds      {result['rounds_played']}")
    print(f"health      {result['health']}")
    print(f"level       {result['level']}")
    print(f"placements  {result['placements']}  (0 = first)")
    print(f"events      {sum(len(r.events) for r in replay.rounds)}")

    if args.verify:
        ok = replay_game(config, replay).to_json() == replay.to_json()
        print(f"replay      {'byte-identical' if ok else 'DIVERGED'}")
        if not ok:
            return 1

    if args.out:
        args.out.write_text(replay.to_json(), encoding="utf-8", newline="\n")
        print(f"wrote       {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
