"""Single source of 'now' so tests and demos can control time."""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

BUSINESS_TZ = ZoneInfo("Europe/Madrid")

_frozen: dt.datetime | None = None


def now() -> dt.datetime:
    return _frozen if _frozen is not None else dt.datetime.now(dt.UTC)


def today() -> dt.date:
    """Business date in Madrid."""
    return now().astimezone(BUSINESS_TZ).date()


def freeze(at: dt.datetime | None) -> None:
    """Freeze the clock (tests only). Pass None to unfreeze."""
    global _frozen
    if at is not None and at.tzinfo is None:
        raise ValueError("freeze() needs a timezone-aware datetime")
    _frozen = at
