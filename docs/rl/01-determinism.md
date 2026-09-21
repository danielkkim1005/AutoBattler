# 1. Determinism and random streams

*Introduced in v0.1 (the agent stream), v0.2 (per-round streams), and v0.3
(line-ending-proof config hashes).*

## Why an RL environment must be deterministic

Deterministic does not mean "no randomness". This game is full of it: every
shop is a draw. It means the randomness is a *function of the seed*, so the
same seed and the same actions always produce the same game.

RL needs that for four things:

- **Debugging.** When a policy does something baffling in episode 48,213, you
  need to replay that exact episode and step through it. A replay that plays
  out differently the second time is useless.
- **Regression testing.** If an engine change alters any outcome, a
  byte-for-byte comparison of replays catches it immediately.
- **Fair comparison.** To compare two policies, or two rulesets, you want them
  to face the *same* luck. Otherwise you are measuring luck.
- **Reproducibility.** A training result you cannot reproduce is an anecdote.

## What the engine guarantees

Same seed + same `config_hash` + same action sequence → byte-identical replay.
`tests/test_determinism.py` checks it three ways: the same seed played twice, a
recorded action list replayed through `replay_game`, and an AST scan proving
nothing under `engine/` calls the process-wide `random` module.

## Lesson: one random stream per decision-maker (v0.1)

Say the agents drew from the engine's rng. The random agent draws once per
decision to pick an action. Now replay that game from its recorded actions:
the agents are gone, so they make no draws, and the engine's stream sits in a
different place than it did live. The opening shops still match, because they
were rolled before anyone decided anything. From the first agent decision on,
every roll comes out differently, and the replay diverges.

So agents get their own stream (`AGENT_STREAM_SALT` in `engine/game.py`). The
general rule: **anything that will not be present at replay time must not draw
from a stream that will be.**

## Lesson: one stream per round, per purpose (v0.2)

v0.1 still had one engine stream for everything: shops, rerolls, and anything
combat might need. That couples things that should be independent:

```
v0.1:  seed ─► rng ─► shop R1 ─► reroll ─► shop R2 ─► reroll ─► reroll ─► shop R3 ...

v0.2:  seed ─► master ─┬─► round 1 seed ─┬─► shop stream    (shops, rerolls)
                       │                  └─► combat stream  (move conflicts)
                       ├─► round 2 seed ─┬─► shop stream
                       │                  └─► combat stream
                       └─► ...
```

In v0.1, one extra reroll in round 3 shifts every random number for the rest of
the game. Round 4 onward becomes a different game, not because the reroll
changed anything that matters but because it moved the stream along.

**Why that matters for RL: credit assignment.** When a policy learns whether
"reroll in round 3" was a good idea, it compares outcomes with and without it.
With coupled streams, that comparison is confounded by a completely new
sequence of luck for the rest of the game. The signal about the reroll drowns
in unrelated noise. With per-round streams, the reroll's consequences travel
only through game state — gold spent, units bought — which is exactly what you
want the policy to learn from.

In code: `round_streams()` in `engine/game.py` takes exactly one 64-bit draw
from the master stream per round, whatever happens that round. Two tests pin
this: `test_rerolls_do_not_shift_the_next_rounds_shops` and
`test_each_round_takes_exactly_one_draw_from_the_master_stream`.

## Common random numbers

Compare agent A against agent B on seeds 0–499, then compare A′ against B on
the same seeds. Because each round's randomness depends only on seed and round
number, both comparisons face the same shops for as long as the games stay
alike. Differences in outcome come from the change you made, not from luck.
Statisticians call this **common random numbers**. It is a variance-reduction
technique: fewer games are needed to detect a real difference.

It is only partial here. Shop draws are weighted by copies left in the pool, so
once two games buy different units, the same random number can pick a
different unit. The shared luck fades as games diverge. It is still strictly
better than no sharing, and it costs nothing.

## Pitfalls as the project grows

- **Never seed from `hash()` of a string.** Python salts string hashes per
  process (`PYTHONHASHSEED`), so `hash("shop")` differs between runs. The
  engine seeds with `random.Random(f"{round_seed}:shop")`, which runs the string
  through SHA-512 and is stable across processes and machines.
- **Never iterate a `set`.** Set order for strings depends on those same salted
  hashes. This is why the spec bans it and every unit loop goes through
  `sorted(...)`.
- **Hash content, not bytes on disk** (fixed in v0.3). `config_hash` was the
  SHA-256 of `rules.yaml`'s raw bytes, and git on Windows rewrites LF as CRLF on
  checkout. The same ruleset hashed `d3699bd1…` with LF and `cfac4cdb…` with
  CRLF, so a `git checkout` — or a friend on another OS — would have orphaned
  every recorded replay. Now line endings are normalised before hashing, and
  `.gitattributes` pins LF as well. The general lesson: an identity hash must
  be a function of *meaning*, and everything that is not meaning has to be
  normalised away first.
- **Parallel rollouts.** When you run many environments at once for training,
  give each its own seed. Never share one `random.Random` across processes.
- **Your network is a separate problem.** GPU training is often
  nondeterministic even with fixed seeds. That is a property of the learner,
  not the environment; keep the environment deterministic regardless, so at
  least that half is solid.

## Try it

```bash
python -m pytest tests/test_determinism.py tests/test_fair_combat.py -k "stream or seed or replay or shift" -v
```
