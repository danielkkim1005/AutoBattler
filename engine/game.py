"""The round loop.

Each round: income is paid, shops are rolled for both players, players act,
boards fight, damage is applied, dead players are removed.

Both players plan against the same round state. Ordering between them does not
matter because planning actions never touch shared state except the pool, which
is resolved on purchase in player-index order.

Since v0.4 a round is three explicit phases, so that something outside the
engine - an RL environment waiting on a learner's next action - can drive it
one action at a time:

    ctx = begin_round(state, rng)        # income, shops, public snapshot
    act(state, ctx, seat, action)        # any number of times, any seat
    finish_round(state, ctx)             # combat, damage, eliminations

``resolve`` composes the three for the common case where agents are called
directly. Agents receive an observation (engine/observation.py), never the
state itself.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any, Protocol, Sequence

from engine import events
from engine.actions import END_TURN, apply_action
from engine.combat import CombatResult, resolve_combat
from engine.config import Config
from engine.economy import round_income
from engine.observation import observe, snapshot_public
from engine.replay import Replay, RoundRecord
from engine.shop import roll_shop
from engine.state import GameState, PlayerState, new_game

# Agents decide on their own random stream, derived from the same seed but
# never interleaved with the engine's. See docs/rl/01-determinism.md.
AGENT_STREAM_SALT = 0x5EED


class Agent(Protocol):
    """A decision maker for one seat.

    Called repeatedly during the planning phase until it returns ``end_turn``
    or the configured action cap is hit. It sees only an observation: its own
    live state, and everyone else as they stood when planning began.
    """

    name: str

    def choose(self, observation: dict[str, Any], rng: random.Random) -> dict:
        ...


@dataclass
class RoundContext:
    """One round in progress: its record so far and its private streams."""

    record: RoundRecord
    shop_rng: random.Random
    combat_rng: random.Random


def round_streams(rng: random.Random) -> tuple[random.Random, random.Random]:
    """Split one round's randomness into a shop stream and a combat stream.

    The master ``rng`` gives up exactly one draw per round, whatever happens in
    that round. So a reroll in round 3, or a fight that goes differently, never
    shifts what round 4 rolls: every round's randomness depends only on the
    seed and the round number. That is what lets two configs, or two agents,
    be compared on genuinely shared luck (docs/rl/01-determinism.md).
    """
    round_seed = rng.getrandbits(64)
    return (random.Random(f"{round_seed}:shop"),
            random.Random(f"{round_seed}:combat"))


def pay_income(state: GameState) -> None:
    for player in state.living_players():
        player.gold += round_income(state.config, player.gold, player.streak)


def roll_shops(state: GameState, rng: random.Random) -> None:
    for player in state.living_players():
        player.shop = roll_shop(state.config, state.pool, player.level, rng)


def planning_order(state: GameState) -> list[int]:
    """Seats that plan this round, in the order their purchases resolve."""
    return [p.index for p in state.living_players()]


def begin_round(state: GameState, rng: random.Random) -> RoundContext:
    """Open a round: advance the counter, pay income, roll shops, and freeze
    the public snapshot that observations are built from."""
    state.round += 1
    shop_rng, combat_rng = round_streams(rng)
    ctx = RoundContext(RoundRecord(round=state.round), shop_rng, combat_rng)
    pay_income(state)
    roll_shops(state, shop_rng)
    snapshot_public(state)
    return ctx


def act(state: GameState, ctx: RoundContext, seat: int, action: dict) -> None:
    """Apply one planning action for one seat and record it."""
    apply_action(state, state.players[seat], action, ctx.shop_rng)
    ctx.record.actions.append((seat, action))


def plan_turn(state: GameState, ctx: RoundContext, seat: int, agent: Agent,
              agent_rng: random.Random) -> None:
    """Ask one agent for actions until it ends its turn or hits the cap.

    Agents draw from ``agent_rng``, never from the round's streams. Keeping
    them apart is what makes a recorded action list replayable: on replay the
    agents are gone, but the engine's streams must land in the same place.
    """
    for _ in range(state.config.planning["max_actions_per_round"]):
        action = agent.choose(observe(state, seat), agent_rng)
        act(state, ctx, seat, action)
        if action["type"] == END_TURN:
            return
    # The agent never ended its turn; the cap stands in for it.
    act(state, ctx, seat, {"type": END_TURN})


def combat_damage(config: Config, survivors: Sequence,
                  tier_of: dict[str, int]) -> int:
    """Damage dealt to the loser, per the configured formula."""
    formula = config.damage["formula"]
    base = config.damage["base"]
    if formula == "flat_plus_survivors":
        return base + len(survivors)
    return base + sum(tier_of[u.template_id] for u in survivors)  # flat_plus_tiers


def apply_combat_result(state: GameState, result: CombatResult,
                        tier_of: dict[str, int]) -> None:
    """Apply damage and update streaks. A draw damages nobody."""
    if result.winner is None:
        for player in state.players:
            player.record_result("draw")
        return

    loser = 1 - result.winner
    damage = combat_damage(state.config, result.survivors[result.winner], tier_of)
    state.players[loser].health -= damage
    state.players[result.winner].record_result("win")
    state.players[loser].record_result("loss")


def remove_dead_players(state: GameState) -> None:
    for player in state.players:
        if player.health <= 0:
            player.health = max(player.health, 0)
            player.alive = False


def finish_round(state: GameState, ctx: RoundContext) -> CombatResult:
    """Close a round: fight, apply damage, remove the dead."""
    result = resolve_combat(state, ctx.combat_rng)
    ctx.record.events = result.log.records()
    tier_of = {tid: state.templates[tid].tier for tid in sorted(state.templates)}
    apply_combat_result(state, result, tier_of)
    remove_dead_players(state)
    state.public = {}  # observations are only valid during planning
    return result


def resolve(state: GameState, rng: random.Random, agents: Sequence[Agent],
            agent_rng: random.Random | None = None,
            recorded: Sequence[tuple[int, dict]] | None = None) -> RoundRecord:
    """Run one full round and return its replay record.

    Takes state and a seeded rng, mutates the state, returns the round record.
    ``rng`` is the engine's master stream, from which each round derives its
    own shop and combat streams. ``agent_rng`` is the agents' and is unused
    when replaying a recorded action list.
    """
    ctx = begin_round(state, rng)
    if recorded is None:
        if agent_rng is None:
            raise ValueError("agent_rng is required when agents are deciding")
        for seat in planning_order(state):
            plan_turn(state, ctx, seat, agents[seat], agent_rng)
    else:
        for seat, action in recorded:
            act(state, ctx, seat, action)
    finish_round(state, ctx)
    return ctx.record


def game_over(state: GameState) -> bool:
    return len(state.living_players()) < 2 or state.round >= state.config.match["max_rounds"]


def placements(state: GameState) -> list[int]:
    """0 is first place. Equal standing means a shared placement."""
    def standing(player: PlayerState) -> tuple[int, int]:
        return (0 if player.alive else 1, -player.health)

    ranked = sorted(state.players, key=lambda p: (standing(p), p.index))
    result = [0] * len(state.players)
    place = 0
    for i, player in enumerate(ranked):
        if i > 0 and standing(player) != standing(ranked[i - 1]):
            place = i
        result[player.index] = place
    return result


def final_result(state: GameState) -> dict:
    """The replay's result block. Lists are indexed by seat."""
    return {
        "placements": placements(state),
        "health": [p.health for p in state.players],
        "level": [p.level for p in state.players],
        "gold": [p.gold for p in state.players],
        "rounds_played": state.round,
    }


