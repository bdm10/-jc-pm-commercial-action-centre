# Data dictionary and import contract

The app keeps three kinds of data apart, in separate PostgreSQL schemas:

| Schema | Contents | Who writes |
|---|---|---|
| `facts` | Read-only commercial facts from approved sources: customers, mappings, assignments, certified measure values, purchase documents, source refresh provenance, data issues | Importer and refresh job only. The API only reads. |
| `app` | Application records: users, teams, opportunities, actions, follow-ups, assignment overrides, observed outcomes, rule config versions, append-only audit log | API (audited) and refresh job |
| `ai` | AI-generated drafts with the exact facts supplied, guard result, provider and model | API when a user requests an AI draft |

App records reference customers by `(source_entity, source_customer_id)`, not by foreign key into `facts`. Replacing a facts snapshot therefore never deletes user work.

## 1. Import contract (v1)

A **package** is a folder of UTF-8 CSV files. Templates with one example row are in [`data/templates/`](../data/templates); the example values are fictitious.

```bash
cd backend
.venv/bin/python -m app.cli validate ../path/to/package   # report only
.venv/bin/python -m app.cli import   ../path/to/package   # validate, load, re-evaluate
```

**How a package is handled**
- **Full snapshot:** facts for the entities in `manifest.csv` are replaced. `customer_mapping.csv` replaces all mappings.
- **Package rejected, nothing loaded:** a missing file or column, an invalid manifest, a refresh timestamp in the future, `data_classification=live` without `ALLOW_LIVE_IMPORT=true`, or more than 5 % invalid or rejected rows in a file.
- **Row-level problems:** the row is dropped and recorded in `facts.data_issue`. Exact duplicates are kept once (warning). Conflicting duplicates are all dropped (error), and the affected customer's recommendations are suppressed.
- **Identical package:** re-importing a package with the same checksum is a no-op.
- **Matching:** mappings are never inferred. A customer pair is linked only by a `customer_mapping.csv` row with `mapping_status=approved`, an approver and an approval date.


### `manifest.csv`

**Grain:** One row per source entity included in the package.  
**Purpose:** Declares provenance and freshness. Facts for these entities are replaced as a full snapshot.
  
**Unique key:** `source_entity`

| Column | Type | Required | Description | Example |
|---|---|---|---|---|
| `source_entity` | enum (JC / PM) | yes | Source entity. JC and PM records are never merged. | `PM` |
| `source_model` | str | yes | Semantic model or system that produced the extract (e.g. 'PM Ventas base'). | `PM Ventas base` |
| `source_refreshed_at` | datetime | yes | Timestamp of the last successful refresh of the source model. | `2026-10-16T06:00:00+02:00` |
| `period_start` | date | yes | First date covered by the extract (inclusive). | `2024-01-01` |
| `period_end` | date | yes | Last date covered by the extract (inclusive). | `2026-10-15` |
| `extract_grain` | str | yes | Grain statement for the extract. | `customer-month for measures; invoice line for purchases` |
| `data_classification` | enum (synthetic / anonymised / live) | yes | synthetic, anonymised or live. 'live' is refused unless ALLOW_LIVE_IMPORT=true. | `synthetic` |
| `filters_applied` | str | yes | Reference to the approved default filters applied when extracting (name/version of the filter definition, not the filters themselves). | `default filters per approved model guide vX` |
| `contract_version` | enum (1) | yes | Import contract version. | `1` |

### `customers.csv`

**Grain:** One row per customer per source entity.  
**Purpose:** Customer identity as held by each source. Names are display-only and are NEVER used to match JC and PM customers.
  
**Unique key:** `source_entity`, `source_customer_id`

