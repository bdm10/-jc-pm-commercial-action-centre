"""Administration: provisional rule configuration, data issues, imports, refresh, audit."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.common import bad_request, freshness
from app.auth.deps import require_role
from app.db import get_db
from app.models import facts as F
from app.models.records import AppUser, AuditLog, Opportunity, RuleConfig
from app.rules.config import DEFAULT_PARAMS, merged_params, validate_params
from app.services.audit import audit
from app.services.refresh import run_refresh
from app.services.rule_config import active_config

router = APIRouter(prefix="/admin")
admin_only = require_role("admin")


@router.get("/config")
def get_config(user: AppUser = Depends(admin_only), db: Session = Depends(get_db)) -> dict:
    version, params = active_config(db)
    history = [{"version": r.version, "created_at": r.created_at.isoformat(), "note": r.note, "approval_status": r.approval_status,
                "created_by_user_id": r.created_by_user_id}
               for r in db.execute(select(RuleConfig).order_by(RuleConfig.version.desc()).limit(20)).scalars()]
    return {"version": version, "approval_status": "provisional", "params": params, "defaults": DEFAULT_PARAMS, "history": history}


class ConfigIn(BaseModel):
    params: dict[str, Any]
    note: str = Field(min_length=3, max_length=500)


@router.put("/config")
def put_config(body: ConfigIn, user: AppUser = Depends(admin_only), db: Session = Depends(get_db)) -> dict:
    merged = merged_params(body.params)
    problems = validate_params(merged)
    if problems:
        raise bad_request("invalid_config", problems=problems)
    prev_version, prev = active_config(db)
    row = RuleConfig(params=merged, approval_status="provisional", note=body.note, created_by_user_id=user.id)
    db.add(row)
    db.flush()
    audit(db, user.id, "rule_config_changed", "rule_config", row.version, {"from_version": prev_version, "note": body.note})
    db.commit()
    stats = run_refresh(db, actor_user_id=user.id)
    return {"version": row.version, "refresh": stats}


@router.get("/data-issues")
def data_issues(stage: str = "", severity: str = "", limit: int = Query(300, ge=1, le=2000),
                user: AppUser = Depends(admin_only), db: Session = Depends(get_db)) -> dict:
    stmt = select(F.DataIssue).order_by(F.DataIssue.severity, F.DataIssue.issue_code)
    if stage:
        stmt = stmt.where(F.DataIssue.stage == stage)
    if severity:
        stmt = stmt.where(F.DataIssue.severity == severity)
    rows = db.execute(stmt.limit(limit)).scalars().all()
    reports = db.execute(select(Opportunity).where(Opportunity.dismissed_reason == "data_incorrect")).scalars().all()
    return {
        "items": [{"id": i.id, "stage": i.stage, "severity": i.severity, "issue_code": i.issue_code,
                   "source_entity": i.source_entity, "source_customer_id": i.source_customer_id, "detail": i.detail,
                   "detected_at": i.detected_at.isoformat()} for i in rows],
        "user_reports": [{"opportunity_id": o.id, "source_entity": o.source_entity, "source_customer_id": o.source_customer_id,
                          "opp_type": o.opp_type, "note": o.dismissed_note,
                          "reported_at": o.dismissed_at.isoformat() if o.dismissed_at else None} for o in reports],
    }


@router.get("/imports")
def imports(user: AppUser = Depends(admin_only), db: Session = Depends(get_db)) -> dict:
    _, params = active_config(db)
    runs = db.execute(select(F.ImportRun).order_by(F.ImportRun.id.desc()).limit(20)).scalars().all()
    return {"freshness": freshness(db, params),
            "runs": [{"id": r.id, "started_at": r.started_at.isoformat(), "package_label": r.package_label, "status": r.status,
                      "summary": r.summary} for r in runs]}


@router.post("/refresh")
def refresh(user: AppUser = Depends(admin_only), db: Session = Depends(get_db)) -> dict:
    return run_refresh(db, actor_user_id=user.id)


@router.get("/audit")
def audit_log(limit: int = Query(100, ge=1, le=500), user: AppUser = Depends(admin_only), db: Session = Depends(get_db)) -> dict:
    rows = db.execute(select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)).scalars().all()
    return {"items": [{"id": r.id, "at": r.at.isoformat(), "actor_user_id": r.actor_user_id, "action": r.action,
                       "entity_type": r.entity_type, "entity_id": r.entity_id, "detail": r.detail} for r in rows]}
