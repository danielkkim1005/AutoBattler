# 5. The environment interface

*Introduced in v0.4.*

`rl/env.py` wraps the two-player game as a single-agent environment: your
learner plays one seat, a fixed policy plays the other.

```python
from agents import GreedyAgent
from rl import AutoBattlerEnv

env = AutoBattlerEnv(opponent=GreedyAgent, seat=0, reward="terminal")
obs, info = env.reset(seed=0)
while not env.done:
    action = my_policy(obs, info["action_mask"])
    obs, reward, terminated, truncated, info = env.step(action)
replay = env.replay()   # a normal replay: re-runnable, analysable
```

To see it run, with no learner at all:

```bash
python -m rl.demo --episodes 20
```

## One step is one planning action

A round is many decisions: buy, buy, level, move, end turn. Each is one
`step`. The step that ends the turn also runs the rest of the round — the
opponent's planning if it plans after you, the combat, damage — and opens the
next round, so the observation you get back is already your next decision.

The alternative, one step per round with a compound action, would need an
enormous action space. Per-decision steps keep it at 98 and let the policy see
the result of each purchase before choosing the next.

## The action space: 98 discrete actions

| Block | Count | Meaning |
| --- | --- | --- |
| end turn | 1 | |
| buy slot *s* | 5 | |
| sell board[*i*] | 5 | your *i*-th unit, oldest first |
| reroll | 1 | |
| buy level | 1 | |
| move board[*i*] → square *j* | 75 | 5 units × 15 squares |
| swap board[*i*] ↔ board[*j*] | 10 | |

Units are addressed by **board index**, not uid. Uids grow without bound over
a game, and a network needs a fixed output size. The cost: index 2 means a
different unit after you sell index 1. The mask keeps that from mattering.

## Masks, not penalties

At any moment most of the 98 actions are illegal. There are two ways to handle
that:

- **Penalise** illegal actions with negative reward. The network has to learn
  the rules by trial and error, wastes most early experience on nonsense, and
  the penalty competes with the real objective.
- **Mask** them: set their probability to zero before sampling, so they are
  never chosen and never learned about.

Masking is the standard answer. Huang & Ontañón, *A Closer Look at Invalid
Action Masking in Policy Gradient Algorithms* (2020), show it scales where
penalties fail. So the environment **raises on an illegal action** rather than
penalising it, and supplies the mask in `info["action_mask"]` and through
`env.action_masks()` — the method name `sb3-contrib`'s `MaskablePPO` looks
for.

`test_mask_is_exactly_the_legal_actions` checks, along a real episode, that
the mask and the engine agree exactly, and that encoding and decoding are
inverses.

## The observation: 371 floats

| Part | Size | Encoding |
| --- | --- | --- |
| scalars | 11 | round, your health/gold/level/streak/board fill, opponent's health/gold/level/streak/alive — scaled to roughly [0, 1] |
| your board | 150 | 15 squares × 10 unit types, one-hot |
| opponent's board | 150 | same, frozen at round start |
| shop | 50 | 5 slots × 10 unit types, one-hot |
| pool | 10 | copies left ÷ copies at start |

`env.encoder.names()` labels all 371 positions, so a vector can always be read
back. When a trained policy does something odd, look at what it actually saw.

The scaling constants (`GOLD_SCALE`, `STREAK_SCALE` in `rl/spaces.py`) shape
the network's input, not the game, so they live in `rl/` rather than
`rules.yaml`.

## Rewards, and why shaping is dangerous

**`terminal`** (default): +1 win, −1 loss, 0 draw, at the very end. It is
honest, and sparse: about 100 decisions per episode, one signal.

**`shaped`**: adds a reward for improving your health lead during the game.
Shaping can speed learning a lot, and it can also quietly change what the agent
optimises. Reward a unit purchase with +0.1, say, and you may well get an agent
that buys constantly and loses.

The safe form is **potential-based shaping** (Ng, Harada & Russell, 1999). Pick
a potential Φ(state), and reward the change in it:

> F = γ·Φ(s′) − Φ(s)

Summed over an episode, these terms cancel, leaving Φ(end) − Φ(start). If Φ is
zero at both ends, the shaping adds *exactly nothing* to any episode's return.
It only moves reward earlier in time. Because it cannot change which policy is
best, it cannot be gamed.

Here Φ = (your health − their health) ÷ starting health, defined as 0 at
terminal states. Both games start level, so Φ(start) = 0. Two tests prove the
identity on real episodes:

- `test_shaping_with_gamma_one_changes_no_episode_total` — shaped and
  unshaped rewards sum to the same number;
- `test_shaping_preserves_the_discounted_return` — with γ = 0.97, the
  discounted returns match.

**Pass your learner's discount as `gamma`.** With γ < 1 you will see small
nonzero rewards on every step, even steps that change nothing. That is the
(γ − 1)·Φ term, and it is correct. A mismatched γ breaks the guarantee.

## Termination versus truncation

Gymnasium separates two ways an episode can stop, and learners treat them
differently:

- **terminated** — the episode reached a true end state. There is no future
  reward, so the value target is just the final reward.
- **truncated** — an outside time limit cut the episode short. The future
  still exists, so the value target should bootstrap from V(s′).

Reaching `max_rounds` is a *rule of the game* (highest health wins), so it is
**termination**. `truncated` is always False here. Getting this wrong biases
value estimates in a way that is hard to diagnose later.

## Every episode is a replay

`env.replay()` returns an ordinary replay, and
`test_episodes_are_reproducible_and_replayable` checks that it re-runs byte for
byte from both seats. When a trained agent does something strange in episode
48,213, save that replay and step through it with the same tools as any other
game.

## Seeds for training and evaluation

`reset(seed=None)` uses 0, 1, 2, … in order, so even an unseeded run is
reproducible. Train on one range and evaluate on a disjoint one — say, seeds
from 1,000,000 up — so a policy cannot memorise its evaluation shops. Evaluate
with the [lesson 3](03-evaluation.md) protocol: seat-swapped, per-seed
intervals, against fixed baselines.

## Plugging in a library (sketch)

The environment has no dependencies. To use it with gymnasium-based libraries,
wrap it. The following is an **untested sketch**, needing
`pip install gymnasium numpy sb3-contrib`:

```python
import gymnasium as gym
import numpy as np
from rl import AutoBattlerEnv

class GymAutoBattler(gym.Env):
    def __init__(self, **kwargs):
        self.inner = AutoBattlerEnv(**kwargs)
        self.action_space = gym.spaces.Discrete(self.inner.n_actions)
        self.observation_space = gym.spaces.Box(
            -np.inf, np.inf, (self.inner.obs_size,), np.float32)

    def reset(self, seed=None, options=None):
        obs, info = self.inner.reset(seed=seed)
        return np.asarray(obs, np.float32), info

    def step(self, action):
        obs, r, term, trunc, info = self.inner.step(int(action))
        return np.asarray(obs, np.float32), r, term, trunc, info

    def action_masks(self):
        return np.asarray(self.inner.action_masks(), bool)
```

## Baselines and throughput

- A masked random policy lost all 10 of 10 games against `GreedyAgent` in the
  demo run. That is the floor.
- `PositionalAgent` beats `GreedyAgent` about 60% of the time. That is a
  reasonable first bar for a learner.
- Throughput is about **6,600 steps a second**, around 38 episodes, on one
  process with a masked random policy. A million training steps is under three
  minutes of pure environment time, before the learner's own cost.
