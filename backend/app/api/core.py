"""Meta, current user, demo users and the Today view."""

from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import clock
from app.api.common import (
    ACTION_TYPES,
    DISMISS_REASONS,
    customer_brief,
    customers_by_key,
    effective_status,
    freshness,
    not_found,
    present_opportunity,
    user_names,
)
from app.auth.deps import current_user
from app.config import get_settings
from app.db import get_db
from app.models.records import Activity, AppUser, FollowUp, Opportunity, Team, TeamManager, TeamMember
from app.services.access import build_scope
from app.services.rule_config import active_config

router = APIRouter()


@router.get("/meta")
def meta() -> dict:
    """Public bootstrap information. Contains no customer data."""
    s = get_settings()
    return {
        "app": "jc-pm-commercial-action-centre",
        "app_env": s.app_env,
        "auth_mode": s.auth_mode or None,
        "auth_configured": s.auth_mode in ("entra", "demo") and (s.auth_mode != "demo" or s.demo_mode),
        "demo_mode": s.demo_mode,
        "access_gate": bool(s.demo_access_password),
        "ai_enabled": s.ai_provider != "none" and bool(s.anthropic_api_key),
        "entra": {"tenant_id": s.entra_tenant_id, "client_id": s.entra_spa_client_id, "scope": s.entra_api_scope}
        if s.auth_mode == "entra" else None,
    }


@router.get("/demo/users")
def demo_users(db: Session = Depends(get_db)) -> list[dict]:
    if not get_settings().demo_mode:
        raise not_found()
    return [{"email": u.email, "display_name": u.display_name, "role": u.role}
            for u in db.execute(select(AppUser).where(AppUser.active.is_(True)).order_by(AppUser.id)).scalars()]


@router.get("/me")
def me(user: AppUser = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    version, params = active_config(db)
    managed = db.execute(select(Team.name).join(TeamManager, TeamManager.team_id == Team.id).where(TeamManager.user_id == user.id)).scalars().all()
    member = db.execute(select(Team.name).join(TeamMember, TeamMember.team_id == Team.id).where(TeamMember.user_id == user.id)).scalars().all()
    wf = params["workflow"]
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "role": user.role,
        "teams_managed": managed,
        "teams_member": member,
        "options": {
            "action_types": ACTION_TYPES,
            "dismiss_reasons": DISMISS_REASONS,
            "snooze_options_days": wf["snooze_options_days"],
            "follow_up_max_days_ahead": wf["follow_up_max_days_ahead"],
            "today_max_cards": wf["today_max_cards"],
        },
        "config_version": version,
        "rules_status": "provisional",
        "freshness": freshness(db, params),
        "today": clock.today().isoformat(),
    }


def present_follow_up(fu: FollowUp, today, customers, names, last_activity: Activity | None, opp: Opportunity | None) -> dict:
    return {
        "id": fu.id,
        "due_date": fu.due_date.isoformat(),
        "status": fu.status,
        "days_overdue": max(0, (today - fu.due_date).days),
        "owner": {"id": fu.owner_user_id, "display_name": names.get(fu.owner_user_id)},
        "customer": customer_brief(customers.get((fu.source_entity, fu.source_customer_id)), fu.source_entity, fu.source_customer_id),
        "opportunity_id": fu.opportunity_id,
        "opp_type": opp.opp_type if opp else None,
        "last_action": {"action_type": last_activity.action_type, "note": last_activity.note,
                        "created_at": last_activity.created_at.isoformat()} if last_activity else None,
        "closed_at": fu.closed_at.isoformat() if fu.closed_at else None,
    }


def follow_up_context(db: Session, fus: list[FollowUp]):
    act_ids = [f.created_by_activity_id for f in fus if f.created_by_activity_id]
    acts = {a.id: a for a in db.execute(select(Activity).where(Activity.id.in_(act_ids))).scalars()} if act_ids else {}
    opp_ids = [f.opportunity_id for f in fus if f.opportunity_id]
    opps = {o.id: o for o in db.execute(select(Opportunity).where(Opportunity.id.in_(opp_ids))).scalars()} if opp_ids else {}
    return acts, opps


@router.get("/today")
def today_view(user: AppUser = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    version, params = active_config(db)
    scope = build_scope(db, user)
    today = clock.today()
    fresh = freshness(db, params)
    stale = {f["entity"] for f in fresh if f["is_stale"]}
    names = user_names(db)

    fus = [f for f in db.execute(
        select(FollowUp).where(FollowUp.owner_user_id == user.id, FollowUp.status == "open", FollowUp.due_date <= today)
        .order_by(FollowUp.due_date)
    ).scalars() if scope.can_see(f.source_entity, f.source_customer_id)]
    due_keys = {(f.source_entity, f.source_customer_id) for f in fus}

    candidates = [
        o for o in db.execute(select(Opportunity).where(Opportunity.status.in_(("open", "snoozed")),
                                                        Opportunity.condition_active.is_(True))).scalars()
        if effective_status(o, today) == "open" and scope.can_see(o.source_entity, o.source_customer_id)
    ]
    hidden_stale = sum(1 for o in candidates if o.source_entity in stale)
    candidates = [o for o in candidates if o.source_entity not in stale]

    by_customer: dict[tuple[str, str], list[Opportunity]] = defaultdict(list)
    for o in candidates:
        by_customer[(o.source_entity, o.source_customer_id)].append(o)
    groups = []
    for key, items in by_customer.items():
        if key in due_keys:
            continue  # already in "follow-ups due": one alert per customer
        items.sort(key=lambda o: o.priority_score, reverse=True)
        groups.append((key, items))
    groups.sort(key=lambda g: g[1][0].priority_score, reverse=True)
    max_cards = int(params["workflow"]["today_max_cards"])
    shown = groups[:max_cards]

    keys = {k for k, _ in shown} | due_keys
    customers = customers_by_key(db, keys)
    acts, opps = follow_up_context(db, fus)
    cards = []
    for key, items in shown:
        best = items[0]
        cards.append({
            "customer": customer_brief(customers.get(key), *key),
            "assignee": {"id": scope.assignees.get(key), "display_name": names.get(scope.assignees.get(key))},
            "opportunity": present_opportunity(best, today),
            "other_signals": [{"id": o.id, "opp_type": o.opp_type} for o in items[1:]],
        })
    return {
        "date": today.isoformat(),
        "freshness": fresh,
        "follow_ups_due": [present_follow_up(f, today, customers, names, acts.get(f.created_by_activity_id), opps.get(f.opportunity_id)) for f in fus],
        "cards": cards,
        "more_count": max(0, len(groups) - len(shown)),
        "hidden_due_to_stale_data": hidden_stale,
        "config_version": version,
        "rules_status": "provisional",
    }
