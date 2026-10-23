"""Request authentication. Fails closed.

* AUTH_MODE unset          -> every protected request is rejected (401 auth_not_configured).
* AUTH_MODE=demo           -> X-Demo-User header selects a seeded user. Never in production.
* AUTH_MODE=entra          -> Bearer access token validated against Entra ID; user matched by object ID.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.entra import TokenError, validate_token
from app.config import get_settings
from app.db import get_db
from app.models.records import AppUser


def _deny(status: int, code: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code})


def current_user(request: Request, db: Session = Depends(get_db)) -> AppUser:
    s = get_settings()
    if s.auth_mode == "demo":
        if not s.demo_mode:
            raise _deny(401, "demo_mode_disabled")
        email = request.headers.get("X-Demo-User", "").strip().lower()
        if not email:
            raise _deny(401, "demo_user_required")
        user = db.execute(select(AppUser).where(AppUser.email == email, AppUser.active.is_(True))).scalar_one_or_none()
        if user is None:
            raise _deny(401, "unknown_user")
        return user
    if s.auth_mode == "entra":
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            raise _deny(401, "token_required")
        try:
            ident = validate_token(header.removeprefix("Bearer ").strip(), s)
        except TokenError as exc:
            raise _deny(401, str(exc).split(":")[0]) from exc
        user = db.execute(select(AppUser).where(AppUser.entra_object_id == ident.object_id)).scalar_one_or_none()
        if user is None or not user.active:
            raise _deny(403, "user_not_provisioned")
        return user
    raise _deny(401, "auth_not_configured")


def require_role(*roles: str):
    def dep(user: AppUser = Depends(current_user)) -> AppUser:
        if user.role not in roles:
            raise _deny(403, "forbidden")
        return user

    return dep
