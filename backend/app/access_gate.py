"""Shared-password gate for hosted demos (HTTP Basic authentication).

Wraps the whole application, so the interface, static assets, API and API docs
all require the access password. Only /healthz (no data) stays open for the
hosting platform's health check. Browsers show their native sign-in prompt and
then send the credentials with every same-origin request, including the SPA's
API calls.

This is an access barrier for a synthetic-data demo, not user authentication:
behind it, demo-user switching is still available by design.
"""

from __future__ import annotations

import base64
import binascii
import secrets
import time
from collections import deque

from starlette.types import ASGIApp, Receive, Scope, Send

OPEN_PATHS = frozenset({"/healthz"})
REALM = "JC-PM Commercial Action Centre (demo)"
MAX_FAILURES = 20  # per client IP ...
WINDOW_SECONDS = 600  # ... per 10 minutes, then 429 until the window passes


class AccessGate:
    def __init__(self, app: ASGIApp, user: str, password: str):
        self.app = app
        self._user = user.encode()
        self._password = password.encode()
        self._failures: dict[str, deque[float]] = {}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") in OPEN_PATHS:
            await self.app(scope, receive, send)
            return
        client = (scope.get("client") or ("unknown", 0))[0]
        now = time.monotonic()
        failures = self._recent_failures(client, now)
        if len(failures) >= MAX_FAILURES:
            await self._reply(send, 429, b'{"error":{"code":"too_many_attempts"}}', [(b"retry-after", str(WINDOW_SECONDS).encode())])
            return
        if self._authorised(scope):
            await self.app(scope, receive, send)
            return
        if _has_basic_header(scope):  # count wrong passwords, not the browser's first unauthenticated request
            failures.append(now)
        await self._reply(send, 401, b'{"error":{"code":"access_required"}}',
                          [(b"www-authenticate", f'Basic realm="{REALM}", charset="UTF-8"'.encode())])

    def _authorised(self, scope: Scope) -> bool:
        raw = dict(scope.get("headers") or []).get(b"authorization", b"")
        if not raw.lower().startswith(b"basic "):
            return False
        try:
            decoded = base64.b64decode(raw[6:].strip(), validate=True)
        except (binascii.Error, ValueError):
            return False
        user, sep, password = decoded.partition(b":")
        if not sep:
            return False
        ok_user = secrets.compare_digest(user, self._user)
        ok_password = secrets.compare_digest(password, self._password)
        return ok_user and ok_password

    def _recent_failures(self, client: str, now: float) -> deque[float]:
        if len(self._failures) > 10_000:  # bound memory under a spray of addresses
            self._failures.clear()
        q = self._failures.setdefault(client, deque())
        while q and now - q[0] > WINDOW_SECONDS:
            q.popleft()
        return q

    @staticmethod
    async def _reply(send: Send, status: int, body: bytes, extra: list[tuple[bytes, bytes]]) -> None:
        headers = [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()),
                   (b"cache-control", b"no-store"), *extra]
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": body})


def _has_basic_header(scope: Scope) -> bool:
    return dict(scope.get("headers") or []).get(b"authorization", b"").lower().startswith(b"basic ")
