"""Manager view: assignments, overdue follow-ups, opportunity status, observed outcomes, reassignment."""

from __future__ import annotations

import datetime as dt
from collections import Counter, defaultdict

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import clock
from app.api.common import bad_request, customer_brief, customers_by_key, not_found, user_names
from app.api.core import follow_up_context, present_follow_up
from app.api.workflow import clean_note
from app.auth.deps import require_role
from app.db import get_db
from app.models import facts as F
from app.models.records import (
    ACTIVE_OPPORTUNITY_STATUSES,
    Activity,
    AppUser,
    AssignmentOverride,
    FollowUp,
    ObservedOutcome,
    Opportunity,
    Team,
    TeamManager,
)
from app.services.access import build_scope
from app.services.audit import audit

router = APIRouter()


@router.get("/team")
def team_view(user: AppUser = Depends(require_role("manager", "admin")), db: Session = Depends(get_db)) -> dict:
    scope = build_scope(db, user)
    today = clock.today()
    now = clock.now()
    names = user_names(db)
    users = {u.id: u for u in db.execute(select(AppUser).where(AppUser.active.is_(True))).scalars()}
    member_ids = sorted(uid for uid, u in users.items() if u.role in ("sales", "manager")
                        and (scope.visible_user_ids is None or uid in scope.visible_user_ids))
    teams = db.execute(select(Team.name).join(TeamManager, TeamManager.team_id == Team.id)
                       .where(TeamManager.user_id == user.id)).scalars().all() if user.role == "manager" else ["*"]
    visible = scope.visible_customers()

    def in_scope(e: str, c: str) -> bool:
        return visible is None or (e, c) in visible

    opps = [o for o in db.execute(select(Opportunity)).scalars() if in_scope(o.source_entity, o.source_customer_id)]
    fus = [f for f in db.execute(select(FollowUp).where(FollowUp.status == "open")).scalars()
           if f.owner_user_id in member_ids and in_scope(f.source_entity, f.source_customer_id)]
    acts = [a for a in db.execute(select(Activity).where(Activity.created_at >= now - dt.timedelta(days=30))).scalars()
            if a.user_id in member_ids]
    outcomes = [oc for oc in db.execute(select(ObservedOutcome).where(ObservedOutcome.detected_at >= now - dt.timedelta(days=90))).scalars()
                if in_scope(oc.source_entity, oc.source_customer_id)]

    assigned = Counter(uid for k, uid in scope.assignees.items() if in_scope(*k))
    open_by_owner = Counter(scope.assignees.get((o.source_entity, o.source_customer_id)) for o in opps
                            if o.status in ACTIVE_OPPORTUNITY_STATUSES and o.condition_active)
    opp_owner = {o.id: scope.assignees.get((o.source_entity, o.source_customer_id)) for o in opps}
    members = [{
        "id": uid, "display_name": names[uid], "role": users[uid].role,
        "assigned_customers": assigned.get(uid, 0),
        "active_opportunities": open_by_owner.get(uid, 0),
        "actions_last_30d": sum(1 for a in acts if a.user_id == uid),
        "follow_ups_open": sum(1 for f in fus if f.owner_user_id == uid),
        "follow_ups_overdue": sum(1 for f in fus if f.owner_user_id == uid and f.due_date < today),
        "observed_outcomes_90d": sum(1 for oc in outcomes if opp_owner.get(oc.opportunity_id) == uid),
    } for uid in member_ids]

    status_by_type: dict[str, Counter] = defaultdict(Counter)
    for o in opps:
        if o.status in ACTIVE_OPPORTUNITY_STATUSES or (o.resolved_at or o.dismissed_at or o.first_detected_at) >= now - dt.timedelta(days=90):
            status = o.status if o.condition_active or o.status not in ACTIVE_OPPORTUNITY_STATUSES else "unconfirmed"
            status_by_type[o.opp_type][status] += 1

    overdue = [f for f in fus if f.due_date < today]
    keys = {(f.source_entity, f.source_customer_id) for f in overdue} | {(oc.source_entity, oc.source_customer_id) for oc in outcomes}
    customers = customers_by_key(db, keys)
    f_acts, f_opps = follow_up_context(db, overdue)
    opp_by_id = {o.id: o for o in opps}
    first_actor = {}
    for a in db.execute(select(Activity).where(Activity.opportunity_id.in_([oc.opportunity_id for oc in outcomes]))
                        .order_by(Activity.created_at)).scalars() if outcomes else []:
        first_actor.setdefault(a.opportunity_id, a)

    issue_rows = [i for i in db.execute(select(F.DataIssue)).scalars()
                  if i.source_customer_id is None or in_scope(i.source_entity, i.source_customer_id)]
    return {
        "teams": teams,
        "members": members,
        "overdue_follow_ups": [present_follow_up(f, today, customers, names, f_acts.get(f.created_by_activity_id), f_opps.get(f.opportunity_id))
                               for f in sorted(overdue, key=lambda f: f.due_date)],
        "opportunity_status": {t: dict(c) for t, c in status_by_type.items()},
        "actions_last_30d": dict(Counter(a.action_type for a in acts)),
        "observed_outcomes": [{
            "opportunity_id": oc.opportunity_id,
            "opp_type": opp_by_id[oc.opportunity_id].opp_type if oc.opportunity_id in opp_by_id else None,
            "customer": customer_brief(customers.get((oc.source_entity, oc.source_customer_id)), oc.source_entity, oc.source_customer_id),
            "action": {"action_type": first_actor[oc.opportunity_id].action_type,
                       "user": names.get(first_actor[oc.opportunity_id].user_id)} if oc.opportunity_id in first_actor else None,
            "first_action_at": oc.first_action_at.isoformat(),
            "observed_document_date": oc.observed_document_date.isoformat(),
            "label": "observed_post_action_not_attributed",
        } for oc in sorted(outcomes, key=lambda oc: oc.observed_document_date, reverse=True)],
        "data_issues": dict(Counter(i.issue_code for i in issue_rows if i.severity != "info")),
        "user_reported_data_problems": sum(1 for o in opps if o.dismissed_reason == "data_incorrect"),
    }


