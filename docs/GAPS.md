# Gap list: definitions, fields and integration requirements

_Status: 17 Oct 2026 · prototype milestone 1 · owner of this list: technical owner (to be named)_

**What was reviewed**
- *JC PM Commercial Action Centre – Reference Pack*. This is a draft completion template, kept outside Git. Every `[Complete]` field in it is still open. No Nexora mapping, semantic-model guide, approved definitions or MiPM screenshots were attached.
- The organisation's Power BI semantic-model configuration (names and default query filters only). It is not reproduced here, and no model was queried.

**Bottom line:** no commercial definition is approved yet. The prototype therefore runs on **synthetic data and provisional rules only**. Both are labelled as such in the UI, the API and the data.

---

## 1. Confirmed: governance rules the build relies on

| # | Rule | Source | Where enforced |
|---|---|---|---|
| C1 | A customer is identified by `(source entity, source customer ID)`. JC and PM customers are **never matched by name**. | Pack §7, brief | Import contract; `services/snapshot.py`; test `test_same_name_customers_are_not_linked` |
| C2 | JC and PM figures are **not added together** without approved mapping and consolidation rules. | Pack §4, §7 | Evidence carries its entity; the UI shows each entity separately |
| C3 | Certified measures and approved mappings are authoritative. Financial measures are **not rebuilt from raw fields**. | Brief, pack §4 | The contract imports measure values computed by the source; the app never multiplies quantity × price |
| C4 | Missing mappings and stale sources appear as **data issues**, not as customer-risk recommendations. | Pack §4 | Rule gating plus `facts.data_issue`; Today hides stale entities |
| C5 | All thresholds stay provisional until approved. | Pack §4 | Config is versioned and always `approval_status = provisional` |
| C6 | Nobody is labelled "lost" until the definition, including the prior-12-month convention, is approved. | Pack §4, brief | `lost_customer_definition_approved = false`; tests assert the label never appears |
| C7 | Prototype limits: synthetic or anonymised data only, no ERP writeback, no automatic messages. | Pack §6 | Imports with `data_classification=live` are refused unless `ALLOW_LIVE_IMPORT=true`. There is no outbound integration. |
| C8 | Action set: contacted, meeting booked, offer requested, no response, not relevant. Optional note and date; target under 30 s. | Pack §5 | Action sheet; e2e test asserts under 30 s |
| C9 | Later orders are **observed post-action results**, not proven uplift. | Pack §5, brief | `observed_outcome` label; Team view caveat |
| C10 | The named models exist in the organisation's Power BI configuration: *JUVE Ventas base* (fiscal-year default period) and *PM Ventas base* (calendar-year default period). Each has documented default query filters (excluding self-consumption, non-invoiced movement types, non-product and non-inventory lines). | Organisation Power BI config | The import manifest requires `filters_applied` to reference the approved filter definition |

> C10 confirms only how the models are queried. It does **not** confirm which measures are certified for this use, access rights, or refresh schedules. The *Nexora sales* model is currently **disabled** in that configuration.

## 2. Provisional prototype assumptions (to approve or replace)

These are implemented and configurable. None is approved. Full detail is in [RULES.md](RULES.md).

| # | Assumption | Current value |
|---|---|---|
| A1 | Stale cutoff: older source refreshes suppress that entity's recommendations | 48 h |
| A2 | A month counts as complete once the refresh is N days into the next month | 3 days |
| A3 | A certified monthly measure may be **summed** across months for comparison windows | yes (`additive_over_months`) |
| A4 | A month with no row means zero sales (the extract is complete for its declared period) | yes |
| A5 | Transfer, no reorder: grace / maximum age / minimum orders before transfer | 30 d / 365 d / 2 orders in 12 m |
| A6 | Declining: last 6 complete months vs the same months a year earlier; decline ≥ 25 %; prior period ≥ €3,000; decline ≥ €1,500; history ≥ 18 m | as listed |
| A7 | Overdue: median interval over 18 m; ≥ 5 orders; overdue when days since last order ≥ max(1.5 × median, median + 14); interval ≤ 120 d | as listed |
| A8 | An "order" is a distinct invoice date. Credit notes never count as orders. | yes |
| A9 | Seasonal accounts: excluded only when the source flags them; an unknown flag is treated as non-seasonal | yes (see synthetic case `seasonal_unflagged`) |
| A10 | Transferred-out accounts are excluded from decline and overdue rules in the origin entity | yes |
| A11 | Priority = type weight × (1 + log10(1 + 12-month size / 1,000)) × urgency; bands high ≥ 3.8, medium ≥ 2.8 | provisional weights |
| A12 | Today shows ≤ 5 customers, one card per customer. Customers with a due follow-up appear only under follow-ups. | 5 |
| A13 | Snooze 7/14/30 d. Dismissal reasons: already handled, not relevant, data incorrect, duplicate, other. Dismissal cooldown 90 d. An item resurfaces 21 d after the last action if it persists with no follow-up. | as listed |
| A14 | Observed outcome = first invoice in that entity within 60 d after the first action | 60 d |
| A15 | Managers see their teams' accounts on Today and Team. Reassignment moves open follow-ups to the new owner. | yes |
| A16 | One approved mapping per customer pair. Several approved mappings for one customer are flagged as ambiguous, not merged. | yes |

