# 2. When the environment picks the winner

*Found after v0.1. Fixed in v0.2.*

## The symptom

Two copies of `GreedyAgent`, a fully deterministic agent, played each other
over 100 seeds. Same code in both seats, so the result should be about 50/50.
It came out 38 to 62.

## Isolating it

To rule out the economy, strip the game down to one fight: the same unit on
the same square of both boards. Nothing distinguishes the sides, so the only
fair outcome is a draw. Under v0.1 rules:

| Unit | Range | Winner | Survivor HP |
| --- | --- | --- | --- |
| footman, scout, shieldman, knight, duelist, warden | 1 | player 0 | 2–7 |
| apprentice, ranger, adept | 3 | player 0 | 3–4 |
| archmage | 4 | player 1 | 10 |

Every fight was decided, and always by a sliver. That pattern is the
signature of a tie-break, not a strategy.

## The mechanism

The spec resolved a tick like this: "for each living unit sorted by id", act.
Each unit acted on a field that lower ids had *already changed that tick*.
Player 0 buys first, so it tends to hold the lower ids. Two effects follow, and
they pull in opposite directions:

1. **First strike.** In a mutual last-hit race, the lower id swings first and
   kills its opponent before the opponent's turn arrives. Favours player 0.
2. **First step.** The lower id also *moves* first, so it walks into range
   first — and the higher id, acting later that same tick, finds it already in
   range and takes the opening shot. Favours player 1.

Melee mirrors are decided by effect 1. The archmage flips because at range 4
effect 2 dominates. Across whole games player 1 came out ahead, which suggests
effect 2 matters more once real boards mix ranges — an inference from the
pattern, not something isolated separately.

## Is it real, or is it luck?

38 wins in 100 games could be noise. The tool for deciding is a **confidence
interval**. For a win rate, use the **Wilson score interval**. It behaves
better than the textbook `p ± 1.96·√(p(1−p)/n)` for small samples and for
rates near 0 or 1.

Over 500 seeds, v0.1 rules:

> player 0 won 41.0% — 95% interval **[36.8%, 45.4%]**

The interval excludes 50%, so this is not luck. As a rule of thumb, a 95%
interval on a roughly even win rate is about **±1/√n**:

| Games | Interval width | Smallest bias you can see |
| --- | --- | --- |
| 100 | ±10 pts | a blowout |
| 500 | ±4.4 pts | this bug |
| 2,000 | ±2.2 pts | a subtle balance edge |

Plan sample sizes from that table *before* running an experiment, not after.

## Why this matters for RL

- **RL optimises the environment you built, not the game you meant.** A seat
  advantage is free reward, and a learning agent will find it. It can learn a
  quirk of tick ordering instead of anything about the game.
- **Self-play inherits it.** If a policy always trains in one seat, it learns
  that seat's value, and that knowledge does not transfer to the other seat.
  If seats alternate, the value function has to absorb a side-dependent
  offset that is pure noise from the game's point of view.
- **Evaluations lie.** Player 0 sat about 9 points below even. Roughly
  speaking, an agent that wins 55% from a neutral seat would score around 46%
  from that one — a winner measured as a loser. A seat edge can hide a real
  skill gap or invent one.
- **Weak agents cannot see it.** The random agents came out at 49.0% under the
  old rules and 48.8% under the new ones. Their play was so noisy that a
  9-point structural edge vanished into it. The bias only surfaced once the
  agents were competent enough to make fights close, and close fights are
  exactly where tie-breaks decide things. **Every time your agents get
  stronger, re-audit the environment.**

## The fix: simultaneous resolution

Each tick now runs in three phases (`_tick_simultaneous` in `engine/combat.py`):

1. **Decide.** Every unit picks its target and its action from the field *as
   it stood at the start of the tick*. Nobody sees anybody else's move.
2. **Strike.** Every decided attack lands, including attacks from units that
   die this tick. Deaths are settled only after all damage is in.
3. **Move.** Survivors step. A destination must have been empty at the start
   of the tick.

This is the same idea as a turn-based game where both players submit orders
and they are revealed together. Consequences:

- A perfect mirror kills both units on the same tick and is a **draw**.
- A unit killed this tick still swings. Compare
  `test_a_unit_that_dies_this_tick_still_lands_its_attack` with
  `test_sequential_mode_lets_the_first_mover_kill_before_the_swing`: same
  board, different resolution, and the second one *is* the bias.
- Two units can claim the same empty square. That is settled by
  `combat.move_conflict`.

### Why `move_conflict` defaults to `random`

`lowest_id` would hand every contested square to whoever bought first, which is
the same bias again in miniature. `random` is a seeded draw from the round's
*combat* stream (see [lesson 1](01-determinism.md)), so it is fair in
expectation, reproducible, and cannot disturb the shops.

## After the fix

| greedy vs greedy, 500 seeds | Player 0 share | 95% interval |
| --- | --- | --- |
| v0.1 rules (`sequential`) | 41.0% | [36.8%, 45.4%] |
| v0.2 rules (`simultaneous`) | 52.2% | [47.8%, 56.5%] |

All ten mirror matches draw.

**"No bias detected" is not "no bias".** At 500 games the interval is about
±4.4 points, so a bias smaller than that would be invisible. One known
asymmetry remains by design: within a round, player 0 buys first and so has
first claim on a contested pool copy. The spec mandates it, and it is not
detectable at this sample size. If you ever need finer resolution, run 2,000+
games — and seat-swap them, so that any residual edge cancels out
([lesson 3](03-evaluation.md), coming in v0.3).

The v0.1 rule is still available as `combat.resolution: sequential`, so you can
reproduce every number on this page.

## Try it

```bash
python -m pytest tests/test_fair_combat.py -v
```
