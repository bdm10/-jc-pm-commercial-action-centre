"""Recording actions, follow-ups, snoozing and dismissing.

Recording an action marks the work as DONE; it says nothing about the customer
outcome. Outcomes are only ever observed later in the source data.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import clock
from app.api.common import (
    ACTION_TYPES,
    DISMISS_REASONS,
    bad_request,
    customers_by_key,
    not_found,
    scoped_opportunity,
    user_names,
)
from app.api.core import follow_up_context, present_follow_up
from app.auth.deps import current_user
from app.db import get_db
from app.models.records import ACTIVE_OPPORTUNITY_STATUSES, Activity, AppUser, FollowUp
from app.services.access import build_scope
from app.services.audit import audit
from app.services.rule_config import active_config

router = APIRouter()
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def clean_note(v: str | None) -> str | None:
    if v is None:
        return None
    v = _CONTROL.sub("", v).strip()
    return v or None


class ActionIn(BaseModel):
    client_request_id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    source_entity: Literal["JC", "PM"]
    source_customer_id: str = Field(min_length=1, max_length=60)
    opportunity_id: int | None = None
    action_type: Literal[ACTION_TYPES]  # type: ignore[valid-type]
    note: str | None = Field(default=None, max_length=280)
    follow_up_date: dt.date | None = None

    _clean = field_validator("note")(clean_note)


@router.post("/actions")
def record_action(body: ActionIn, user: AppUser = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    existing = db.execute(select(Activity).where(Activity.client_request_id == body.client_request_id)).scalar_one_or_none()
    if existing is not None:
        if existing.user_id != user.id:
            raise bad_request("duplicate_request_id")
        return {"activity_id": existing.id, "duplicate": True}

    scope = build_scope(db, user)
    if not scope.can_see(body.source_entity, body.source_customer_id):
        raise not_found()
    _, params = active_config(db)
    today = clock.today()
    if body.follow_up_date is not None:
        max_ahead = int(params["workflow"]["follow_up_max_days_ahead"])
        if not (today <= body.follow_up_date <= today + dt.timedelta(days=max_ahead)):
            raise bad_request("invalid_follow_up_date", max_days_ahead=max_ahead)

    opp = None
    if body.opportunity_id is not None:
        opp = scoped_opportunity(db, scope, body.opportunity_id)
        if (opp.source_entity, opp.source_customer_id) != (body.source_entity, body.source_customer_id):
            raise bad_request("opportunity_customer_mismatch")
        if opp.status not in ACTIVE_OPPORTUNITY_STATUSES:
            raise bad_request("opportunity_not_active")

    now = clock.now()
    act = Activity(client_request_id=body.client_request_id, opportunity_id=opp.id if opp else None,
                   source_entity=body.source_entity, source_customer_id=body.source_customer_id, user_id=user.id,
                   action_type=body.action_type, note=body.note, follow_up_date=body.follow_up_date, created_at=now)
    db.add(act)
    try:
        db.flush()
    except IntegrityError:  # concurrent duplicate submit
        db.rollback()
        return {"duplicate": True}

    # Recording an action completes this user's open follow-ups for the customer.
    closed = []
    for fu in db.execute(select(FollowUp).where(FollowUp.source_entity == body.source_entity,
                                                FollowUp.source_customer_id == body.source_customer_id,
                                                FollowUp.owner_user_id == user.id, FollowUp.status == "open")).scalars():
        fu.status, fu.closed_at, fu.closed_by_activity_id = "done", now, act.id
        closed.append(fu.id)
        audit(db, user.id, "follow_up_completed", "follow_up", fu.id, {"activity_id": act.id})

    new_fu = None
    if body.follow_up_date is not None:
        new_fu = FollowUp(source_entity=body.source_entity, source_customer_id=body.source_customer_id,
                          opportunity_id=opp.id if opp else None, owner_user_id=user.id, due_date=body.follow_up_date,
                          status="open", created_by_activity_id=act.id, created_at=now)
        db.add(new_fu)
        db.flush()
        audit(db, user.id, "follow_up_created", "follow_up", new_fu.id, {"due_date": body.follow_up_date.isoformat()})

    if opp is not None:
        before = opp.status
        if body.action_type == "not_relevant":
            opp.status, opp.dismissed_reason, opp.dismissed_at, opp.dismissed_by_user_id = "dismissed", "not_relevant", now, user.id
            opp.dismissed_note = body.note
        else:
            opp.status = "in_progress"
            opp.snoozed_until = None
        opp.last_action_at = now
        audit(db, user.id, "opportunity_status_changed", "opportunity", opp.id, {"from": before, "to": opp.status, "activity_id": act.id})

    audit(db, user.id, "activity_recorded", "activity", act.id,
          {"action_type": body.action_type, "customer": f"{body.source_entity}:{body.source_customer_id}",
           "opportunity_id": opp.id if opp else None, "has_note": bool(body.note)})
    db.commit()
    return {
        "activity_id": act.id,
        "opportunity_status": opp.status if opp else None,
        "follow_up": {"id": new_fu.id, "due_date": new_fu.due_date.isoformat()} if new_fu else None,
        "follow_ups_completed": closed,
        "duplicate": False,
    }


class SnoozeIn(BaseModel):
    days: int = Field(ge=1, le=90)
    reason: str | None = Field(default=None, max_length=280)

    _clean = field_validator("reason")(clean_note)


@router.post("/opportunities/{opp_id}/snooze")
def snooze(opp_id: int, body: SnoozeIn, user: AppUser = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    scope = build_scope(db, user)
    o = scoped_opportunity(db, scope, opp_id)
    _, params = active_config(db)
    if body.days not in params["workflow"]["snooze_options_days"]:
        raise bad_request("invalid_snooze_days", options=params["workflow"]["snooze_options_days"])
    if o.status not in ("open", "in_progress", "snoozed"):
        raise bad_request("opportunity_not_active")
    until = clock.today() + dt.timedelta(days=body.days)
    before = o.status
    o.status, o.snoozed_until, o.snooze_reason = "snoozed", until, body.reason
    audit(db, user.id, "opportunity_snoozed", "opportunity", o.id, {"from": before, "until": until.isoformat(), "reason": body.reason})
    db.commit()
    return {"id": o.id, "status": o.status, "snoozed_until": until.isoformat()}


class DismissIn(BaseModel):
    reason_code: Literal[DISMISS_REASONS]  # type: ignore[valid-type]
    note: str | None = Field(default=None, max_length=280)

    _clean = field_validator("note")(clean_note)


@router.post("/opportunities/{opp_id}/dismiss")
def dismiss(opp_id: int, body: DismissIn, user: AppUser = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    scope = build_scope(db, user)
    o = scoped_opportunity(db, scope, opp_id)
    if o.status not in ACTIVE_OPPORTUNITY_STATUSES:
        raise bad_request("opportunity_not_active")
    if body.reason_code in ("other", "data_incorrect") and not body.note:
        raise bad_request("note_required")
    before = o.status
    o.status, o.dismissed_reason, o.dismissed_note = "dismissed", body.reason_code, body.note
    o.dismissed_at, o.dismissed_by_user_id = clock.now(), user.id
    audit(db, user.id, "opportunity_dismissed", "opportunity", o.id, {"from": before, "reason": body.reason_code, "note": body.note})
    db.commit()
    return {"id": o.id, "status": o.status}


@router.get("/follow-ups")
def list_follow_ups(view: Literal["mine", "team"] = "mine", user: AppUser = Depends(current_user),
                    db: Session = Depends(get_db), done_days: int = Query(14, ge=0, le=90)) -> dict:
    scope = build_scope(db, user)
    today = clock.today()
    if view == "team" and user.role == "sales":
        raise not_found()
    stmt = select(FollowUp).order_by(FollowUp.due_date)
    if view == "mine":
        stmt = stmt.where(FollowUp.owner_user_id == user.id)
    elif scope.visible_user_ids is not None:
        stmt = stmt.where(FollowUp.owner_user_id.in_(scope.visible_user_ids))
    since = clock.now() - dt.timedelta(days=done_days)
    rows = [f for f in db.execute(stmt).scalars()
            if (f.status == "open" or (f.status == "done" and f.closed_at and f.closed_at >= since))
            and scope.can_see(f.source_entity, f.source_customer_id)]
    customers = customers_by_key(db, {(f.source_entity, f.source_customer_id) for f in rows})
    names = user_names(db)
    acts, opps = follow_up_context(db, rows)

    def p(f: FollowUp) -> dict:
        return present_follow_up(f, today, customers, names, acts.get(f.created_by_activity_id), opps.get(f.opportunity_id))

    open_rows = [f for f in rows if f.status == "open"]
    return {
        "date": today.isoformat(),
        "overdue": [p(f) for f in open_rows if f.due_date < today],
        "today": [p(f) for f in open_rows if f.due_date == today],
        "upcoming": [p(f) for f in open_rows if f.due_date > today],
        "done_recent": [p(f) for f in sorted((f for f in rows if f.status == "done"), key=lambda f: f.closed_at, reverse=True)],
    }


class FollowUpPatch(BaseModel):
    due_date: dt.date | None = None
    status: Literal["cancelled"] | None = None


@router.patch("/follow-ups/{fu_id}")
def update_follow_up(fu_id: int, body: FollowUpPatch, user: AppUser = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    scope = build_scope(db, user)
    fu = db.get(FollowUp, fu_id)
    if fu is None or not scope.can_see(fu.source_entity, fu.source_customer_id):
        raise not_found()
    is_owner = fu.owner_user_id == user.id
    manages_owner = user.role in ("manager", "admin") and (scope.visible_user_ids is None or fu.owner_user_id in scope.visible_user_ids)
    if not (is_owner or manages_owner):
        raise not_found()
    if fu.status != "open":
        raise bad_request("follow_up_not_open")
    _, params = active_config(db)
    today = clock.today()
    changes = {}
    if body.due_date is not None:
        max_ahead = int(params["workflow"]["follow_up_max_days_ahead"])
        if not (today <= body.due_date <= today + dt.timedelta(days=max_ahead)):
            raise bad_request("invalid_follow_up_date", max_days_ahead=max_ahead)
        changes["due_date"] = [fu.due_date.isoformat(), body.due_date.isoformat()]
        fu.due_date = body.due_date
    if body.status == "cancelled":
        fu.status, fu.closed_at = "cancelled", clock.now()
        changes["status"] = ["open", "cancelled"]
    if not changes:
        raise bad_request("nothing_to_change")
    audit(db, user.id, "follow_up_updated", "follow_up", fu.id, changes)
    db.commit()
    return {"id": fu.id, "status": fu.status, "due_date": fu.due_date.isoformat()}
