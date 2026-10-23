"""Import contract validation, duplicate handling and mapping failures."""

from __future__ import annotations

import csv
import shutil
from pathlib import Path

from sqlalchemy import func, select

from app.importer.load import import_package
from app.importer.validate import validate_package
from app.models import facts as F
from app.services.refresh import run_refresh


def copy_pkg(src: Path, dst: Path) -> Path:
    shutil.copytree(src, dst)
    return dst


def rewrite(path: Path, fn) -> None:
    with path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
        fields = list(rows[0].keys()) if rows else []
    rows, fields = fn(rows, fields)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def test_synthetic_package_validates_and_reports_planted_problems(synthetic_package):
    folder, _ = synthetic_package
    res = validate_package(folder)
    assert res.ok, res.fatal
    codes = {i.issue_code for i in res.issues}
    assert {"duplicate_row_dropped", "conflicting_duplicate_rows", "mapping_customer_not_in_package"} <= codes
    manifest = res.rows["manifest.csv"]
    assert {m["data_classification"] for m in manifest} == {"synthetic"}


def test_exact_duplicates_kept_once_conflicting_duplicates_dropped(db, synthetic_package):
    folder, _ = synthetic_package
    res, run = import_package(db, folder, force=True)
    keys = db.execute(select(F.Purchase.record_key, func.count()).group_by(F.Purchase.source_entity, F.Purchase.record_key)
                      .having(func.count() > 1)).all()
    assert keys == []
    conflict = next(i for i in res.issues if i.issue_code == "conflicting_duplicate_rows")
    # the conflicting customer-month is not loaded at all ...
    n = db.execute(select(func.count()).select_from(F.MeasureMonthly).where(
        F.MeasureMonthly.source_entity == conflict.source_entity,
        F.MeasureMonthly.record_key == conflict.detail["key"][1])).scalar_one()
    assert n == 0
    # ... and the customer is suppressed instead of reading the missing month as zero sales
    run_refresh(db)
    issue = db.execute(select(F.DataIssue).where(F.DataIssue.issue_code == "incomplete_customer_data")).scalar_one()
    assert (issue.source_entity, issue.source_customer_id) == (conflict.source_entity, conflict.source_customer_id)


def test_missing_column_rejects_whole_package_and_keeps_previous_snapshot(db, synthetic_package, tmp_path):
    folder, _ = synthetic_package
    import_package(db, folder, force=True)
    before = db.execute(select(func.count()).select_from(F.Customer)).scalar_one()
    bad = copy_pkg(folder, tmp_path / "bad")
    rewrite(bad / "purchases.csv", lambda rows, f: ([{k: v for k, v in r.items() if k != "document_date"} for r in rows],
                                                    [x for x in f if x != "document_date"]))
    res, run = import_package(db, bad)
    assert not res.ok and run.status == "rejected"
    assert any("missing columns" in p for p in res.fatal)
    assert db.execute(select(func.count()).select_from(F.Customer)).scalar_one() == before


def test_live_data_refused_in_prototype(synthetic_package, tmp_path):
    folder, _ = synthetic_package
    pkg = copy_pkg(folder, tmp_path / "live")
    rewrite(pkg / "manifest.csv", lambda rows, f: ([{**r, "data_classification": "live"} for r in rows], f))
    res = validate_package(pkg)
    assert not res.ok and any("live data is refused" in p for p in res.fatal)


def test_future_refresh_timestamp_refused(synthetic_package, tmp_path):
    folder, _ = synthetic_package
    pkg = copy_pkg(folder, tmp_path / "future")
    rewrite(pkg / "manifest.csv", lambda rows, f: ([{**r, "source_refreshed_at": "2027-01-01T06:00:00+01:00"} for r in rows], f))
    assert not validate_package(pkg).ok


def test_reimporting_identical_package_is_a_no_op(db, synthetic_package):
    folder, _ = synthetic_package
    _, first = import_package(db, folder, force=True)
    _, second = import_package(db, folder)
    assert first is not None and second is None
    assert db.execute(select(func.count()).select_from(F.ImportRun)).scalar_one() == 1


def test_invalid_mappings_are_rejected_row_by_row(synthetic_package, tmp_path):
    folder, _ = synthetic_package
    pkg = copy_pkg(folder, tmp_path / "maps")

    def damage(rows, f):
        rows[0] = {**rows[0], "to_entity": rows[0]["from_entity"]}  # same-entity mapping
        rows[1] = {**rows[1], "approved_by": ""}  # approved without approver
        return rows, f

    rewrite(pkg / "customer_mapping.csv", damage)
    res = validate_package(pkg)
    codes = [i.issue_code for i in res.issues]
    assert "mapping_same_entity" in codes and "approved_mapping_without_approver" in codes
    assert len(res.rows["customer_mapping.csv"]) == res.counts["customer_mapping.csv"]["read"] - 2


def test_rows_for_unknown_customers_are_rejected(synthetic_package, tmp_path):
    folder, _ = synthetic_package
    pkg = copy_pkg(folder, tmp_path / "orphans")
    rewrite(pkg / "purchases.csv", lambda rows, f: (rows + [{**rows[0], "record_key": "X|1", "source_customer_id": "SYN-PM-NOPE"}], f))
    res = validate_package(pkg)
    assert any(i.issue_code == "unknown_customer" and i.source_customer_id == "SYN-PM-NOPE" for i in res.issues)
