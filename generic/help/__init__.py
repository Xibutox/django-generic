"""The help page: what this installation is, and what changed in it.

Both read files the project already keeps - its LICENSE and its
CHANGELOG - rather than asking for the same thing to be written twice.
"""

from generic.help.changelog import Release, Section, parse, read
from generic.help.sources import changelogs, licence

__all__ = [
    "Release",
    "Section",
    "changelogs",
    "licence",
    "parse",
    "read",
]
