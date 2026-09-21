# Changelog

One section per release, newest first. Versions are `MAJOR.MINOR`; see
[docs/VERSIONING.md](docs/VERSIONING.md). Each entry says what changed and,
where it matters, **why it matters for reinforcement learning**. The longer
explanations live in [docs/rl/](docs/rl/README.md).

## v0.4 — RL-ready

**Breaking:** agents now implement `choose(observation, rng)` instead of
`choose(state, player, rng)`. Game outcomes are unchanged: 90 games across
three agent pairings are identical to v0.3, action for action and event for
event.

### Fixed

- **Agents could see the opponent's current-round moves.** Agents received the
  whole `GameState`, and seat 0 plans first, so seat 1's agent could see seat
  0's purchases and positioning from *this* round, seat 0's private shop, and a
  live pool. No existing agent looked, but a learner would have learned to
  exploit it. Agents now get an observation: their own state live, everyone
  else's frozen at the start of planning, shops private. A spying test catches
  the leak, and was checked against a deliberately leaky `observe()` to be sure
  it fails when it should. One residual leak, through the live pool in
  `legal_actions`, is documented and on the roadmap.
  → [docs/rl/04-observations.md](docs/rl/04-observations.md)

### Added

- **`rl.AutoBattlerEnv`**, a gymnasium-style environment with no dependencies:
  `reset` / `step`, one step per planning action, a 98-action discrete space,
  exact action masks (`action_masks()`, MaskablePPO's name), a 371-float
  observation with a name for every position, and `terminal` or
  potential-based `shaped` rewards. Every episode is a replayable game.
  → [docs/rl/05-environment.md](docs/rl/05-environment.md)
- **`python -m rl.demo`**: masked-random episodes, with every replay verified.
- **Phased rounds**: `begin_round` → `act` → `finish_round`, so the
  environment can pause mid-round for the learner. `resolve` composes them as
  before.
- **`engine/observation.py`**: `observe(state, seat)` and the round-start
  public snapshot.
- **[ROADMAP.md](ROADMAP.md)**: a proposed path to v1.0, marking where your
  design decisions are needed.

### Measured

- Environment throughput: about 6,600 steps a second, around 38 episodes, on
  one process.
- A masked random policy lost all 10 demo games to `GreedyAgent`: the floor
  for any learner.

### RL notes

- **Hand-written agents cannot reveal an information leak; learners exploit
  one.** The refactor changed no outcome precisely because nothing was reading
  the leaked data yet.
- **Mask, don't penalise.** Illegal actions raise; the mask removes them from
  the policy's choices entirely.
- **Potential-based shaping cannot be gamed.** It telescopes, adding exactly
  nothing to any episode's return, as two tests verify. Pass the learner's own
  gamma.
- **Hitting `max_rounds` is termination, not truncation.** The rules define a
  winner there, and a learner must not bootstrap past it.

## v0.3 — Trustworthy experiments

**Breaking:** v0.2 replays do not reproduce byte-for-byte. The result block
gained two fields and the ruleset version changed, though game actions and
events are unchanged. `run_game.py` no longer runs sweeps; use `evaluate.py`.

### Fixed

- **`config_hash` depended on line endings.** It was the SHA-256 of
  `rules.yaml`'s raw bytes, and git on Windows (`core.autocrlf=true`) rewrites
  LF as CRLF on checkout. One ruleset hashed two ways (`d3699bd1…` LF,
  `cfac4cdb…` CRLF), so a checkout, or a friend on another OS, would orphan
  every recorded replay. Line endings are now normalised before hashing, and
  `.gitattributes` pins LF. Files that were already LF keep the same hash.
  → [docs/rl/01-determinism.md](docs/rl/01-determinism.md)

### Added

- **`evaluate.py` and the `analysis/` package.** Seat-swapped matchups by
  default, a per-seed confidence interval on every score, paired comparisons
  between rulesets, and unit/trait/level telemetry read straight from replays.
  `--json` writes the full report.
  → [docs/rl/03-evaluation.md](docs/rl/03-evaluation.md)
- **Config overlays** (`load_config(path, overlays)`, `evaluate.py --ablate`):
  a small YAML holding only the keys it changes, merged onto `rules.yaml`.
  Unknown keys are rejected, so a typo cannot quietly nullify an experiment.
  Six ablations ship in `configs/ablations/`.
- **`PositionalAgent`.** Buys exactly like `GreedyAgent`, then forms up —
  melee in front, ranged behind — so any difference between the two is the
  value of positioning alone.
- **Brawl mode** (`board.positioning: false`). Everyone is in range and nobody
  moves: the control for the positioning experiment.
- **`level` and `gold`** in the replay result block.
- **`agents.REGISTRY`**, mapping names to agent classes for the CLIs.

### Measured

All from 300 seeds, seat-swapped, unless noted.

| Question | Answer |
| --- | --- |
| Does positioning matter? *(spec open question 3)* | **Yes.** Positional beats greedy 60.5% [57.5, 63.5]. In a brawl it is exactly 50.0%, so the ~10.5 points are positioning and nothing else. |
| Does income matter? | **Barely, yet.** Income 5 → 7 shortens games by 0.37 rounds and moves no win rate detectably. Games end around round 8.5, before interest compounds. |
| Does `flat_plus_tiers` change things? | Games get 2.45 rounds shorter [2.24, 2.65], and positional's edge shrinks by 2.5 points [0.4, 4.6]. |
| Does `move_conflict: lowest_id` bring back seat bias? | **No detectable effect:** 52.4% vs 52.2% for seat 0, 500 unswapped mirrors. The v0.2 worry was a prediction the data did not bear out. |
| Is going wide dominant? *(open question 2)* | **Still open.** It needs agents with genuinely different strategies, and every current agent levels at the same moment. |
| Is a bench needed? *(open question 1)* | **Still open.** Bench mode is not implemented. |

### RL notes

- **The seed is the unit of evaluation, not the game.** Both games of a
  seat-swapped pair share the same luck. Intervals computed over games would be
  wrong; computed over seeds, they are right.
- **Build the control.** The brawl makes positional-vs-greedy exactly 50%. That
  exact null is what makes the grid result mean something.
- **Pairing is free precision.** Comparing rulesets on the same seeds cut the
  interval on positional's edge from about ±4.1 unpaired to ±1.5.
- **Tuning finding:** games are too short for the economy to matter. Turn
  `starting_health` or the damage formula before touching income.

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
