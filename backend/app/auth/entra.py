"""Microsoft Entra ID access-token validation (SCAFFOLDED).

Implements standard v2.0 access-token checks (signature via the tenant JWKS,
issuer, audience, expiry, tenant, optional scope). Covered by unit tests with
locally signed tokens, but NOT yet verified against a real tenant or app
registration - see docs/INTEGRATION_CHECKLIST.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import jwt
from jwt import PyJWKClient

from app.config import Settings


class TokenError(Exception):
    pass


@dataclass(frozen=True)
class EntraIdentity:
    object_id: str
    tenant_id: str
    name: str | None
    upn: str | None


@lru_cache
def _jwks_client(tenant_id: str) -> PyJWKClient:
    return PyJWKClient(f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys", cache_keys=True)


def validate_token(token: str, settings: Settings, signing_key: Any | None = None) -> EntraIdentity:
    """Validate a bearer token. `signing_key` is injectable for tests; otherwise fetched from JWKS."""
    tenant = settings.entra_tenant_id
    client_id = settings.entra_api_client_id
    if not tenant or not client_id:
        raise TokenError("entra_not_configured")
    try:
        key = signing_key if signing_key is not None else _jwks_client(tenant).get_signing_key_from_jwt(token).key
        claims = jwt.decode(
            token,
            key=key,
            algorithms=["RS256"],
            audience=[client_id, f"api://{client_id}"],
            issuer=f"https://login.microsoftonline.com/{tenant}/v2.0",
            options={"require": ["exp", "iat", "aud", "iss", "oid", "tid"]},
        )
    except jwt.PyJWTError as exc:
        raise TokenError(f"invalid_token: {exc.__class__.__name__}") from exc
    if claims.get("tid") != tenant:
        raise TokenError("wrong_tenant")
    if settings.entra_api_scope:
        required = settings.entra_api_scope.rsplit("/", 1)[-1]
        if required not in str(claims.get("scp", "")).split():
            raise TokenError("missing_scope")
    return EntraIdentity(object_id=claims["oid"], tenant_id=claims["tid"], name=claims.get("name"),
                         upn=claims.get("preferred_username"))
