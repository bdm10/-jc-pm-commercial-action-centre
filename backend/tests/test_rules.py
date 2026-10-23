"""Opportunity rules and boundary cases (pure functions, no database)."""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
from decimal import Decimal

import pytest

from app.rules.config import merged_params
from app.rules.engine import (
    CustomerFacts,
    EntityContext,
    MeasureInfo,
    Transfer,
    add_months,
    evaluate_cadence,
    evaluate_customer,
    evaluate_decline,
    evaluate_transfer,
    last_complete_month,
    priority,
)

P = merged_params(None)
AS_OF = dt.date(2026, 10, 16)
TZ = dt.UTC


def measure(entity: str = "JC", additive: bool = True, status: str = "synthetic") -> MeasureInfo:
    return MeasureInfo(f"{entity}_NET_SALES", "Ventas netas", "Net sales", "SYNTHETIC", f"{entity} model", status, "EUR", additive)


def ctx(entity: str = "JC", stale: bool = False, m: MeasureInfo | None | str = "default", period_start: dt.date = dt.date(2024, 4, 1)) -> EntityContext:
    return EntityContext(
        entity=entity, source_model=f"{entity} model", refreshed_at=dt.datetime(2026, 10, 16, 4, tzinfo=TZ), as_of=AS_OF,
        period_start=period_start, period_end=AS_OF, data_classification="synthetic", is_stale=stale,
        last_complete_month=last_complete_month(AS_OF, 3), measure=measure(entity) if m == "default" else m,
    )


def months_flat(start: dt.date, end: dt.date, value: float) -> dict[dt.date, Decimal]:
    out, cur = {}, start
    while cur <= end:
        out[cur] = Decimal(str(value))
        cur = add_months(cur, 1)
    return out


def every(start: dt.date, end: dt.date, days: int) -> list[dt.date]:
    out, d = [], start
    while d <= end:
        out.append(d)
        d += dt.timedelta(days=days)
    return out


# ------------------------------------------------------------------ helpers


def test_last_complete_month_respects_lag():
    assert last_complete_month(dt.date(2026, 10, 16), 3) == dt.date(2026, 9, 1)
    assert last_complete_month(dt.date(2026, 10, 3), 3) == dt.date(2026, 8, 1)  # Sept not yet complete
    assert last_complete_month(dt.date(2026, 10, 4), 3) == dt.date(2026, 9, 1)


# ------------------------------------------------------------------ declining purchases


def decline_customer(prior_value: float, current_value: float, history_from: dt.date = dt.date(2024, 4, 1)) -> CustomerFacts:
    # Window: Apr-Sep 2026 vs Apr-Sep 2025 (last complete month Sep 2026, 6 months).
    monthly = months_flat(history_from, dt.date(2026, 9, 1), prior_value / 6)
    for m in months_flat(dt.date(2026, 4, 1), dt.date(2026, 9, 1), current_value / 6):
        monthly[m] = Decimal(str(current_value / 6))
    return CustomerFacts("JC", "C1", "Test", monthly=monthly, invoice_days=[dt.date(2026, 10, 1)])


@pytest.mark.parametrize("current,expected", [(7500, "flag"), (7506, "not_met"), (0, "flag")])
def test_decline_threshold_boundary(current, expected):
    # prior 10,000 -> 7,500 is exactly -25% (flags); 7,506 is -24.94% (does not)
    e = evaluate_decline(decline_customer(10000, current), ctx(), P["declining_purchases"])
    assert e.status == expected, e
    if expected == "flag":
        assert e.reason_params["change_pct"] <= -25
        assert {ev["label_key"] for ev in e.evidence} >= {"ev.current_window_value", "ev.prior_window_value", "ev.change_pct"}


def test_decline_materiality():
    small = evaluate_decline(decline_customer(2900, 1000), ctx(), P["declining_purchases"])
    assert (small.status, small.detail_code) == ("not_met", "below_materiality")
    p = {**P["declining_purchases"], "min_abs_decline": 5000}
    e = evaluate_decline(decline_customer(10000, 6000), ctx(), p)  # -40% but only 4,000 decline
    assert (e.status, e.detail_code) == ("not_met", "below_materiality")


def test_decline_minimum_history_boundary():
    # needs 18 months of history ending Sep 2026 -> first activity Apr 2025 or earlier
    ok = evaluate_decline(decline_customer(10000, 5000, history_from=dt.date(2025, 4, 1)), ctx(), P["declining_purchases"])
    assert ok.status == "flag"
    short = evaluate_decline(decline_customer(10000, 5000, history_from=dt.date(2025, 5, 1)), ctx(), P["declining_purchases"])
    assert (short.status, short.detail_code) == ("not_evaluable", "insufficient_history")
    assert short.detail_params == {"months": 17, "required": 18}


