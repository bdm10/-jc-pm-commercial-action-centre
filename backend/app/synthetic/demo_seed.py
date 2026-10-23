"""Demo-only seed: synthetic users/teams, synthetic import, refresh and a little
synthetic action history so every screen has something to show.

Refuses to run when APP_ENV=production.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app import clock
from app.config import get_settings
from app.importer.load import import_package
from app.models.records import Activity, AppUser, FollowUp, Opportunity, Team, TeamManager, TeamMember
from app.rules.engine import evaluate_cadence, priority
from app.services.audit import audit
from app.services.refresh import run_refresh
from app.services.rule_config import active_config
from app.services.snapshot import load_snapshot
from app.synthetic.generate import generate

DEMO_USERS = [
    # email, name, role, salesperson_code, team
    ("ana.ruiz@example.com", "Ana Ruiz", "sales", "SYN-SP-01", "Equipo Piloto (demo)"),
    ("jordi.puig@example.com", "Jordi Puig", "sales", "SYN-SP-02", "Equipo Piloto (demo)"),
    ("carmen.vidal@example.com", "Carmen Vidal", "sales", "SYN-SP-03", "Equipo Piloto (demo)"),
    ("elena.martin@example.com", "Elena Martín", "manager", None, "Equipo Piloto (demo)"),
    ("david.serra@example.com", "David Serra", "sales", "SYN-SP-04", "Equipo B (demo)"),
    ("lucia.ortega@example.com", "Lucía Ortega", "sales", "SYN-SP-05", "Equipo B (demo)"),
    ("pablo.ferrer@example.com", "Pablo Ferrer", "manager", None, "Equipo B (demo)"),
    ("admin@example.com", "Admin (demo)", "admin", None, None),
]


def reset_all(db: Session) -> None:
    db.execute(text("ALTER TABLE app.audit_log DISABLE TRIGGER audit_log_no_update_delete"))
    db.execute(text(
        "TRUNCATE ai.suggestion, app.observed_outcome, app.follow_up, app.activity, app.opportunity, "
        "app.assignment_override, app.rule_config, app.audit_log, app.team_member, app.team_manager, app.team, "
        "app.app_user, facts.data_issue, facts.purchase, facts.measure_monthly, facts.assignment, "
        "facts.customer_mapping, facts.customer, facts.measure_definition, facts.source_refresh, facts.import_run "
        "RESTART IDENTITY CASCADE"
    ))
    db.execute(text("ALTER TABLE app.audit_log ENABLE TRIGGER audit_log_no_update_delete"))
    db.commit()


def seed_users(db: Session) -> dict[str, AppUser]:
    teams: dict[str, Team] = {}
    users: dict[str, AppUser] = {}
    for email, name, role, code, team in DEMO_USERS:
        u = AppUser(email=email, display_name=name, role=role, salesperson_code=code, active=True)
        db.add(u)
        db.flush()
        users[email] = u
        if team:
            if team not in teams:
                teams[team] = Team(name=team)
                db.add(teams[team])
                db.flush()
            if role == "manager":
                db.add(TeamManager(team_id=teams[team].id, user_id=u.id))
            else:
                db.add(TeamMember(team_id=teams[team].id, user_id=u.id))
    db.commit()
    return users


def _act(db: Session, user: AppUser, o: Opportunity, action: str, days_ago: int, note: str | None,
         follow_up_in: int | None) -> None:
    now = clock.now()
    at = now - dt.timedelta(days=days_ago)
    a = Activity(client_request_id=f"seed-{uuid.uuid4()}", opportunity_id=o.id, source_entity=o.source_entity,
                 source_customer_id=o.source_customer_id, user_id=user.id, action_type=action, note=note,
                 follow_up_date=(clock.today() + dt.timedelta(days=follow_up_in)) if follow_up_in is not None else None,
                 created_at=at)
    db.add(a)
    db.flush()
    if a.follow_up_date:
        db.add(FollowUp(source_entity=o.source_entity, source_customer_id=o.source_customer_id, opportunity_id=o.id,
                        owner_user_id=user.id, due_date=a.follow_up_date, status="open", created_by_activity_id=a.id,
                        created_at=at))
    o.status, o.last_action_at = "in_progress", at
    audit(db, user.id, "activity_recorded", "activity", a.id, {"seed": True, "action_type": action})


def seed_history(db: Session, users: dict[str, AppUser], gen) -> None:
    """Synthetic action history so follow-ups, team view and observed outcomes have content."""
    now = clock.now()
    version, params = active_config(db)
    ana, jordi, carmen, david = (users[e] for e in ("ana.ruiz@example.com", "jordi.puig@example.com",
                                                    "carmen.vidal@example.com", "david.serra@example.com"))
    by_code = {u.salesperson_code: u for u in users.values() if u.salesperson_code}
    arche = {(c.entity, c.cid): c.archetype for c in gen.customers}
    sp_of = {(c.entity, c.cid): c.salesperson for c in gen.customers}

    def opps_for(user: AppUser) -> list[Opportunity]:
        rows = db.execute(select(Opportunity).where(Opportunity.status == "open").order_by(Opportunity.priority_score.desc())).scalars()
        return [o for o in rows if sp_of.get((o.source_entity, o.source_customer_id)) == user.salesperson_code
                and arche.get((o.source_entity, o.source_customer_id)) not in ("outcome_demo",)]

    mine = opps_for(ana)
    # keep the top cards untouched for the Today screen; act on lower-ranked ones
    tail = mine[5:] + mine[:5]
    if len(tail) >= 3:
        _act(db, ana, tail[0], "contacted", 6, "Nota sintética: pidió que volvamos a llamar esta semana.", 0)
        _act(db, ana, tail[1], "no_response", 9, None, -2)
        tail[2].status, tail[2].snoozed_until, tail[2].snooze_reason = "snoozed", clock.today() + dt.timedelta(days=7), "Cierre por vacaciones (sintético)"
        audit(db, ana.id, "opportunity_snoozed", "opportunity", tail[2].id, {"seed": True})
    for user, days_ago, due in ((jordi, 12, -4), (david, 10, -1)):
        o = opps_for(user)
        if o:
            _act(db, user, o[0], "meeting_booked", days_ago, "Nota sintética: visita acordada.", due)
    c_opps = opps_for(carmen)
    if c_opps:
        o = c_opps[-1]
        o.status, o.dismissed_reason, o.dismissed_at, o.dismissed_by_user_id = "dismissed", "already_handled", now - dt.timedelta(days=3), carmen.id
        o.dismissed_note = "Nota sintética: gestionado por otra vía."
        audit(db, carmen.id, "opportunity_dismissed", "opportunity", o.id, {"seed": True})

    # Observed-outcome demo: an opportunity detected 25 days ago (evaluated on the data as it was then),
    # an action 20 days later, and a re-order afterwards in the synthetic facts.
    snap = load_snapshot(db, params, now)
    for key, cf in snap.customers.items():
        if arche.get(key) != "outcome_demo":
            continue
        ctx = snap.contexts[cf.entity]
        then = ctx.as_of - dt.timedelta(days=25)
        past_ctx = dataclasses.replace(ctx, as_of=then, refreshed_at=ctx.refreshed_at - dt.timedelta(days=25))
        past_cf = dataclasses.replace(cf, invoice_days=[d for d in cf.invoice_days if d <= then])
        e = evaluate_cadence(past_cf, past_ctx, params["overdue_cadence"])
        if e.status != "flag":
            continue
        score, band, comps = priority(e, params)
        o = Opportunity(source_entity=cf.entity, source_customer_id=cf.customer_id, opp_type=e.opp_type, status="open",
                        priority_score=score, priority_band=band, priority_components=comps,
                        reason_code=e.reason_code, reason_params={**e.reason_params, "next_action": e.next_action_code},
                        evidence=e.evidence, rule_version=e.rule_version, config_version=version,
                        data_refreshed_at=past_ctx.refreshed_at, first_detected_at=now - dt.timedelta(days=25),
                        last_evaluated_at=now - dt.timedelta(days=25))
        db.add(o)
        db.flush()
        owner = by_code.get(sp_of.get(key) or "")
        if owner:
            _act(db, owner, o, "offer_requested", 20, "Nota sintética: enviar propuesta de reposición.", None)
    db.commit()


def seed_demo(data_dir: Path, as_of: dt.date | None = None, stale_entity: str | None = None) -> dict[str, Any]:
    if get_settings().app_env == "production":
        raise SystemExit("seed-demo is disabled in production")
    from app.db import session_factory

    as_of = as_of or clock.today()
    db = session_factory()()
    try:
        reset_all(db)
        users = seed_users(db)
        summary, gen = generate(data_dir, as_of, stale_entity=stale_entity)
        res, run = import_package(db, data_dir, force=True)
        if not res.ok:
            raise SystemExit(f"synthetic package rejected: {res.fatal}")
        stats = run_refresh(db)
        seed_history(db, users, gen)
        stats2 = run_refresh(db)
        return {"generated": summary, "import": res.summary(), "refresh": stats, "refresh_after_history": stats2}
    finally:
        db.close()