| Column | Type | Required | Description | Example |
|---|---|---|---|---|
| `source_entity` | enum (JC / PM) | yes | Source entity. JC and PM records are never merged. | `PM` |
| `source_customer_id` | str | yes | Stable customer ID in the source entity. | `EXAMPLE-PM-0001` |
| `display_name` | str | yes | Customer name for display only. | `Ejemplo S.L. (ficticio)` |
| `channel` | str | no | Commercial channel as defined by the source. | `Horeca` |
| `segment` | str | no | Segment as defined by the source. | `Restauración` |
| `city` | str | no | City. | `Barcelona` |
| `province` | str | no | Province. | `Barcelona` |
| `is_intercompany` | bool | yes | True for group/intercompany accounts. Excluded from all opportunity rules. | `false` |
| `seasonal_flag` | bool | no | Source flag for seasonal accounts. Empty = unknown (treated as not seasonal - provisional). | `` |
| `transfer_cohort` | str | no | Transfer programme/cohort attribute if the source marks the account as transferred (e.g. Nexora wave). Requires an approved mapping before any transfer rule runs. | `` |
| `source_status` | str | no | Status as held by the source (informational; the app does not derive 'lost'). | `Activo` |

### `customer_mapping.csv`

**Grain:** One row per approved (or proposed) link between a customer in one entity and a customer in another.  
**Purpose:** The ONLY way JC and PM customers are linked. Only rows with mapping_status=approved are used. The file replaces all mappings.
  
**Unique key:** `mapping_ref`

| Column | Type | Required | Description | Example |
|---|---|---|---|---|
| `mapping_ref` | str | yes | Stable identifier of the mapping row. | `EXAMPLE-MAP-0001` |
| `from_entity` | enum (JC / PM) | yes | Entity the customer moved from. | `JC` |
| `from_customer_id` | str | yes | Customer ID in from_entity. | `EXAMPLE-JC-0001` |
| `to_entity` | enum (JC / PM) | yes | Entity the customer moved to. | `PM` |
| `to_customer_id` | str | yes | Customer ID in to_entity. | `EXAMPLE-PM-0001` |
| `transfer_date` | date | no | Effective transfer date. Required for transfer rules. | `2026-07-01` |
| `cohort` | str | no | Transfer cohort or wave. | `Nexora-W2` |
| `mapping_status` | enum (approved / provisional / rejected) | yes | approved, provisional or rejected (rejected = confirmed NOT the same customer). | `approved` |
| `approved_by` | str | no | Approver (required when approved). | `Data owner` |
| `approved_at` | date | no | Approval date (required when approved). | `2026-06-20` |

### `assignments.csv`

**Grain:** One row per customer ownership period.  
**Purpose:** Baseline account ownership. Managers can override in the app (audited).

| Column | Type | Required | Description | Example |
|---|---|---|---|---|
| `source_entity` | enum (JC / PM) | yes | Source entity. JC and PM records are never merged. | `PM` |
| `source_customer_id` | str | yes | Customer ID in the source entity. | `EXAMPLE-PM-0001` |
| `salesperson_code` | str | yes | Salesperson code; must match a configured app user. | `EXAMPLE-SP-01` |
| `valid_from` | date | yes | First day of the assignment. | `2026-07-01` |
| `valid_to` | date | no | Last day of the assignment (empty = open). | `` |

### `measure_definitions.csv`

**Grain:** One row per measure supplied in the package.  
**Purpose:** Provenance for every figure the app shows. The app labels figures by certification_status and never presents synthetic or provisional measures as certified.
  
**Unique key:** `measure_code`

| Column | Type | Required | Description | Example |
|---|---|---|---|---|
| `measure_code` | str | yes | Code used in measure_monthly.csv / purchases.csv. | `PM_NET_SALES` |
| `display_name_es` | str | yes | Spanish display name. | `Ventas netas` |
| `display_name_en` | str | yes | English display name. | `Net sales` |
| `certified_measure_name` | str | yes | Exact measure name in the source semantic model. | `[Complete: exact measure name]` |
| `source_model` | str | yes | Semantic model holding the measure. | `PM Ventas base` |
| `source_entity` | enum (JC / PM) | yes | Source entity. JC and PM records are never merged. | `PM` |
| `business_definition` | str | yes | Approved business definition (VAT, discounts, rappels, returns...). | `[Complete]` |
| `certification_status` | enum (certified / provisional / synthetic) | yes | certified, provisional or synthetic. | `synthetic` |
| `unit` | str | yes | Unit or currency. | `EUR` |
| `additive_over_months` | bool | yes | True if monthly values may be summed into longer periods (needed for comparison windows). | `true` |
| `approved_by` | str | no | Finance/data approver (required when certified). | `` |
| `approved_at` | date | no | Approval date (required when certified). | `` |

