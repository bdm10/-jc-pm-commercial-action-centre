"""Test setup: a dedicated PostgreSQL database (TEST_DATABASE_URL), migrations applied once,
clock frozen at 2026-10-17 09:00 Europe/Madrid, synthetic package generated once per session."""

from __future__ import annotations

import datetime as dt
import os

os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", "postgresql+psycopg://cac:cac_local_dev@localhost:5432/cac_test")
os.environ["APP_ENV"] = "test"
os.environ["AUTH_MODE"] = "demo"
os.environ["AI_PROVIDER"] = "none"

import pytest  # noqa: E402
from alembic import command  # noqa: E402

from app import clock  # noqa: E402
from app.cli import _alembic_cfg  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import get_engine, session_factory  # noqa: E402

AS_OF = dt.date(2026, 10, 17)
NOW = dt.datetime(2026, 10, 17, 9, 0, tzinfo=clock.BUSINESS_TZ)


@pytest.fixture(scope="session", autouse=True)
def _migrated():
    get_settings.cache_clear()
    get_engine.cache_clear()
    cfg = _alembic_cfg()
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    yield


@pytest.fixture(autouse=True)
def frozen_clock():
    clock.freeze(NOW)
    yield NOW
    clock.freeze(None)


@pytest.fixture
def db():
    from app.synthetic.demo_seed import reset_all

    s = session_factory()()
    reset_all(s)
    yield s
    s.close()


@pytest.fixture(scope="session")
def synthetic_package(tmp_path_factory):
    from app.synthetic.generate import generate

    clock.freeze(NOW)
    out = tmp_path_factory.mktemp("synthetic")
    summary, gen = generate(out, AS_OF)
    return out, gen


@pytest.fixture
def seeded(db, synthetic_package):
    """Synthetic facts imported and refreshed, demo users, no action history."""
    from app.importer.load import import_package
    from app.services.refresh import run_refresh
    from app.synthetic.demo_seed import seed_users

    folder, gen = synthetic_package
    users = seed_users(db)
    res, run = import_package(db, folder, force=True)
    assert res.ok, res.fatal
    run_refresh(db)
    return {"db": db, "users": users, "gen": gen, "folder": folder}


@pytest.fixture
def seeded_history(seeded):
    from app.services.refresh import run_refresh
    from app.synthetic.demo_seed import seed_history

    seed_history(seeded["db"], seeded["users"], seeded["gen"])
    run_refresh(seeded["db"])
    return seeded


@pytest.fixture
def client(seeded):
    from fastapi.testclient import TestClient

    from app.main import create_app

    return TestClient(create_app())


def as_user(email: str) -> dict[str, str]:
    return {"X-Demo-User": email}


ANA = as_user("ana.ruiz@example.com")
JORDI = as_user("jordi.puig@example.com")
DAVID = as_user("david.serra@example.com")
ELENA = as_user("elena.martin@example.com")  # manager, Equipo Piloto (Ana, Jordi, Carmen)
PABLO = as_user("pablo.ferrer@example.com")  # manager, Equipo B (David, Lucía)
ADMIN = as_user("admin@example.com")
