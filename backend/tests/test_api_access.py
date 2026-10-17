"""Authentication (fail closed) and access isolation between salespeople and teams."""

from __future__ import annotations

import datetime as dt
import uuid

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import select

from app.auth.entra import TokenError, validate_token
from app.config import Settings, get_settings
from app.models.records import AuditLog, FollowUp
from tests.conftest import ADMIN, ANA, DAVID, ELENA, JORDI, PABLO


def first_customer(client, headers) -> tuple[str, str]:
    item = client.get("/api/customers", headers=headers).json()["items"][0]
    return item["source_entity"], item["source_customer_id"]


# ------------------------------------------------------------------ fail closed


def test_requests_without_identity_are_rejected(client):
    assert client.get("/api/today").status_code == 401
    assert client.get("/api/today", headers={"X-Demo-User": "nobody@example.com"}).status_code == 401
    assert client.get("/api/meta").status_code == 200  # public bootstrap info, no customer data


def test_unset_auth_mode_fails_closed(seeded, monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import create_app

    monkeypatch.setenv("AUTH_MODE", "")
    get_settings.cache_clear()
    try:
        c = TestClient(create_app())
        r = c.get("/api/today", headers=ANA)
        assert r.status_code == 401 and r.json()["error"]["code"] == "auth_not_configured"
    finally:
        monkeypatch.setenv("AUTH_MODE", "demo")
        get_settings.cache_clear()


def test_production_refuses_demo_mode_and_missing_auth():
    assert any("AUTH_MODE=entra" in p for p in Settings(app_env="production", auth_mode="demo").startup_problems())
    assert any("AUTH_MODE=entra" in p for p in Settings(app_env="production", auth_mode="").startup_problems())
    assert Settings(app_env="production", auth_mode="demo").demo_mode is False


def test_production_app_will_not_start_in_demo_mode(monkeypatch):
    from app.main import create_app

    monkeypatch.setenv("APP_ENV", "production")
    get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="Unsafe configuration"):
            create_app()
    finally:
        monkeypatch.setenv("APP_ENV", "test")
        get_settings.cache_clear()


# ------------------------------------------------------------------ Entra token validation (scaffold)

TENANT, API = "11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def token(**overrides) -> str:
    now = dt.datetime.now(dt.UTC)
    claims = {"iss": f"https://login.microsoftonline.com/{TENANT}/v2.0", "aud": API, "tid": TENANT, "oid": "oid-1",
              "iat": now, "exp": now + dt.timedelta(minutes=30), "scp": "access_as_user"}
    claims.update(overrides)
    return jwt.encode(claims, KEY, algorithm="RS256")


ENTRA = Settings(auth_mode="entra", entra_tenant_id=TENANT, entra_api_client_id=API, entra_api_scope=f"api://{API}/access_as_user")


def test_entra_valid_token_accepted():
    assert validate_token(token(), ENTRA, signing_key=KEY.public_key()).object_id == "oid-1"


@pytest.mark.parametrize("claims", [
    {"aud": "someone-else"},
    {"tid": "33333333-3333-3333-3333-333333333333"},
    {"exp": dt.datetime.now(dt.UTC) - dt.timedelta(minutes=1)},
    {"scp": "other_scope"},
    {"iss": "https://evil.example.com/v2.0"},
])
def test_entra_bad_tokens_rejected(claims):
    with pytest.raises(TokenError):
        validate_token(token(**claims), ENTRA, signing_key=KEY.public_key())


def test_entra_token_signed_by_other_key_rejected():
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(TokenError):
        validate_token(token(), ENTRA, signing_key=other.public_key())


# ------------------------------------------------------------------ isolation


def test_salesperson_sees_only_assigned_customers(client):
    ana = client.get("/api/customers?limit=200", headers=ANA).json()
    jordi = client.get("/api/customers?limit=200", headers=JORDI).json()
    a = {(i["source_entity"], i["source_customer_id"]) for i in ana["items"]}
    j = {(i["source_entity"], i["source_customer_id"]) for i in jordi["items"]}
    assert a and j and not (a & j)
    assert all(i["assignee"]["display_name"] == "Ana Ruiz" for i in ana["items"])