## 3. Missing business definitions

| # | Decision needed | Proposed owner (role, per reference pack §1) | Blocks |
|---|---|---|---|
| D1 | Exact certified **net sales** measure per model, plus treatment of VAT, discounts, rappels, returns and costs. Finance reviewer. | Finance lead + commercial lead | Any real figure |
| D2 | Whether **gross margin** is shown, and which measure | Finance lead + Finance reviewer | Margin display (not built) |
| D3 | JC/PM **consolidation**: mapping use, migration treatment, intercompany exclusions, double-count prevention | Finance lead + data owner | Any combined view (none built) |
| D4 | **Calendar alignment**: JC defaults to fiscal year, PM to calendar year. Which periods do comparisons use, and when does the JC fiscal year start? | BI / data owners | Comparison windows (prototype uses calendar months) |
| D5 | **Nexora transfer**: eligible cohort, authoritative transfer date, direction(s), grace period, exceptions | Data owner + commercial lead | Rule A5 |
| D6 | **Declining purchases**: metric, comparable periods, seasonality, minimum history, materiality | Finance lead + commercial lead | Rule A6 |
| D7 | **Overdue reorder**: cadence method, minimum orders, tolerance, seasonal-account list or flag | Commercial lead | Rule A7, A9 |
| D8 | **Active / lost** customer: qualifying purchase, observation window, 12-month convention | Finance lead + commercial lead | Any "lost" or "active" label (disabled) |
| D9 | **Priority and suppression**: ranking method, snooze, dismissal reasons, duplicate prevention, stale cutoff | Pilot manager | A11–A13, A1 |
| D10 | **Attribution**: is any method approved? If not, outcomes stay "observed only". | Finance lead | Outcome reporting |

## 4. Missing fields and data

| # | Needed | Notes |
|---|---|---|
| F1 | Workspace and model IDs, owner, approved access method, security restrictions, **latest refresh timestamp** per model | `source_refreshed_at` is mandatory in the contract |
| F2 | Stable customer IDs per entity, and the **Nexora mapping table**: JC ID, PM ID, transfer date, cohort, approval status, approver | `customer_mapping.csv` |
| F3 | **Assignments**: salesperson and manager IDs with validity dates, plus the link from salesperson code to Entra identity | `assignments.csv`; `app_user.salesperson_code` / `entra_object_id` |
| F4 | Grain of each extract and its duplicate controls (stable record keys) | `record_key` columns |
| F5 | Seasonal flag, intercompany flag, customer status | `customers.csv` |
| F6 | Treatment of returns, credit notes and manual entries; the intercompany flag on documents | `document_type`; flag column to add if needed |
| F7 | **Sample reconciliation** of extract totals against an approved report | Required before live use |
| F8 | Anonymised 12–24 month sample with stable IDs and explicit reporting dates | Replaces synthetic data for UAT |
| F9 | MiPM: where visits and notes are recorded today, and 3–5 anonymised screenshots | Workflow fit |

## 5. Integration requirements

Status and steps are in [INTEGRATION_CHECKLIST.md](INTEGRATION_CHECKLIST.md).

| # | Requirement | Current state |
|---|---|---|
| I1 | **Entra ID**: app registrations (API + SPA), scope, user provisioning and role/team source | Backend token validation **scaffolded** (unit-tested with local keys, not against a tenant). Frontend sign-in **not implemented**. |
| I2 | **Certified Fabric / Power BI data**: service principal, read-only access, scheduled export that produces the import contract | **Not started**. The contract, validator and scheduler inbox are ready. |
| I3 | **MiPM**: system of record for activities; embed, link or sync | **Not started**. Decision pending (pack §5). |
| I4 | **Hosting**: container platform, managed PostgreSQL, Key Vault secrets, private networking, backups, retention | Pilot hosting **not started**. A login-protected **synthetic demo** on Render's free tier is configured (`render.yaml`); its image was built and tested locally, not yet deployed. |
| I5 | **AI provider**: approval, data-processing terms, whether customer names may be sent | Adapter implemented and **off by default**. The guard and deterministic fallback are tested; no live call was made. |
| I6 | **Retention and privacy** for notes, audit history and AI drafts | Not defined |
