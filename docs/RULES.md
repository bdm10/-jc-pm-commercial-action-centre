# Opportunity rules (provisional)

> **Every threshold below is a provisional prototype assumption.** None has been approved (see [GAPS.md](GAPS.md) §3).
> Defaults live in `backend/app/rules/config.py`. Administrators change them in **Admin → Reglas**. Each change creates a new, audited config version, still marked provisional, and re-evaluates opportunities.

The engine (`backend/app/rules/engine.py`) is made of pure functions. Each rule returns:

- a **status**: `flag`, `not_met`, `not_evaluable` (not enough history), `suppressed` (unreliable data) or `excluded` (not applicable);
- a machine-readable **reason** with parameters, rendered in Spanish or English by the frontend;
- the **evidence** used. Each figure states its entity, measure, certification status, period, source model and refresh time.

## Gates applied before any rule (in order)

| Condition | Result | Shown as |
|---|---|---|
| Source entity refresh older than `freshness.stale_after_hours` (48 h) | `suppressed: stale_source` | Red banner; that entity's cards hidden; existing opportunities marked *unconfirmed* rather than resolved |
| Intercompany customer (`is_intercompany`) | `excluded: intercompany` | — |
| Rows for this customer rejected on import (for example conflicting duplicates) | `suppressed: incomplete_customer_data` | Data issue. Missing rows would otherwise read as zero sales. |
| A mapping touching the customer is provisional, ambiguous, points to an unknown customer, or has no transfer date | `suppressed: mapping_*` | Data issue |
| Customer carries a `transfer_cohort` but has no approved mapping | `suppressed: unmapped_transfer` | Data issue |

## 1. Transferred customer without reorder (`transfer_no_reorder`)

Evaluated on the **receiving** customer of an **approved** mapping.

| Step | Default | Outcome |
|---|---|---|
| Days since transfer ≤ `grace_days` | 30 | `not_met: within_grace` |
| Days since transfer > `max_days_since_transfer` | 365 | `excluded: transfer_too_old` |
| Any invoice in the receiving entity since the transfer date | — | `not_met: reordered` |
| Invoice days in the origin entity in the `pre_transfer_lookback_months` before transfer < `min_orders_before_transfer` | 12 m / 2 | `excluded: inactive_before_transfer` |
| Otherwise | — | **flag** |

Evidence: transfer date (mapping ref and approver), days since transfer, 0 orders in the receiving entity, orders and last order in the origin entity, origin-entity measure for the 12 months before transfer. All figures are labelled with their own entity and **never added** to receiving-entity figures.

## 2. Declining purchases (`declining_purchases`)

Compares the primary measure for the **last N complete calendar months** with the **same N months a year earlier**. This is seasonality-aware.

| Parameter | Default |
|---|---|
| `window_months` | 6 |
| `min_history_months` (at least window + 12) | 18 |
| `decline_threshold_pct` (flag when change ≤ −threshold) | 25 |
| `min_prior_value` | €3,000 |
| `min_abs_decline` | €1,500 |

Exclusions: customer transferred out of this entity (`excluded: transferred_out`), measure missing or not additive (`suppressed`), extract not covering the prior window (`not_evaluable`).
Evidence: both window values (sum of monthly values of the registered measure, period stated), percentage and absolute change (marked *app calculation, provisional*), last order, and the 12-month reference size.

## 3. Overdue against usual cadence (`overdue_cadence`)

| Parameter | Default |
|---|---|
| `lookback_months` (from the transfer date for transferred-in customers) | 18 |
| `min_orders` (distinct invoice dates) | 5 |
| Typical interval | median of gaps between invoice dates |
| `max_typical_interval_days` (infrequent buyers excluded) | 120 |
| Alert from day | max(⌈typical × `tolerance_factor` (1.5)⌉, typical + `min_days_overdue` (14)) |
| `exclude_seasonal` (only when the source flags the account) | true |

"Days since last order" is measured to the **source refresh date**, not today, because orders after the refresh are not yet known.

## Priority

`score = type_weight × (1 + log10(1 + size / value_scale)) × urgency`

| Component | Default |
|---|---|
| `type_weight` | transfer 1.2 · overdue 1.0 · declining 0.9 |
| size | 12-month measure value in the relevant entity (origin entity for transfers) |
| `value_scale` | 1,000 |
| urgency (1–2) | transfer: days past grace / 60 · declining: (decline − threshold) / 50 · overdue: (days since / typical − tolerance) / 2 |
| bands | high ≥ 3.8 · medium ≥ 2.8 · otherwise low |

Each card shows its band as text and bars, never colour alone. The detail view expands the exact components under *¿Por qué esta prioridad?*

## Workflow rules

| Rule | Default |
|---|---|
| Cards on Today | 5. One card per customer; other signals shown as "+1 otra señal". Customers with a due follow-up appear only in the follow-up list. |
| Recording any action | Opportunity becomes *in progress* and leaves Today. Open follow-ups for that customer by that user are completed. |
| "No relevante" action | Dismisses the opportunity with reason `not_relevant` |
| Snooze | 7 / 14 / 30 days; returns automatically when the snooze ends |
| Dismiss | Reason required; "other" and "data incorrect" need a note. "Data incorrect" reports are listed for admins. No re-alert for the same customer and type for 90 days. |
| Resurfacing | An in-progress item with no open follow-up returns to Today if the condition still holds 21 days after the last action |
| Condition cleared with reliable data | Opportunity becomes *resolved: condition cleared* |
| Observed outcome | First invoice in that entity on or after the first action day, within 60 days. Labelled *observed after action, not attributed*. |
| Duplicate prevention | Partial unique index: one active opportunity per (entity, customer, type). Idempotent action submits via `client_request_id`. |

## Never

- Label a customer as lost (`lost_customer_definition_approved` is false and cannot be switched on from the admin UI).
- Match JC and PM customers by name, or add their figures together.
- Compute sales or margin from quantity × price.
- Present synthetic or provisional figures as certified.
