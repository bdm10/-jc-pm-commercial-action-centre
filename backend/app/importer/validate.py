"""Validate an import package against the contract.

Structural problems (missing file/column, bad manifest, live data without
permission, too many bad rows) reject the whole package. Row-level problems
drop the row and are recorded as data issues; nothing is silently "fixed".
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from app import clock
from app.importer.contract import (
    ASSIGNMENTS,
    CUSTOMERS,
    FILES,
    MANIFEST,
    MAPPING,
    MEASURES,
    MONTHLY,
    PURCHASES,
    Col,
    FileSpec,
)
from app.services.snapshot import Issue

MAX_ROW_ERROR_RATE = 0.05


@dataclass
class ValidationResult:
    package_label: str
    checksum: str
    fatal: list[str] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    rows: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    counts: dict[str, dict[str, int]] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.fatal

    def summary(self) -> dict[str, Any]:
        by_code = Counter(i.issue_code for i in self.issues)
        return {"ok": self.ok, "fatal": self.fatal, "counts": self.counts, "issues_by_code": dict(by_code)}


class RowError(ValueError):
    pass


def _parse(col: Col, raw: str | None) -> Any:
    v = (raw or "").strip()
    if v == "":
        if col.required:
            raise RowError(f"{col.name} is required")
        return None
    if col.type == "str":
        if len(v) > col.max_len:
            raise RowError(f"{col.name} longer than {col.max_len}")
        return v
    if col.type == "enum":
        if v not in col.enum:
            raise RowError(f"{col.name}='{v}' not in {list(col.enum)}")
        return v
    if col.type == "bool":
        if v.lower() not in ("true", "false"):
            raise RowError(f"{col.name} must be true/false")
        return v.lower() == "true"
    if col.type == "date":
        try:
            return dt.date.fromisoformat(v)
        except ValueError as exc:
            raise RowError(f"{col.name} must be YYYY-MM-DD") from exc
    if col.type == "month":
        try:
            y, m = v.split("-")
            return dt.date(int(y), int(m), 1)
        except ValueError as exc:
            raise RowError(f"{col.name} must be YYYY-MM") from exc
    if col.type == "datetime":
        try:
            d = dt.datetime.fromisoformat(v)
        except ValueError as exc:
            raise RowError(f"{col.name} must be ISO 8601") from exc
        if d.tzinfo is None:
            raise RowError(f"{col.name} needs a UTC offset")
        return d
    if col.type == "decimal":
        try:
            d = Decimal(v)
        except InvalidOperation as exc:
            raise RowError(f"{col.name} must be a number with '.' decimals") from exc
        if not d.is_finite():
            raise RowError(f"{col.name} must be finite")
        return d
    raise AssertionError(col.type)


def _checksum(folder: Path) -> str:
    h = hashlib.sha256()
    for spec in FILES:
        p = folder / spec.name
        if p.exists():
            h.update(spec.name.encode())
            h.update(p.read_bytes())
    return h.hexdigest()


def _read(folder: Path, spec: FileSpec, res: ValidationResult) -> list[dict[str, Any]]:
    path = folder / spec.name
    if not path.exists():
        res.fatal.append(f"{spec.name}: file missing")
        return []
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        header = reader.fieldnames or []
        missing = [c.name for c in spec.columns if c.name not in header]
        if missing:
            res.fatal.append(f"{spec.name}: missing columns {missing}")
            return []
        extra = [h for h in header if h not in {c.name for c in spec.columns}]
        if extra:
            res.issues.append(Issue("info", "unknown_columns_ignored", detail={"file": spec.name, "columns": extra}))
        out, errors, total = [], 0, 0
        for line_no, raw in enumerate(reader, start=2):
            total += 1
            try:
                row = {c.name: _parse(c, raw.get(c.name)) for c in spec.columns}
            except RowError as exc:
                errors += 1
                res.issues.append(Issue("error", "invalid_row", raw.get("source_entity") or None,
                                        raw.get("source_customer_id") or None,
                                        {"file": spec.name, "line": line_no, "error": str(exc)}))
                continue
            row["_line"] = line_no
            out.append(row)
    res.counts[spec.name] = {"read": total, "invalid": errors}
    if total and errors / total > MAX_ROW_ERROR_RATE:
        res.fatal.append(f"{spec.name}: {errors}/{total} invalid rows exceeds {MAX_ROW_ERROR_RATE:.0%}")
    return out


def _dedupe(rows: list[dict[str, Any]], key_cols: tuple[str, ...], spec: FileSpec, res: ValidationResult) -> list[dict[str, Any]]:
    """Exact duplicates: keep one (warning). Conflicting duplicates: drop all (error)."""
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        groups[tuple(r[k] for k in key_cols)].append(r)
    out = []
    for key, grp in groups.items():
        if len(grp) == 1:
            out.append(grp[0])
            continue
        payloads = {tuple((k, v) for k, v in sorted(r.items()) if k != "_line") for r in grp}
        entity = grp[0].get("source_entity")
        cust = grp[0].get("source_customer_id")
        detail = {"file": spec.name, "key": [str(k) for k in key], "lines": [r["_line"] for r in grp]}
        if len(payloads) == 1:
            res.issues.append(Issue("warning", "duplicate_row_dropped", entity, cust, detail))
            out.append(grp[0])
        else:
            res.issues.append(Issue("error", "conflicting_duplicate_rows", entity, cust, detail))
    return out


def validate_package(folder: Path, known_salesperson_codes: set[str] | None = None,
                     existing_measures: set[str] | None = None, allow_live: bool = False,
                     synthetic_only: bool = False) -> ValidationResult:
    folder = Path(folder)
    res = ValidationResult(package_label=folder.name, checksum=_checksum(folder) if folder.exists() else "")
    if not folder.is_dir():
        res.fatal.append(f"{folder}: not a directory")
        return res

    manifest = _read(folder, MANIFEST, res)
    customers = _read(folder, CUSTOMERS, res)
    mappings = _read(folder, MAPPING, res)
    assignments = _read(folder, ASSIGNMENTS, res)
    measures = _read(folder, MEASURES, res)
    monthly = _read(folder, MONTHLY, res)
    purchases = _read(folder, PURCHASES, res)
    if res.fatal:
        return res

    # --- manifest
    now = clock.now()
    entities: dict[str, dict[str, Any]] = {}
    for m in manifest:
        if m["source_entity"] in entities:
            res.fatal.append(f"manifest.csv: entity {m['source_entity']} declared twice")
        entities[m["source_entity"]] = m
        if m["source_refreshed_at"] > now + dt.timedelta(hours=1):
            res.fatal.append(f"manifest.csv: {m['source_entity']} source_refreshed_at is in the future")
        if m["period_start"] > m["period_end"]:
            res.fatal.append(f"manifest.csv: {m['source_entity']} period_start after period_end")
        if m["data_classification"] == "live" and not allow_live:
            res.fatal.append("manifest.csv: live data is refused in this prototype (set ALLOW_LIVE_IMPORT=true only after approval)")
        if synthetic_only and m["data_classification"] != "synthetic":
            res.fatal.append("manifest.csv: this hosted demo accepts synthetic data only")
    if not entities:
        res.fatal.append("manifest.csv: no entities declared")
    if res.fatal:
        return res

    def in_package(row: dict[str, Any], spec: FileSpec, entity_col: str = "source_entity") -> bool:
        if row[entity_col] not in entities:
            res.issues.append(Issue("error", "entity_not_in_manifest", row[entity_col], row.get("source_customer_id"),
                                    {"file": spec.name, "line": row["_line"]}))
            return False
        return True

    # --- measures
    measures = _dedupe(measures, ("measure_code",), MEASURES, res)
    valid_measures = []
    for m in measures:
        if m["certification_status"] == "certified" and not (m["approved_by"] and m["approved_at"]):
            res.issues.append(Issue("error", "certified_measure_without_approval", m["source_entity"],
                                    detail={"file": MEASURES.name, "line": m["_line"], "measure_code": m["measure_code"]}))
            continue
        valid_measures.append(m)
    measure_codes = {m["measure_code"] for m in valid_measures} | (existing_measures or set())

    # --- customers
    customers = [r for r in customers if in_package(r, CUSTOMERS)]
    customers = _dedupe(customers, ("source_entity", "source_customer_id"), CUSTOMERS, res)
    cust_keys = {(c["source_entity"], c["source_customer_id"]) for c in customers}

    def known_customer(row: dict[str, Any], spec: FileSpec) -> bool:
        if (row["source_entity"], row["source_customer_id"]) not in cust_keys:
            res.issues.append(Issue("error", "unknown_customer", row["source_entity"], row["source_customer_id"],
                                    {"file": spec.name, "line": row["_line"]}))
            return False
        return True

    # --- mappings (never inferred; only validated)
    mappings = _dedupe(mappings, ("mapping_ref",), MAPPING, res)
    valid_mappings = []
    for m in mappings:
        detail = {"file": MAPPING.name, "line": m["_line"], "mapping_ref": m["mapping_ref"]}
        if m["from_entity"] == m["to_entity"]:
            res.issues.append(Issue("error", "mapping_same_entity", m["from_entity"], m["from_customer_id"], detail))
            continue
        if m["mapping_status"] == "approved" and not (m["approved_by"] and m["approved_at"]):
            res.issues.append(Issue("error", "approved_mapping_without_approver", m["to_entity"], m["to_customer_id"], detail))
            continue
        for ent, cid in ((m["from_entity"], m["from_customer_id"]), (m["to_entity"], m["to_customer_id"])):
            if ent in entities and (ent, cid) not in cust_keys:
                res.issues.append(Issue("warning", "mapping_customer_not_in_package", ent, cid, detail))
        valid_mappings.append(m)

    # --- assignments
    assignments = [r for r in assignments if in_package(r, ASSIGNMENTS) and known_customer(r, ASSIGNMENTS)]
    by_customer: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for a in assignments:
        if a["valid_to"] and a["valid_to"] < a["valid_from"]:
            res.issues.append(Issue("error", "invalid_assignment_period", a["source_entity"], a["source_customer_id"],
                                    {"file": ASSIGNMENTS.name, "line": a["_line"]}))
            continue
        if known_salesperson_codes is not None and a["salesperson_code"] not in known_salesperson_codes:
            res.issues.append(Issue("warning", "unknown_salesperson_code", a["source_entity"], a["source_customer_id"],
                                    {"file": ASSIGNMENTS.name, "line": a["_line"], "salesperson_code": a["salesperson_code"]}))
        by_customer[(a["source_entity"], a["source_customer_id"])].append(a)
    valid_assignments = []
    for key, rows in by_customer.items():
        rows.sort(key=lambda r: r["valid_from"])
        for prev, cur in zip(rows, rows[1:]):
            if prev["valid_to"] is None or prev["valid_to"] >= cur["valid_from"]:
                res.issues.append(Issue("warning", "overlapping_assignments", key[0], key[1],
                                        {"file": ASSIGNMENTS.name, "lines": [prev["_line"], cur["_line"]]}))
        valid_assignments.extend(rows)

    # --- monthly measures
    monthly = [r for r in monthly if in_package(r, MONTHLY) and known_customer(r, MONTHLY)]
    monthly = _dedupe(monthly, ("source_entity", "record_key"), MONTHLY, res)
    natural = Counter((r["source_entity"], r["source_customer_id"], r["measure_code"], r["month"]) for r in monthly)
    valid_monthly = []
    for r in monthly:
        detail = {"file": MONTHLY.name, "line": r["_line"]}
        if natural[(r["source_entity"], r["source_customer_id"], r["measure_code"], r["month"])] > 1:
            res.issues.append(Issue("error", "duplicate_customer_month", r["source_entity"], r["source_customer_id"],
                                    {**detail, "month": r["month"].isoformat(), "measure_code": r["measure_code"]}))
            continue
        if r["measure_code"] not in measure_codes:
            res.issues.append(Issue("error", "unregistered_measure", r["source_entity"], r["source_customer_id"],
                                    {**detail, "measure_code": r["measure_code"]}))
            continue
        man = entities[r["source_entity"]]
        if not (man["period_start"].replace(day=1) <= r["month"] <= man["period_end"]):
            res.issues.append(Issue("error", "outside_declared_period", r["source_entity"], r["source_customer_id"], detail))
            continue
        valid_monthly.append(r)

    # --- purchases
    purchases = [r for r in purchases if in_package(r, PURCHASES) and known_customer(r, PURCHASES)]
    purchases = _dedupe(purchases, ("source_entity", "record_key"), PURCHASES, res)
    valid_purchases = []
    for r in purchases:
        detail = {"file": PURCHASES.name, "line": r["_line"]}
        man = entities[r["source_entity"]]
        refreshed_day = man["source_refreshed_at"].astimezone(clock.BUSINESS_TZ).date()
        if not (man["period_start"] <= r["document_date"] <= min(man["period_end"], refreshed_day)):
            res.issues.append(Issue("error", "outside_declared_period", r["source_entity"], r["source_customer_id"], detail))
            continue
        if r["amount"] is not None and (r["amount_measure_code"] not in measure_codes or not r["currency"]):
            res.issues.append(Issue("error", "amount_without_registered_measure", r["source_entity"], r["source_customer_id"], detail))
            continue
        if r["document_type"] == "invoice" and r["quantity"] is not None and r["quantity"] < 0:
            res.issues.append(Issue("warning", "negative_quantity_on_invoice", r["source_entity"], r["source_customer_id"], detail))
        valid_purchases.append(r)

    res.rows = {
        MANIFEST.name: manifest,
        CUSTOMERS.name: customers,
        MAPPING.name: valid_mappings,
        ASSIGNMENTS.name: valid_assignments,
        MEASURES.name: valid_measures,
        MONTHLY.name: valid_monthly,
        PURCHASES.name: valid_purchases,
    }
    for name, rows in res.rows.items():
        res.counts.setdefault(name, {})["accepted"] = len(rows)
    for spec in (MONTHLY, PURCHASES):
        c = res.counts[spec.name]
        if c["read"] and (c["read"] - c["accepted"]) / c["read"] > MAX_ROW_ERROR_RATE:
            res.fatal.append(f"{spec.name}: {c['read'] - c['accepted']}/{c['read']} rows rejected exceeds {MAX_ROW_ERROR_RATE:.0%}")
    return res
