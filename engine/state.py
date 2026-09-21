"""Mutable game state: players, boards, and the shared pool."""

from __future__ import annotations

from dataclasses import dataclass, field

from engine.board import all_squares
from engine.config import Config
from engine.pool import Pool
from engine.units import BoardUnit, UnitTemplate, load_templates


@dataclass
class PlayerState:
    index: int
    name: str
    health: int
    gold: int
    level: int
    board: dict[int, BoardUnit] = field(default_factory=dict)
    shop: list[str | None] = field(default_factory=list)
    streak: int = 0
    streak_kind: str | None = None
    alive: bool = True

    def units(self) -> list[BoardUnit]:
        """Board units in sorted-uid order. The only sanctioned iteration."""
        return [self.board[uid] for uid in sorted(self.board)]

    def occupied(self) -> dict[tuple[int, int], int]:
        return {u.pos(): u.uid for u in self.units()}

    def free_squares(self, config: Config) -> list[tuple[int, int]]:
        taken = self.occupied()
        return [sq for sq in all_squares(config) if sq not in taken]

    def board_full(self, config: Config) -> bool:
        return len(self.board) >= config.board_size(self.level)

    def record_result(self, result: str) -> None:
        """Extend or reset the streak. A draw breaks it."""
        if result == "draw":
            self.streak = 0
            self.streak_kind = None
            return
        if result == self.streak_kind:
            self.streak += 1
        else:
            self.streak_kind = result
            self.streak = 1


@dataclass
class GameState:
    config: Config
    templates: dict[str, UnitTemplate]
    pool: Pool
    players: list[PlayerState]
    round: int = 0
    next_uid: int = 0
    # What every player may know about every other player this round, frozen
    # at the start of planning (v0.4). See engine/observation.py.
    public: dict = field(default_factory=dict)

    def new_uid(self) -> int:
        uid = self.next_uid
        self.next_uid += 1
        return uid

    def living_players(self) -> list[PlayerState]:
        return [p for p in self.players if p.alive]


def new_game(config: Config, player_names: list[str]) -> GameState:
    expected = config.match["players"]
    if len(player_names) != expected:
        raise ValueError(f"expected {expected} players, got {len(player_names)}")

    templates = load_templates(config)
    players = [
        PlayerState(
            index=i,
            name=name,
            health=config.match["starting_health"],
            gold=config.economy["starting_gold"],
            level=config.level["starting"],
            shop=[None] * config.shop["slots"],
        )
        for i, name in enumerate(player_names)
    ]
    return GameState(
        config=config,
        templates=templates,
        pool=Pool(config, templates),
        players=players,
    )
