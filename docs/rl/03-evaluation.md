# 3. Evaluating agents and rulesets honestly

*Introduced in v0.3.*

Every claim of the form "agent A is better than B" or "this rule change makes
games longer" is a statistical claim. This note covers the protocol
`evaluate.py` follows and why each piece is there. When you train agents, you
will evaluate every checkpoint this way, so it is worth getting right once.

## The protocol

```bash
python evaluate.py --agents positional greedy --seeds 300
```

1. **A fixed list of seeds.** Seeds 0–199 by default (`--seeds` and
   `--first-seed` change that). The same list every time, so results are
   comparable across runs and across releases.
2. **Seat swapping.** Each seed is played twice: A in seat 0, then A in seat 1.
   Any seat advantage then hits both agents equally and cancels out.
3. **The seed is the unit, not the game.** Both games of a pair share the same
   luck, so they are not independent. Each seed yields one score — 0, 0.25,
   0.5, 0.75 or 1, averaged over its two games — and the confidence interval
   comes from the spread of those per-seed scores.
4. **An interval on every number.** A win rate without an interval is not a
   result.

## Why seat swapping is not optional

Swapping removes seat bias from the comparison, even bias you do not know
about. It also gives you a free sanity check. When A and B are the same
deterministic agent, both games of a pair are the *same game* with the labels
exchanged, so every seed must score exactly 0.5:

```
greedy (A) vs greedy (B)  seat-swapped
  A score  50.0%  [50.0, 50.0]
```

`test_seat_swapping_scores_identical_agents_at_exactly_one_half` pins that. If
it ever fails, the evaluator or the engine is broken.

Use `--no-swap` only when measuring seat bias itself. Then read the
`seat 0 share` line instead.

## Two intervals for two shapes of data

- **Wilson interval** (`wilson_interval`) — for independent yes/no trials,
  such as "seat 0 won 205 of 500 games". That is what the seat-bias numbers use.
- **Mean interval** (`mean_interval`) — for per-seed scores, which are not
  yes/no. That is what the A-score line uses.

Rule of thumb for planning: a 95% interval on an even win rate is about
**±1/√n**. `games_for_margin(0.02)` says a ±2-point margin needs about 2,400
games. Decide the sample size *before* looking at results. Adding seeds until
the answer looks significant is how false findings are made.

## Controls: prove the measurement can say "no difference"

`PositionalAgent` buys exactly like `GreedyAgent` and differs only in where it
puts units. In a brawl (`configs/ablations/brawl.yaml`), squares do not matter,
so the two must be indistinguishable:

| positional vs greedy, 300 seeds, swapped | A score | 95% interval |
| --- | --- | --- |
| grid (the real game) | 60.5% | [57.5, 63.5] |
| brawl (the control) | 50.0% | [50.0, 50.0] |
| **paired difference** | **−10.5 pts** | **[−13.5, −7.5]** |

The control coming out at exactly 50% is what licenses the conclusion: the
10.5 points really are positioning, not some other difference that slipped in.
**Every time you claim an agent learned something specific, build the control
that would show it did not.**

This answers the spec's third open question: positioning contributes, and even
a naive formation — melee in front, ranged behind — is worth about 10 points
against back-line clumping.

## Comparing rulesets: pairing by seed

```bash
python evaluate.py --agents positional greedy --seeds 300 --ablate configs/ablations/long_game.yaml
```

This plays the same seeds under both rulesets and reports the per-seed
*difference*. Shared luck cancels in the difference — the common random numbers
from [lesson 1](01-determinism.md) paying off:

300 seeds, seat-swapped, positional vs greedy:

| Ablation | Rounds, paired Δ | Positional's edge, paired Δ |
| --- | --- | --- |
| `long_game` (health 20 → 40) | +6.96 [+6.67, +7.24] | +0.0 pts [−1.5, +1.5] |
| `damage_tiers` | −2.45 [−2.65, −2.24] | −2.5 pts [−4.6, −0.4] |
| `rich` (income 5 → 7) | −0.37 [−0.69, −0.04] | −2.7 pts [−6.7, +1.4] |

Look at the `long_game` edge interval: ±1.5 points. Each arm on its own
carries about ±3, so subtracting two independent runs would give roughly ±4.1.
Pairing by seed cut that to ±1.5 — nearly a third, for free.

**What this says about tuning.** Income barely moves anything. Games end
around round 8.5 with both players near max level, before interest can
compound. Until games run longer, the economy is not a real lever. That makes
`starting_health` or the damage formula the first knobs to turn, not the
income numbers.

## Overlays: how to write an ablation

An ablation is a small YAML file holding only the keys it changes:

```yaml
# configs/ablations/rich.yaml
economy:
  base_income: 7
```

It is merged onto `rules.yaml` at load time. Three properties matter for
experiments:

- **It cannot go stale.** A full copy of `rules.yaml` silently keeps old values
  when the base changes. An overlay only ever changes what it names.
- **Typos fail loudly.** An overlay setting `damge:` would otherwise merge
  quietly, change nothing, and turn the whole experiment into a measurement of
  noise. Unknown keys are rejected at load.
- **It has its own hash.** The base and each overlay are hashed together, in
  order, so every replay records exactly which recipe produced it.

## Carrying this into training

When you train agents in v0.4 and beyond:

- **Hold out evaluation seeds.** Train on one seed range, evaluate on another,
  or the agent can overfit to the specific shops it saw.
- **Evaluate against fixed baselines.** `GreedyAgent` and `PositionalAgent` do
  not change, which makes them a ruler you can measure every checkpoint with.
  Self-play win rates alone drift, because the opponent improves too.
- **Log the interval, not just the mean.** A checkpoint that goes from 61% to
  63% on 100 seeds has not shown an improvement; the intervals overlap almost
  entirely.
- **Re-audit the environment** ([lesson 2](02-environment-bias.md)) whenever a
  trained agent does something surprising. Sometimes it has found a bug.

## Try it

```bash
python evaluate.py --agents positional greedy --seeds 300 --ablate configs/ablations/brawl.yaml
python evaluate.py --agents greedy greedy --seeds 500 --no-swap --ablate configs/ablations/sequential.yaml
python -m pytest tests/test_measurement.py -v
```
