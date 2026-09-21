# Autobattler

A headless, deterministic autobattler engine, built as an environment for
reinforcement learning. `rules.yaml` holds every number, [`SPEC.md`](SPEC.md)
holds the semantics, and `engine/` implements them without printing, sleeping,
or rendering anything.

**Current release: v0.3 — Trustworthy experiments.** See [CHANGELOG.md](CHANGELOG.md).

```bash
python -m pytest tests/ -q
python run_game.py --seed 42 --verify
python evaluate.py --agents positional greedy --seeds 300
```

## Tuning workflow

1. **Ask one question per overlay.** Copy a file in `configs/ablations/` and
   change only the keys your question is about.
2. **Compare on shared seeds:**
   `python evaluate.py --agents positional greedy --seeds 300 --ablate configs/ablations/yours.yaml`
3. **Read the paired-difference lines.** An interval that excludes 0 is a real
   effect. One that straddles 0 means "not detectable at this sample size" —
   add seeds, or accept that the effect is small.
4. **Adopt the change** by copying the overlay's values into `rules.yaml`, run
   `python -m pytest tests/ -q`, and commit.

[docs/rl/03-evaluation.md](docs/rl/03-evaluation.md) explains why each step is
there, and what v0.3 already measured.

## Documentation

| Read this | For |
| --- | --- |
| [CHANGELOG.md](CHANGELOG.md) | What changed in each release, and why it matters for RL. |
| [docs/rl/](docs/rl/README.md) | RL notes: lessons from this codebase, in reading order. |
| [docs/VERSIONING.md](docs/VERSIONING.md) | The `MAJOR.MINOR` scheme and the release checklist. |
| [SPEC.md](SPEC.md) | Game semantics. Changed sections are marked with their version. |

## Layout

| Path | What lives there |
| --- | --- |
| `engine/version.py` | The release version. Stamped into every replay. |
| `engine/config.py` | Loads, validates, and hashes `rules.yaml`. The only door to the file. |
| `engine/state.py` | `GameState`, `PlayerState`, board ownership. |
| `engine/actions.py` | Planning actions: legality, enumeration, application. |
| `engine/shop.py` | Tier draw, then a unit weighted by copies left in the pool. |
| `engine/pool.py` | The shared pool. Buying takes a copy, selling returns it. |
| `engine/economy.py` | Income, interest, streaks, refunds. |
| `engine/traits.py` | Breakpoints and the bonuses they unlock. |
| `engine/combat.py` | Board merge, simultaneous tick resolution, targeting, movement. |
| `engine/game.py` | The round loop, per-round random streams, damage, placements. |
| `engine/replay.py` | The replay record and its deterministic serialisation. |
| `agents/` | `RandomAgent` (the floor), `GreedyAgent` (buys greedily), `PositionalAgent` (greedy buying plus a formation). |
| `analysis/` | Statistics, replay telemetry, seat-swapped evaluation. Reads replays; never changes an outcome. |
| `configs/ablations/` | Overlays: one question each, merged onto `rules.yaml`. |
| `run_game.py` | Play one game; write or verify its replay. |
| `evaluate.py` | Sweeps with confidence intervals; ruleset comparisons. |

## Determinism

Identical seed + `config_hash` + action sequence produces a byte-identical
replay. That is asserted three ways in `tests/test_determinism.py`.

Randomness is split into streams so that nothing drifts: agents deliberate on
their own stream, and each round derives a private shop stream and combat
stream from one draw of the master stream. Why each split exists, and what
breaks without it, is in [docs/rl/01-determinism.md](docs/rl/01-determinism.md).

## Changes made to the provided `rules.yaml`

- **v0.1 fixed** `skirmisher:{...}`, which had no space after the key and made
  the file invalid YAML.
- **v0.1 added** `economy.cost_by_tier` (there was no unit price) and
  `planning.max_actions_per_round` (a rail against agents that never end their
  turn).
- **v0.2 added** `combat.resolution` and `combat.move_conflict`, and quoted
  `version`, which must now match `engine/version.py`.
- **v0.3 enabled** `board.positioning: false` (a brawl).

All of these are guesses at your intent. Change the numbers freely; nothing
reads them except through `Config`, which rejects unsupported options at load.

## Judgment calls the spec left open

Each of these changes outcomes, so they are listed rather than buried.

**Ticks resolve simultaneously** (v0.2). Every unit decides from the same
snapshot, then all attacks land, then survivors move. The spec's original
unit-by-unit rule gave player 0 a measurable disadvantage; the full story is in
[docs/rl/02-environment-bias.md](docs/rl/02-environment-bias.md).

**A unit in range but on cooldown holds its ground.** Read literally, the spec
has it step toward its target while waiting, which walks ranged units into
melee and makes `range` meaningless.

**Traits count copies, not distinct units.** Two footmen activate vanguard.
Counting unique unit ids (the TFT convention) would make breakpoint 2 very hard
to reach on a 2-to-5 unit board.

**Trait bonuses are baked in at construction.** Combat units are built fresh
each fight with bonuses folded into their stats, so `max_health` is written once
and never again. A cooldown bonus is floored at 1 tick.

**Shop units are weighted by copies remaining.** A contested unit gets rarer as
opponents buy it. A tier with nothing left yields an empty slot.

**Draws damage nobody and break both streaks.** The spec only defines damage to
a losing player.

**New units go on the first free square** in `(x, y)` order. `placements` uses
0 for first place, and ties share a placement.

## Event log conventions

The record is fixed at `{tick, type, actor, target, value}`, which forces some
overloading:

| type | actor | target | value |
| --- | --- | --- | --- |
| `spawn` | unit uid | owner's player index | `{unit, x, y, max_health, attack_damage, attack_cooldown, range}` — field square, post-trait stats |
| `trait_applied` | unit uid | trait name | stat delta |
| `attack` | attacker uid | target uid | damage |
| `death` | dead uid | lowest uid that hit it this tick | final health (≤ 0) |
| `move` | unit uid | uid it is chasing | destination `[x, y]` |
| `combat_end` | winning player index, or `null` on a draw | — | final tick |

## The spec's open questions

| Question | Status (v0.3) |
| --- | --- |
| Does positioning contribute anything? | **Yes, about 10.5 points** of win rate for a simple formation, with the brawl as an exact-50% control. |
| Does `flat_plus_survivors` make going wide dominant? | Open. It needs agents with genuinely different strategies. |
| Is a bench needed? | Open. `purchase_when_board_full: bench` is rejected at load until implemented. |

Details and numbers are in the v0.3 section of [CHANGELOG.md](CHANGELOG.md).

## Attribution

Design inspired by Teamfight Tactics (Riot Games), Dota Underlords (Valve),
Auto Chess (Drodo), and Merge Tactics (Supercell). No assets, names, art, or
code from any of those games are used here. This project is unaffiliated with
and not endorsed by any of them.