def test_decline_extract_period_too_short():
    e = evaluate_decline(decline_customer(10000, 5000), ctx(period_start=dt.date(2025, 6, 1)), P["declining_purchases"])
    assert (e.status, e.detail_code) == ("not_evaluable", "extract_period_too_short")


def test_decline_suppressed_without_reliable_measure():
    assert evaluate_decline(decline_customer(10000, 1000), ctx(m=None), P["declining_purchases"]).detail_code == "missing_measure_definition"
    e = evaluate_decline(decline_customer(10000, 1000), ctx(m=measure(additive=False)), P["declining_purchases"])
    assert (e.status, e.detail_code) == ("suppressed", "measure_not_additive")


def test_decline_not_flagged_for_customer_transferred_out():
    c = decline_customer(10000, 1000)
    c.outbound = Transfer("M1", "JC", "C1", "PM", "P1", dt.date(2026, 6, 1), "W1", "owner", dt.date(2026, 5, 1))
    e = evaluate_decline(c, ctx(), P["declining_purchases"])
    assert (e.status, e.detail_code) == ("excluded", "transferred_out")


@pytest.mark.parametrize("attr,value,code,status", [
    ("is_intercompany", True, "intercompany", "excluded"),
    ("mapping_problem", "mapping_not_approved", "mapping_not_approved", "suppressed"),
    ("mapping_problem", "ambiguous_mapping", "ambiguous_mapping", "suppressed"),
    ("data_problem", "incomplete_customer_data", "incomplete_customer_data", "suppressed"),
    ("transfer_cohort", "W3", "unmapped_transfer", "suppressed"),
])
def test_unreliable_or_excluded_customers_never_flag(attr, value, code, status):
    c = decline_customer(10000, 0)
    setattr(c, attr, value)
    for e in (evaluate_decline(c, ctx(), P["declining_purchases"]), evaluate_cadence(c, ctx(), P["overdue_cadence"])):
        assert (e.status, e.detail_code) == (status, code)


def test_stale_source_suppresses_every_rule():
    c = decline_customer(10000, 0)
    for e in evaluate_customer(c, {"JC": ctx(stale=True)}, {("JC", "C1"): c}, P):
        assert (e.status, e.detail_code) == ("suppressed", "stale_source")


# ------------------------------------------------------------------ overdue cadence


def cadence_customer(last: dt.date, interval: int = 20, n: int = 10, seasonal: bool | None = None) -> CustomerFacts:
    days = [last - dt.timedelta(days=interval * i) for i in range(n)][::-1]
    return CustomerFacts("JC", "C2", "Test", invoice_days=days, seasonal_flag=seasonal,
                         monthly=months_flat(dt.date(2025, 1, 1), dt.date(2026, 9, 1), 1000))


@pytest.mark.parametrize("days_since,expected", [(33, "not_met"), (34, "flag")])
def test_cadence_threshold_boundary(days_since, expected):
    # typical 20 days: alert from max(ceil(20*1.5)=30, 20+14=34) = 34 days
    e = evaluate_cadence(cadence_customer(AS_OF - dt.timedelta(days=days_since)), ctx(), P["overdue_cadence"])
    assert e.status == expected
    if expected == "flag":
        assert e.reason_params["typical_interval_days"] == 20
        assert e.reason_params["days_since_last"] == 34


def test_cadence_minimum_orders_boundary():
    assert evaluate_cadence(cadence_customer(AS_OF - dt.timedelta(days=60), n=4), ctx(), P["overdue_cadence"]).detail_code == "insufficient_orders"
    assert evaluate_cadence(cadence_customer(AS_OF - dt.timedelta(days=60), n=5), ctx(), P["overdue_cadence"]).status == "flag"


def test_cadence_seasonal_flag_excludes_but_unknown_is_evaluated():
    last = AS_OF - dt.timedelta(days=60)
    assert evaluate_cadence(cadence_customer(last, seasonal=True), ctx(), P["overdue_cadence"]).detail_code == "seasonal_account"
    assert evaluate_cadence(cadence_customer(last, seasonal=None), ctx(), P["overdue_cadence"]).status == "flag"


def test_cadence_infrequent_buyer_excluded():
    e = evaluate_cadence(cadence_customer(AS_OF - dt.timedelta(days=400), interval=130, n=5), ctx(),
                         {**P["overdue_cadence"], "lookback_months": 60})
    assert e.detail_code == "infrequent_buyer"


