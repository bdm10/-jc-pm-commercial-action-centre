"""Shared helpers for API responses."""

from __future__ import annotations

import datetime as dt
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import clock
from app.models import facts as F
from app.models.records import AppUser, ObservedOutcome, Opportunity
from app.rules.engine import last_complete_month
from app.services.access import Scope
from app.services.snapshot import is_stale, latest_refreshes

ACTION_TYPES = ("contacted", "meeting_booked", "offer_requested", "no_response", "not_relevant")
DISMISS_REASONS = ("already_handled", "not_relevant", "data_incorrect", "duplicate", "other")
KEY_FIGURES = {"transfer_no_reorder": ("e2", "e6"), "declining_purchases": ("e3", "e1", "e2"), "overdue_cadence": ("e2", "e3")}


def not_found() -> HTTPException:
    # Out-of-scope records are reported as not found so their existence is not disclosed.
    return HTTPException(status_code=404, detail={"code": "not_found"})


def bad_request(code: str, **extra: Any) -> HTTPException:
    return HTTPException(status_code=400, detail={"code": code, **extra})


def freshness(db: Session, params: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for entity, r in sorted(latest_refreshes(db).items()):
        as_of = r.source_refreshed_at.astimezone(clock.BUSINESS_TZ).date()
        out.append({
            "entity": entity,
            "source_model": r.source_model,
            "refreshed_at": r.source_refreshed_at.isoformat(),
            "as_of": as_of.isoformat(),
            "last_complete_month": last_complete_month(as_of, int(params["freshness"]["month_complete_lag_days"])).isoformat(),
            "data_classification": r.data_classification,
            "is_stale": is_stale(r.source_refreshed_at, params),
            "stale_after_hours": params["freshness"]["stale_after_hours"],
        })
    return out


def user_names(db: Session) -> dict[int, str]:
    return {u.id: u.display_name for u in db.execute(select(AppUser)).scalars()}


def customers_by_key(db: Session, keys: set[tuple[str, str]] | None = None) -> dict[tuple[str, str], F.Customer]:
    rows = db.execute(select(F.Customer)).scalars()
    return {(c.source_entity, c.source_customer_id): c for c in rows if keys is None or (c.source_entity, c.source_customer_id) in keys}


def customer_brief(c: F.Customer | None, entity: str, cid: str) -> dict[str, Any]:
    return {
        "source_entity": entity,
        "source_customer_id": cid,
        "display_name": c.display_name if c else None,
        "city": c.city if c else None,
        "channel": c.channel if c else None,
        "in_current_extract": c is not None,
    }


def effective_status(o: Opportunity, today: dt.date) -> str:
    if o.status == "snoozed" and o.snoozed_until and o.snoozed_until <= today:
        return "open"
    return o.status


def present_opportunity(o: Opportunity, today: dt.date, outcome: ObservedOutcome | None = None,
                        full: bool = False) -> dict[str, Any]:
    key_ids = KEY_FIGURES.get(o.opp_type, ())
    by_id = {e["id"]: e for e in o.evidence}
    d: dict[str, Any] = {
        "id": o.id,
        "opp_type": o.opp_type,
        "status": effective_status(o, today),
        "condition_active": o.condition_active,
        "priority_band": o.priority_band,
        "priority_score": o.priority_score,
        "reason_code": o.reason_code,
        "reason_params": o.reason_params,
        "next_action": o.reason_params.get("next_action"),
        "key_figures": [by_id[i] for i in key_ids if i in by_id],
        "data_refreshed_at": o.data_refreshed_at.isoformat(),
        "first_detected_at": o.first_detected_at.isoformat(),
        "last_action_at": o.last_action_at.isoformat() if o.last_action_at else None,
        "snoozed_until": o.snoozed_until.isoformat() if o.snoozed_until else None,
        "dismissed_reason": o.dismissed_reason,
        "resolved_at": o.resolved_at.isoformat() if o.resolved_at else None,
        "resolution_code": o.resolution_code,
        "observed_outcome": present_outcome(outcome) if outcome else None,
    }
    if full:
        d.update({
            "evidence": o.evidence,
            "priority_components": o.priority_components,
            "rule_version": o.rule_version,
            "config_version": o.config_version,
            "snooze_reason": o.snooze_reason,
            "dismissed_note": o.dismissed_note,
            "dismissed_at": o.dismissed_at.isoformat() if o.dismissed_at else None,
        })
    return d


def present_outcome(oc: ObservedOutcome) -> dict[str, Any]:
    return {
        "outcome_code": oc.outcome_code,
        "label": "observed_post_action_not_attributed",
        "first_action_at": oc.first_action_at.isoformat(),
        "observed_document_date": oc.observed_document_date.isoformat(),
        "observed_document_ref": oc.observed_document_ref,
        "detected_at": oc.detected_at.isoformat(),
    }


def outcomes_for(db: Session, opp_ids: list[int]) -> dict[int, ObservedOutcome]:
    if not opp_ids:
        return {}
    return {oc.opportunity_id: oc for oc in db.execute(select(ObservedOutcome).where(ObservedOutcome.opportunity_id.in_(opp_ids))).scalars()}


def scoped_opportunity(db: Session, scope: Scope, opp_id: int) -> Opportunity:
    o = db.get(Opportunity, opp_id)
    if o is None or not scope.can_see(o.source_entity, o.source_customer_id):
        raise not_found()
    return o