### `measure_monthly.csv`

**Grain:** One row per source entity x customer x measure x calendar month with a non-zero value. A month with no row means zero for that customer (the extract is complete for its declared period).  
**Purpose:** Certified measure values evaluated BY THE SOURCE MODEL. The app does not rebuild them from lines.
  
**Unique key:** `source_entity`, `record_key`

| Column | Type | Required | Description | Example |
|---|---|---|---|---|
| `source_entity` | enum (JC / PM) | yes | Source entity. JC and PM records are never merged. | `PM` |
| `source_customer_id` | str | yes | Customer ID. | `EXAMPLE-PM-0001` |
| `measure_code` | str | yes | Registered measure code. | `PM_NET_SALES` |
| `month` | month | yes | Calendar month (YYYY-MM). | `2026-09` |
| `value` | decimal | yes | Measure value for the month (can be negative after credit notes). | `1834.50` |
| `currency` | str | yes | ISO currency. | `EUR` |
| `record_key` | str | yes | Stable unique key of the row within the entity (used for duplicate control). | `PM|EXAMPLE-PM-0001|PM_NET_SALES|2026-09` |

### `purchases.csv`

**Grain:** One row per invoice or credit-note line.  
**Purpose:** Dates, documents, products and quantities used for reorder and cadence rules and shown as evidence. 'amount' is optional and only displayed with its registered measure.
  
**Unique key:** `source_entity`, `record_key`

| Column | Type | Required | Description | Example |
|---|---|---|---|---|
| `source_entity` | enum (JC / PM) | yes | Source entity. JC and PM records are never merged. | `PM` |
| `record_key` | str | yes | Stable unique key of the line within the entity. | `PM|EXAMPLE-FV-0001|1` |
| `source_customer_id` | str | yes | Customer ID. | `EXAMPLE-PM-0001` |
| `document_date` | date | yes | Invoice or credit-note date. | `2026-09-18` |
| `document_type` | enum (invoice / credit_note) | yes | invoice or credit_note. Credit notes never count as orders. | `invoice` |
| `document_ref` | str | yes | Document number. | `EXAMPLE-FV-0001` |
| `brand` | str | no | Brand. | `Marca Ejemplo` |
| `sku` | str | no | SKU code. | `EXAMPLE-SKU-01` |
| `sku_description` | str | no | SKU description. | `Cava Brut 75cl` |
| `channel` | str | no | Channel. | `Horeca` |
| `quantity` | decimal | no | Quantity in `unit`. | `12` |
| `unit` | str | no | Unit of quantity. | `botella` |
| `amount` | decimal | no | Line value of a registered measure (optional). | `214.80` |
| `amount_measure_code` | str | no | Measure code for `amount` (required if amount is set). | `PM_NET_SALES` |
| `currency` | str | no | ISO currency (required if amount is set). | `EUR` |


## 2. Facts tables (`facts` schema)

| Table | Grain / key | Notes |
|---|---|---|
| `import_run` | one per import attempt | checksum, status (`loaded` / `rejected`), validation summary |
| `source_refresh` | one per entity per run | `source_model`, `source_refreshed_at`, period, grain, `data_classification`, `filters_applied` |
| `measure_definition` | `measure_code` | certified measure name, definition, `certification_status` (certified / provisional / synthetic), `additive_over_months`, approver |
| `customer` | (`source_entity`, `source_customer_id`) unique | display name is display-only |
| `customer_mapping` | `mapping_ref` unique | from/to entity and ID, transfer date, cohort, status, approver |
| `assignment` | customer × validity period | baseline ownership by `salesperson_code` |
| `measure_monthly` | (`source_entity`, `record_key`) and (entity, customer, measure, month) unique | values supplied by the source model |
| `purchase` | (`source_entity`, `record_key`) unique | document lines; `amount` only with a registered measure code |
| `data_issue` | one per finding | `stage` import / refresh, `severity`, `issue_code`, customer, detail |