def test_cadence_ignores_credit_note_only_activity():
    # invoice_days only ever contains invoices (credit notes are filtered when loading); an empty list is not evaluable
    e = evaluate_cadence(CustomerFacts("JC", "C3", "T"), ctx(), P["overdue_cadence"])
    assert e.detail_code == "insufficient_orders"


# ------------------------------------------------------------------ transfer without reorder


def transfer_pair(days_since: int, pm_orders: list[dt.date] | None = None, jc_orders: int = 6):
    tdate = AS_OF - dt.timedelta(days=days_since)
    t = Transfer("M9", "JC", "J1", "PM", "P1", tdate, "W2", "owner", tdate - dt.timedelta(days=20))
    jc = CustomerFacts("JC", "J1", "Mismo Nombre", invoice_days=[tdate - dt.timedelta(days=15 * (i + 1)) for i in range(jc_orders)][::-1],
                       monthly=months_flat(dt.date(2025, 1, 1), add_months(tdate.replace(day=1), -1), 2000), outbound=t)
    pm = CustomerFacts("PM", "P1", "Mismo Nombre", invoice_days=pm_orders or [], inbound=t)
    return jc, pm


@pytest.mark.parametrize("days,expected,code", [(30, "not_met", "within_grace"), (31, "flag", "condition_met"),
                                                (365, "flag", "condition_met"), (366, "excluded", "transfer_too_old")])
def test_transfer_grace_and_max_boundaries(days, expected, code):
    jc, pm = transfer_pair(days)
    e = evaluate_transfer(pm, ctx("PM"), jc, ctx("JC"), P["transfer_no_reorder"])
    assert (e.status, e.detail_code) == (expected, code)


def test_transfer_reordered_is_not_flagged():
    jc, pm = transfer_pair(60, pm_orders=[AS_OF - dt.timedelta(days=20)])
    e = evaluate_transfer(pm, ctx("PM"), jc, ctx("JC"), P["transfer_no_reorder"])
    assert (e.status, e.detail_code) == ("not_met", "reordered")


def test_transfer_requires_activity_before_transfer():
    jc, pm = transfer_pair(60, jc_orders=1)
    e = evaluate_transfer(pm, ctx("PM"), jc, ctx("JC"), P["transfer_no_reorder"])
    assert (e.status, e.detail_code) == ("excluded", "inactive_before_transfer")


def test_transfer_evidence_keeps_entities_separate():
    jc, pm = transfer_pair(60)
    e = evaluate_transfer(pm, ctx("PM"), jc, ctx("JC"), P["transfer_no_reorder"])
    assert e.status == "flag"
    by_label = {ev["label_key"]: ev for ev in e.evidence}
    # The origin entity's sales are labelled JC and are NOT combined with anything from PM.
    assert by_label["ev.pre_transfer_12m_value"]["entity"] == "JC"
    assert by_label["ev.orders_since_transfer"]["entity"] == "PM"
    assert by_label["ev.transfer_date"]["provenance"]["type"] == "approved_mapping"


def test_transfer_without_counterpart_is_suppressed():
    jc, pm = transfer_pair(60)
    e = evaluate_transfer(pm, ctx("PM"), None, None, P["transfer_no_reorder"])
    assert (e.status, e.detail_code) == ("suppressed", "mapping_customer_not_found")


def test_same_name_without_mapping_is_never_linked():
    jc, pm = transfer_pair(60)
    jc.outbound = pm.inbound = None  # identical names, no mapping
    results = evaluate_customer(pm, {"PM": ctx("PM"), "JC": ctx("JC")}, {("JC", "J1"): jc, ("PM", "P1"): pm}, P)
    assert results[0].detail_code == "not_transferred"


# ------------------------------------------------------------------ priority and labels


def test_priority_is_transparent_and_monotonic():
    jc, pm = transfer_pair(60)
    e = evaluate_transfer(pm, ctx("PM"), jc, ctx("JC"), P["transfer_no_reorder"])
    s1, band, comp = priority(e, P)
    assert comp["formula"] and comp["size_evidence_id"] == "e6"
    bigger = dataclasses.replace(e, size_value=(e.size_value or 0) * 10)
    assert priority(bigger, P)[0] > s1
    assert band in ("high", "medium", "low")


def test_rules_never_label_a_customer_lost():
    c = decline_customer(10000, 0)  # stopped buying entirely
    c.invoice_days = every(dt.date(2025, 1, 5), dt.date(2026, 2, 1), 20)
    text = json.dumps([dataclasses.asdict(e) for e in evaluate_customer(c, {"JC": ctx()}, {("JC", "C1"): c}, P)], default=str).lower()
    assert "lost" not in text and "perdid" not in text
    assert P["lost_customer_definition_approved"] is False
