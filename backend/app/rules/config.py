"""Rule parameters.

EVERY value here is a PROVISIONAL PROTOTYPE ASSUMPTION. None has been approved
by the business (see docs/GAPS.md). Administrators can change them in the app;
each change creates a new, audited config version that is still marked
provisional.
"""

from __future__ import annotations

import copy
from typing import Any

RULES_VERSION = "2026.10-p1"  # bump when rule *logic* changes (parameters are versioned separately)

DEFAULT_PARAMS: dict[str, Any] = {
    "freshness": {
        # Older source refreshes suppress every recommendation for that entity.
        "stale_after_hours": 48,
        # A calendar month is treated as complete once the source refresh is this many days into the next month.
        "month_complete_lag_days": 3,
    },
    "measures": {
        # Which imported measure each rule reads per entity. JC and PM measures are never combined.
        "primary_measure_code": {"JC": "JC_NET_SALES", "PM": "PM_NET_SALES"},
    },
    "transfer_no_reorder": {
        "enabled": True,
        "grace_days": 30,
        "max_days_since_transfer": 365,
        "min_orders_before_transfer": 2,
        "pre_transfer_lookback_months": 12,
    },
    "declining_purchases": {
        "enabled": True,
        # Compare the last N complete months with the same N months one year earlier (seasonality-aware).
        "window_months": 6,
        "min_history_months": 18,
        "decline_threshold_pct": 25,
        "min_prior_value": 3000,
        "min_abs_decline": 1500,
    },
    "overdue_cadence": {
        "enabled": True,
        "lookback_months": 18,
        "min_orders": 5,
        "tolerance_factor": 1.5,
        "min_days_overdue": 14,
        "max_typical_interval_days": 120,
        "exclude_seasonal": True,
    },
    "priority": {
        "type_weight": {"transfer_no_reorder": 1.2, "overdue_cadence": 1.0, "declining_purchases": 0.9},
        # value_factor = 1 + log10(1 + size / value_scale)
        "value_scale": 1000,
        "high_threshold": 3.8,
        "medium_threshold": 2.8,
    },
    "workflow": {
        "today_max_cards": 5,
        "snooze_options_days": [7, 14, 30],
        "dismiss_cooldown_days": 90,
        "resurface_after_days": 21,
        "outcome_window_days": 60,
        "follow_up_max_days_ahead": 180,
    },
    # The approved "lost customer" definition is not available. While False the app never labels a customer as lost.
    "lost_customer_definition_approved": False,
}

OPPORTUNITY_TYPES = ("transfer_no_reorder", "declining_purchases", "overdue_cadence")


def merged_params(overrides: dict[str, Any] | None) -> dict[str, Any]:
    """Defaults deep-merged with stored overrides (unknown keys are ignored)."""
    result = copy.deepcopy(DEFAULT_PARAMS)
    if not overrides:
        return result

    def merge(base: dict[str, Any], upd: dict[str, Any]) -> None:
        for key, value in upd.items():
            if key not in base:
                continue
            if isinstance(base[key], dict) and isinstance(value, dict):
                merge(base[key], value)
            else:
                base[key] = value

    merge(result, overrides)
    return result


def validate_params(params: dict[str, Any]) -> list[str]:
    """Sanity checks for admin edits. Returns human-readable problems."""
    problems: list[str] = []

    def num(path: str, value: Any, lo: float, hi: float) -> None:
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not (lo <= value <= hi):
            problems.append(f"{path} must be a number between {lo} and {hi}")

    f = params["freshness"]
    num("freshness.stale_after_hours", f["stale_after_hours"], 1, 24 * 30)
    num("freshness.month_complete_lag_days", f["month_complete_lag_days"], 0, 20)
    t = params["transfer_no_reorder"]
    num("transfer_no_reorder.grace_days", t["grace_days"], 0, 365)
    num("transfer_no_reorder.max_days_since_transfer", t["max_days_since_transfer"], 1, 3650)
    num("transfer_no_reorder.min_orders_before_transfer", t["min_orders_before_transfer"], 0, 100)
    num("transfer_no_reorder.pre_transfer_lookback_months", t["pre_transfer_lookback_months"], 1, 36)
    if t["grace_days"] >= t["max_days_since_transfer"]:
        problems.append("transfer_no_reorder.grace_days must be lower than max_days_since_transfer")
    d = params["declining_purchases"]
    num("declining_purchases.window_months", d["window_months"], 1, 12)
    num("declining_purchases.min_history_months", d["min_history_months"], 13, 60)
    num("declining_purchases.decline_threshold_pct", d["decline_threshold_pct"], 1, 100)
    num("declining_purchases.min_prior_value", d["min_prior_value"], 0, 10_000_000)
    num("declining_purchases.min_abs_decline", d["min_abs_decline"], 0, 10_000_000)
    c = params["overdue_cadence"]
    num("overdue_cadence.lookback_months", c["lookback_months"], 3, 60)
    num("overdue_cadence.min_orders", c["min_orders"], 3, 200)
    num("overdue_cadence.tolerance_factor", c["tolerance_factor"], 1, 10)
    num("overdue_cadence.min_days_overdue", c["min_days_overdue"], 0, 365)
    num("overdue_cadence.max_typical_interval_days", c["max_typical_interval_days"], 1, 730)
    p = params["priority"]
    num("priority.value_scale", p["value_scale"], 1, 1_000_000)
    num("priority.high_threshold", p["high_threshold"], 0, 100)
    num("priority.medium_threshold", p["medium_threshold"], 0, 100)
    if p["medium_threshold"] > p["high_threshold"]:
        problems.append("priority.medium_threshold must not exceed priority.high_threshold")
    w = params["workflow"]
    num("workflow.today_max_cards", w["today_max_cards"], 1, 20)
    num("workflow.dismiss_cooldown_days", w["dismiss_cooldown_days"], 0, 730)
    num("workflow.resurface_after_days", w["resurface_after_days"], 1, 365)
    num("workflow.outcome_window_days", w["outcome_window_days"], 1, 365)
    if params.get("lost_customer_definition_approved") is not False:
        problems.append("lost_customer_definition_approved can only be enabled with an approved definition (code change)")
    return problems
