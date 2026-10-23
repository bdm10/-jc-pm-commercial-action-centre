"""Refresh job: duplicates, stale data, mapping failures, cooldown, resurfacing and observed outcomes."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import func, select

from app import clock
from app.importer.load import import_package
from app.models import facts as F
from app.models.records import ObservedOutcome, Opportunity
from app.services.refresh import run_refresh
from app.synthetic.generate import generate
from tests.conftest import AS_OF, NOW


def active_count(db) -> int:
    return db.execute(select(func.count()).select_from(Opportunity).where(
        Opportunity.status.in_(("open", "in_progress", "snoozed")))).scalar_one()


def keys_by_archetype(gen, archetype: str) -> list[tuple[str, str]]:
    return [(c.entity, c.cid) for c in gen.customers if c.archetype == archetype]


def test_repeated_refresh_creates_no_duplicates(seeded):
    db = seeded["db"]
    n = active_count(db)
    assert n > 0
    for _ in range(3):
        stats = run_refresh(db)
        assert stats["created"] == 0
    assert active_count(db) == n
    dupes = db.execute(select(Opportunity.source_entity, Opportunity.source_customer_id, Opportunity.opp_type, func.count())
                       .group_by(Opportunity.source_entity, Opportunity.source_customer_id, Opportunity.opp_type)
                       .having(func.count() > 1)).all()
    assert dupes == []


def test_planted_positive_cases_are_flagged_and_negatives_are_not(seeded):
    db, gen = seeded["db"], seeded["gen"]
    flagged = {(o.source_entity, o.source_customer_id, o.opp_type) for o in db.execute(select(Opportunity)).scalars()}
    for k in keys_by_archetype(gen, "transfer_pending"):
        assert (*k, "transfer_no_reorder") in flagged
    for k in keys_by_archetype(gen, "declining"):
        assert (*k, "declining_purchases") in flagged
    for k in keys_by_archetype(gen, "overdue"):
        assert (*k, "overdue_cadence") in flagged
    for arch in ("transfer_grace", "transfer_reordered", "seasonal", "small_decline", "mild_decline", "slightly_late",
                 "intercompany", "transfer_unmapped", "transfer_provisional", "ambiguous_mapping", "transfer_pending_origin"):
        for k in keys_by_archetype(gen, arch):
            assert not any(f[:2] == k for f in flagged), (arch, k)


def test_mapping_failures_become_data_issues_not_recommendations(seeded):
    db, gen = seeded["db"], seeded["gen"]
    issues = {(i.issue_code, i.source_entity, i.source_customer_id) for i in db.execute(select(F.DataIssue)).scalars()}
    for arch, code in (("transfer_unmapped", "unmapped_transfer"), ("transfer_provisional", "mapping_not_approved"),
                       ("ambiguous_mapping", "ambiguous_mapping"), ("mapped_to_missing_customer", "mapping_customer_not_found")):
        for k in keys_by_archetype(gen, arch):
            assert (code, *k) in issues, (arch, code)


def test_same_name_customers_are_not_linked(seeded):
    db, gen = seeded["db"], seeded["gen"]
    twins = [c for c in gen.customers if gen.notes.get(c.cid, "").startswith("name_twin")]
    assert len(twins) == 2 and twins[0].name == twins[1].name and twins[0].entity != twins[1].entity
    ids = {t.cid for t in twins}
    links = db.execute(select(F.CustomerMapping).where(
        F.CustomerMapping.from_customer_id.in_(ids) | F.CustomerMapping.to_customer_id.in_(ids))).scalars().all()
    assert links == []


def test_stale_source_suppresses_new_recommendations(db, tmp_path):
    from app.synthetic.demo_seed import seed_users

    seed_users(db)
    generate(tmp_path, AS_OF, stale_entity="PM")
    import_package(db, tmp_path, force=True)
    stats = run_refresh(db)
    assert stats["created"] > 0
    pm_new = db.execute(select(func.count()).select_from(Opportunity).where(Opportunity.source_entity == "PM")).scalar_one()
    assert pm_new == 0
    stale = db.execute(select(F.DataIssue).where(F.DataIssue.issue_code == "stale_source")).scalars().all()
    assert [i.source_entity for i in stale] == ["PM"]


def test_existing_opportunities_become_unconfirmed_when_data_goes_stale(seeded):
    db = seeded["db"]
    assert active_count(db) > 0
    clock.freeze(NOW + dt.timedelta(days=4))  # no new extract for 4 days (> 48h cutoff)
    stats = run_refresh(db)
    assert stats["unconfirmed"] > 0 and stats["resolved"] == 0
    still_confirmed = db.execute(select(func.count()).select_from(Opportunity).where(Opportunity.condition_active.is_(True))).scalar_one()
    assert still_confirmed == 0


def test_dismissed_opportunity_is_not_raised_again_during_cooldown(seeded):
    db = seeded["db"]
    o = db.execute(select(Opportunity).where(Opportunity.status == "open").limit(1)).scalar_one()
    o.status, o.dismissed_reason, o.dismissed_at = "dismissed", "not_relevant", clock.now()
    db.commit()
    stats = run_refresh(db)
    assert stats["cooldown_skipped"] >= 1
    same = db.execute(select(func.count()).select_from(Opportunity).where(
        Opportunity.source_entity == o.source_entity, Opportunity.source_customer_id == o.source_customer_id,
        Opportunity.opp_type == o.opp_type)).scalar_one()
    assert same == 1


def test_snooze_expiry_resurfaces_the_opportunity(seeded):
    db = seeded["db"]
    o = db.execute(select(Opportunity).where(Opportunity.status == "open").limit(1)).scalar_one()
    o.status, o.snoozed_until = "snoozed", clock.today()
    db.commit()
    run_refresh(db)
    db.refresh(o)
    assert o.status == "open" and o.reason_params.get("resurfaced") == "snooze_ended"


def test_observed_outcome_is_recorded_and_labelled(seeded_history):
    db, gen = seeded_history["db"], seeded_history["gen"]
    key = keys_by_archetype(gen, "outcome_demo")[0]
    o = db.execute(select(Opportunity).where(Opportunity.source_entity == key[0], Opportunity.source_customer_id == key[1],
                                             Opportunity.opp_type == "overdue_cadence")).scalar_one()
    assert o.status == "resolved" and o.resolution_code == "condition_cleared"
    oc = db.execute(select(ObservedOutcome).where(ObservedOutcome.opportunity_id == o.id)).scalar_one()
    assert oc.outcome_code == "order_observed_after_action"
    assert oc.observed_document_date >= oc.first_action_at.astimezone(clock.BUSINESS_TZ).date()
