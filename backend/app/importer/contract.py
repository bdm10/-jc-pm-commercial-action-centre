"""Import contract v1: a package is a directory of UTF-8 CSV files.

This module is the single source of truth for the contract. The data
dictionary (docs/DATA_DICTIONARY.md) and the templates in data/templates/ are
generated from it with `python -m app.cli contract-docs` / `contract-templates`.

Conventions: comma-separated, header row required, ISO dates (YYYY-MM-DD),
months as YYYY-MM, timestamps ISO 8601 with offset, '.' as decimal separator,
booleans true/false. Empty cell = null.
"""

from __future__ import annotations

from dataclasses import dataclass, field

CONTRACT_VERSION = "1"
ENTITIES = ("JC", "PM")


@dataclass(frozen=True)
class Col:
    name: str
    type: str  # str | date | month | datetime | decimal | bool | enum
    required: bool
    description: str
    example: str
    enum: tuple[str, ...] = ()
    max_len: int = 200


@dataclass(frozen=True)
class FileSpec:
    name: str
    grain: str
    purpose: str
    columns: tuple[Col, ...]
    keys: tuple[str, ...] = ()
    example_rows: tuple[tuple[str, ...], ...] = field(default=())


E = Col("source_entity", "enum", True, "Source entity. JC and PM records are never merged.", "PM", ENTITIES, 8)

MANIFEST = FileSpec(
    "manifest.csv",
    "One row per source entity included in the package.",
    "Declares provenance and freshness. Facts for these entities are replaced as a full snapshot.",
    (
        E,
        Col("source_model", "str", True, "Semantic model or system that produced the extract (e.g. 'PM Ventas base').", "PM Ventas base", max_len=120),
        Col("source_refreshed_at", "datetime", True, "Timestamp of the last successful refresh of the source model.", "2026-10-16T06:00:00+02:00"),
        Col("period_start", "date", True, "First date covered by the extract (inclusive).", "2024-01-01"),
        Col("period_end", "date", True, "Last date covered by the extract (inclusive).", "2026-10-15"),
        Col("extract_grain", "str", True, "Grain statement for the extract.", "customer-month for measures; invoice line for purchases"),
        Col("data_classification", "enum", True, "synthetic, anonymised or live. 'live' is refused unless ALLOW_LIVE_IMPORT=true.", "synthetic", ("synthetic", "anonymised", "live"), 20),
        Col("filters_applied", "str", True, "Reference to the approved default filters applied when extracting (name/version of the filter definition, not the filters themselves).", "default filters per approved model guide vX", max_len=500),
        Col("contract_version", "enum", True, "Import contract version.", "1", (CONTRACT_VERSION,), 4),
    ),
    keys=("source_entity",),
)

CUSTOMERS = FileSpec(
    "customers.csv",
    "One row per customer per source entity.",
    "Customer identity as held by each source. Names are display-only and are NEVER used to match JC and PM customers.",
    (
        E,
        Col("source_customer_id", "str", True, "Stable customer ID in the source entity.", "EXAMPLE-PM-0001", max_len=60),
        Col("display_name", "str", True, "Customer name for display only.", "Ejemplo S.L. (ficticio)"),
        Col("channel", "str", False, "Commercial channel as defined by the source.", "Horeca", max_len=60),
        Col("segment", "str", False, "Segment as defined by the source.", "Restauración", max_len=60),
        Col("city", "str", False, "City.", "Barcelona", max_len=120),
        Col("province", "str", False, "Province.", "Barcelona", max_len=120),
        Col("is_intercompany", "bool", True, "True for group/intercompany accounts. Excluded from all opportunity rules.", "false"),
        Col("seasonal_flag", "bool", False, "Source flag for seasonal accounts. Empty = unknown (treated as not seasonal - provisional).", ""),
        Col("transfer_cohort", "str", False, "Transfer programme/cohort attribute if the source marks the account as transferred (e.g. Nexora wave). Requires an approved mapping before any transfer rule runs.", "", max_len=60),
        Col("source_status", "str", False, "Status as held by the source (informational; the app does not derive 'lost').", "Activo", max_len=60),
    ),
    keys=("source_entity", "source_customer_id"),
)

MAPPING = FileSpec(
    "customer_mapping.csv",
    "One row per approved (or proposed) link between a customer in one entity and a customer in another.",
    "The ONLY way JC and PM customers are linked. Only rows with mapping_status=approved are used. The file replaces all mappings.",
    (
        Col("mapping_ref", "str", True, "Stable identifier of the mapping row.", "EXAMPLE-MAP-0001", max_len=60),
        Col("from_entity", "enum", True, "Entity the customer moved from.", "JC", ENTITIES, 8),
        Col("from_customer_id", "str", True, "Customer ID in from_entity.", "EXAMPLE-JC-0001", max_len=60),
        Col("to_entity", "enum", True, "Entity the customer moved to.", "PM", ENTITIES, 8),
        Col("to_customer_id", "str", True, "Customer ID in to_entity.", "EXAMPLE-PM-0001", max_len=60),
        Col("transfer_date", "date", False, "Effective transfer date. Required for transfer rules.", "2026-07-01"),
        Col("cohort", "str", False, "Transfer cohort or wave.", "Nexora-W2", max_len=60),
        Col("mapping_status", "enum", True, "approved, provisional or rejected (rejected = confirmed NOT the same customer).", "approved", ("approved", "provisional", "rejected"), 20),
        Col("approved_by", "str", False, "Approver (required when approved).", "Data owner", max_len=120),
        Col("approved_at", "date", False, "Approval date (required when approved).", "2026-06-20"),
    ),
    keys=("mapping_ref",),
)

