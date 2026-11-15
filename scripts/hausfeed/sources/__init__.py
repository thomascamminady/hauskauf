"""Portal adapters. Add a new portal by implementing ``hausfeed.core.Source`` and listing it in ``ALL``."""

from __future__ import annotations

from hausfeed.core import Source
from hausfeed.sources.immowelt import Immowelt
from hausfeed.sources.kleinanzeigen import Kleinanzeigen
from hausfeed.sources.ohnemakler import OhneMakler

ALL: list[Source] = [Immowelt(), Kleinanzeigen(), OhneMakler()]


def by_name(names: list[str] | None = None) -> list[Source]:
    if not names:
        return ALL
    return [s for s in ALL if s.name in names]
