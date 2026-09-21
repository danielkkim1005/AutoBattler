# 4. What an agent is allowed to know

*Found and fixed in v0.4.*

## The leak

Up to v0.3, an agent's `choose` received the entire `GameState`. Seat 0 plans
first, so by the time seat 1's agent was called, the state already held:

- seat 0's purchases, sales, and unit moves **from this round**, before combat;
- seat 0's **private shop**;
- seat 0's gold after spending, and a pool already missing what it bought.

The spec says both players "plan against the same round state". Nothing
enforced that. Seat 1 simply planned against a later one.

## Why nobody noticed, and why that is not reassuring

The hand-written agents never looked. v0.4 switched every agent to
observations, and 90 games across three agent pairings came out identical to
v0.3, action for action and event for event. The leak had no effect *because
nothing exploited it*.

A learned policy is different. **A network uses any input that correlates with
reward**, whether or not you meant it to be information. Hand a seat-1 learner
its opponent's final formation for this round, and it will learn to
counter-position against it, because that wins.

## Why it matters for RL

- **Train/test mismatch.** A policy trained on leaked information depends on
  it. Put it against a human, or in any setting where both sides really plan
  blind, and it is relying on an input that no longer exists. It fails in ways
  that never showed up in training.
- **It is a seat bias, again.** Only seat 1 could exploit the leak, so a
  learner would become stronger in seat 1 for reasons that have nothing to do
  with the game — lesson 2, in learned form.
- **Hidden information is part of the game.** Not knowing what your opponent is
  doing *right now* is the design, not a limitation. An environment that
  reveals it is a different, easier game.

## What an observation contains

`engine/observation.py` builds a plain, JSON-serialisable dict:

| Field | Whose | Freshness |
| --- | --- | --- |
| `self`: health, gold, level, streak, board, shop, board size, level cost | yours | **live** — reflects your actions this round |
| `opponents[]`: health, gold, level, streak, alive, board | theirs | **frozen** at the start of planning |
| `pool` | shared | **frozen** at the start of planning |
| `legal_actions` | yours | live |
| opponents' shops | — | **never** |

"Frozen at the start of planning" is what scouting shows you in the genre, and
it is identical whichever seat plans first. That is what makes the two seats
symmetric.

## The residual leak, documented rather than hidden

`legal_actions` is computed from the *live* pool. If seat 0 buys the last copy
of a unit, the matching purchase disappears from seat 1's legal actions, and
seat 1 learns something it should not. Closing that gap means making planning
genuinely simultaneous — both seats submit, then purchases resolve — which
changes the spec's "pool resolved on purchase in player-index order". That is
a design decision for you, so it is on the roadmap rather than done quietly.

With 12 copies of each tier-1 unit and 5 of each tier-3, it only bites when a
unit is nearly exhausted.

## Partial observability

In RL terms, the game is now a **partially observable** Markov game: the state
holds more than any one agent sees. Two consequences for training:

- **The observation is not the state.** Two different states — say, your
  opponent bought a knight this round or did not — produce the same
  observation. The policy must act well across both.
- **Memory can help.** What your opponent built three rounds ago is not in the
  current observation. A policy that remembers it, through a recurrent network
  or by stacking recent observations, can know more than one that does not.
  Worth trying once a memoryless baseline works.

## How it is tested

`tests/test_env.py` puts a spying agent in seat 1 that records every
observation it is handed:

- `test_seat_one_cannot_see_seat_zeros_moves_this_round` — the opponent board
  it sees is always the round-start board, its gold never changes mid-round,
  and no shop is present;
- `test_pool_counts_are_frozen_during_planning` — every observation in a round
  carries the same pool.

To be sure those tests have teeth, they were run against a deliberately leaky
`observe` that showed opponents live. Both failed, as they should.

## Try it

```bash
python -m pytest tests/test_env.py -k "cannot_see or frozen or plain_json" -v
```