## 3. Application records (`app` schema)

| Table | Purpose | Key fields |
|---|---|---|
| `app_user` | people using the app | `role` (sales / manager / admin), `salesperson_code`, `entra_object_id` |
| `team`, `team_member`, `team_manager` | authorised scope for managers | — |
| `assignment_override` | in-app reassignment (latest non-superseded wins over the baseline) | `assigned_by_user_id`, `reason`, `superseded_at` |
| `rule_config` | versioned rule parameters | `params`, `approval_status` (always provisional), `note` |
| `opportunity` | one detected opportunity | `opp_type`, `status` (open / in_progress / snoozed / dismissed / resolved), `condition_active`, priority score, band and components, reason code and params, **evidence**, `rule_version`, `config_version`, `data_refreshed_at`, snooze / dismiss / resolve fields. Partial unique index on active (entity, customer, type). |
| `activity` | an action completed by a user (not an outcome) | `action_type`, `note` (≤ 280), `follow_up_date`, `client_request_id` (idempotency) |
| `follow_up` | a dated follow-up | owner, due date, status (open / done / cancelled), created and closed by activity |
| `observed_outcome` | later invoice observed after the first action | `first_action_at`, `observed_document_date` / `ref`. Label: *observed, not attributed*. |
| `audit_log` | append-only history of every change | blocked from UPDATE and DELETE by a database trigger |

## 4. AI drafts (`ai` schema)

| Table | Key fields |
|---|---|
| `suggestion` | customer, opportunity, provider, model, `prompt_version`, language, **`facts_used`** (exact facts sent), `output`, `guard_status` (passed / rejected) and `guard_detail`, requesting user |

## 5. Evidence item format

Every figure behind a recommendation is stored with the opportunity and returned by the API:

```json
{
  "id": "e1",
  "label_key": "ev.current_window_value",
  "kind": "money",
  "value": 8336.0,
  "unit": "EUR",
  "entity": "JC",
  "provenance": {
    "type": "synthetic_measure",
    "measure_code": "JC_NET_SALES",
    "measure_name": "SYNTHETIC - not a certified measure",
    "certification_status": "synthetic",
    "source_model": "JUVE Ventas base (SYNTHETIC)",
    "refreshed_at": "2026-10-17T04:00:00+00:00",
    "period": {"start": "2026-04-01", "end": "2026-09-30"},
    "derivation": "sum_of_monthly_values"
  }
}
```

Other provenance types:
- `certified_measure`: only when the measure definition is certified and approved.
- `app_calculation`: percentages, differences and day counts. Always provisional.
- `source_documents`: dates and counts taken from invoices.
- `approved_mapping`: transfer date, with the mapping reference and approver.

## 6. Synthetic data

`python -m app.cli generate-synthetic` (or `seed-demo`) creates a package in `data/synthetic/`, which is gitignored and regenerated on demand. In that package:
- every ID starts with `SYN-`, every product carries `(SINT)`, and measures are `certification_status=synthetic`;
- dates are anchored to the run date, so the data is always fresh for demos;
- `--stale-entity PM` simulates a stale source.

| Planted case | Expected behaviour |
|---|---|
| transfer pending / within grace / already reordered | flag / not met / not met |
| declining, mild decline (14 %), small decline under materiality | flag / not met / not met |
| overdue, slightly late, seasonal (flagged), seasonal (unflagged) | flag / not met / excluded / **flag** (shows the open seasonal-definition gap) |
| stopped buying 7 months ago | declining + overdue on **one** card, never "lost" |
| new customer (≈5 months) | decline not evaluable |
| unmapped transfer, provisional mapping, ambiguous one-to-two mapping, mapping to a missing customer | data issues; no recommendation |
| same display name in JC and PM, no mapping | never linked |
| intercompany account | excluded |
| unassigned customer, unknown salesperson code | admin-only opportunity plus data issue |
| exact duplicate lines, conflicting duplicate month, month made negative by a credit note | warning / error and suppression / info |
