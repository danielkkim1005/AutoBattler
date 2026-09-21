# RL notes

What building this environment teaches about reinforcement learning. Each note
starts from a real bug or design decision in this repo, names the release that
introduced it, and points at the code and tests that show it.

Read them in order; later notes lean on earlier ones.

| # | Note | Release | The lesson in one line |
| --- | --- | --- | --- |
| 1 | [Determinism and random streams](01-determinism.md) | v0.1, v0.2 | Randomness must be a function of the seed, and each consumer gets its own stream. |
| 2 | [When the environment picks the winner](02-environment-bias.md) | v0.2 | A learning agent will exploit any structural bias, and weak agents can't reveal one. |

## Vocabulary used throughout

- **Environment** — the game engine, seen from the agent's side: it receives
  actions and hands back observations and rewards.
- **Policy** — whatever picks actions. `GreedyAgent` is a hand-written policy;
  a trained network is a learned one.
- **Episode** — one full game, from the first shop to a winner.
- **Seat** — which player index an agent plays as. Seat 0 plans first and
  fights from the left half.
- **Seed** — the integer every random outcome in an episode derives from.
