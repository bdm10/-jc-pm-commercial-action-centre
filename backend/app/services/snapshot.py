"""Load the current facts snapshot into the rules engine's input structures."""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import clock
from app.models import facts as F
from app.rules.engine import CustomerFacts, EntityContext, MeasureInfo, Transfer, last_complete_month


@dataclass
class Issue:
    severity: str
    issue_code: str
    source_entity: str | None = None
    source_customer_id: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class Snapshot:
    contexts: dict[str, EntityContext]
    customers: dict[tuple[str, str], CustomerFacts]
    measures: dict[str, MeasureInfo]
    issues: list[Issue]


def latest_refreshes(db: Session) -> dict[str, F.SourceRefresh]:
    """Most recent successful source refresh per entity."""
    rows = db.execute(
        select(F.SourceRefresh)
        .join(F.ImportRun, F.ImportRun.id == F.SourceRefresh.run_id)
        .where(F.ImportRun.status == "loaded")
        .order_by(F.SourceRefresh.id.desc())
    ).scalars()
    out: dict[str, F.SourceRefresh] = {}
    for r in rows:
        out.setdefault(r.source_entity, r)
    return out


def is_stale(refreshed_at: dt.datetime, params: dict[str, Any], now: dt.datetime | None = None) -> bool:
    now = now or clock.now()
    return (now - refreshed_at) > dt.timedelta(hours=float(params["freshness"]["stale_after_hours"]))


def _measure_info(m: F.MeasureDefinition) -> MeasureInfo:
    return MeasureInfo(
        code=m.measure_code,
        name_es=m.display_name_es,
        name_en=m.display_name_en,
        certified_measure_name=m.certified_measure_name,
        source_model=m.source_model,
        certification_status=m.certification_status,
        unit=m.unit,
        additive_over_months=m.additive_over_months,
    )


def load_snapshot(db: Session, params: dict[str, Any], now: dt.datetime | None = None,
                  keys: set[tuple[str, str]] | None = None) -> Snapshot:
    """Load facts for all customers, or only for `keys` plus their mapped counterparts (detail views)."""
    now = now or clock.now()
    existing_keys = {(e, c) for e, c in db.execute(select(F.Customer.source_entity, F.Customer.source_customer_id))}
    if keys is not None:
        keys = set(keys)
        for m in db.execute(select(F.CustomerMapping)).scalars():
            a, b = (m.from_entity, m.from_customer_id), (m.to_entity, m.to_customer_id)
            if a in keys or b in keys:
                keys |= {a, b}

    def wanted(entity: str, cid: str) -> bool:
        return keys is None or (entity, cid) in keys

    issues: list[Issue] = []
    measures = {m.measure_code: _measure_info(m) for m in db.execute(select(F.MeasureDefinition)).scalars()}
    primary_codes: dict[str, str] = params["measures"]["primary_measure_code"]

    contexts: dict[str, EntityContext] = {}
    for entity, r in latest_refreshes(db).items():
        stale = is_stale(r.source_refreshed_at, params, now)
        as_of = r.source_refreshed_at.astimezone(clock.BUSINESS_TZ).date()
        measure = measures.get(primary_codes.get(entity, ""))
        if measure is None:
            issues.append(Issue("error", "missing_measure_definition", entity,
                                detail={"measure_code": primary_codes.get(entity)}))
        if stale:
            issues.append(Issue("error", "stale_source", entity, detail={
                "refreshed_at": r.source_refreshed_at.isoformat(),
                "stale_after_hours": params["freshness"]["stale_after_hours"],
            }))
        contexts[entity] = EntityContext(
            entity=entity,
            source_model=r.source_model,
            refreshed_at=r.source_refreshed_at,
            as_of=as_of,
            period_start=r.period_start,
            period_end=r.period_end,
            data_classification=r.data_classification,
            is_stale=stale,
            last_complete_month=last_complete_month(as_of, int(params["freshness"]["month_complete_lag_days"])),
            measure=measure,
        )

    customers: dict[tuple[str, str], CustomerFacts] = {}
    for c in db.execute(select(F.Customer)).scalars():
        if not wanted(c.source_entity, c.source_customer_id):
            continue
        customers[(c.source_entity, c.source_customer_id)] = CustomerFacts(
            entity=c.source_entity,
            customer_id=c.source_customer_id,
            display_name=c.display_name,
            is_intercompany=c.is_intercompany,
            seasonal_flag=c.seasonal_flag,
            transfer_cohort=c.transfer_cohort,
        )

    for entity, code in primary_codes.items():
        stmt = select(F.MeasureMonthly.source_customer_id, F.MeasureMonthly.month, F.MeasureMonthly.value).where(
            F.MeasureMonthly.source_entity == entity, F.MeasureMonthly.measure_code == code
        )
        if keys is not None:
            stmt = stmt.where(F.MeasureMonthly.source_customer_id.in_([c for e, c in keys if e == entity]))
        rows = db.execute(stmt)
        for cid, month, value in rows:
            cf = customers.get((entity, cid))
            if cf is not None:
                cf.monthly[month] = Decimal(value)

    days: dict[tuple[str, str], set[dt.date]] = defaultdict(set)
    pstmt = select(F.Purchase.source_entity, F.Purchase.source_customer_id, F.Purchase.document_date).where(
        F.Purchase.document_type == "invoice"
    )
    if keys is not None:
        pstmt = pstmt.where(F.Purchase.source_customer_id.in_([c for _, c in keys]))
    for entity, cid, d in db.execute(pstmt):
        days[(entity, cid)].add(d)
    for key, ds in days.items():
        if key in customers:
            customers[key].invoice_days = sorted(ds)

    _apply_mappings(db, customers, issues, existing_keys)

    # Rows rejected on import (conflicting duplicates, unregistered measures...) leave a customer's
    # history incomplete. Absent rows would otherwise read as zero sales, so suppress that customer.
    incomplete = db.execute(
        select(F.DataIssue.source_entity, F.DataIssue.source_customer_id).where(
            F.DataIssue.stage == "import", F.DataIssue.severity == "error",
            F.DataIssue.source_customer_id.is_not(None),
            F.DataIssue.detail["file"].as_string().in_(["measure_monthly.csv", "purchases.csv"]),
        )
    ).all()
    for entity, cid in set(incomplete):
        if not wanted(entity, cid):
            continue
        cf = customers.get((entity, cid))
        if cf is not None:
            cf.data_problem = "incomplete_customer_data"
            issues.append(Issue("warning", "incomplete_customer_data", entity, cid,
                                {"reason": "rows rejected on import; recommendations suppressed"}))

    for cf in customers.values():
        if cf.transfer_cohort and cf.inbound is None and cf.outbound is None and cf.mapping_problem is None:
            issues.append(Issue("warning", "unmapped_transfer", cf.entity, cf.customer_id, {"cohort": cf.transfer_cohort}))
        negatives = sorted(m.isoformat() for m, v in cf.monthly.items() if v < 0)
        if negatives:
            issues.append(Issue("info", "negative_month_value", cf.entity, cf.customer_id, {"months": negatives[:6]}))

    return Snapshot(contexts=contexts, customers=customers, measures=measures, issues=issues)


