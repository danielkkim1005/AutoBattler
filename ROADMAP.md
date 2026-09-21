# Roadmap to v1.0

A proposal, not a commitment. v1.0 means: **friends can play it, it is
reasonably balanced, and a trained agent can play too.** Each release keeps
the `MAJOR.MINOR` scheme ([docs/VERSIONING.md](docs/VERSIONING.md)) and ships
with a changelog entry and, where it teaches something, an RL note.

Items marked **decision** need your call before they can be built. Each is a
design question about the game, not an engineering one.

## Done

| Release | Title |
| --- | --- |
| v0.1 | Headless engine |
| v0.2 | Fair fights |
| v0.3 | Trustworthy experiments |
| v0.4 | RL-ready |

## Proposed

### v0.5 — Strategy and the bench

Answers the spec's two remaining open questions.

- **Bench** (`purchase_when_board_full: bench`): bench slots, place and bench
  actions, and an extended action space. **Decision:** bench size, and whether
  bench units count toward traits.
- **Strategy-diverse agents**, needed to test whether going wide dominates:
  a "wide" agent that levels early and fills the board, and a "tall" agent
  that rerolls for higher tiers.
- **Simultaneous planning**, closing the last observation leak (lesson 4).
  **Decision:** it changes the spec's "pool resolved in player-index order".

### v0.6 — First learner

- A training script: masked PPO against `GreedyAgent`, with seat
  randomisation and held-out evaluation seeds.
- Learning curves evaluated with the lesson 3 protocol.
- An RL note on what the learner exploited — every environment bug a learner
  finds gets fixed and written up.

### v0.7 — Replay viewer

- A renderer for the event log: browser-based or terminal. The engine already
  records everything it needs (spawn, move, attack, death; a test proves the
  log rebuilds every fight).
- **Decision:** browser or terminal. Browser is friendlier; terminal is
  cheaper.

### v0.8 — Human play

- A human agent behind the same observation interface, so humans and bots are
  interchangeable.
- Hot-seat play on one machine first.
- **Decision:** is hot-seat enough for friends, or is networked play a v1.0
  requirement? Networked play means a server and hosting — the largest single
  item on this list, and it costs real money.

### v0.9 — Content and balance

- More units and traits, plus star-ups (combining copies), if wanted.
  **Decision:** which genre mechanics to adopt.
- A balance pass with `evaluate.py`, using the trained agent from v0.6 as the
  strongest test.
- Longer games. v0.3 found income barely matters because games end near round
  8.5, so `starting_health` or the damage formula come first.

### v1.0 — Playtest release

- Packaged so a friend can install and play.
- A stable replay format, and a promise not to break it within 1.x.
- A playtest feedback loop.
