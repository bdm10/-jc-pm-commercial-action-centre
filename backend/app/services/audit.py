from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models.records import AuditLog


def audit(db: Session, actor_user_id: int | None, action: str, entity_type: str, entity_id: Any, detail: dict[str, Any] | None = None) -> None:
    """Append an audit record in the caller's transaction."""
    db.add(AuditLog(actor_user_id=actor_user_id, action=action, entity_type=entity_type,
                    entity_id=str(entity_id), detail=detail or {}))
