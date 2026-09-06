# Autobattler — v0

A headless, deterministic autobattler engine. `rules.yaml` holds every number,
[`SPEC.md`](SPEC.md) holds the semantics, and `engine/` implements them without
printing, sleeping, or rendering anything.

```bash
python -m pytest tests/ -q
python run_game.py --seed 42 --verify
python run_game.py --agents greedy random --games 100 --summary
```

## Layout

| Path | What lives there |
| --- | --- |
| `engine/config.py` | Loads, validates, and hashes `rules.yaml`. The only door to the file. |
| `engine/state.py` | `GameState`, `PlayerState`, board ownership. |
| `engine/actions.py` | Planning actions: legality, enumeration, application. |
| `engine/shop.py` | Tier draw, then a unit weighted by copies left in the pool. |
| `engine/pool.py` | The shared pool. Buying takes a copy, selling returns it. |
| `engine/economy.py` | Income, interest, streaks, refunds. |
| `engine/traits.py` | Breakpoints and the bonuses they unlock. |
| `engine/combat.py` | Board merge, tick loop, targeting, movement. |
| `engine/game.py` | The round loop, damage, placements, full games. |
| `engine/replay.py` | The replay record and its deterministic serialisation. |
| `agents/` | `RandomAgent` (the floor) and `GreedyAgent` (a non-degenerate opponent). |
| `run_game.py` | CLI harness. All printing lives here. |

## Determinism

`tests/test_determinism.py` asserts the property the spec demands: identical
seed + `config_hash` + action sequence produces a byte-identical replay. It
checks three ways — the same seed twice, a recorded action list replayed
through `replay_game`, and a static AST scan proving nothing under `engine/`
calls the process-wide `random`.

Making that true required **splitting the RNG into two streams**. The engine
stream (`random.Random(seed)`) rolls shops. The agent stream
(`random.Random(seed ^ 0x5EED)`) is what agents deliberate with. If agents drew
from the engine stream, replaying a recorded action list — where the agents are
gone and draw nothing — would leave the engine's generator in a different place
and desync every later shop roll. The spec says a replay is reproducible from
seed + hash + *actions*, which only holds if agent deliberation is off the
engine's stream.

## Changes made to `rules.yaml`

**One bug fix.** Line 83 read `skirmisher:{breakpoint: 2, ...}`. YAML requires a
space after the key, so the file did not parse at all. Now `skirmisher: {...}`.

**Two additions,** because the engine needed values the file did not carry and
the spec forbids hardcoding them in Python:

- `economy.cost_by_tier: {1: 1, 2: 2, 3: 3}` — there was no unit purchase price
  anywhere. Cost equals tier, which is the genre default; `sell_refund: full`
  refunds exactly this.
- `planning.max_actions_per_round: 200` — a safety rail so an agent that never
  returns `end_turn` is cut off instead of looping forever.

Both are guesses at your intent. Change the numbers freely; nothing reads them
except through `Config`.

## Judgment calls the spec left open

Each of these changes outcomes, so they are listed rather than buried.

**A unit in range but on cooldown holds its ground.** The spec says a unit
attacks if in range and off cooldown, "otherwise" it steps toward its target.
Read literally, a ranged unit would keep walking while its cooldown ticks and
end up in melee, which makes `range` meaningless. Implemented as: in range means
stay put, whether or not the attack is ready.

**Traits count copies, not distinct units.** Two footmen activate vanguard.
Counting unique unit ids instead (the TFT convention) would make breakpoint 2
very hard to reach on a 2-to-5 unit board.

**Trait bonuses are baked in at construction.** `CombatUnit`s are built fresh at
the start of each combat with bonuses already folded into their stat fields, so
`max_health` is written once and never again — the spec's invariant holds
literally. A cooldown bonus is floored at 1 tick so a future buff cannot produce
free attacks.

**Shop units are weighted by copies remaining.** A contested unit gets rarer as
opponents buy it. A tier with nothing left yields an empty slot, and the tier
draw is still consumed so the RNG stream stays aligned.

**Draws damage nobody and break both streaks.** The spec only defines damage to
a losing player.

**New units are placed on the first free square** in `(x, y)` order, and
`placements` uses 0 for first place, with ties sharing a placement.

## Event log conventions

The record is fixed at `{tick, type, actor, target, value}`, which forces two
overloads:

- `trait_applied` — `actor` is the unit uid, `target` is the trait name,
  `value` is the stat delta. One event per unit per stat, all at tick 0.
- `combat_end` — `actor` is the winning player index (`null` on a draw),
  `value` is the ending tick.
- `move` — `value` is the destination `[x, y]`; `target` is who it is chasing.

## Open questions, unchanged

The spec's three ablations are all reachable by editing `rules.yaml` alone:
`purchase_when_board_full`, the `damage.formula`, and `board.positioning`.

Two observations from the seed sweeps, neither investigated:

- `GreedyAgent` beats `RandomAgent` in 50/50 games at an average of 5.4 rounds.
  Games are short — `flat_plus_survivors` plus a 20-health pool ends things
  fast, which is worth a look before reading anything into agent strength.
- Random-vs-random over 50 seeds went 20/30 to player 1. Within noise at that
  sample size, but player 0 plans first and takes pool priority, and lower uids
  act first within a tick, so a real side bias is plausible. Worth a larger
  sweep before tuning anything.

`board.positioning: false` is accepted by the config but not yet branched on;
combat always uses the grid.

## Attribution

Design inspired by Teamfight Tactics (Riot Games), Dota Underlords (Valve),
Auto Chess (Drodo), and Merge Tactics (Supercell). No assets, names, art, or
code from any of those games are used here. This project is unaffiliated with
and not endorsed by any of them.
