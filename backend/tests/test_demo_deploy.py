"""Hosted demo: shared-password gate, fail-closed configuration, synthetic-only data, daily refresh."""

from __future__ import annotations

import base64
import csv
import datetime as dt
import shutil

import pytest
from sqlalchemy import text

from app import clock
from app.config import Settings, get_settings
from app.importer.validate import validate_package
from app.synthetic.generate import generate
from tests.conftest import ANA, NOW

PASSWORD = "correct-horse-battery-staple-42"
REMOTE_DB = "postgresql+psycopg://demo:secret@db.internal:5432/demo"


def basic(user: str, password: str) -> dict[str, str]:
    return {"Authorization": "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()}


@pytest.fixture
def gated(seeded, monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import create_app

    monkeypatch.setenv("DEMO_ACCESS_PASSWORD", PASSWORD)
    get_settings.cache_clear()
    try:
        yield TestClient(create_app())
    finally:
        monkeypatch.delenv("DEMO_ACCESS_PASSWORD")
        get_settings.cache_clear()


# ------------------------------------------------------------------ access gate


@pytest.mark.parametrize("path", ["/", "/customers", "/assets/index.js", "/api/meta", "/api/today", "/api/demo/users",
                                  "/api/docs", "/api/openapi.json", "/api/admin/config"])
def test_everything_requires_the_access_password(gated, path):
    r = gated.get(path, headers=ANA)  # a demo-user header alone is not enough
    assert r.status_code == 401
    assert r.headers["www-authenticate"].startswith("Basic realm=")
    assert "Ana" not in r.text


def test_wrong_or_malformed_credentials_are_rejected(gated):
    assert gated.get("/api/today", headers={**ANA, **basic("demo", "wrong")}).status_code == 401
    assert gated.get("/api/today", headers={**ANA, **basic("other", PASSWORD)}).status_code == 401
    assert gated.get("/api/today", headers={**ANA, "Authorization": "Basic !!!notbase64"}).status_code == 401
    assert gated.post("/api/actions", headers=ANA, json={}).status_code == 401


def test_correct_password_opens_ui_and_api(gated):
    auth = basic("demo", PASSWORD)
    assert gated.get("/api/today", headers={**ANA, **auth}).status_code == 200
    assert gated.get("/api/demo/users", headers=auth).status_code == 200
    # behind the gate the app's own scoping still applies
    assert gated.get("/api/team", headers={**ANA, **auth}).status_code == 403


def test_health_check_is_open_and_returns_no_data(gated):
    r = gated.get("/healthz")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_repeated_wrong_passwords_are_throttled(gated):
    bad = basic("demo", "guess")
    codes = [gated.get("/api/meta", headers=bad).status_code for _ in range(21)]
    assert codes[:20] == [401] * 20 and codes[20] == 429
    # even the right password is refused from that client until the window passes
    assert gated.get("/api/meta", headers=basic("demo", PASSWORD)).status_code == 429


def test_responses_are_not_indexed(gated):
    assert gated.get("/healthz").headers["x-robots-tag"] == "noindex, nofollow"


# ------------------------------------------------------------------ fail-closed demo configuration


def demo_settings(**kw) -> Settings:
    base = {"app_env": "demo", "auth_mode": "demo", "database_url": REMOTE_DB, "demo_access_password": PASSWORD}
    return Settings(**{**base, **kw})


def test_valid_demo_configuration_starts():
    assert demo_settings().startup_problems() == []


@pytest.mark.parametrize("kw,fragment", [
    ({"demo_access_password": ""}, "DEMO_ACCESS_PASSWORD"),
    ({"demo_access_password": "short"}, "DEMO_ACCESS_PASSWORD"),
    ({"auth_mode": ""}, "AUTH_MODE=demo"),
    ({"ai_provider": "anthropic", "anthropic_api_key": "x"}, "AI_PROVIDER=none"),
    ({"allow_live_import": True}, "synthetic data only"),
    ({"import_inbox": "/data/inbox"}, "synthetic data only"),
    ({"database_url": "postgresql+psycopg://cac:cac_local_dev@localhost/cac"}, "local development"),
])
def test_unsafe_demo_configuration_refuses_to_start(kw, fragment):
    assert any(fragment in p for p in demo_settings(**kw).startup_problems())


def test_demo_password_cannot_be_combined_with_entra():
    s = Settings(auth_mode="entra", entra_tenant_id="t", entra_api_client_id="c", demo_access_password=PASSWORD)
    assert any("AUTH_MODE=entra" in p for p in s.startup_problems())


def test_platform_database_urls_use_the_psycopg_driver():
    assert Settings(database_url="postgres://u:p@h/db").database_url == "postgresql+psycopg://u:p@h/db"
    assert Settings(database_url="postgresql://u:p@h:5432/db").database_url == "postgresql+psycopg://u:p@h:5432/db"


# ------------------------------------------------------------------ synthetic data only


def test_hosted_demo_refuses_non_synthetic_packages(synthetic_package, tmp_path):
    folder, _ = synthetic_package
    pkg = tmp_path / "anon"
    shutil.copytree(folder, pkg)
    rows = list(csv.DictReader((pkg / "manifest.csv").open(encoding="utf-8")))
    with (pkg / "manifest.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows([{**r, "data_classification": "anonymised"} for r in rows])
    assert validate_package(pkg).ok  # allowed in a local prototype ...
    res = validate_package(pkg, synthetic_only=True)  # ... but not in the hosted demo
    assert not res.ok and any("synthetic data only" in p for p in res.fatal)


def test_synthetic_refresh_time_is_never_in_the_future(tmp_path):
    clock.freeze(dt.datetime(2026, 10, 17, 1, 30, tzinfo=clock.BUSINESS_TZ))  # just after midnight
    generate(tmp_path, dt.date(2026, 10, 17))
    for row in csv.DictReader((tmp_path / "manifest.csv").open(encoding="utf-8")):
        assert dt.datetime.fromisoformat(row["source_refreshed_at"]) <= clock.now()
    assert validate_package(tmp_path).ok


# ------------------------------------------------------------------ daily refresh


def test_demo_refresh_only_reseeds_stale_data(seeded):
    from app.services.demo import data_age_hours, demo_refresh

    assert demo_refresh(if_stale=True) == {"reseeded": False, "reason": "fresh", "age_hours": 3.0}
    clock.freeze(NOW + dt.timedelta(hours=24))
    result = demo_refresh(if_stale=True)
    assert result["reseeded"] is True and result["previous_age_hours"] == 27.0
    assert data_age_hours() < 24  # regenerated for the new day


def test_demo_refresh_skips_while_another_process_holds_the_lock(seeded):
    from app.db import get_engine
    from app.services.demo import LOCK_KEY, demo_refresh

    with get_engine().connect() as other:
        assert other.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": LOCK_KEY}).scalar()
        try:
            assert demo_refresh(if_stale=False)["reason"] == "another process is reseeding"
        finally:
            other.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": LOCK_KEY})