def play_game(config: Config, seed: int, agents: Sequence[Agent],
              player_names: Sequence[str] | None = None) -> Replay:
    """Play a full game from a seed and return the replay."""
    names = list(player_names) if player_names else [a.name for a in agents]
    state = new_game(config, names)
    rng = random.Random(seed)
    agent_rng = random.Random(seed ^ AGENT_STREAM_SALT)

    replay = Replay(config_hash=config.config_hash, seed=seed, players=names)
    while not game_over(state):
        replay.rounds.append(resolve(state, rng, agents, agent_rng))

    replay.result = final_result(state)
    return replay


def replay_game(config: Config, replay: Replay) -> Replay:
    """Re-run a recorded game from its own action log. Used to prove determinism."""
    state = new_game(config, list(replay.players))
    rng = random.Random(replay.seed)

    fresh = Replay(config_hash=config.config_hash, seed=replay.seed,
                   players=list(replay.players))
    for recorded in replay.action_sequence():
        fresh.rounds.append(resolve(state, rng, [], recorded=recorded))

    fresh.result = final_result(state)
    return fresh


__all__ = [
    "Agent",
    "RoundContext",
    "begin_round",
    "act",
    "plan_turn",
    "finish_round",
    "resolve",
    "play_game",
    "replay_game",
    "placements",
    "game_over",
    "events",
]
