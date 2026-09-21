"""Loading and hashing of ``rules.yaml``.

The YAML file is the single source of truth for game parameters. Nothing in
``engine/`` hardcodes a value that appears there; this module is the only door
between the file and the rest of the engine.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

DEFAULT_RULES_PATH = Path(__file__).resolve().parent.parent / "rules.yaml"


class ConfigError(ValueError):
    """Raised when rules.yaml is internally inconsistent."""


@dataclass(frozen=True)
class Config:
    """Parsed ``rules.yaml`` plus the hash that identifies it in a replay."""

    raw: Mapping[str, Any]
    config_hash: str

    # -- sections -----------------------------------------------------------
    @property
    def version(self) -> str:
        return str(self.raw["version"])

    @property
    def match(self) -> Mapping[str, Any]:
        return self.raw["match"]

    @property
    def economy(self) -> Mapping[str, Any]:
        return self.raw["economy"]

    @property
    def planning(self) -> Mapping[str, Any]:
        return self.raw["planning"]

    @property
    def shop(self) -> Mapping[str, Any]:
        return self.raw["shop"]

    @property
    def pool(self) -> Mapping[str, Any]:
        return self.raw["pool"]

    @property
    def level(self) -> Mapping[str, Any]:
        return self.raw["level"]

    @property
    def board(self) -> Mapping[str, Any]:
        return self.raw["board"]

    @property
    def combat(self) -> Mapping[str, Any]:
        return self.raw["combat"]

    @property
    def damage(self) -> Mapping[str, Any]:
        return self.raw["damage"]

    @property
    def traits(self) -> Mapping[str, Any]:
        return self.raw["traits"]

    @property
    def units(self) -> list[Mapping[str, Any]]:
        return self.raw["units"]

    @property
    def purchase_when_board_full(self) -> str:
        return self.raw["purchase_when_board_full"]

    # -- derived lookups ----------------------------------------------------
    def tier_odds(self, level: int) -> list[float]:
        return self.shop["tier_odds"][level]

    def board_size(self, level: int) -> int:
        return self.level["board_size_by_level"][level]

    def level_cost(self, level: int) -> int | None:
        """Gold to go from ``level`` to ``level + 1``; None at max level."""
        return self.level["buy_cost"].get(level)

    def unit_cost(self, tier: int) -> int:
        return self.economy["cost_by_tier"][tier]

    def copies_for_tier(self, tier: int) -> int:
        return self.pool["copies_by_tier"][tier]


# Every enumerated option the engine understands. An option that is spelled
# right but not implemented yet is absent here on purpose: it should fail when
# the file loads, not twenty rounds into a sweep.
ALLOWED_OPTIONS: dict[tuple[str, str], tuple[Any, ...]] = {
    ("combat", "resolution"): ("simultaneous", "sequential"),
    ("combat", "move_conflict"): ("random", "lowest_id"),
    ("combat", "target_rule"): ("nearest", "lowest_health"),
    ("combat", "target_tiebreak"): ("lowest_id",),
    ("combat", "move_metric"): ("chebyshev", "manhattan"),
    ("combat", "timeout_result"): ("most_total_health",),
    ("damage", "formula"): ("flat_plus_survivors", "flat_plus_tiers"),
    ("economy", "sell_refund"): ("full", "half"),
    ("board", "positioning"): (True, False),
}
ALLOWED_TOP_LEVEL: dict[str, tuple[Any, ...]] = {
    "purchase_when_board_full": ("block",),
}


def _validate(raw: Mapping[str, Any]) -> None:
    """Fail loudly on config that would silently produce nonsense."""
    if not isinstance(raw.get("version"), str):
        raise ConfigError(
            "version must be a quoted string such as \"0.2\"; "
            f"got {raw.get('version')!r}. Unquoted, YAML reads 0.10 as 0.1."
        )

    if raw["match"]["players"] != 2:
        raise ConfigError("the engine supports exactly 2 players: combat is two "
                          "mirrored halves and damage goes to 'the other' player")

    for (section, key), allowed in ALLOWED_OPTIONS.items():
        value = raw[section][key]
        if value not in allowed:
            raise ConfigError(f"{section}.{key} = {value!r} is not supported; "
                              f"expected one of {list(allowed)}")
    for key, allowed in ALLOWED_TOP_LEVEL.items():
        if raw[key] not in allowed:
            raise ConfigError(f"{key} = {raw[key]!r} is not supported; "
                              f"expected one of {list(allowed)}")

    for level, row in raw["shop"]["tier_odds"].items():
        total = sum(row)
        if abs(total - 1.0) > 1e-9:
            raise ConfigError(f"tier_odds[{level}] sums to {total}, expected 1.0")

    tiers = {int(u["tier"]) for u in raw["units"]}
    for tier in sorted(tiers):
        if tier not in raw["pool"]["copies_by_tier"]:
            raise ConfigError(f"no pool copies configured for tier {tier}")
        if tier not in raw["economy"]["cost_by_tier"]:
            raise ConfigError(f"no unit cost configured for tier {tier}")

    ids = [u["id"] for u in raw["units"]]
    if len(ids) != len(set(ids)):
        raise ConfigError("duplicate unit id in units")

    trait_names = set(raw["traits"])
    for unit in raw["units"]:
        if unit["trait"] not in trait_names:
            raise ConfigError(f"unit {unit['id']} has unknown trait {unit['trait']}")

    start = raw["level"]["starting"]
    top = raw["level"]["max"]
    for level in range(start, top + 1):
        if level not in raw["level"]["board_size_by_level"]:
            raise ConfigError(f"no board size configured for level {level}")
        if level not in raw["shop"]["tier_odds"]:
            raise ConfigError(f"no tier odds configured for level {level}")

    width = raw["board"]["width"]
    height = raw["board"]["height"]
    if raw["level"]["board_size_by_level"][top] > width * height:
        raise ConfigError("max board size exceeds the squares available")


def canonical_bytes(data: bytes) -> bytes:
    """The bytes a config hash is taken over: the file with LF line endings.

    Git on Windows rewrites LF as CRLF on checkout by default, which would give
    one file two hashes depending on the machine - and orphan every replay
    recorded on the other one. Normalising first makes the hash a property of
    the content, not the platform. (.gitattributes also pins LF, belt and
    braces.)
    """
    return data.replace(b"\r\n", b"\n")


def _merge_overlay(base: Any, overlay: Any, where: str) -> Any:
    """Deep-merge an overlay onto the base. Mappings merge; anything else,
    lists included, is replaced wholesale.

    A string key the base does not have is rejected. An overlay that says
    ``damge:`` instead of ``damage:`` would otherwise merge silently, change
    nothing, and turn an ablation into a measurement of pure noise. Integer
    keys may be new, so an overlay can add a level or a tier.
    """
    if not (isinstance(base, Mapping) and isinstance(overlay, Mapping)):
        return overlay
    merged = dict(base)
    for key, value in overlay.items():
        if key not in base:
            if isinstance(key, str):
                raise ConfigError(f"overlay sets {where}{key}, which the base "
                                  "ruleset does not have - a typo?")
            merged[key] = value
        else:
            merged[key] = _merge_overlay(base[key], value, f"{where}{key}.")
    return merged


def load_config(path: str | Path = DEFAULT_RULES_PATH,
                overlays: tuple[str | Path, ...] = ()) -> Config:
    """Read, validate, and hash the ruleset, optionally with overlays.

    An overlay is a small YAML file holding only the keys it changes, merged
    onto the base in order. It is how ablations are written: one reviewable
    diff that cannot drift out of date as the base ruleset evolves.

    With no overlays, ``config_hash`` is the SHA-256 of the base file, exactly
    as the spec defines it. With overlays, it hashes the base and each overlay,
    each framed by its length so that no two combinations can collide. Any
    edit to any of those files - a comment included - makes a new hash, and so
    a new replay lineage. Line endings do not.
    """
    base = canonical_bytes(Path(path).read_bytes())
    raw = yaml.safe_load(base.decode("utf-8"))
    if not overlays:
        _validate(raw)
        return Config(raw=raw, config_hash=hashlib.sha256(base).hexdigest())

    parts = [base] + [canonical_bytes(Path(o).read_bytes()) for o in overlays]
    digest = hashlib.sha256()
    for part in parts:
        digest.update(len(part).to_bytes(8, "big"))
        digest.update(part)
    for part in parts[1:]:
        raw = _merge_overlay(raw, yaml.safe_load(part.decode("utf-8")) or {}, "")
    _validate(raw)
    return Config(raw=raw, config_hash=digest.hexdigest())
