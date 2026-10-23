"""Deterministic opportunity rules (pure functions, no database access).

Three opportunity types:
  * transfer_no_reorder  - customer moved between entities under an APPROVED
                           mapping and has not ordered in the receiving entity.
  * declining_purchases  - certified measure for the last N complete months is
                           materially below the same months one year earlier.
  * overdue_cadence      - customer is late against their own usual ordering
                           interval.

All thresholds are provisional (see app/rules/config.py). Every evaluation
returns a status, a machine-readable reason and the evidence used, with
provenance for each figure. Unreliable inputs (stale source, unapproved or
ambiguous mapping, missing measure definition) SUPPRESS the recommendation and
surface a data issue instead of a customer-risk signal.

The engine never sums JC and PM figures, never matches customers by name and
never labels a customer as "lost".
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass, field
from decimal import Decimal
from statistics import median
from typing import Any, Literal

from app.rules.config import RULES_VERSION

Status = Literal["flag", "not_met", "not_evaluable", "suppressed", "excluded"]


# --------------------------------------------------------------------------- inputs


@dataclass(frozen=True)
class MeasureInfo:
    code: str
    name_es: str
    name_en: str
    certified_measure_name: str
    source_model: str
    certification_status: str  # certified | provisional | synthetic
    unit: str
    additive_over_months: bool


@dataclass(frozen=True)
class EntityContext:
    entity: str
    source_model: str
    refreshed_at: dt.datetime
    as_of: dt.date  # business date of the source refresh: rules never look past it
    period_start: dt.date
    period_end: dt.date
    data_classification: str
    is_stale: bool
    last_complete_month: dt.date  # first day of the last complete calendar month
    measure: MeasureInfo | None


@dataclass(frozen=True)
class Transfer:
    mapping_ref: str
    from_entity: str
    from_customer_id: str
    to_entity: str
    to_customer_id: str
    transfer_date: dt.date
    cohort: str | None
    approved_by: str | None
    approved_at: dt.date | None


@dataclass
class CustomerFacts:
    entity: str
    customer_id: str
    display_name: str
    is_intercompany: bool = False
    seasonal_flag: bool | None = None
    transfer_cohort: str | None = None
    monthly: dict[dt.date, Decimal] = field(default_factory=dict)  # primary measure by first-of-month
    invoice_days: list[dt.date] = field(default_factory=list)  # sorted distinct invoice dates
    inbound: Transfer | None = None  # approved mapping INTO this customer
    outbound: Transfer | None = None  # approved mapping OUT of this customer
    mapping_problem: str | None = None  # issue code when a mapping touching this customer is unusable
    data_problem: str | None = None  # issue code when this customer's facts were incomplete on import


@dataclass
class Evaluation:
    opp_type: str
    status: Status
    detail_code: str
    detail_params: dict[str, Any] = field(default_factory=dict)
    reason_code: str | None = None
    reason_params: dict[str, Any] = field(default_factory=dict)
    next_action_code: str | None = None
    evidence: list[dict[str, Any]] = field(default_factory=list)
    size_value: float | None = None  # account size used for priority (certified measure, own entity)
    size_evidence_id: str | None = None
    urgency: float = 1.0
    rule_version: str = RULES_VERSION


# --------------------------------------------------------------------------- helpers


def month_start(d: dt.date) -> dt.date:
    return d.replace(day=1)


def add_months(d: dt.date, n: int) -> dt.date:
    y, m = divmod(d.month - 1 + n, 12)
    return dt.date(d.year + y, m + 1, 1)


def month_end(first_of_month: dt.date) -> dt.date:
    return add_months(first_of_month, 1) - dt.timedelta(days=1)


def months_between(start: dt.date, end: dt.date) -> list[dt.date]:
    """Inclusive list of month starts."""
    out, cur = [], month_start(start)
    while cur <= end:
        out.append(cur)
        cur = add_months(cur, 1)
    return out


def last_complete_month(refreshed_on: dt.date, lag_days: int) -> dt.date:
    """Month M counts as complete once the refresh is `lag_days` into M+1."""
    return add_months(month_start(refreshed_on - dt.timedelta(days=lag_days)), -1)


def window_sum(monthly: dict[dt.date, Decimal], start: dt.date, n_months: int) -> Decimal:
    # Contract: months without a row had no sales (the extract is complete for its declared period).
    return sum((monthly.get(add_months(start, i), Decimal(0)) for i in range(n_months)), Decimal(0))


def first_activity_month(c: CustomerFacts) -> dt.date | None:
    candidates = [m for m, v in c.monthly.items() if v != 0]
    if c.invoice_days:
        candidates.append(month_start(c.invoice_days[0]))
    return min(candidates) if candidates else None


def _period(start: dt.date, end: dt.date) -> dict[str, str]:
    return {"start": start.isoformat(), "end": end.isoformat()}


def _measure_provenance(ctx: EntityContext, start: dt.date, end: dt.date, derivation: str) -> dict[str, Any]:
    m = ctx.measure
    assert m is not None
    return {
        "type": "certified_measure" if m.certification_status == "certified" else f"{m.certification_status}_measure",
        "measure_code": m.code,
        "measure_name": m.certified_measure_name,
        "certification_status": m.certification_status,
        "source_model": m.source_model,
        "refreshed_at": ctx.refreshed_at.isoformat(),
        "period": _period(start, end),
        "derivation": derivation,
    }


def _doc_provenance(ctx: EntityContext, start: dt.date | None = None, end: dt.date | None = None) -> dict[str, Any]:
    p: dict[str, Any] = {
        "type": "source_documents",
        "source_model": ctx.source_model,
        "refreshed_at": ctx.refreshed_at.isoformat(),
        "certification_status": ctx.data_classification,
    }
    if start and end:
        p["period"] = _period(start, end)
    return p


def _calc_provenance(formula_key: str, inputs: list[str]) -> dict[str, Any]:
    return {"type": "app_calculation", "formula_key": formula_key, "inputs": inputs, "certification_status": "provisional"}


def _mapping_provenance(t: Transfer) -> dict[str, Any]:
    return {
        "type": "approved_mapping",
        "mapping_ref": t.mapping_ref,
        "approved_by": t.approved_by,
        "approved_at": t.approved_at.isoformat() if t.approved_at else None,
        "certification_status": "approved_mapping",
    }


def ev(eid: str, label_key: str, kind: str, value: Any, entity: str | None, provenance: dict[str, Any], **extra: Any) -> dict[str, Any]:
    item = {"id": eid, "label_key": label_key, "kind": kind, "value": value, "entity": entity, "provenance": provenance}
    item.update(extra)
    return item


def _money(v: Decimal) -> float:
    return float(round(v, 2))


# --------------------------------------------------------------------------- gatekeeping


def _gate(c: CustomerFacts, ctx: EntityContext, opp_type: str) -> Evaluation | None:
    """Conditions that stop any rule from producing a recommendation."""
    if ctx.is_stale:
        return Evaluation(opp_type, "suppressed", "stale_source", {"refreshed_at": ctx.refreshed_at.isoformat()})
    if c.is_intercompany:
        return Evaluation(opp_type, "excluded", "intercompany")
    if c.data_problem:
        return Evaluation(opp_type, "suppressed", c.data_problem)
    if c.mapping_problem:
        return Evaluation(opp_type, "suppressed", c.mapping_problem)
    if c.transfer_cohort and c.inbound is None and c.outbound is None:
        return Evaluation(opp_type, "suppressed", "unmapped_transfer", {"cohort": c.transfer_cohort})
    return None


# --------------------------------------------------------------------------- rules


def evaluate_transfer(
    c: CustomerFacts,
    ctx: EntityContext,
    counterpart: CustomerFacts | None,
    counterpart_ctx: EntityContext | None,
    p: dict[str, Any],
) -> Evaluation:
    t_type = "transfer_no_reorder"
    if not p["enabled"]:
        return Evaluation(t_type, "excluded", "rule_disabled")
    gated = _gate(c, ctx, t_type)
    if gated:
        return gated
    t = c.inbound
    if t is None:
        return Evaluation(t_type, "excluded", "not_transferred")
    if counterpart is None or counterpart_ctx is None:
        return Evaluation(t_type, "suppressed", "mapping_customer_not_found", {"mapping_ref": t.mapping_ref})

    days_since = (ctx.as_of - t.transfer_date).days
    if days_since < 0:
        return Evaluation(t_type, "not_met", "transfer_in_future", {"transfer_date": t.transfer_date.isoformat()})
    if days_since <= p["grace_days"]:
        return Evaluation(
            t_type,
            "not_met",
            "within_grace",
            {"grace_ends": (t.transfer_date + dt.timedelta(days=p["grace_days"])).isoformat(), "days_since_transfer": days_since},
        )
    if days_since > p["max_days_since_transfer"]:
        return Evaluation(t_type, "excluded", "transfer_too_old", {"days_since_transfer": days_since})

    orders_since = [d for d in c.invoice_days if t.transfer_date <= d <= ctx.as_of]
    if orders_since:
        return Evaluation(t_type, "not_met", "reordered", {"first_order_date": orders_since[0].isoformat()})

    lookback_start = add_months(month_start(t.transfer_date), -p["pre_transfer_lookback_months"])
    pre_orders = [d for d in counterpart.invoice_days if lookback_start <= d < t.transfer_date]
    if len(pre_orders) < p["min_orders_before_transfer"]:
        return Evaluation(
            t_type,
            "excluded",
            "inactive_before_transfer",
            {"orders_before_transfer": len(pre_orders), "required": p["min_orders_before_transfer"]},
        )

    e = Evaluation(t_type, "flag", "condition_met")
    e.reason_code = "transfer_no_reorder"
    e.next_action_code = "confirm_first_order"
    e.reason_params = {
        "from_entity": t.from_entity,
        "to_entity": t.to_entity,
        "transfer_date": t.transfer_date.isoformat(),
        "days_since_transfer": days_since,
        "grace_days": p["grace_days"],
    }
    e.evidence = [
        ev("e1", "ev.transfer_date", "date", t.transfer_date.isoformat(), t.to_entity, _mapping_provenance(t),
           from_entity=t.from_entity, from_customer_id=t.from_customer_id, cohort=t.cohort),
        ev("e2", "ev.days_since_transfer", "days", days_since, t.to_entity,
           _calc_provenance("days_between", ["e1", "data_as_of"]), data_as_of=ctx.as_of.isoformat()),
        ev("e3", "ev.orders_since_transfer", "count", 0, t.to_entity,
           _doc_provenance(ctx, t.transfer_date, ctx.as_of)),
        ev("e4", "ev.orders_before_transfer", "count", len(pre_orders), t.from_entity,
           _doc_provenance(counterpart_ctx, lookback_start, t.transfer_date - dt.timedelta(days=1))),
        ev("e5", "ev.last_order_before_transfer", "date", pre_orders[-1].isoformat(), t.from_entity,
           _doc_provenance(counterpart_ctx)),
    ]
    # Size: the certified measure in the ORIGIN entity for the months before the transfer.
    # Shown with its entity label and never added to receiving-entity figures.
    if counterpart_ctx.measure and counterpart_ctx.measure.additive_over_months:
        size_end = add_months(month_start(t.transfer_date), -1)
        size_start = add_months(size_end, -11)
        size = window_sum(counterpart.monthly, size_start, 12)
        e.evidence.append(
            ev("e6", "ev.pre_transfer_12m_value", "money", _money(size), t.from_entity,
               _measure_provenance(counterpart_ctx, size_start, month_end(size_end), "sum_of_monthly_values"),
               unit=counterpart_ctx.measure.unit)
        )
        e.size_value, e.size_evidence_id = float(size), "e6"
    e.urgency = 1.0 + min(1.0, (days_since - p["grace_days"]) / 60.0)
    return e


def evaluate_decline(c: CustomerFacts, ctx: EntityContext, p: dict[str, Any]) -> Evaluation:
    t_type = "declining_purchases"
    if not p["enabled"]:
        return Evaluation(t_type, "excluded", "rule_disabled")
    gated = _gate(c, ctx, t_type)
    if gated:
        return gated
    if c.outbound and c.outbound.transfer_date <= ctx.as_of:
        return Evaluation(t_type, "excluded", "transferred_out", {"to_entity": c.outbound.to_entity,
                                                                 "transfer_date": c.outbound.transfer_date.isoformat()})
    if ctx.measure is None:
        return Evaluation(t_type, "suppressed", "missing_measure_definition")
    if not ctx.measure.additive_over_months:
        return Evaluation(t_type, "suppressed", "measure_not_additive", {"measure_code": ctx.measure.code})

    n = int(p["window_months"])
    cur_end = ctx.last_complete_month
    cur_start = add_months(cur_end, -(n - 1))
    prior_start = add_months(cur_start, -12)
    prior_end = add_months(cur_end, -12)
    if prior_start < month_start(ctx.period_start):
        return Evaluation(t_type, "not_evaluable", "extract_period_too_short",
                          {"needed_from": prior_start.isoformat(), "extract_from": ctx.period_start.isoformat()})

    required = max(int(p["min_history_months"]), n + 12)
    first = first_activity_month(c)
    history = len(months_between(first, cur_end)) if first and first <= cur_end else 0
    if history < required:
        return Evaluation(t_type, "not_evaluable", "insufficient_history", {"months": history, "required": required})

    current = window_sum(c.monthly, cur_start, n)
    prior = window_sum(c.monthly, prior_start, n)
    params = {
        "current_start": cur_start.isoformat(), "current_end": month_end(cur_end).isoformat(),
        "prior_start": prior_start.isoformat(), "prior_end": month_end(prior_end).isoformat(),
    }
    if prior < Decimal(str(p["min_prior_value"])):
        return Evaluation(t_type, "not_met", "below_materiality", {**params, "prior": _money(prior)})
    change_pct = float((current - prior) / prior * 100)
    abs_decline = prior - current
    if change_pct > -float(p["decline_threshold_pct"]):
        return Evaluation(t_type, "not_met", "change_within_threshold", {**params, "change_pct": round(change_pct, 1)})
    if abs_decline < Decimal(str(p["min_abs_decline"])):
        return Evaluation(t_type, "not_met", "below_materiality", {**params, "abs_decline": _money(abs_decline)})

    e = Evaluation(t_type, "flag", "condition_met")
    e.reason_code = "declining_purchases"
    e.next_action_code = "review_demand"
    e.reason_params = {"entity": c.entity, "change_pct": round(change_pct, 1), **params}
    e.evidence = [
        ev("e1", "ev.current_window_value", "money", _money(current), c.entity,
           _measure_provenance(ctx, cur_start, month_end(cur_end), "sum_of_monthly_values"), unit=ctx.measure.unit),
        ev("e2", "ev.prior_window_value", "money", _money(prior), c.entity,
           _measure_provenance(ctx, prior_start, month_end(prior_end), "sum_of_monthly_values"), unit=ctx.measure.unit),
        ev("e3", "ev.change_pct", "pct", round(change_pct, 1), c.entity, _calc_provenance("pct_change", ["e1", "e2"])),
        ev("e4", "ev.abs_change", "money", _money(current - prior), c.entity,
           _calc_provenance("difference", ["e1", "e2"]), unit=ctx.measure.unit),
    ]
    if c.invoice_days:
        e.evidence.append(ev("e5", "ev.last_order", "date", c.invoice_days[-1].isoformat(), c.entity, _doc_provenance(ctx)))
    size_start = add_months(prior_end, -11)
    size = window_sum(c.monthly, size_start, 12)
    e.evidence.append(
        ev("e6", "ev.prior_12m_value", "money", _money(size), c.entity,
           _measure_provenance(ctx, size_start, month_end(prior_end), "sum_of_monthly_values"), unit=ctx.measure.unit)
    )
    e.size_value, e.size_evidence_id = float(size), "e6"
    e.urgency = 1.0 + min(1.0, (-change_pct - float(p["decline_threshold_pct"])) / 50.0)
    return e


def evaluate_cadence(c: CustomerFacts, ctx: EntityContext, p: dict[str, Any]) -> Evaluation:
    t_type = "overdue_cadence"
    if not p["enabled"]:
        return Evaluation(t_type, "excluded", "rule_disabled")
    gated = _gate(c, ctx, t_type)
    if gated:
        return gated
    if c.outbound and c.outbound.transfer_date <= ctx.as_of:
        return Evaluation(t_type, "excluded", "transferred_out", {"to_entity": c.outbound.to_entity,
                                                                 "transfer_date": c.outbound.transfer_date.isoformat()})
    if p["exclude_seasonal"] and c.seasonal_flag:
        return Evaluation(t_type, "excluded", "seasonal_account")

    lookback_start = add_months(month_start(ctx.as_of), -int(p["lookback_months"]))
    if c.inbound:
        lookback_start = max(lookback_start, c.inbound.transfer_date)
    days = [d for d in c.invoice_days if lookback_start <= d <= ctx.as_of]
    if len(days) < p["min_orders"]:
        return Evaluation(t_type, "not_evaluable", "insufficient_orders", {"orders": len(days), "required": p["min_orders"]})

    intervals = [(b - a).days for a, b in zip(days, days[1:])]
    typical = int(math.floor(median(intervals) + 0.5))
    if typical > p["max_typical_interval_days"]:
        return Evaluation(t_type, "excluded", "infrequent_buyer", {"typical_interval_days": typical})
    last = days[-1]
    days_since = (ctx.as_of - last).days
    threshold_days = max(math.ceil(typical * float(p["tolerance_factor"])), typical + int(p["min_days_overdue"]))
    expected_by = last + dt.timedelta(days=typical)
    if days_since < threshold_days:
        return Evaluation(t_type, "not_met", "within_cadence",
                          {"typical_interval_days": typical, "days_since_last": days_since,
                           "alert_from": (last + dt.timedelta(days=threshold_days)).isoformat()})

    e = Evaluation(t_type, "flag", "condition_met")
    e.reason_code = "overdue_cadence"
    e.next_action_code = "remind_reorder"
    e.reason_params = {
        "entity": c.entity,
        "typical_interval_days": typical,
        "days_since_last": days_since,
        "last_order_date": last.isoformat(),
        "expected_by": expected_by.isoformat(),
    }
    e.evidence = [
        ev("e1", "ev.last_order", "date", last.isoformat(), c.entity, _doc_provenance(ctx)),
        ev("e2", "ev.days_since_last", "days", days_since, c.entity,
           _calc_provenance("days_between", ["e1", "data_as_of"]), data_as_of=ctx.as_of.isoformat()),
        ev("e3", "ev.typical_interval", "days", typical, c.entity,
           _calc_provenance("median_interval", ["e4"])),
        ev("e4", "ev.orders_in_lookback", "count", len(days), c.entity, _doc_provenance(ctx, lookback_start, ctx.as_of)),
        ev("e5", "ev.expected_by", "date", expected_by.isoformat(), c.entity, _calc_provenance("date_plus_days", ["e1", "e3"])),
    ]
    if ctx.measure and ctx.measure.additive_over_months:
        size_start = add_months(ctx.last_complete_month, -11)
        size = window_sum(c.monthly, size_start, 12)
        e.evidence.append(
            ev("e6", "ev.last_12m_value", "money", _money(size), c.entity,
               _measure_provenance(ctx, size_start, month_end(ctx.last_complete_month), "sum_of_monthly_values"),
               unit=ctx.measure.unit)
        )
        e.size_value, e.size_evidence_id = float(size), "e6"
    e.urgency = 1.0 + min(1.0, max(0.0, days_since / typical - float(p["tolerance_factor"])) / 2.0)
    return e


# --------------------------------------------------------------------------- orchestration


def evaluate_customer(
    c: CustomerFacts,
    contexts: dict[str, EntityContext],
    customers: dict[tuple[str, str], CustomerFacts],
    params: dict[str, Any],
) -> list[Evaluation]:
    ctx = contexts.get(c.entity)
    if ctx is None:
        return [Evaluation(t, "suppressed", "no_source_refresh") for t in
                ("transfer_no_reorder", "declining_purchases", "overdue_cadence")]
    counterpart = counterpart_ctx = None
    if c.inbound:
        counterpart = customers.get((c.inbound.from_entity, c.inbound.from_customer_id))
        counterpart_ctx = contexts.get(c.inbound.from_entity)
    return [
        evaluate_transfer(c, ctx, counterpart, counterpart_ctx, params["transfer_no_reorder"]),
        evaluate_decline(c, ctx, params["declining_purchases"]),
        evaluate_cadence(c, ctx, params["overdue_cadence"]),
    ]


def priority(e: Evaluation, params: dict[str, Any]) -> tuple[float, str, dict[str, Any]]:
    """Transparent priority: type weight x value factor x urgency. Returns (score, band, components)."""
    pp = params["priority"]
    weight = float(pp["type_weight"].get(e.opp_type, 1.0))
    size = max(0.0, e.size_value or 0.0)
    value_factor = 1.0 + math.log10(1.0 + size / float(pp["value_scale"]))
    urgency = round(e.urgency, 3)
    score = round(weight * value_factor * urgency, 3)
    band = "high" if score >= pp["high_threshold"] else "medium" if score >= pp["medium_threshold"] else "low"
    components = {
        "type_weight": weight,
        "value_factor": round(value_factor, 3),
        "urgency": urgency,
        "size_value": round(size, 2),
        "size_evidence_id": e.size_evidence_id,
        "formula": "type_weight × (1 + log10(1 + size / value_scale)) × urgency",
        "value_scale": pp["value_scale"],
        "thresholds": {"high": pp["high_threshold"], "medium": pp["medium_threshold"]},
    }
    return score, band, components
