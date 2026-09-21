"""v0.4: observations without leaks, and the RL environment."""

from __future__ import annotations

import json
import random

import pytest
from conftest import tweak

from agents import GreedyAgent, PositionalAgent
from engine.game import play_game, replay_game, resolve
from engine.observation import observe
from engine.state import new_game
from rl.env import AutoBattlerEnv
from rl.spaces import ActionSpace


# -- observations: what a seat may know ---------------------------------------

class Spy(GreedyAgent):
    """Greedy, but records every observation it is handed."""

    def __init__(self, name="spy"):
        super().__init__(name)
        self.seen = []

    def choose(self, observation, rng):
        self.seen.append(json.loads(json.dumps(observation)))
        return super().choose(observation, rng)


def test_seat_one_cannot_see_seat_zeros_moves_this_round(config):
    """Seat 0 plans first. Whatever it buys this round must stay hidden from
    seat 1 until the next round's snapshot."""
    state = new_game(config, ["first", "spy"])
    spy = Spy()
    rng, agent_rng = random.Random(4), random.Random(4)
    for _ in range(3):
        before = [u.uid for u in state.players[0].units()]
        gold_before = None
        spy.seen.clear()
        resolve(state, rng, [GreedyAgent("first"), spy], agent_rng)
        for obs in spy.seen:
            opponent = obs["opponents"][0]
            assert [u["uid"] for u in opponent["board"]] == before
            assert gold_before in (None, opponent["gold"])
            gold_before = opponent["gold"]
            assert "shop" not in opponent, "an opponent's shop is private"


def test_pool_counts_are_frozen_during_planning(config):
    state = new_game(config, ["a", "spy"])
    spy = Spy()
    resolve(state, random.Random(2), [GreedyAgent("a"), spy], random.Random(2))
    pools = {json.dumps(obs["pool"], sort_keys=True) for obs in spy.seen}
    assert len(pools) == 1, "a live pool would reveal the opponent's purchases"


def test_observations_are_plain_json(config):
    spy = Spy()
    play_game(config, 1, [spy, GreedyAgent("b")])
    assert spy.seen, "the spy must have been asked at least once"


def test_observe_outside_planning_is_an_error(state):
    with pytest.raises(RuntimeError, match="planning"):
        observe(state, 0)


# -- the action space -------------------------------------------------------

def test_default_action_space_size(config):
    assert ActionSpace(config).size == 1 + 5 + 5 + 1 + 1 + 5 * 15 + 10


def test_mask_is_exactly_the_legal_actions(config):
    """Along a real episode: every masked index decodes to a legal action,
    every legal action has an index, and encode/decode are inverses."""
    env = AutoBattlerEnv(config)
    space = env.actions
    rng = random.Random(0)
    obs, info = env.reset(seed=3)
    checked = 0
    while not env.done and checked < 400:
        view = env.observation()
        uids = [u["uid"] for u in view["self"]["board"]]
        legal = view["legal_actions"]
        masked = [i for i, ok in enumerate(info["action_mask"]) if ok]
        assert sorted(space.encode(a, uids) for a in legal) == masked
        for index in masked:
            assert space.decode(index, uids) in legal
            assert space.encode(space.decode(index, uids), uids) == index
        obs, _, _, _, info = env.step(rng.choice(masked))
        checked += 1
    assert checked > 50


def test_an_illegal_action_is_refused(config):
    env = AutoBattlerEnv(config)
    env.reset(seed=0)
    illegal = env.action_masks().index(False)
    with pytest.raises(ValueError, match="not legal"):
        env.step(illegal)


# -- the environment ------------------------------------------------------

def run_episode(env, seed, policy_seed=0):
    rng = random.Random(policy_seed)
    obs, info = env.reset(seed=seed)
    trace = [obs]
    rewards = []
    while not env.done:
        legal = [i for i, ok in enumerate(info["action_mask"]) if ok]
        obs, reward, terminated, truncated, info = env.step(rng.choice(legal))
        assert truncated is False
        trace.append(obs)
        rewards.append(reward)
    return trace, rewards, info


@pytest.mark.parametrize("seat", [0, 1])
def test_episodes_are_reproducible_and_replayable(config, seat):
    env = AutoBattlerEnv(config, seat=seat)
    trace, rewards, _ = run_episode(env, seed=7)
    replay = env.replay()
    assert replay_game(config, replay).to_json() == replay.to_json()

    again, rewards_again, _ = run_episode(AutoBattlerEnv(config, seat=seat), seed=7)
    assert again == trace and rewards_again == rewards


def test_observation_vector_matches_its_names(config):
    env = AutoBattlerEnv(config)
    obs, _ = env.reset(seed=0)
    assert len(obs) == env.obs_size == len(env.encoder.names())
    assert all(isinstance(v, float) for v in obs)


def test_terminal_reward_matches_placements(config):
    for seed in range(5):
        env = AutoBattlerEnv(config, opponent=GreedyAgent)
        _, rewards, info = run_episode(env, seed)
        places = info["result"]["placements"]
        expected = 1.0 if places[0] < places[1] else -1.0 if places[0] > places[1] else 0.0
        assert rewards[-1] == expected
        assert all(r == 0.0 for r in rewards[:-1]), "terminal mode is sparse"


def test_shaping_with_gamma_one_changes_no_episode_total(config):
    """Potential-based shaping telescopes: sum of shaped rewards equals the
    terminal reward exactly, because Phi(start) = Phi(end) = 0."""
    for seed in range(5):
        _, plain, _ = run_episode(AutoBattlerEnv(config, reward="terminal"), seed)
        _, shaped, _ = run_episode(AutoBattlerEnv(config, reward="shaped"), seed)
        assert any(r != 0.0 for r in shaped[:-1]), "shaping must move reward earlier"
        assert sum(shaped) == pytest.approx(sum(plain))


def test_shaping_preserves_the_discounted_return(config):
    """With gamma < 1 the identity holds for the discounted return:
    G_shaped = G_plain - Phi(s0), and Phi(s0) = 0 at an even start."""
    gamma = 0.97
    for seed in range(3):
        _, plain, _ = run_episode(AutoBattlerEnv(config, reward="terminal", gamma=gamma), seed)
        _, shaped, _ = run_episode(AutoBattlerEnv(config, reward="shaped", gamma=gamma), seed)
        discounted = lambda rs: sum(r * gamma ** t for t, r in enumerate(rs))
        assert discounted(shaped) == pytest.approx(discounted(plain))


def test_the_action_cap_forces_the_turn_to_end(config):
    capped = tweak(config, planning={"max_actions_per_round": 2})
    env = AutoBattlerEnv(capped)
    env.reset(seed=0)
    reroll = env.actions.offsets["reroll"]
    assert env.action_masks()[reroll], "9 gold at the start affords rerolls"
    env.step(reroll)
    env.step(reroll)
    first_round = env.replay().rounds[0].actions
    learner = [a for seat, a in first_round if seat == 0]
    assert [a["type"] for a in learner] == ["reroll", "reroll", "end_turn"]
    assert env.state.round == 2


def test_the_opponent_is_any_agent(config):
    env = AutoBattlerEnv(config, opponent=PositionalAgent, seat=1)
    _, _, info = run_episode(env, seed=2)
    assert env.replay().players[0].startswith("agent:positional")
    assert "result" in info
