"""Load a validated package as a full snapshot for the entities in its manifest."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.importer.contract import ASSIGNMENTS, CUSTOMERS, MANIFEST, MAPPING, MEASURES, MONTHLY, PURCHASES
from app.importer.validate import ValidationResult, validate_package
from app.models import facts as F
from app.models.records import AppUser
from app.services.audit import audit


def _strip(row: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in row.items() if not k.startswith("_")}


def import_package(db: Session, folder: Path, force: bool = False, actor_user_id: int | None = None) -> tuple[ValidationResult, F.ImportRun | None]:
    codes = {c for c in db.execute(select(AppUser.salesperson_code)).scalars() if c}
    existing_measures = set(db.execute(select(F.MeasureDefinition.measure_code)).scalars())
    res = validate_package(folder, known_salesperson_codes=codes, existing_measures=existing_measures,
                           allow_live=get_settings().allow_live_import)

    if not force and res.checksum:
        last = db.execute(select(F.ImportRun).where(F.ImportRun.status == "loaded").order_by(F.ImportRun.id.desc()).limit(1)).scalar_one_or_none()
        if last is not None and last.checksum == res.checksum:
            return res, None  # identical package already loaded: idempotent no-op

    run = F.ImportRun(package_label=res.package_label, checksum=res.checksum or "-",
                      status="loaded" if res.ok else "rejected", summary=res.summary())
    db.add(run)
    db.flush()
    if not res.ok:
        audit(db, actor_user_id, "import_rejected", "import_run", run.id, res.summary())
        db.commit()
        return res, run

    entities = [m["source_entity"] for m in res.rows[MANIFEST.name]]
    for m in res.rows[MANIFEST.name]:
        db.add(F.SourceRefresh(run_id=run.id, **{k: v for k, v in _strip(m).items() if k != "contract_version"}))

    # Full-snapshot replacement for the declared entities.
    for model in (F.Customer, F.Assignment, F.MeasureMonthly, F.Purchase):
        db.execute(delete(model).where(model.source_entity.in_(entities)))
    db.execute(delete(F.MeasureDefinition).where(F.MeasureDefinition.source_entity.in_(entities)))
    # The mapping file is the complete register of cross-entity links: it replaces all mappings.
    db.execute(delete(F.CustomerMapping))

    for r in res.rows[MEASURES.name]:
        db.add(F.MeasureDefinition(run_id=run.id, **_strip(r)))
    db.flush()
    for spec, model in ((CUSTOMERS, F.Customer), (MAPPING, F.CustomerMapping), (ASSIGNMENTS, F.Assignment),
                        (MONTHLY, F.MeasureMonthly), (PURCHASES, F.Purchase)):
        rows = [{**_strip(r), "run_id": run.id} for r in res.rows[spec.name]]
        if rows:
            db.execute(insert(model), rows)

    db.execute(delete(F.DataIssue).where(F.DataIssue.stage == "import"))
    for i in res.issues:
        db.add(F.DataIssue(stage="import", run_id=run.id, severity=i.severity, issue_code=i.issue_code,
                           source_entity=i.source_entity, source_customer_id=i.source_customer_id, detail=i.detail))
    audit(db, actor_user_id, "import_loaded", "import_run", run.id, {**res.summary(), "entities": entities})
    db.commit()
    return res, run