@router.get("/team/assignments")
def assignments(q: str = "", user: AppUser = Depends(require_role("manager", "admin")), db: Session = Depends(get_db)) -> dict:
    scope = build_scope(db, user)
    names = user_names(db)
    visible = scope.visible_customers()
    rows = db.execute(select(F.Customer).order_by(F.Customer.display_name)).scalars()
    active = Counter((o.source_entity, o.source_customer_id) for o in db.execute(
        select(Opportunity).where(Opportunity.status.in_(ACTIVE_OPPORTUNITY_STATUSES), Opportunity.condition_active.is_(True))).scalars())
    ql = q.strip().lower()
    items = []
    for c in rows:
        key = (c.source_entity, c.source_customer_id)
        if visible is not None and key not in visible:
            continue
        if ql and ql not in c.display_name.lower() and ql not in c.source_customer_id.lower():
            continue
        uid = scope.assignees.get(key)
        items.append({**customer_brief(c, *key), "assignee": {"id": uid, "display_name": names.get(uid)},
                      "active_opportunities": active.get(key, 0)})
    assignable = [{"id": u.id, "display_name": u.display_name, "role": u.role}
                  for u in db.execute(select(AppUser).where(AppUser.active.is_(True)).order_by(AppUser.display_name)).scalars()
                  if scope.can_assign_to(u)]
    return {"items": items[:300], "total": len(items), "assignable_users": assignable}


class ReassignIn(BaseModel):
    source_entity: str = Field(pattern=r"^(JC|PM)$")
    source_customer_id: str = Field(min_length=1, max_length=60)
    user_id: int
    reason: str | None = Field(default=None, max_length=280)

    _clean = field_validator("reason")(clean_note)


@router.post("/assignments")
def reassign(body: ReassignIn, user: AppUser = Depends(require_role("manager", "admin")), db: Session = Depends(get_db)) -> dict:
    scope = build_scope(db, user)
    key = (body.source_entity, body.source_customer_id)
    if not scope.can_see(*key):
        raise not_found()
    target = db.get(AppUser, body.user_id)
    if target is None or not scope.can_assign_to(target):
        raise bad_request("assignee_not_in_scope")
    previous = scope.assignees.get(key)
    if previous == target.id:
        raise bad_request("already_assigned")
    now = clock.now()
    for o in db.execute(select(AssignmentOverride).where(AssignmentOverride.source_entity == key[0],
                                                         AssignmentOverride.source_customer_id == key[1],
                                                         AssignmentOverride.superseded_at.is_(None))).scalars():
        o.superseded_at = now
    db.add(AssignmentOverride(source_entity=key[0], source_customer_id=key[1], user_id=target.id,
                              assigned_by_user_id=user.id, reason=body.reason, created_at=now))
    moved = []
    if previous is not None:
        for fu in db.execute(select(FollowUp).where(FollowUp.source_entity == key[0], FollowUp.source_customer_id == key[1],
                                                    FollowUp.owner_user_id == previous, FollowUp.status == "open")).scalars():
            fu.owner_user_id = target.id
            moved.append(fu.id)
    audit(db, user.id, "customer_reassigned", "customer", f"{key[0]}:{key[1]}",
          {"from_user_id": previous, "to_user_id": target.id, "reason": body.reason, "follow_ups_moved": moved})
    db.commit()
    return {"customer": f"{key[0]}:{key[1]}", "assignee_id": target.id, "follow_ups_moved": moved}
