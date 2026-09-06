"""The round loop.

Each round: income is paid, shops are rolled for both players, players act,
boards fight, damage is applied, dead players are removed.

Both players plan against the same round state. Ordering between them does not
matter because planning actions never touch shared state except the pool, which
is resolved on purchase in player-index order.
"""

from __future__ import annotations

import random
from typing import Protocol, Sequence

from engine import events
from engine.actions import END_TURN, apply_action
from engine.combat import CombatResult, resolve_combat
from engine.config import Config
from engine.economy import round_income
from engine.replay import Replay, RoundRecord
from engine.shop import roll_shop
from engine.state import GameState, PlayerState, new_game

# Agents decide on their own random stream, derived from the same seed but
# never interleaved with the engine's. See run_planning.
AGENT_STREAM_SALT = 0x5EED


class Agent(Protocol):
    """A decision maker for one player.

    Called repeatedly during the planning phase until it returns ``end_turn``
    or the configured action cap is hit.
    """

    name: str

    def choose(self, state: GameState, player: PlayerState,
               rng: random.Random) -> dict:
        ...


def pay_income(state: GameState) -> None:
    for player in state.living_players():
        player.gold += round_income(state.config, player.gold, player.streak)


def roll_shops(state: GameState, rng: random.Random) -> None:
    for player in state.living_players():
        player.shop = roll_shop(state.config, state.pool, player.level, rng)


def run_planning(state: GameState, agents: Sequence[Agent],
                 rng: random.Random, agent_rng: random.Random) -> list[tuple[int, dict]]:
    """Let each living player act until it ends its turn. Returns the actions.

    Agents draw from ``agent_rng``, never from the engine's ``rng``. Keeping the
    streams apart is what makes a recorded action list replayable: on replay the
    agents are gone, but the engine's stream must land in exactly the same place.
    """
    cap = state.config.planning["max_actions_per_round"]
    taken: list[tuple[int, dict]] = []

    for player in state.living_players():
        agent = agents[player.index]
        for _ in range(cap):
            action = agent.choose(state, player, agent_rng)
            apply_action(state, player, action, rng)
            taken.append((player.index, action))
            if action["type"] == END_TURN:
                break
        else:
            # Agent never ended its turn; the cap stands in for one.
            forced = {"type": END_TURN}
            apply_action(state, player, forced, rng)
            taken.append((player.index, forced))

    return taken


def replay_planning(state: GameState, actions: Sequence[tuple[int, dict]],
                    rng: random.Random) -> list[tuple[int, dict]]:
    """Apply a recorded action list instead of asking agents."""
    for player_index, action in actions:
        apply_action(state, state.players[player_index], action, rng)
    return list(actions)


def combat_damage(config: Config, survivors: Sequence,
                  tier_of: dict[str, int]) -> int:
    """Damage dealt to the loser, per the configured formula."""
    formula = config.damage["formula"]
    base = config.damage["base"]
    if formula == "flat_plus_survivors":
        return base + len(survivors)
    if formula == "flat_plus_tiers":
        return base + sum(tier_of[u.template_id] for u in survivors)
    raise ValueError("unknown damage formula: " + str(formula))


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


def resolve(state: GameState, rng: random.Random, agents: Sequence[Agent],
            agent_rng: random.Random | None = None,
            recorded: Sequence[tuple[int, dict]] | None = None) -> RoundRecord:
    """Run one full round and return its replay record.

    Takes state and a seeded rng, mutates the state, returns the round record.
    ``rng`` is the engine stream; ``agent_rng`` is the agents' and is unused
    when replaying a recorded action list.
    """
    state.round += 1
    record = RoundRecord(round=state.round)

    pay_income(state)
    roll_shops(state, rng)

    if recorded is None:
        if agent_rng is None:
            raise ValueError("agent_rng is required when agents are deciding")
        record.actions = run_planning(state, agents, rng, agent_rng)
    else:
        record.actions = replay_planning(state, recorded, rng)

    result = resolve_combat(state, rng)
    record.events = result.log.records()

    tier_of = {tid: state.templates[tid].tier for tid in sorted(state.templates)}
    apply_combat_result(state, result, tier_of)
    remove_dead_players(state)
    return record


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

    replay.result = {
        "placements": placements(state),
        "health": [p.health for p in state.players],
        "rounds_played": state.round,
    }
    return replay


def replay_game(config: Config, replay: Replay) -> Replay:
    """Re-run a recorded game from its own action log. Used to prove determinism."""
    state = new_game(config, list(replay.players))
    rng = random.Random(replay.seed)

    fresh = Replay(config_hash=config.config_hash, seed=replay.seed,
                   players=list(replay.players))
    for recorded in replay.action_sequence():
        fresh.rounds.append(resolve(state, rng, [], recorded=recorded))

    fresh.result = {
        "placements": placements(state),
        "health": [p.health for p in state.players],
        "rounds_played": state.round,
    }
    return fresh


__all__ = [
    "Agent",
    "resolve",
    "play_game",
    "replay_game",
    "placements",
    "game_over",
    "events",
]
