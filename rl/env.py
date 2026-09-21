"""A single-agent environment around the two-player game (v0.4).

The learner plays one seat; a fixed policy plays the other. The API follows
gymnasium's conventions without depending on it:

    env = AutoBattlerEnv(opponent=GreedyAgent, seat=0)
    obs, info = env.reset(seed=0)
    while True:
        action = pick(obs, info["action_mask"])
        obs, reward, terminated, truncated, info = env.step(action)
        if terminated or truncated:
            break
    replay = env.replay()        # every episode is a replayable game

One ``step`` is one planning action. Ending the turn (or hitting the action
cap) lets the opponent finish planning, runs the combat, and opens the next
round, all inside that one step.

Design decisions, each explained in docs/rl/05-environment.md:

* **Illegal actions raise.** Pass ``action_masks()`` to your learner. A penalty
  for illegal actions teaches the network the rules slowly and badly; a mask
  removes them from consideration entirely.
* **Rewards.** ``terminal``: +1 win, -1 loss, 0 draw, only at the end.
  ``shaped``: adds potential-based shaping on the health difference, which
  provably leaves the best policy unchanged. Pass your learner's discount as
  ``gamma``.
* **``max_rounds`` is termination, not truncation.** The rules define a winner
  at the round limit, so the episode really is over. ``truncated`` is always
  False.
* **Opponents see observations too.** Whatever policy sits in the other seat
  gets the same leak-free view as the learner.
"""

from __future__ import annotations

import random
from typing import Any, Callable

from engine.actions import END_TURN
from engine.config import Config, load_config
from engine.game import (
    AGENT_STREAM_SALT,
    act,
    begin_round,
    final_result,
    finish_round,
    game_over,
    plan_turn,
    planning_order,
)
from engine.observation import observe, snapshot_public
from engine.replay import Replay
from engine.state import new_game
from rl.spaces import ActionSpace, ObservationEncoder

REWARD_MODES = ("terminal", "shaped")


class AutoBattlerEnv:
    def __init__(self, config: Config | None = None,
                 opponent: Callable[[], Any] | None = None,
                 seat: int = 0, reward: str = "terminal", gamma: float = 1.0,
                 name: str = "agent:learner") -> None:
        if reward not in REWARD_MODES:
            raise ValueError(f"reward must be one of {REWARD_MODES}")
        if seat not in (0, 1):
            raise ValueError("seat must be 0 or 1")
        if opponent is None:
            from agents import GreedyAgent
            opponent = GreedyAgent
        self.config = config or load_config()
        self.opponent_factory = opponent
        self.seat = seat
        self.reward_mode = reward
        self.gamma = gamma
        self.name = name

        self.actions = ActionSpace(self.config)
        self.encoder = ObservationEncoder(self.config)
        self.n_actions = self.actions.size
        self.obs_size = self.encoder.size

        self._episode = 0
        self.state = None
        self.done = True

    # -- episode control ----------------------------------------------------
    def reset(self, seed: int | None = None,
              options: dict | None = None) -> tuple[list[float], dict]:
        """Start an episode. Without a seed, episodes use 0, 1, 2, ... in turn,
        so even an unseeded run is reproducible."""
        if seed is None:
            seed = self._episode
        self._episode += 1
        self.seed = seed

        self.opponent = self.opponent_factory()
        names = [self.name, self.opponent.name]
        if self.seat == 1:
            names.reverse()
        self.state = new_game(self.config, names)
        self.rng = random.Random(seed)
        self.agent_rng = random.Random(seed ^ AGENT_STREAM_SALT)
        self._replay = Replay(config_hash=self.config.config_hash, seed=seed,
                              players=names)
        self.done = False
        self._phi = self._potential()
        self._open_round()
        return self.encoder.encode(self.observation()), self._info()

    def step(self, index: int) -> tuple[list[float], float, bool, bool, dict]:
        if self.done:
            raise RuntimeError("the episode is over; call reset()")
        view = self.observation()
        action = self.actions.decode(index, [u["uid"] for u in view["self"]["board"]])
        if action is None or action not in view["legal_actions"]:
            raise ValueError(f"action {index} ({self.actions.describe(index)}) is "
                             "not legal now; mask with action_masks()")

        act(self.state, self.ctx, self.seat, action)
        self._actions_this_round += 1
        cap = self.config.planning["max_actions_per_round"]
        if action["type"] == END_TURN or self._actions_this_round >= cap:
            if action["type"] != END_TURN:
                act(self.state, self.ctx, self.seat, {"type": END_TURN})
            self._close_round()

        reward = self._shaping() + self._terminal_reward()
        return (self.encoder.encode(self.observation()), reward, self.done,
                False, self._info())

    # -- round plumbing -----------------------------------------------------
    def _open_round(self) -> None:
        """Begin a round and let every seat before the learner plan."""
        self.ctx = begin_round(self.state, self.rng)
        self._actions_this_round = 0
        order = planning_order(self.state)
        for seat in order[:order.index(self.seat)]:
            plan_turn(self.state, self.ctx, seat, self.opponent, self.agent_rng)

    def _close_round(self) -> None:
        """Let every seat after the learner plan, fight, and open the next."""
        order = planning_order(self.state)
        for seat in order[order.index(self.seat) + 1:]:
            plan_turn(self.state, self.ctx, seat, self.opponent, self.agent_rng)
        finish_round(self.state, self.ctx)
        self._replay.rounds.append(self.ctx.record)
        if game_over(self.state):
            self.done = True
            self._replay.result = final_result(self.state)
            snapshot_public(self.state)  # so a terminal observation exists
        else:
            self._open_round()

    # -- rewards --------------------------------------------------------------
    def _potential(self) -> float:
        """Phi: health lead as a fraction of starting health. Zero at terminal
        states, which is what makes the shaping telescope exactly."""
        if self.done:
            return 0.0
        me = self.state.players[self.seat]
        them = self.state.players[1 - self.seat]
        return (me.health - them.health) / self.config.match["starting_health"]

    def _shaping(self) -> float:
        """gamma * Phi(s') - Phi(s), every step. Zero in terminal mode."""
        phi = self._potential()
        shaped = self.gamma * phi - self._phi
        self._phi = phi
        return shaped if self.reward_mode == "shaped" else 0.0

    def _terminal_reward(self) -> float:
        if not self.done:
            return 0.0
        places = self._replay.result["placements"]
        mine, theirs = places[self.seat], places[1 - self.seat]
        return 1.0 if mine < theirs else -1.0 if mine > theirs else 0.0

    # -- views ------------------------------------------------------------
    def observation(self) -> dict[str, Any]:
        """The learner's observation as a dict: for debugging and logging."""
        return observe(self.state, self.seat)

    def action_masks(self) -> list[bool]:
        """Legal actions as booleans, named for sb3-contrib's MaskablePPO."""
        if self.done:
            return [False] * self.n_actions
        view = self.observation()
        return self.actions.mask(view["legal_actions"],
                                 [u["uid"] for u in view["self"]["board"]])

    def _info(self) -> dict[str, Any]:
        info: dict[str, Any] = {"action_mask": self.action_masks(),
                                "round": self.state.round, "seed": self.seed}
        if self.done:
            info["result"] = self._replay.result
        return info

    def replay(self) -> Replay:
        """The episode so far as a replay; complete once the episode is done."""
        return self._replay
