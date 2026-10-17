from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.records import RuleConfig
from app.rules.config import merged_params


def active_config(db: Session) -> tuple[int, dict[str, Any]]:
    """Latest config version and its parameters (defaults when nothing is stored yet: version 0)."""
    row = db.execute(select(RuleConfig).order_by(RuleConfig.version.desc()).limit(1)).scalar_one_or_none()
    if row is None:
        return 0, merged_params(None)
    return row.version, merged_params(row.params)
