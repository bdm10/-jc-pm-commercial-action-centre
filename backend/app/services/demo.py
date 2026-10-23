"""Hosted-demo housekeeping: keep the synthetic data fresh.

Synthetic data is anchored to the day it is generated. Left alone, it would
cross the stale-data cutoff after two days and the demo would hide every
recommendation. In APP_ENV=demo the app therefore regenerates the synthetic
demo (data, users and sample history) once the data is older than
DEMO_RESEED_AFTER_HOURS: at start-up and on a background timer. Actions
recorded during a demo are cleared at that point.

A PostgreSQL advisory lock ensures only one process reseeds at a time.
"""

from __future__ import annotations

import datetime as dt
import logging
import tempfile
import threading
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, text

from app import clock
from app.config import get_settings
from app.db import get_engine, session_factory
from app.models import facts as F
from app.models.records import AppUser

log = logging.getLogger("cac.demo")
LOCK_KEY = 74_210_931  # arbitrary, app-specific advisory-lock key
CHECK_EVERY_SECONDS = 15 * 60


def data_age_hours() -> float | None:
    """Hours since the newest source refresh, or None if the demo has never been seeded."""
    with session_factory()() as db:
        if not db.execute(select(func.count()).select_from(AppUser)).scalar_one():
            return None
        newest = db.execute(select(func.max(F.SourceRefresh.source_refreshed_at))).scalar_one()
    if newest is None:
        return None
    return (clock.now() - newest).total_seconds() / 3600


def demo_refresh(if_stale: bool = True) -> dict[str, Any]:
    """Regenerate the synthetic demo if it is missing or older than the configured age."""
    from app.synthetic.demo_seed import seed_demo

    threshold = get_settings().demo_reseed_after_hours
    with get_engine().connect() as conn:
        if not conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": LOCK_KEY}).scalar():
            return {"reseeded": False, "reason": "another process is reseeding"}
        try:
            age = data_age_hours()
            if if_stale and age is not None and age < threshold:
                return {"reseeded": False, "reason": "fresh", "age_hours": round(age, 1)}
            with tempfile.TemporaryDirectory(prefix="cac-synthetic-") as folder:
                result = seed_demo(Path(folder))
            log.info("demo data regenerated (previous age: %s h)", None if age is None else round(age, 1))
            return {"reseeded": True, "previous_age_hours": None if age is None else round(age, 1),
                    "opportunities": result["refresh_after_history"]}
        finally:
            conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": LOCK_KEY})
            conn.commit()


def start_demo_refresher() -> threading.Event:
    """Background timer for long-running demos. Returns an event that stops it."""
    stop = threading.Event()

    def loop() -> None:
        while not stop.wait(CHECK_EVERY_SECONDS):
            try:
                result = demo_refresh(if_stale=True)
                if result.get("reseeded"):
                    log.info("scheduled demo refresh at %s: %s", dt.datetime.now(clock.BUSINESS_TZ).isoformat(), result)
            except Exception:  # keep the timer alive; the next tick retries
                log.exception("scheduled demo refresh failed")

    threading.Thread(target=loop, name="demo-refresher", daemon=True).start()
    return stop
