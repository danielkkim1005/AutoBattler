"""Run masked-random episodes through the environment and check them.

    python -m rl.demo --episodes 20
    python -m rl.demo --episodes 20 --reward shaped --seat 1

A stand-in for a learner: it picks uniformly among legal actions, which is
exactly what an untrained policy with a correct mask does. Every episode's
replay is re-run from its action log and must come back byte-identical.
"""

from __future__ import annotations

import argparse
import random

from agents import REGISTRY
from engine.game import replay_game
from rl.env import REWARD_MODES, AutoBattlerEnv


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--episodes", type=int, default=20)
    parser.add_argument("--opponent", default="greedy", choices=sorted(REGISTRY))
    parser.add_argument("--seat", type=int, default=0, choices=(0, 1))
    parser.add_argument("--reward", default="terminal", choices=REWARD_MODES)
    parser.add_argument("--gamma", type=float, default=1.0)
    args = parser.parse_args()

    env = AutoBattlerEnv(opponent=REGISTRY[args.opponent], seat=args.seat,
                         reward=args.reward, gamma=args.gamma)
    print(f"action space {env.n_actions}   observation {env.obs_size} floats   "
          f"learner seat {args.seat} vs {args.opponent}   reward {args.reward}")

    policy_rng = random.Random(12345)
    wins = draws = steps = mismatches = 0
    returns = []
    for episode in range(args.episodes):
        obs, info = env.reset(seed=episode)
        total, done = 0.0, False
        while not done:
            legal = [i for i, ok in enumerate(info["action_mask"]) if ok]
            obs, reward, done, _, info = env.step(policy_rng.choice(legal))
            total += reward
            steps += 1
        returns.append(total)
        placements = info["result"]["placements"]
        wins += placements[args.seat] < placements[1 - args.seat]
        draws += placements[0] == placements[1]
        replay = env.replay()
        if replay_game(env.config, replay).to_json() != replay.to_json():
            mismatches += 1

    n = args.episodes
    print(f"episodes {n}   steps {steps} ({steps / n:.0f}/episode)   "
          f"learner wins {wins}   draws {draws}")
    print(f"mean return {sum(returns) / n:+.3f}   "
          f"replays reproduced {n - mismatches}/{n}")
    return 1 if mismatches else 0


if __name__ == "__main__":
    raise SystemExit(main())
