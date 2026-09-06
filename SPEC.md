# Autobattler — v0 Spec

Companion to `rules.yaml`. That file holds every number; this file holds the
semantics that numbers can't express. If the two disagree, `rules.yaml` wins
and this file is out of date.

## Invariants

The engine is pure and headless. No printing, no sleeping, no wall-clock time,
no rendering. `resolve()` takes state and a seeded RNG and returns state.

All randomness flows through a single `random.Random` instance passed in
explicitly. No module-level `random`, no unseeded calls, anywhere in `engine/`.

All iteration over units is by sorted `unit_id`. Never iterate a `set`, and
never depend on `dict` insertion order for anything that affects outcomes.

Combat advances in integer ticks, as fast as the CPU allows. The renderer
replays the event log at human speed. The engine has no concept of frames.

Templates are immutable; instances are mutable copies. A unit's `max_health`
is never written to.

## Round loop

Each round runs: income is paid, shops are rolled for both players, players
act, boards fight, damage is applied, dead players are removed.

Income is `base_income`, plus interest (`gold // interest_per`, capped), plus
any streak bonus. Paid before the shop rolls so it can be spent the same round.

During the planning phase a player may take any number of legal actions in any
order: buy a shop slot, sell a board unit, reroll the shop, buy a level, move a
unit to an empty square, swap two units, or end turn. Both players plan against
the same round state; ordering between players does not matter because planning
actions never touch shared state except the pool, which is resolved on purchase
in player-index order.

A purchase removes a copy from the shared pool. If the pool is empty for that
unit it cannot appear in a shop at all. Selling returns the copy to the pool.

## Combat resolution

Boards are merged into a single field, player 0 on the left half, player 1
mirrored on the right.

Per tick, for each living unit sorted by id: if its current target is dead or
unset, acquire a new one by `target_rule` with `target_tiebreak`. If the target
is within `range`, and `ticks_until_attack` has reached zero, deal
`attack_damage` and reset the cooldown. Otherwise step `move_per_tick` toward
the target along the axis that most reduces `move_metric` distance, preferring
the x-axis on ties, and skipping the move if the destination is occupied.
Decrement cooldowns at the end of the tick.

Combat ends when one side has no living units, or at `tick_cap`, in which case
`timeout_result` decides.

## Event log

Every mutation appends a record: `{tick, type, actor, target, value}` where
`type` is one of `attack`, `death`, `move`, `trait_applied`, `combat_end`.
This is the only output the renderer consumes and the primary artifact for
debugging both the engine and agent behaviour.

## Replay format

```json
{
  "version": "0.1.0",
  "config_hash": "<sha256 of rules.yaml>",
  "seed": 42,
  "players": ["agent:ppo-1200", "human:daniel"],
  "rounds": [
    {"round": 1, "actions": [[0, {"type": "buy", "slot": 2}]], "events": []}
  ],
  "result": {"placements": [1, 0]}
}
```

Identical `seed` + `config_hash` + action sequence must produce a byte-identical
replay. This is asserted by a test, not assumed.

## Open questions

Whether `purchase_when_board_full: block` produces bad play, or whether a bench
is needed. Whether `flat_plus_survivors` damage makes going wide dominant.
Whether positioning contributes anything once the economy is tuned. All three
are config-level ablations, not rewrites.

## Attribution

Design inspired by Teamfight Tactics (Riot Games), Dota Underlords (Valve),
Auto Chess (Drodo), and Merge Tactics (Supercell). No assets, names, art, or
code from any of those games are used here. This project is unaffiliated with
and not endorsed by any of them.
