"""The single source of the release version.

Versions are MAJOR.MINOR (see docs/VERSIONING.md). Every replay records this
string, so any replay can be traced back to the release that produced it.
rules.yaml carries the same string; a test fails if the two drift apart.
"""

__version__ = "0.2"
