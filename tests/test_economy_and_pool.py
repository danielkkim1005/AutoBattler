"""Income, interest, streaks, the shared pool, and purchase legality."""

from __future__ import annotations

import random

from conftest import place, tweak
from engine.actions import apply_action, is_legal, legal_actions
from engine.economy import interest, round_income, sell_refund, streak_bonus
from engine.game import pay_income, roll_shops
from engine.shop import roll_shop


# -- economy ---------------------------------------------------------------

def test_interest_is_capped(config):
    assert interest(config, 0) == 0
    assert interest(config, 9) == 0
    assert interest(config, 10) == 1
    assert interest(config, 49) == 4
    assert interest(config, 50) == 5
    assert interest(config, 500) == 5, "interest_cap must bite"


def test_streak_bonus_uses_the_largest_threshold_met(config):
    assert streak_bonus(config, 0) == 0
    assert streak_bonus(config, 2) == 0
    assert streak_bonus(config, 3) == 1
    assert streak_bonus(config, 4) == 1
    assert streak_bonus(config, 5) == 2
    assert streak_bonus(config, 12) == 2


def test_round_income_sums_its_three_parts(config):
    assert round_income(config, gold=0, streak=0) == 5
    assert round_income(config, gold=30, streak=0) == 8
    assert round_income(config, gold=30, streak=5) == 10


def test_income_is_paid_before_shops_roll(state):
    """Income must be spendable the same round it is paid."""
    starting = state.players[0].gold
    pay_income(state)
    assert state.players[0].gold == starting + 5
    roll_shops(state, random.Random(1))
    assert any(slot is not None for slot in state.players[0].shop)


def test_streaks_extend_and_reset(state):
    player = state.players[0]
    for _ in range(3):
        player.record_result("win")
    assert (player.streak, player.streak_kind) == (3, "win")
    player.record_result("loss")
    assert (player.streak, player.streak_kind) == (1, "loss")
    player.record_result("draw")
    assert (player.streak, player.streak_kind) == (0, None)


def test_sell_refund_is_full_by_default(config):
    assert sell_refund(config, 1) == config.unit_cost(1)
    assert sell_refund(config, 3) == config.unit_cost(3)
    halved = tweak(config, economy={"sell_refund": "half"})
    assert sell_refund(halved, 3) == config.unit_cost(3) // 2


# -- pool ------------------------------------------------------------------

def test_buying_takes_from_the_shared_pool(state):
    player = state.players[0]
    player.gold = 10
    player.shop = ["footman", None, None, None, None]
    before = state.pool.remaining("footman")

    apply_action(state, player, {"type": "buy", "slot": 0}, random.Random(0))
    assert state.pool.remaining("footman") == before - 1
    assert len(player.board) == 1
    assert player.shop[0] is None


def test_selling_returns_the_copy(state):
    player = state.players[0]
    player.gold = 10
    player.shop = ["footman", None, None, None, None]
    before_gold = player.gold
    before_pool = state.pool.remaining("footman")

    rng = random.Random(0)
    apply_action(state, player, {"type": "buy", "slot": 0}, rng)
    uid = next(iter(player.board))
    apply_action(state, player, {"type": "sell", "uid": uid}, rng)

    assert state.pool.remaining("footman") == before_pool
    assert player.gold == before_gold, "full refund must round-trip exactly"
    assert player.board == {}


def test_the_pool_is_shared_between_players(state):
    for player in state.players:
        player.gold = 10
        player.shop = ["footman", None, None, None, None]
    before = state.pool.remaining("footman")

    rng = random.Random(0)
    apply_action(state, state.players[0], {"type": "buy", "slot": 0}, rng)
    apply_action(state, state.players[1], {"type": "buy", "slot": 0}, rng)
    assert state.pool.remaining("footman") == before - 2


def test_an_exhausted_unit_cannot_appear_in_a_shop(state, config):
    """Drain every tier-1 unit but one; only that one can ever be offered."""
    for template_id in sorted(state.templates):
        if state.templates[template_id].tier != 1 or template_id == "scout":
            continue
        while state.pool.remaining(template_id) > 0:
            state.pool.take(template_id)

    rng = random.Random(4)
    for _ in range(40):
        for slot in roll_shop(config, state.pool, level=1, rng=rng):
            assert slot in (None, "scout")


def test_an_empty_tier_yields_empty_slots(state, config):
    for template_id in sorted(state.templates):
        while state.pool.remaining(template_id) > 0:
            state.pool.take(template_id)
    assert roll_shop(config, state.pool, level=1, rng=random.Random(0)) == [None] * 5


def test_buying_is_blocked_when_the_pool_is_empty(state):
    player = state.players[0]
    player.gold = 10
    player.shop = ["footman", None, None, None, None]
    while state.pool.remaining("footman") > 0:
        state.pool.take("footman")
    assert not is_legal(state, player, {"type": "buy", "slot": 0})


# -- board limits ----------------------------------------------------------

def test_a_full_board_blocks_purchases(state, config):
    player = state.players[0]
    player.gold = 50
    place(state, 0, "footman", 0, 0)
    place(state, 0, "scout", 0, 1)
    assert player.board_full(config), "level 2 seats exactly 2 units"

    player.shop = ["knight", None, None, None, None]
    assert not is_legal(state, player, {"type": "buy", "slot": 0})

    apply_action(state, player, {"type": "buy_level"}, random.Random(0))
    assert player.level == 3
    assert is_legal(state, player, {"type": "buy", "slot": 0})


def test_levelling_stops_at_max(state, config):
    player = state.players[0]
    player.gold = 1000
    rng = random.Random(0)
    while player.level < config.level["max"]:
        apply_action(state, player, {"type": "buy_level"}, rng)
    assert player.level == config.level["max"]
    assert not is_legal(state, player, {"type": "buy_level"})


def test_move_and_swap_legality(state, config):
    player = state.players[0]
    a = place(state, 0, "footman", 0, 0)
    b = place(state, 0, "scout", 1, 1)

    assert not is_legal(state, player, {"type": "move", "uid": a, "x": 1, "y": 1})
    assert not is_legal(state, player, {"type": "move", "uid": a, "x": 9, "y": 0})
    assert is_legal(state, player, {"type": "move", "uid": a, "x": 2, "y": 2})

    apply_action(state, player, {"type": "swap", "a": a, "b": b}, random.Random(0))
    assert player.board[a].pos() == (1, 1)
    assert player.board[b].pos() == (0, 0)


def test_legal_actions_are_ordered_and_all_legal(state):
    player = state.players[0]
    player.gold = 10
    player.shop = ["footman", "scout", None, None, None]
    place(state, 0, "knight", 2, 2)

    actions = legal_actions(state, player)
    assert actions[0] == {"type": "end_turn"}
    assert all(is_legal(state, player, a) for a in actions)
    assert legal_actions(state, player) == actions, "enumeration must be stable"
