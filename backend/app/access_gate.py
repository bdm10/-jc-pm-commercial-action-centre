"""Application-level login gate for hosted demos.

Wraps the whole application: the interface, static assets, API and API docs
all require signing in with the demo username and password, which are read
from environment variables (DEMO_ACCESS_USER / DEMO_ACCESS_PASSWORD) and never
stored in the repository.

* Browser page requests without a session are redirected to /login, a small
  self-contained page served by this gate. Signing in sets a signed, HttpOnly
  session cookie.
* API and other non-page requests without a session get 401 JSON
  ({"error": {"code": "login_required"}}); the SPA then sends the user to /login.
* Scripts may instead send the same credentials as HTTP Basic authentication.
  No Basic challenge is ever sent, so browsers never show their own prompt.
* /healthz (no data) stays open for the hosting platform's health check.

Sessions are signed with a key derived from SESSION_SECRET *and* the current
credentials, so changing the password signs everyone out. Repeated wrong
passwords from one client are throttled.

This is an access barrier for a synthetic-data demo, not user authentication:
behind it, demo-user switching is still available by design.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import html
import secrets
import time
from collections import deque
from urllib.parse import parse_qs, quote, urlsplit

from starlette.types import ASGIApp, Receive, Scope, Send

COOKIE = "cac_session"
OPEN_PATHS = frozenset({"/healthz", "/favicon.svg"})
MAX_FAILURES = 20  # per client address ...
WINDOW_SECONDS = 600  # ... per 10 minutes, then 429 until the window passes
MAX_FORM_BYTES = 4096


class AccessGate:
    def __init__(self, app: ASGIApp, user: str, password: str, session_secret: str = "", session_hours: float = 12.0):
        self.app = app
        self._user = user.encode()
        self._password = password.encode()
        secret = session_secret.encode() or secrets.token_bytes(32)  # without SESSION_SECRET sessions end on restart
        self._key = hmac.new(secret, b"cac-session-v1\0" + self._user + b"\0" + self._password, hashlib.sha256).digest()
        self._ttl = int(session_hours * 3600)
        self._failures: dict[str, deque[float]] = {}

    # ------------------------------------------------------------------ ASGI entry point

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        method = scope.get("method", "GET")
        if path in OPEN_PATHS:
            await self.app(scope, receive, send)
            return
        if path == "/login":
            if method == "POST":
                await self._login_submit(scope, receive, send)
            else:
                await self._login_page(scope, send)
            return
        if path == "/logout":
            await self._redirect(send, "/login", clear_cookie=True)
            return

        if self._valid_session(scope):
            await self.app(scope, receive, send)
            return
        client = _client(scope)
        basic = self._basic_credentials(scope)
        if basic is not None and self._throttled(client):
            await _reply(send, 429, b'{"error":{"code":"too_many_attempts"}}', "application/json",
                         [(b"retry-after", str(WINDOW_SECONDS).encode())])
            return
        if basic is not None:
            if self._credentials_ok(*basic):
                await self.app(scope, receive, send)
                return
            self._record_failure(client)
        if method in ("GET", "HEAD") and not path.startswith("/api/") and _wants_html(scope):
            target = path + ("?" + scope["query_string"].decode("latin-1") if scope.get("query_string") else "")
            await self._redirect(send, "/login?next=" + quote(_safe_next(target), safe=""))
            return
        await _reply(send, 401, b'{"error":{"code":"login_required"}}', "application/json")

    # ------------------------------------------------------------------ login page and form

    async def _login_page(self, scope: Scope, send: Send, error: bool = False, status: int = 200, next_path: str | None = None) -> None:
        if next_path is None:
            next_path = _safe_next(parse_qs(scope.get("query_string", b"").decode("latin-1")).get("next", ["/"])[0])
        if not error and self._valid_session(scope):
            await self._redirect(send, next_path)
            return
        body = _LOGIN_HTML.replace("{{next}}", html.escape(next_path, quote=True)).replace(
            "{{error}}", _ERROR_HTML if error else "")
        await _reply(send, status, body.encode(), "text/html; charset=utf-8", [
            (b"content-security-policy", b"default-src 'none'; style-src 'unsafe-inline'; img-src data:; "
                                         b"form-action 'self'; base-uri 'none'; frame-ancestors 'none'"),
        ])

    async def _login_submit(self, scope: Scope, receive: Receive, send: Send) -> None:
        client = _client(scope)
        if self._throttled(client):
            await _reply(send, 429, "Demasiados intentos. Inténtelo de nuevo en unos minutos. / Too many attempts.".encode(),
                         "text/plain; charset=utf-8", [(b"retry-after", str(WINDOW_SECONDS).encode())])
            return
        form = await _read_form(receive)
        next_path = _safe_next(form.get("next", "/"))
        if self._credentials_ok(form.get("username", "").encode(), form.get("password", "").encode()):
            await self._redirect(send, next_path, cookie=self._new_session(), secure=scope.get("scheme") == "https")
            return
        self._record_failure(client)
        await self._login_page(scope, send, error=True, status=401, next_path=next_path)

    # ------------------------------------------------------------------ credentials and sessions

    def _credentials_ok(self, user: bytes, password: bytes) -> bool:
        ok_user = secrets.compare_digest(user, self._user)
        ok_password = secrets.compare_digest(password, self._password)
        return ok_user and ok_password

    def _new_session(self) -> str:
        payload = f"v1.{int(time.time()) + self._ttl}"
        sig = hmac.new(self._key, payload.encode(), hashlib.sha256).hexdigest()
        return f"{payload}.{sig}"

    def _valid_session(self, scope: Scope) -> bool:
        token = _cookie(scope, COOKIE)
        if not token or token.count(".") != 2:
            return False
        version, expiry, sig = token.split(".")
        expected = hmac.new(self._key, f"{version}.{expiry}".encode(), hashlib.sha256).hexdigest()
        if version != "v1" or not secrets.compare_digest(sig, expected):
            return False
        return expiry.isdigit() and int(expiry) > time.time()

    @staticmethod
    def _basic_credentials(scope: Scope) -> tuple[bytes, bytes] | None:
        raw = _header(scope, b"authorization")
        if not raw.lower().startswith(b"basic "):
            return None
        try:
            decoded = base64.b64decode(raw[6:].strip(), validate=True)
        except (binascii.Error, ValueError):
            return b"", b""
        user, _, password = decoded.partition(b":")
        return user, password

    # ------------------------------------------------------------------ throttling

    def _recent(self, client: str) -> deque[float]:
        if len(self._failures) > 10_000:  # bound memory under a spray of addresses
            self._failures.clear()
        q = self._failures.setdefault(client, deque())
        now = time.monotonic()
        while q and now - q[0] > WINDOW_SECONDS:
            q.popleft()
        return q

    def _throttled(self, client: str) -> bool:
        return len(self._recent(client)) >= MAX_FAILURES

    def _record_failure(self, client: str) -> None:
        self._recent(client).append(time.monotonic())

    # ------------------------------------------------------------------ responses

    async def _redirect(self, send: Send, location: str, cookie: str | None = None, secure: bool = False,
                        clear_cookie: bool = False) -> None:
        headers = [(b"location", location.encode("latin-1", "ignore"))]
        if cookie is not None:
            attrs = f"{COOKIE}={cookie}; Path=/; HttpOnly; SameSite=Lax; Max-Age={self._ttl}" + ("; Secure" if secure else "")
            headers.append((b"set-cookie", attrs.encode()))
        if clear_cookie:
            headers.append((b"set-cookie", f"{COOKIE}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0".encode()))
        await _reply(send, 303, b"", "text/plain", headers)


# ---------------------------------------------------------------------- helpers


def _header(scope: Scope, name: bytes) -> bytes:
    for k, v in scope.get("headers") or []:
        if k == name:
            return v
    return b""


def _cookie(scope: Scope, name: str) -> str | None:
    for part in _header(scope, b"cookie").decode("latin-1").split(";"):
        k, _, v = part.strip().partition("=")
        if k == name:
            return v
    return None


def _client(scope: Scope) -> str:
    return (scope.get("client") or ("unknown", 0))[0]


def _wants_html(scope: Scope) -> bool:
    accept = _header(scope, b"accept").decode("latin-1").lower()
    return "text/html" in accept or not accept


def _safe_next(value: str) -> str:
    """Only same-site relative paths: no scheme, no host, no protocol-relative or backslash tricks."""
    value = (value or "/").strip()
    parts = urlsplit(value)
    if (not value.startswith("/") or value.startswith("//") or "\\" in value or parts.scheme or parts.netloc
            or len(value) > 2000 or value.startswith("/login") or value.startswith("/logout")):
        return "/"
    return value


async def _read_form(receive: Receive) -> dict[str, str]:
    body = b""
    more = True
    while more:
        message = await receive()
        body += message.get("body", b"")
        more = message.get("more_body", False)
        if len(body) > MAX_FORM_BYTES:
            return {}
    fields = parse_qs(body.decode("utf-8", "replace"), keep_blank_values=True)
    return {k: v[0] for k, v in fields.items()}


async def _reply(send: Send, status: int, body: bytes, content_type: str, extra: list[tuple[bytes, bytes]] | None = None) -> None:
    headers = [(b"content-type", content_type.encode()), (b"content-length", str(len(body)).encode()),
               (b"cache-control", b"no-store"), *(extra or [])]
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})


_ERROR_HTML = '<p class="error" role="alert">Usuario o contraseña incorrectos.<br><span lang="en">Wrong username or password.</span></p>'

_LOGIN_HTML = """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>Acceso · Centro de Acción Comercial (demo)</title>
<style>
  :root { color-scheme: light; }
  * { box-sizing: border-box; }
  body { margin: 0; min-height: 100vh; display: grid; place-items: center; padding: 16px;
         background: #f5f4f0; color: #1b2230; font: 16px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif; }
  main { width: 100%; max-width: 400px; background: #fff; border: 1px solid #e3dfd7; border-radius: 14px; padding: 24px;
         box-shadow: 0 2px 8px rgba(27,34,48,.05); }
  h1 { font-size: 20px; margin: 0 0 2px; }
  .sub { color: #5f6777; margin: 0 0 18px; font-size: 14px; }
  .note { background: #fbf0d9; color: #7f5200; border-radius: 10px; padding: 8px 12px; font-size: 13.5px; margin-bottom: 18px; }
  label { display: block; font-weight: 600; font-size: 14.5px; margin: 12px 0 6px; }
  input { width: 100%; min-height: 48px; border: 1px solid #cbc5ba; border-radius: 10px; padding: 10px 12px; font: inherit; }
  input:focus-visible, button:focus-visible { outline: 3px solid #2457c5; outline-offset: 2px; }
  button { width: 100%; min-height: 48px; margin-top: 18px; border: 0; border-radius: 10px; background: #6e1d35; color: #fff;
           font: inherit; font-weight: 650; cursor: pointer; }
  button:hover { background: #58172a; }
  .error { background: #f8e8e6; color: #8b2a2a; border-radius: 10px; padding: 8px 12px; font-size: 14px; }
  .en { color: #5f6777; font-size: 13px; }
</style>
</head>
<body>
<main>
  <h1>Centro de Acción Comercial</h1>
  <p class="sub">JC / PM · Acceso a la demo <span class="en">· Demo sign-in</span></p>
  <p class="note">Demo con datos sintéticos, no certificados. <span lang="en">Synthetic, non-certified data.</span></p>
  {{error}}
  <form method="post" action="/login">
    <input type="hidden" name="next" value="{{next}}">
    <label for="username">Usuario <span class="en" lang="en">/ Username</span></label>
    <input id="username" name="username" autocomplete="username" autocapitalize="none" spellcheck="false" required autofocus>
    <label for="password">Contraseña <span class="en" lang="en">/ Password</span></label>
    <input id="password" name="password" type="password" autocomplete="current-password" required>
    <button type="submit">Entrar <span lang="en">· Sign in</span></button>
  </form>
</main>
</body>
</html>
"""
