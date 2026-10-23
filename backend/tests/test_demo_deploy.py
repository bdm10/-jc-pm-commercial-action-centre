"""Hosted demo: login gate, fail-closed configuration, synthetic-only data, daily refresh."""

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
USER = "demo-presenter"
REMOTE_DB = "postgresql+psycopg://demo:secret@db.internal:5432/demo"
HTML = {"Accept": "text/html,application/xhtml+xml"}


def basic(user: str, password: str) -> dict[str, str]:
    return {"Authorization": "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()}


def make_gated_client(monkeypatch, password: str = PASSWORD, secret: str = "session-secret-for-tests"):
    from fastapi.testclient import TestClient

    from app.main import create_app

    monkeypatch.setenv("DEMO_ACCESS_USER", USER)
    monkeypatch.setenv("DEMO_ACCESS_PASSWORD", password)
    monkeypatch.setenv("SESSION_SECRET", secret)
    get_settings.cache_clear()
    return TestClient(create_app(), follow_redirects=False)


@pytest.fixture
def gated(seeded, monkeypatch):
    try:
        yield make_gated_client(monkeypatch)
    finally:
        for k in ("DEMO_ACCESS_USER", "DEMO_ACCESS_PASSWORD", "SESSION_SECRET"):
            monkeypatch.delenv(k, raising=False)
        get_settings.cache_clear()


def login(client, user: str = USER, password: str = PASSWORD, next_path: str = "/"):
    return client.post("/login", data={"username": user, "password": password, "next": next_path})


# ------------------------------------------------------------------ login gate


@pytest.mark.parametrize("path", ["/api/meta", "/api/today", "/api/demo/users", "/api/admin/config", "/api/docs",
                                  "/assets/index.js"])
def test_api_and_assets_require_login(gated, path):
    r = gated.get(path, headers=ANA)  # a demo-user header alone is not enough
    assert r.status_code == 401 and r.json() == {"error": {"code": "login_required"}}
    assert "www-authenticate" not in r.headers  # never trigger the browser's own password prompt


@pytest.mark.parametrize("path", ["/", "/customers", "/customers/JC/SYN-JC-10236?x=1", "/team"])
def test_pages_redirect_to_the_login_page_and_keep_the_destination(gated, path):
    r = gated.get(path, headers=HTML)
    assert r.status_code == 303
    assert r.headers["location"].startswith("/login?next=")
    from urllib.parse import unquote

    assert unquote(r.headers["location"].split("next=", 1)[1]) == path


def test_login_page_is_self_contained_and_shows_no_app_data(gated):
    r = gated.get("/login?next=/customers", headers=HTML)
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    assert 'name="password"' in r.text and 'value="/customers"' in r.text
    assert "Ana" not in r.text and "SYN-" not in r.text
    assert "default-src 'none'" in r.headers["content-security-policy"]


def test_wrong_credentials_are_rejected(gated):
    for user, password in ((USER, "wrong"), ("other", PASSWORD), ("", "")):
        r = login(gated, user, password)
        assert r.status_code == 401 and "incorrectos" in r.text and "set-cookie" not in r.headers
    assert gated.get("/api/today", headers={**ANA, **basic(USER, "wrong")}).status_code == 401
    assert gated.get("/api/today", headers={**ANA, "Authorization": "Basic !!!notbase64"}).status_code == 401
    assert gated.post("/api/actions", headers=ANA, json={}).status_code == 401


def test_login_sets_a_session_that_opens_ui_and_api(gated):
    r = login(gated, next_path="/customers/JC/SYN-JC-10236")
    assert r.status_code == 303 and r.headers["location"] == "/customers/JC/SYN-JC-10236"
    cookie = r.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=Lax" in cookie and "cac_session=" in cookie
    assert gated.get("/api/today", headers=ANA).status_code == 200
    assert gated.get("/api/demo/users").status_code == 200
    assert gated.get("/api/team", headers=ANA).status_code == 403  # the app's own scoping still applies behind the gate
    assert gated.get("/login", headers=HTML).status_code == 303  # already signed in


def test_spa_routes_fall_back_to_index_after_login(gated):
    from pathlib import Path

    from app.config import get_settings as gs

    dist = (Path(__file__).resolve().parent.parent / gs().frontend_dist).resolve()
    if not (dist / "index.html").exists():
        pytest.skip("frontend not built")
    login(gated)
    for path in ("/", "/customers", "/customers/JC/SYN-JC-10236", "/follow-ups", "/team"):
        r = gated.get(path, headers=HTML)
        assert r.status_code == 200 and '<div id="root">' in r.text, path


def test_logout_ends_the_session(gated):
    login(gated)
    assert gated.get("/api/meta").status_code == 200
    r = gated.get("/logout")
    assert r.status_code == 303 and r.headers["location"] == "/login" and "Max-Age=0" in r.headers["set-cookie"]
    assert gated.get("/api/meta").status_code == 401


def test_tampered_or_foreign_session_cookies_are_rejected(gated, monkeypatch):
    login(gated)
    token = gated.cookies.get("cac_session")
    version, expiry, sig = token.split(".")
    for forged in (f"{version}.{int(expiry) + 10**6}.{sig}",  # extended expiry without the key
                   "v1.9999999999.deadbeef", "", "garbage"):
        gated.cookies.clear()
        gated.cookies.set("cac_session", forged)
        assert gated.get("/api/meta").status_code == 401, forged
    gated.cookies.clear()
    gated.cookies.set("cac_session", token)  # the genuine token still works
    assert gated.get("/api/meta").status_code == 200


def test_changing_the_password_signs_everyone_out(gated, monkeypatch):
    login(gated)
    token = gated.cookies.get("cac_session")
    assert gated.get("/api/meta").status_code == 200
    other = make_gated_client(monkeypatch, password=PASSWORD + "-rotated")
    other.cookies.set("cac_session", token)
    assert other.get("/api/meta").status_code == 401


def test_session_expires(gated, monkeypatch):
    import app.access_gate as gate

    login(gated)
    real = gate.time.time
    monkeypatch.setattr(gate.time, "time", lambda: real() + 13 * 3600)
    assert gated.get("/api/meta").status_code == 401


@pytest.mark.parametrize("target", ["https://evil.example/x", "//evil.example", "/\\evil.example", "javascript:alert(1)", "/logout"])
def test_login_never_redirects_off_site(gated, target):
    r = login(gated, next_path=target)
    assert r.status_code == 303 and r.headers["location"] == "/"


def test_scripts_can_use_basic_credentials(gated):
    auth = basic(USER, PASSWORD)
    assert gated.get("/api/today", headers={**ANA, **auth}).status_code == 200


def test_health_check_is_open_and_returns_no_data(gated):
    r = gated.get("/healthz")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_repeated_wrong_passwords_are_throttled(gated):
    codes = [login(gated, password="guess").status_code for _ in range(21)]
    assert codes[:20] == [401] * 20 and codes[20] == 429
    assert login(gated).status_code == 429  # even the right password, until the window passes


def test_responses_are_not_indexed(gated):
    assert gated.get("/healthz").headers["x-robots-tag"] == "noindex, nofollow"


# ------------------------------------------------------------------ fail-closed demo configuration


def demo_settings(**kw) -> Settings:
    base = {"app_env": "demo", "auth_mode": "demo", "database_url": REMOTE_DB, "demo_access_password": PASSWORD,
            "demo_access_user": USER}
    return Settings(**{**base, **kw})


def test_valid_demo_configuration_starts():
    assert demo_settings().startup_problems() == []


@pytest.mark.parametrize("kw,fragment", [
    ({"demo_access_password": ""}, "DEMO_ACCESS_PASSWORD"),
    ({"demo_access_password": "short"}, "DEMO_ACCESS_PASSWORD"),
    ({"demo_access_user": ""}, "DEMO_ACCESS_USER"),
    ({"auth_mode": ""}, "AUTH_MODE=demo"),
    ({"ai_provider": "anthropic", "anthropic_api_key": "x"}, "AI_PROVIDER=none"),
    ({"allow_live_import": True}, "synthetic data only"),
    ({"import_inbox": "/data/inbox"}, "synthetic data only"),
    ({"database_url": "postgresql+psycopg://cac:cac_local_dev@localhost/cac"}, "local development"),
])
def test_unsafe_demo_configuration_refuses_to_start(kw, fragment):
    assert any(fragment in p for p in demo_settings(**kw).startup_problems())


def test_demo_password_cannot_be_combined_with_entra():
    s = Settings(auth_mode="entra", entra_tenant_id="t", entra_api_client_id="c", demo_access_password=PASSWORD,
                 demo_access_user=USER)
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