ASSIGNMENTS = FileSpec(
    "assignments.csv",
    "One row per customer ownership period.",
    "Baseline account ownership. Managers can override in the app (audited).",
    (
        E,
        Col("source_customer_id", "str", True, "Customer ID in the source entity.", "EXAMPLE-PM-0001", max_len=60),
        Col("salesperson_code", "str", True, "Salesperson code; must match a configured app user.", "EXAMPLE-SP-01", max_len=60),
        Col("valid_from", "date", True, "First day of the assignment.", "2026-07-01"),
        Col("valid_to", "date", False, "Last day of the assignment (empty = open).", ""),
    ),
)

MEASURES = FileSpec(
    "measure_definitions.csv",
    "One row per measure supplied in the package.",
    "Provenance for every figure the app shows. The app labels figures by certification_status and never presents synthetic or provisional measures as certified.",
    (
        Col("measure_code", "str", True, "Code used in measure_monthly.csv / purchases.csv.", "PM_NET_SALES", max_len=60),
        Col("display_name_es", "str", True, "Spanish display name.", "Ventas netas", max_len=120),
        Col("display_name_en", "str", True, "English display name.", "Net sales", max_len=120),
        Col("certified_measure_name", "str", True, "Exact measure name in the source semantic model.", "[Complete: exact measure name]"),
        Col("source_model", "str", True, "Semantic model holding the measure.", "PM Ventas base", max_len=120),
        E,
        Col("business_definition", "str", True, "Approved business definition (VAT, discounts, rappels, returns...).", "[Complete]", max_len=2000),
        Col("certification_status", "enum", True, "certified, provisional or synthetic.", "synthetic", ("certified", "provisional", "synthetic"), 20),
        Col("unit", "str", True, "Unit or currency.", "EUR", max_len=10),
        Col("additive_over_months", "bool", True, "True if monthly values may be summed into longer periods (needed for comparison windows).", "true"),
        Col("approved_by", "str", False, "Finance/data approver (required when certified).", "", max_len=120),
        Col("approved_at", "date", False, "Approval date (required when certified).", ""),
    ),
    keys=("measure_code",),
)

MONTHLY = FileSpec(
    "measure_monthly.csv",
    "One row per source entity x customer x measure x calendar month with a non-zero value. A month with no row means zero for that customer (the extract is complete for its declared period).",
    "Certified measure values evaluated BY THE SOURCE MODEL. The app does not rebuild them from lines.",
    (
        E,
        Col("source_customer_id", "str", True, "Customer ID.", "EXAMPLE-PM-0001", max_len=60),
        Col("measure_code", "str", True, "Registered measure code.", "PM_NET_SALES", max_len=60),
        Col("month", "month", True, "Calendar month (YYYY-MM).", "2026-09"),
        Col("value", "decimal", True, "Measure value for the month (can be negative after credit notes).", "1834.50"),
        Col("currency", "str", True, "ISO currency.", "EUR", max_len=3),
        Col("record_key", "str", True, "Stable unique key of the row within the entity (used for duplicate control).", "PM|EXAMPLE-PM-0001|PM_NET_SALES|2026-09", max_len=120),
    ),
    keys=("source_entity", "record_key"),
)

PURCHASES = FileSpec(
    "purchases.csv",
    "One row per invoice or credit-note line.",
    "Dates, documents, products and quantities used for reorder and cadence rules and shown as evidence. 'amount' is optional and only displayed with its registered measure.",
    (
        E,
        Col("record_key", "str", True, "Stable unique key of the line within the entity.", "PM|EXAMPLE-FV-0001|1", max_len=120),
        Col("source_customer_id", "str", True, "Customer ID.", "EXAMPLE-PM-0001", max_len=60),
        Col("document_date", "date", True, "Invoice or credit-note date.", "2026-09-18"),
        Col("document_type", "enum", True, "invoice or credit_note. Credit notes never count as orders.", "invoice", ("invoice", "credit_note"), 20),
        Col("document_ref", "str", True, "Document number.", "EXAMPLE-FV-0001", max_len=60),
        Col("brand", "str", False, "Brand.", "Marca Ejemplo", max_len=120),
        Col("sku", "str", False, "SKU code.", "EXAMPLE-SKU-01", max_len=60),
        Col("sku_description", "str", False, "SKU description.", "Cava Brut 75cl"),
        Col("channel", "str", False, "Channel.", "Horeca", max_len=60),
        Col("quantity", "decimal", False, "Quantity in `unit`.", "12"),
        Col("unit", "str", False, "Unit of quantity.", "botella", max_len=20),
        Col("amount", "decimal", False, "Line value of a registered measure (optional).", "214.80"),
        Col("amount_measure_code", "str", False, "Measure code for `amount` (required if amount is set).", "PM_NET_SALES", max_len=60),
        Col("currency", "str", False, "ISO currency (required if amount is set).", "EUR", max_len=3),
    ),
    keys=("source_entity", "record_key"),
)

FILES: tuple[FileSpec, ...] = (MANIFEST, CUSTOMERS, MAPPING, ASSIGNMENTS, MEASURES, MONTHLY, PURCHASES)
FILES_BY_NAME = {f.name: f for f in FILES}
