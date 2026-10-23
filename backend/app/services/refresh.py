"""Scheduled refresh: re-evaluate opportunities against the current facts snapshot.

* One active opportunity per customer and type (no duplicate alerts).
* Snoozed opportunities return when the snooze ends; in-progress ones resurface
  if the condition persists long after the last action with no follow-up.
* Dismissed opportunities are not re-raised during the cooldown period.
* When data for a customer becomes unreliable the opportunity is kept but
  marked unconfirmed (hidden from Today) rather than resolved.
* Later orders after an action are recorded as OBSERVED post-action results,
  never as attributed uplift.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app import clock
from app.models import facts as F
from app.models.records import (
    ACTIVE_OPPORTUNITY_STATUSES,
    Activity,
    FollowUp,
    ObservedOutcome,
    Opportunity,
)
from app.rules.engine import Evaluation, evaluate_customer, priority
from app.services.access import effective_assignees
from app.services.audit import audit
from app.services.rule_config import active_config
from app.services.snapshot import Issue, load_snapshot


def _apply_flag(o: Opportunity, e: Evaluation, params: dict[str, Any], version: int, refreshed_at: dt.datetime) -> None:
    score, band, components = priority(e, params)
    o.priority_score, o.priority_band, o.priority_components = score, band, components
    o.reason_code, o.reason_params = e.reason_code or e.opp_type, {**e.reason_params, "next_action": e.next_action_code}
    o.evidence = e.evidence
    o.rule_version, o.config_version = e.rule_version, version
    o.data_refreshed_at = refreshed_at
    o.condition_active = True


def run_refresh(db: Session, actor_user_id: int | None = None) -> dict[str, Any]:
    now = clock.now()
    today = clock.today()
    version, params = active_config(db)
    wf = params["workflow"]
    snap = load_snapshot(db, params, now)
    issues: list[Issue] = list(snap.issues)
    assignees = effective_assignees(db, today)

    active = {
        (o.source_entity, o.source_customer_id, o.opp_type): o
        for o in db.execute(select(Opportunity).where(Opportunity.status.in_(ACTIVE_OPPORTUNITY_STATUSES))).scalars()
    }
    cooldown_from = now - dt.timedelta(days=int(wf["dismiss_cooldown_days"]))
    recently_dismissed = {
        (o.source_entity, o.source_customer_id, o.opp_type)
        for o in db.execute(
            select(Opportunity).where(Opportunity.status == "dismissed", Opportunity.dismissed_at >= cooldown_from)
        ).scalars()
    }
    open_follow_up_opps = set(
        db.execute(select(FollowUp.opportunity_id).where(FollowUp.status == "open", FollowUp.opportunity_id.is_not(None))).scalars()
    )

    stats = {"evaluated": 0, "flagged": 0, "created": 0, "updated": 0, "resolved": 0, "unconfirmed": 0,
             "resurfaced": 0, "suppressed": 0, "not_evaluable": 0, "cooldown_skipped": 0}

    for key, cf in snap.customers.items():
        ctx = snap.contexts.get(cf.entity)
        for e in evaluate_customer(cf, snap.contexts, snap.customers, params):
            stats["evaluated"] += 1
            okey = (cf.entity, cf.customer_id, e.opp_type)
            existing = active.get(okey)
            if e.status == "flag":
                stats["flagged"] += 1
                if key not in assignees:
                    issues.append(Issue("warning", "unassigned_customer_with_opportunity", cf.entity, cf.customer_id,
                                        {"opp_type": e.opp_type}))
                if existing is None:
                    if okey in recently_dismissed:
                        stats["cooldown_skipped"] += 1
                        continue
                    o = Opportunity(source_entity=cf.entity, source_customer_id=cf.customer_id, opp_type=e.opp_type,
                                    status="open", first_detected_at=now, last_evaluated_at=now)
                    _apply_flag(o, e, params, version, ctx.refreshed_at)
                    db.add(o)
                    db.flush()
                    audit(db, actor_user_id, "opportunity_created", "opportunity", o.id,
                          {"opp_type": e.opp_type, "customer": f"{cf.entity}:{cf.customer_id}", "score": o.priority_score})
                    stats["created"] += 1
                    continue
                _apply_flag(existing, e, params, version, ctx.refreshed_at)
                existing.last_evaluated_at = now
                stats["updated"] += 1
                if existing.status == "snoozed" and existing.snoozed_until and existing.snoozed_until <= today:
                    existing.status, existing.snoozed_until = "open", None
                    existing.reason_params = {**existing.reason_params, "resurfaced": "snooze_ended"}
                    audit(db, actor_user_id, "opportunity_snooze_ended", "opportunity", existing.id)
                    stats["resurfaced"] += 1
                elif (
                    existing.status == "in_progress"
                    and existing.id not in open_follow_up_opps
                    and existing.last_action_at
                    and existing.last_action_at <= now - dt.timedelta(days=int(wf["resurface_after_days"]))
                ):
                    existing.status = "open"
                    existing.reason_params = {**existing.reason_params, "resurfaced": "condition_persists"}
                    audit(db, actor_user_id, "opportunity_resurfaced", "opportunity", existing.id)
                    stats["resurfaced"] += 1
            elif e.status in ("suppressed", "not_evaluable"):
                stats[e.status] += 1
                if existing is not None:
                    # Cannot confirm the condition with reliable data: hide, don't resolve.
                    existing.condition_active = False
                    existing.last_evaluated_at = now
                    existing.reason_params = {**existing.reason_params, "unconfirmed_reason": e.detail_code}
                    stats["unconfirmed"] += 1
            else:  # not_met / excluded with reliable data: the condition no longer holds
                if existing is not None:
                    existing.status = "resolved"
                    existing.resolved_at = now
                    existing.resolution_code = "condition_cleared"
                    existing.condition_active = False
                    existing.last_evaluated_at = now
                    existing.reason_params = {**existing.reason_params, "cleared_by": e.detail_code}
                    audit(db, actor_user_id, "opportunity_resolved", "opportunity", existing.id,
                          {"resolution": "condition_cleared", "detail": e.detail_code})
                    stats["resolved"] += 1

    stats["observed_outcomes"] = record_observed_outcomes(db, int(wf["outcome_window_days"]))

    db.execute(delete(F.DataIssue).where(F.DataIssue.stage == "refresh"))
    for i in issues:
        db.add(F.DataIssue(stage="refresh", severity=i.severity, issue_code=i.issue_code,
                           source_entity=i.source_entity, source_customer_id=i.source_customer_id, detail=i.detail))
    stats["data_issues"] = len(issues)
    audit(db, actor_user_id, "refresh_completed", "refresh", now.isoformat(),
          {**stats, "config_version": version, "entities": {k: v.refreshed_at.isoformat() for k, v in snap.contexts.items()}})
    db.commit()
    return stats


def record_observed_outcomes(db: Session, window_days: int) -> int:
    """For each opportunity with an action, record the first later invoice in that entity (observed, not attributed)."""
    have = set(db.execute(select(ObservedOutcome.opportunity_id)).scalars())
    first_actions = db.execute(
        select(Activity.opportunity_id, Activity.source_entity, Activity.source_customer_id, Activity.created_at)
        .where(Activity.opportunity_id.is_not(None), Activity.action_type != "not_relevant")
        .order_by(Activity.created_at)
    ).all()
    seen: set[int] = set()
    created = 0
    for opp_id, entity, cid, at in first_actions:
        if opp_id in have or opp_id in seen:
            continue
        seen.add(opp_id)
        action_day = at.astimezone(clock.BUSINESS_TZ).date()
        p = db.execute(
            select(F.Purchase)
            .where(F.Purchase.source_entity == entity, F.Purchase.source_customer_id == cid,
                   F.Purchase.document_type == "invoice", F.Purchase.document_date >= action_day,
                   F.Purchase.document_date <= action_day + dt.timedelta(days=window_days))
            .order_by(F.Purchase.document_date, F.Purchase.document_ref)
            .limit(1)
        ).scalar_one_or_none()
        if p is None:
            continue
        db.add(ObservedOutcome(opportunity_id=opp_id, source_entity=entity, source_customer_id=cid,
                               outcome_code="order_observed_after_action", first_action_at=at,
                               observed_document_date=p.document_date, observed_document_ref=p.document_ref))
        audit(db, None, "observed_outcome_recorded", "opportunity", opp_id,
              {"document_date": p.document_date.isoformat(), "label": "observed_post_action_not_attributed"})
        created += 1
    return created
