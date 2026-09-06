"""Command-line harness: play games and write replays.

Printing lives here, outside engine/, because the engine is headless by
contract. This script is the reference consumer of the replay format.

    python run_game.py --seed 42 --out replay.json
    python run_game.py --agents greedy random --games 100 --summary
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from agents import GreedyAgent, RandomAgent
from engine.config import DEFAULT_RULES_PATH, load_config
from engine.game import play_game, replay_game

AGENTS = {"greedy": GreedyAgent, "random": RandomAgent}


def build_agents(names: list[str]):
    return [AGENTS[name](f"agent:{name}-{i}") for i, name in enumerate(names)]


def summarise(config, agent_names: list[str], games: int, first_seed: int) -> dict:
    """Play a seed sweep and count outcomes. Useful for config ablations."""
    tally = {"p0": 0, "p1": 0, "draw": 0}
    rounds = 0
    for offset in range(games):
        replay = play_game(config, first_seed + offset, build_agents(agent_names))
        placements = replay.result["placements"]
        rounds += replay.result["rounds_played"]
        if placements[0] == placements[1]:
            tally["draw"] += 1
        elif placements[0] < placements[1]:
            tally["p0"] += 1
        else:
            tally["p1"] += 1
    return {"games": games, "avg_rounds": round(rounds / games, 2), **tally}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run autobattler games.")
    parser.add_argument("--rules", type=Path, default=DEFAULT_RULES_PATH)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--agents", nargs=2, default=["greedy", "random"],
                        choices=sorted(AGENTS))
    parser.add_argument("--games", type=int, default=1,
                        help="play a seed sweep starting at --seed")
    parser.add_argument("--out", type=Path, help="write the replay JSON here")
    parser.add_argument("--summary", action="store_true",
                        help="print win counts instead of a single game")
    parser.add_argument("--verify", action="store_true",
                        help="re-run the replay and check it is byte-identical")
    args = parser.parse_args()

    config = load_config(args.rules)

    if args.summary or args.games > 1:
        print(json.dumps(summarise(config, args.agents, args.games, args.seed),
                         indent=2))
        return 0

    replay = play_game(config, args.seed, build_agents(args.agents))
    print(f"config_hash {replay.config_hash[:16]}  seed {replay.seed}")
    print(f"rounds      {replay.result['rounds_played']}")
    print(f"health      {replay.result['health']}")
    print(f"placements  {replay.result['placements']}  (0 = first)")
    print(f"events      {sum(len(r.events) for r in replay.rounds)}")

    if args.verify:
        reproduced = replay_game(config, replay)
        ok = reproduced.to_json() == replay.to_json()
        print(f"replay      {'byte-identical' if ok else 'DIVERGED'}")
        if not ok:
            return 1

    if args.out:
        args.out.write_text(replay.to_json(), encoding="utf-8", newline="\n")
        print(f"wrote       {args.out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
