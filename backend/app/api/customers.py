"""Customer list, customer detail and conversation points."""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from decimal import Decimal
from statistics import median
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import clock
from app.ai.talking_points import ai_points, template_points
from app.api.common import (
    customer_brief,
    effective_status,
    freshness,
    not_found,
    outcomes_for,
    present_opportunity,
    user_names,
)
from app.auth.deps import current_user
from app.db import get_db
from app.models import facts as F
from app.models.records import ACTIVE_OPPORTUNITY_STATUSES, Activity, AppUser, FollowUp, Opportunity
from app.rules.engine import add_months, evaluate_customer, month_end
from app.services.access import build_scope
from app.services.rule_config import active_config
from app.services.snapshot import load_snapshot

router = APIRouter()
BAND_ORDER = {"high": 0, "medium": 1, "low": 2}


@router.get("/customers")
def list_customers(
    q: str = "",
    entity: Literal["JC", "PM", ""] = "",
    with_opportunity: bool = False,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: AppUser = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    scope = build_scope(db, user)
    today = clock.today()
    names = user_names(db)
    visible = scope.visible_customers()
    stmt = select(F.Customer)
    if entity:
        stmt = stmt.where(F.Customer.source_entity == entity)
    if q.strip():
        like = f"%{q.strip().lower()}%"
        stmt = stmt.where(func.lower(F.Customer.display_name).like(like) | func.lower(F.Customer.source_customer_id).like(like))
    rows = [c for c in db.execute(stmt).scalars() if visible is None or (c.source_entity, c.source_customer_id) in visible]

    opps: dict[tuple[str, str], list[Opportunity]] = defaultdict(list)
    for o in db.execute(select(Opportunity).where(Opportunity.status.in_(ACTIVE_OPPORTUNITY_STATUSES))).scalars():
        opps[(o.source_entity, o.source_customer_id)].append(o)
    last_order = dict(
        ((e, c), d) for e, c, d in db.execute(
            select(F.Purchase.source_entity, F.Purchase.source_customer_id, func.max(F.Purchase.document_date))
            .where(F.Purchase.document_type == "invoice")
            .group_by(F.Purchase.source_entity, F.Purchase.source_customer_id)
        )
    )
    issue_keys = set(db.execute(select(F.DataIssue.source_entity, F.DataIssue.source_customer_id)
                                .where(F.DataIssue.source_customer_id.is_not(None), F.DataIssue.severity != "info")).all())

    items = []
    for c in rows:
        key = (c.source_entity, c.source_customer_id)
        active = [o for o in opps.get(key, []) if o.condition_active]
        if with_opportunity and not active:
            continue
        best = min(active, key=lambda o: (BAND_ORDER.get(o.priority_band, 9), -o.priority_score)) if active else None
        items.append({
            **customer_brief(c, *key),
            "assignee": {"id": scope.assignees.get(key), "display_name": names.get(scope.assignees.get(key))},
            "opportunities": [{"id": o.id, "opp_type": o.opp_type, "status": effective_status(o, today), "priority_band": o.priority_band}
                              for o in sorted(active, key=lambda o: -o.priority_score)],
            "best_priority": best.priority_band if best else None,
            "best_score": best.priority_score if best else None,
            "last_order_date": last_order[key].isoformat() if key in last_order else None,
            "has_data_issue": key in issue_keys,
        })
    items.sort(key=lambda i: (i["best_score"] is None, -(i["best_score"] or 0), i["display_name"]))
    return {"total": len(items), "items": items[offset: offset + limit]}


def _sum(monthly: dict[dt.date, Decimal], start: dt.date, n: int) -> float:
    return float(sum((monthly.get(add_months(start, i), Decimal(0)) for i in range(n)), Decimal(0)))


@router.get("/customers/{entity}/{customer_id}")
def customer_detail(entity: Literal["JC", "PM"], customer_id: str, user: AppUser = Depends(current_user),
                    db: Session = Depends(get_db)) -> dict:
    scope = build_scope(db, user)
    if not scope.can_see(entity, customer_id):
        raise not_found()
    c = db.execute(select(F.Customer).where(F.Customer.source_entity == entity, F.Customer.source_customer_id == customer_id)).scalar_one_or_none()
    if c is None:
        raise not_found()
    version, params = active_config(db)
    today = clock.today()
    names = user_names(db)
    snap = load_snapshot(db, params, keys={(entity, customer_id)})
    cf = snap.customers[(entity, customer_id)]
    ctx = snap.contexts.get(entity)
    key = (entity, customer_id)

    # --- commercial summary: figures from this entity only, labelled with their measure
    summary: dict[str, Any] = {"entity": entity, "last_order_date": cf.invoice_days[-1].isoformat() if cf.invoice_days else None}
    if ctx and ctx.measure:
        lcm = ctx.last_complete_month
        cur_start, prev_start = add_months(lcm, -11), add_months(lcm, -23)
        summary["measure"] = {"code": ctx.measure.code, "name_es": ctx.measure.name_es, "name_en": ctx.measure.name_en,
                              "certified_measure_name": ctx.measure.certified_measure_name,
                              "certification_status": ctx.measure.certification_status, "source_model": ctx.measure.source_model,
                              "unit": ctx.measure.unit}
        summary["last_12m"] = {"value": _sum(cf.monthly, cur_start, 12), "start": cur_start.isoformat(), "end": month_end(lcm).isoformat()}
        summary["prior_12m"] = {"value": _sum(cf.monthly, prev_start, 12), "start": prev_start.isoformat(),
                                "end": month_end(add_months(lcm, -12)).isoformat()}
        summary["monthly"] = [{"month": add_months(lcm, -i).isoformat(), "value": float(cf.monthly.get(add_months(lcm, -i), 0))}
                              for i in range(23, -1, -1)]
    year_ago = (ctx.as_of if ctx else today) - dt.timedelta(days=365)
    recent_days = [d for d in cf.invoice_days if d >= year_ago]
    summary["orders_last_12m"] = len(recent_days)
    if len(recent_days) >= 3:
        summary["typical_interval_days"] = int(median([(b - a).days for a, b in zip(recent_days, recent_days[1:])]))

    # --- linked accounts: approved mappings only; figures are shown per entity and never added together
    links = []
    for direction, t in (("inbound", cf.inbound), ("outbound", cf.outbound)):
        if t is None:
            continue
        other_key = (t.from_entity, t.from_customer_id) if direction == "inbound" else (t.to_entity, t.to_customer_id)
        other = snap.customers.get(other_key)
        links.append({
            "direction": direction, "mapping_ref": t.mapping_ref, "transfer_date": t.transfer_date.isoformat(),
            "cohort": t.cohort, "approved_by": t.approved_by,
            "other": {"source_entity": other_key[0], "source_customer_id": other_key[1],
                      "display_name": other.display_name if other else None,
                      "last_order_date": other.invoice_days[-1].isoformat() if other and other.invoice_days else None,
                      "can_open": scope.can_see(*other_key)},
        })

    # --- data issues for this customer (shown as data problems, not customer risk)
    issues = [{"severity": i.severity, "issue_code": i.issue_code, "detail": i.detail, "stage": i.stage}
              for i in db.execute(select(F.DataIssue).where(F.DataIssue.source_entity == entity,
                                                            F.DataIssue.source_customer_id == customer_id)).scalars()]
    evaluations = [{"opp_type": e.opp_type, "status": e.status, "detail_code": e.detail_code, "detail_params": e.detail_params}
                   for e in evaluate_customer(cf, snap.contexts, snap.customers, params)]

    all_opps = list(db.execute(select(Opportunity).where(Opportunity.source_entity == entity,
                                                         Opportunity.source_customer_id == customer_id)
                               .order_by(Opportunity.first_detected_at.desc())).scalars())
    outcomes = outcomes_for(db, [o.id for o in all_opps])
    active = [o for o in all_opps if o.status in ACTIVE_OPPORTUNITY_STATUSES]
    closed = [o for o in all_opps if o.status not in ACTIVE_OPPORTUNITY_STATUSES][:5]

    # --- recent purchases (document lines as supplied; no totals are derived)
    lines = db.execute(select(F.Purchase).where(F.Purchase.source_entity == entity, F.Purchase.source_customer_id == customer_id)
                       .order_by(F.Purchase.document_date.desc(), F.Purchase.document_ref, F.Purchase.record_key)).scalars()
    docs: dict[str, dict[str, Any]] = {}
    for p in lines:
        if p.document_ref not in docs:
            if len(docs) >= 8:
                break
            docs[p.document_ref] = {"document_ref": p.document_ref, "document_date": p.document_date.isoformat(),
                                    "document_type": p.document_type, "lines": []}
        docs[p.document_ref]["lines"].append({
            "brand": p.brand, "sku": p.sku, "sku_description": p.sku_description,
            "quantity": float(p.quantity) if p.quantity is not None else None, "unit": p.unit,
            "amount": float(p.amount) if p.amount is not None else None, "amount_measure_code": p.amount_measure_code,
        })

    acts = list(db.execute(select(Activity).where(Activity.source_entity == entity, Activity.source_customer_id == customer_id)
                           .order_by(Activity.created_at.desc())).scalars())
    opp_type = {o.id: o.opp_type for o in all_opps}
    fus = list(db.execute(select(FollowUp).where(FollowUp.source_entity == entity, FollowUp.source_customer_id == customer_id,
                                                 FollowUp.status == "open").order_by(FollowUp.due_date)).scalars())
    shown_active = [o for o in active if o.condition_active]
    return {
        "customer": {**customer_brief(c, entity, customer_id), "segment": c.segment, "province": c.province,
                     "is_intercompany": c.is_intercompany, "seasonal_flag": c.seasonal_flag,
                     "transfer_cohort": c.transfer_cohort, "source_status": c.source_status},
        "assignee": {"id": scope.assignees.get(key), "display_name": names.get(scope.assignees.get(key))},
        "freshness": [f for f in freshness(db, params) if f["entity"] in {entity} | {link["other"]["source_entity"] for link in links}],
        "summary": summary,
        "linked_accounts": links,
        "data_issues": issues,
        "rule_evaluations": evaluations,
        "opportunities": [present_opportunity(o, today, outcomes.get(o.id), full=True) for o in active],
        "closed_opportunities": [present_opportunity(o, today, outcomes.get(o.id), full=True) for o in closed],
        "recent_documents": list(docs.values()),
        "activities": [{"id": a.id, "action_type": a.action_type, "note": a.note, "created_at": a.created_at.isoformat(),
                        "user": {"id": a.user_id, "display_name": names.get(a.user_id)},
                        "follow_up_date": a.follow_up_date.isoformat() if a.follow_up_date else None,
                        "opportunity_id": a.opportunity_id, "opp_type": opp_type.get(a.opportunity_id)} for a in acts],
        "open_follow_ups": [{"id": f.id, "due_date": f.due_date.isoformat(), "owner": {"id": f.owner_user_id, "display_name": names.get(f.owner_user_id)},
                             "opportunity_id": f.opportunity_id} for f in fus],
        "talking_points": template_points(shown_active),
        "config_version": version,
        "rules_status": "provisional",
        "lost_label_enabled": bool(params.get("lost_customer_definition_approved")),
    }


class TalkingPointsIn(BaseModel):
    language: Literal["es", "en"] = "es"


@router.post("/customers/{entity}/{customer_id}/ai-talking-points")
def customer_ai_points(entity: Literal["JC", "PM"], customer_id: str, body: TalkingPointsIn,
                       user: AppUser = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    scope = build_scope(db, user)
    if not scope.can_see(entity, customer_id):
        raise not_found()
    c = db.execute(select(F.Customer).where(F.Customer.source_entity == entity, F.Customer.source_customer_id == customer_id)).scalar_one_or_none()
    if c is None:
        raise not_found()
    opps = list(db.execute(select(Opportunity).where(Opportunity.source_entity == entity, Opportunity.source_customer_id == customer_id,
                                                     Opportunity.status.in_(ACTIVE_OPPORTUNITY_STATUSES),
                                                     Opportunity.condition_active.is_(True))).scalars())
    notes = [n for n in db.execute(select(Activity.note).where(Activity.source_entity == entity, Activity.source_customer_id == customer_id,
                                                               Activity.note.is_not(None)).order_by(Activity.created_at.desc()).limit(3)).scalars()]
    return ai_points(db, {"display_name": c.display_name, "source_entity": entity, "source_customer_id": customer_id},
                     opps, notes, body.language, user.id)