def _apply_mappings(db: Session, customers: dict[tuple[str, str], CustomerFacts], issues: list[Issue],
                    existing_keys: set[tuple[str, str]]) -> None:
    """Attach APPROVED, unambiguous mappings. Everything else becomes a data issue.

    Customers are never matched by name: the only link is an explicit mapping row.
    """
    mappings = list(db.execute(select(F.CustomerMapping)).scalars())

    def flag(entity: str, cid: str, code: str, detail: dict[str, Any], severity: str = "warning") -> None:
        issues.append(Issue(severity, code, entity, cid, detail))
        cf = customers.get((entity, cid))
        if cf is not None and cf.mapping_problem is None:
            cf.mapping_problem = code

    approved: list[F.CustomerMapping] = []
    for m in mappings:
        detail = {"mapping_ref": m.mapping_ref, "from": f"{m.from_entity}:{m.from_customer_id}", "to": f"{m.to_entity}:{m.to_customer_id}"}
        if m.mapping_status == "rejected":
            continue  # explicitly not the same customer
        if m.mapping_status != "approved":
            flag(m.from_entity, m.from_customer_id, "mapping_not_approved", detail)
            flag(m.to_entity, m.to_customer_id, "mapping_not_approved", detail)
            continue
        missing = [k for k in ((m.from_entity, m.from_customer_id), (m.to_entity, m.to_customer_id)) if k not in existing_keys]
        if missing:
            for e, c in ((m.from_entity, m.from_customer_id), (m.to_entity, m.to_customer_id)):
                flag(e, c, "mapping_customer_not_found", {**detail, "missing": [f"{a}:{b}" for a, b in missing]})
            continue
        if m.transfer_date is None:
            flag(m.to_entity, m.to_customer_id, "mapping_missing_transfer_date", detail)
            flag(m.from_entity, m.from_customer_id, "mapping_missing_transfer_date", detail)
            continue
        approved.append(m)

    by_from: dict[tuple[str, str], list[F.CustomerMapping]] = defaultdict(list)
    by_to: dict[tuple[str, str], list[F.CustomerMapping]] = defaultdict(list)
    for m in approved:
        by_from[(m.from_entity, m.from_customer_id)].append(m)
        by_to[(m.to_entity, m.to_customer_id)].append(m)

    for m in approved:
        fk, tk = (m.from_entity, m.from_customer_id), (m.to_entity, m.to_customer_id)
        if len(by_from[fk]) > 1 or len(by_to[tk]) > 1:
            detail = {"mapping_ref": m.mapping_ref, "from": f"{fk[0]}:{fk[1]}", "to": f"{tk[0]}:{tk[1]}"}
            flag(fk[0], fk[1], "ambiguous_mapping", detail)
            flag(tk[0], tk[1], "ambiguous_mapping", detail)
            continue
        t = Transfer(
            mapping_ref=m.mapping_ref,
            from_entity=m.from_entity,
            from_customer_id=m.from_customer_id,
            to_entity=m.to_entity,
            to_customer_id=m.to_customer_id,
            transfer_date=m.transfer_date,
            cohort=m.cohort,
            approved_by=m.approved_by,
            approved_at=m.approved_at,
        )
        if tk in customers:
            customers[tk].inbound = t
        if fk in customers:
            customers[fk].outbound = t

    # Deduplicate issues raised once per mapping row for the same customer and code.
    seen: set[tuple[Any, ...]] = set()
    unique: list[Issue] = []
    for i in issues:
        key = (i.issue_code, i.source_entity, i.source_customer_id, i.detail.get("mapping_ref"))
        if key not in seen:
            seen.add(key)
            unique.append(i)
    issues[:] = unique
