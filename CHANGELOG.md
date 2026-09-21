# Changelog

One section per release, newest first. Versions are `MAJOR.MINOR`; see
[docs/VERSIONING.md](docs/VERSIONING.md). Each entry says what changed and,
where it matters, **why it matters for reinforcement learning**. The longer
explanations live in [docs/rl/](docs/rl/README.md).

## v0.2 — Fair fights

**Breaking:** replays from v0.1 do not reproduce on v0.2. Combat resolves
differently and the random streams are laid out differently.

### Fixed

- **Seat bias from tick order.** v0.1 resolved each tick one unit at a time in
  uid order, so each unit saw what lower uids had just done. A perfectly
  mirrored fight was never a draw, and over 500 greedy-vs-greedy games player 0
  won only 41.0% (95% CI 36.8–45.4%). Ticks now resolve simultaneously: every
  unit decides from the same snapshot, every attack lands, then survivors move.
  All ten mirror matches now draw, and player 0 wins 52.2% (CI 47.8–56.5%).
  The old rule remains as `combat.resolution: sequential`, for measuring.
  → [docs/rl/02-environment-bias.md](docs/rl/02-environment-bias.md)
- **Unsupported options failed mid-game.** `purchase_when_board_full: bench`
  loaded fine, then crashed on the first purchase with a full board. Every
  enumerated option is now checked when `rules.yaml` loads, as is the
  two-player limit.
- **Unit construction order.** Combat units were built player by player. That
  was deterministic, but not the spec's "sorted by `unit_id`". Now it is.

### Added

- **Per-round random streams.** The master rng gives up exactly one draw per
  round and derives a shop stream and a combat stream from it. A reroll in
  round 3, or a fight that goes differently, no longer shifts what round 4
  rolls. → [docs/rl/01-determinism.md](docs/rl/01-determinism.md)
- **`spawn` events.** The log named uids but never said what they were or where
  they started, so it could not drive a renderer. `spawn` carries template,
  field square, and final post-trait stats. A test rebuilds every fight from
  the log alone.
- **`combat.move_conflict`** (`random` | `lowest_id`) settles two units
  claiming one square. It defaults to `random`, a seeded draw from the combat
  stream, because `lowest_id` quietly favours whoever bought first.
- **Release versioning.** `engine/version.py` is the source; `rules.yaml` must
  match it, and replays record it. Annotated git tags per release.

### RL notes

- An environment bias is something a learning agent *will* find and exploit.
  A policy trained with a seat advantage learns the seat, not the game.
- The random agents could not see the bias at all: 49.0% under the old rules
  and 48.8% under the new. Their noise swamped it. Only competent agents
  exposed it, so re-audit the environment every time your agents get stronger.
- Isolated random streams give **common random numbers**: two agents or two
  configs compared on the same seed face the same luck for as long as their
  games stay alike, which cuts the games needed to detect a real difference.

## v0.1 — Headless engine

First playable engine, built from `SPEC.md` and `rules.yaml`: round loop,
income and interest, shop and shared pool, levels, traits, grid combat on a
merged 3×10 field, a five-field event log, and replays that reserialise
byte-identically. Two baseline agents, `RandomAgent` and `GreedyAgent`.

Files in this release say `0.1.0`, from before the `MAJOR.MINOR` scheme.

### Fixed in the provided ruleset

- `skirmisher:{...}` had no space after the key, so `rules.yaml` was invalid
  YAML and did not load.

### Added to the provided ruleset

- `economy.cost_by_tier` — the file had no unit purchase price.
- `planning.max_actions_per_round` — cuts off an agent that never ends its turn.

### RL notes

- Agents draw from their own random stream, separate from the engine's. On
  replay the agents are absent and make no draws; had they shared the engine's
  stream, every later shop roll would desync.