def test_cross_salesperson_access_is_not_disclosed(client):
    ent, cid = first_customer(client, DAVID)
    assert client.get(f"/api/customers/{ent}/{cid}", headers=ANA).status_code == 404
    body = {"client_request_id": uuid.uuid4().hex, "source_entity": ent, "source_customer_id": cid, "action_type": "contacted"}
    assert client.post("/api/actions", json=body, headers=ANA).status_code == 404
    assert client.post(f"/api/customers/{ent}/{cid}/ai-talking-points", json={}, headers=ANA).status_code == 404
    opp = next(i for i in client.get("/api/customers?with_opportunity=true", headers=DAVID).json()["items"])["opportunities"][0]
    assert client.post(f"/api/opportunities/{opp['id']}/snooze", json={"days": 7}, headers=ANA).status_code == 404
    assert client.post(f"/api/opportunities/{opp['id']}/dismiss", json={"reason_code": "already_handled"}, headers=ANA).status_code == 404


def test_managers_see_only_their_teams(client):
    ana_c, david_c = first_customer(client, ANA), first_customer(client, DAVID)
    assert client.get("/api/customers/{}/{}".format(*ana_c), headers=ELENA).status_code == 200
    assert client.get("/api/customers/{}/{}".format(*david_c), headers=ELENA).status_code == 404
    assert client.get("/api/customers/{}/{}".format(*david_c), headers=PABLO).status_code == 200
    assert client.get("/api/customers/{}/{}".format(*ana_c), headers=PABLO).status_code == 404
    team = client.get("/api/team", headers=ELENA).json()
    assert {m["display_name"] for m in team["members"]} == {"Ana Ruiz", "Jordi Puig", "Carmen Vidal", "Elena Martín"}


def test_role_gates(client):
    assert client.get("/api/team", headers=ANA).status_code == 403
    assert client.get("/api/follow-ups?view=team", headers=ANA).status_code == 404
    assert client.get("/api/admin/config", headers=ELENA).status_code == 403
    assert client.get("/api/admin/config", headers=ADMIN).status_code == 200


def test_today_is_scoped_and_deduplicated(client):
    t = client.get("/api/today", headers=ANA).json()
    assert 0 < len(t["cards"]) <= 5
    keys = [(c["customer"]["source_entity"], c["customer"]["source_customer_id"]) for c in t["cards"]]
    assert len(keys) == len(set(keys))
    assert all(c["assignee"]["display_name"] == "Ana Ruiz" for c in t["cards"])
    scores = [c["opportunity"]["priority_score"] for c in t["cards"]]
    assert scores == sorted(scores, reverse=True)


# ------------------------------------------------------------------ reassignment


def test_manager_reassigns_within_scope_only(client, seeded):
    db = seeded["db"]
    ent, cid = first_customer(client, ANA)
    users = {u["display_name"]: u["id"] for u in client.get("/api/team/assignments", headers=ELENA).json()["assignable_users"]}
    assert "David Serra" not in users  # other team
    david_id = seeded["users"]["david.serra@example.com"].id
    r = client.post("/api/assignments", json={"source_entity": ent, "source_customer_id": cid, "user_id": david_id}, headers=ELENA)
    assert r.status_code == 400 and r.json()["error"]["code"] == "assignee_not_in_scope"
    r = client.post("/api/assignments", json={"source_entity": ent, "source_customer_id": cid, "user_id": users["Jordi Puig"],
                                              "reason": "Cobertura vacaciones"}, headers=ELENA)
    assert r.status_code == 200
    assert client.get(f"/api/customers/{ent}/{cid}", headers=ANA).status_code == 404
    assert client.get(f"/api/customers/{ent}/{cid}", headers=JORDI).status_code == 200
    assert db.execute(select(AuditLog).where(AuditLog.action == "customer_reassigned")).scalars().first() is not None
    # managers cannot touch other teams' customers; salespeople cannot reassign at all
    d_ent, d_cid = first_customer(client, DAVID)
    assert client.post("/api/assignments", json={"source_entity": d_ent, "source_customer_id": d_cid, "user_id": users["Jordi Puig"]},
                       headers=ELENA).status_code == 404
    assert client.post("/api/assignments", json={"source_entity": ent, "source_customer_id": cid, "user_id": users["Ana Ruiz"]},
                       headers=JORDI).status_code == 403


def test_reassignment_moves_open_follow_ups(client, seeded):
    db = seeded["db"]
    ent, cid = first_customer(client, ANA)
    client.post("/api/actions", headers=ANA, json={"client_request_id": uuid.uuid4().hex, "source_entity": ent, "source_customer_id": cid,
                                                     "action_type": "contacted", "follow_up_date": "2026-10-20"})
    jordi_id = seeded["users"]["jordi.puig@example.com"].id
    client.post("/api/assignments", json={"source_entity": ent, "source_customer_id": cid, "user_id": jordi_id}, headers=ELENA)
    fu = db.execute(select(FollowUp).where(FollowUp.source_customer_id == cid, FollowUp.status == "open")).scalar_one()
    db.refresh(fu)
    assert fu.owner_user_id == jordi_id
