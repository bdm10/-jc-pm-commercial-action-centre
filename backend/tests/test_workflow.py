"""Persistent actions, follow-ups, snooze/dismiss and audit history."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from app.models.records import Activity, AuditLog, FollowUp, Opportunity
from tests.conftest import ADMIN, ANA


def top_card(client):
    return client.get("/api/today", headers=ANA).json()["cards"][0]


def action(card, **kw):
    c = card["customer"]
    return {"client_request_id": uuid.uuid4().hex, "source_entity": c["source_entity"], "source_customer_id": c["source_customer_id"],
            "opportunity_id": card["opportunity"]["id"], "action_type": "contacted", **kw}


def test_record_action_with_follow_up_persists_and_leaves_today(client, seeded):
    db = seeded["db"]
    card = top_card(client)
    r = client.post("/api/actions", headers=ANA, json=action(card, note="Hablar con el encargado el lunes", follow_up_date="2026-10-21"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["opportunity_status"] == "in_progress" and body["follow_up"]["due_date"] == "2026-10-21"
    act = db.get(Activity, body["activity_id"])
    assert act.note == "Hablar con el encargado el lunes" and act.action_type == "contacted"
    # action completed != outcome achieved: the opportunity is in progress, not resolved
    assert db.get(Opportunity, card["opportunity"]["id"]).status == "in_progress"
    ids = [c["opportunity"]["id"] for c in client.get("/api/today", headers=ANA).json()["cards"]]
    assert card["opportunity"]["id"] not in ids
    up = client.get("/api/follow-ups", headers=ANA).json()["upcoming"]
    assert any(f["customer"]["source_customer_id"] == card["customer"]["source_customer_id"] for f in up)
    assert db.execute(select(func.count()).select_from(AuditLog).where(AuditLog.action == "activity_recorded")).scalar_one() == 1


def test_duplicate_submission_is_idempotent(client, seeded):
    body = action(top_card(client))
    first = client.post("/api/actions", headers=ANA, json=body).json()
    second = client.post("/api/actions", headers=ANA, json=body).json()
    assert second["duplicate"] is True and second["activity_id"] == first["activity_id"]
    assert seeded["db"].execute(select(func.count()).select_from(Activity)).scalar_one() == 1


def test_next_action_completes_due_follow_up(client, seeded):
    db = seeded["db"]
    card = top_card(client)
    client.post("/api/actions", headers=ANA, json=action(card, action_type="no_response", follow_up_date="2026-10-17"))
    due = client.get("/api/today", headers=ANA).json()["follow_ups_due"]
    assert [f["customer"]["source_customer_id"] for f in due] == [card["customer"]["source_customer_id"]]
    # the customer appears once: as a follow-up, not also as a card
    assert all(c["customer"]["source_customer_id"] != card["customer"]["source_customer_id"]
               for c in client.get("/api/today", headers=ANA).json()["cards"])
    r = client.post("/api/actions", headers=ANA, json=action(card, action_type="meeting_booked"))
    assert r.json()["follow_ups_completed"]
    assert db.execute(select(func.count()).select_from(FollowUp).where(FollowUp.status == "open")).scalar_one() == 0


@pytest.mark.parametrize("patch,code", [
    ({"note": "x" * 281}, 422),
    ({"follow_up_date": "2026-10-01"}, 400),  # in the past
    ({"follow_up_date": "2027-12-01"}, 400),  # too far ahead
    ({"action_type": "sent_email"}, 422),  # not an allowed action type
])
def test_action_validation(client, patch, code):
    assert client.post("/api/actions", headers=ANA, json=action(top_card(client), **patch)).status_code == code


def test_not_relevant_dismisses_the_opportunity(client, seeded):
    card = top_card(client)
    client.post("/api/actions", headers=ANA, json=action(card, action_type="not_relevant", note="Cerrado por obras"))
    o = seeded["db"].get(Opportunity, card["opportunity"]["id"])
    assert (o.status, o.dismissed_reason) == ("dismissed", "not_relevant")


def test_snooze_and_dismiss(client, seeded):
    card = top_card(client)
    oid = card["opportunity"]["id"]
    assert client.post(f"/api/opportunities/{oid}/snooze", headers=ANA, json={"days": 5}).status_code == 400
    r = client.post(f"/api/opportunities/{oid}/snooze", headers=ANA, json={"days": 7, "reason": "De vacaciones"})
    assert r.json()["snoozed_until"] == "2026-10-24"
    assert oid not in [c["opportunity"]["id"] for c in client.get("/api/today", headers=ANA).json()["cards"]]
    card2 = top_card(client)
    oid2 = card2["opportunity"]["id"]
    assert client.post(f"/api/opportunities/{oid2}/dismiss", headers=ANA, json={"reason_code": "other"}).status_code == 400
    assert client.post(f"/api/opportunities/{oid2}/dismiss", headers=ANA, json={"reason_code": "data_incorrect",
                                                                                "note": "Cliente cerrado en el ERP"}).status_code == 200
    reports = client.get("/api/admin/data-issues", headers=ADMIN).json()["user_reports"]
    assert [r["opportunity_id"] for r in reports] == [oid2]


def test_follow_up_reschedule_and_cancel(client):
    card = top_card(client)
    fu = client.post("/api/actions", headers=ANA, json=action(card, follow_up_date="2026-10-20")).json()["follow_up"]
    assert client.patch(f"/api/follow-ups/{fu['id']}", headers=ANA, json={"due_date": "2026-10-22"}).json()["due_date"] == "2026-10-22"
    assert client.patch(f"/api/follow-ups/{fu['id']}", headers=ANA, json={"status": "cancelled"}).json()["status"] == "cancelled"


def test_audit_log_is_append_only(client, seeded):
    db = seeded["db"]
    client.post("/api/actions", headers=ANA, json=action(top_card(client)))
    with pytest.raises(DBAPIError):
        db.execute(text("UPDATE app.audit_log SET action = 'tampered'"))
        db.commit()
    db.rollback()
    with pytest.raises(DBAPIError):
        db.execute(text("DELETE FROM app.audit_log"))
        db.commit()
    db.rollback()


def test_customer_detail_shows_evidence_history_and_no_lost_label(client):
    card = top_card(client)
    c = card["customer"]
    client.post("/api/actions", headers=ANA, json=action(card, note="Nota de prueba"))
    d = client.get(f"/api/customers/{c['source_entity']}/{c['source_customer_id']}", headers=ANA).json()
    assert d["opportunities"][0]["evidence"] and d["opportunities"][0]["priority_components"]["formula"]
    assert d["activities"][0]["note"] == "Nota de prueba"
    assert d["talking_points"] and d["rules_status"] == "provisional" and d["lost_label_enabled"] is False
    d.pop("lost_label_enabled")
    assert "perdid" not in str(d).lower() and "lost" not in str(d).lower()
