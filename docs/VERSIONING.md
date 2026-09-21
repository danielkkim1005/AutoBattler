# Versioning

## The scheme: `MAJOR.MINOR`

Releases are numbered `v0.1`, `v0.2`, … `v1.0`. There is no third "patch"
number: every release is a deliberate, themed step, and small fixes ride along
with the next one.

- **`0.x`** — pre-release. Anything may change between minors, including
  replay compatibility, the rules, and the agent API.
- **`v1.0`** — the first release your friends can play: a working UI, a
  balanced ruleset, and a stable replay format.
- **After `1.0`** — bump `MAJOR` for anything that breaks old replays, configs,
  or agents; bump `MINOR` for everything else.

If a patch number is ever needed, say a hotfix that changes no behaviour,
`0.3.1` sorts correctly after `0.3`, so adding one later breaks nothing.

## Where the version lives

| Place | Role |
| --- | --- |
| `engine/version.py` | The single source: `__version__ = "0.2"`. |
| `rules.yaml` → `version` | The ruleset shipped with the release. Must match; `test_rules_version_matches_the_engine_release` fails if they drift. Quoted on purpose — unquoted, YAML reads `0.10` as the float `0.1`. |
| Replay header → `version` | Stamped from `engine/version.py` on every replay, so any replay names the release that produced it. |
| Git tag `vX.Y` | An annotated tag on the release commit, carrying the release title. |
| `CHANGELOG.md` | One section per release: what changed, and why it matters for RL. |

A replay reproduces byte-for-byte only on the release that made it, with the
same `config_hash`. To re-run an old one:

```bash
git checkout v0.1
```

## Releasing

1. Bump `engine/version.py` and `rules.yaml` together.
2. Add the `CHANGELOG.md` section, including RL notes and anything you measured.
3. Run the suite: `python -m pytest tests/ -q`.
4. Commit with Conventional Commits — `feat`, `fix`, `docs`, and `!` plus a
   `BREAKING CHANGE:` footer when old replays stop reproducing.
5. Tag it: `git tag -a v0.2 -m "v0.2 — Fair fights"`.

## Release history

| Version | Title | One line |
| --- | --- | --- |
| `v0.1` | Headless engine | Round loop, shop, pool, traits, grid combat, byte-identical replays. Files say `0.1.0`, from before this scheme. |
| `v0.2` | Fair fights | Simultaneous tick resolution removes a measured seat bias; per-round random streams; spawn events. |
| `v0.3` | Trustworthy experiments | Seat-swapped evaluation with intervals, config overlays, a positioning agent and its brawl control; line-ending-proof config hashes. |
| `v0.4` | RL-ready | Leak-free observations; a gym-style environment with masks, a 371-float observation, and safe shaping. |

The proposed path from here to `v1.0` is in [ROADMAP.md](../ROADMAP.md).
