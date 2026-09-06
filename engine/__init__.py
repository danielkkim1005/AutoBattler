"""Pure, headless autobattler engine.

Invariants enforced across this package:

* No printing, sleeping, wall-clock time, or rendering.
* All randomness flows through a ``random.Random`` passed in explicitly.
  There is no module-level ``random`` import anywhere under ``engine/``.
* All iteration over units is by sorted ``uid``. Sets are never iterated, and
  no outcome depends on ``dict`` insertion order.
* Templates are immutable; instances are mutable copies. ``max_health`` is
  written once at construction and never again.
"""

from engine.config import Config, load_config
from engine.events import Event, EventLog
from engine.replay import Replay

__all__ = ["Config", "load_config", "Event", "EventLog", "Replay"]
