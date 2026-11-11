"""HTTP hardening for a single-operator app (same rules as the old Project Zero, rewritten).

* Host allow-list (DNS-rebinding protection): loopback names plus ``PZ_ALLOWED_HOSTS``.
* Cross-site writes refused (CSRF from other web pages): a state-changing request whose ``Origin`` is not this host,
  or that the browser marks ``Sec-Fetch-Site: cross-site``, gets 403.
* Optional bearer token (``PZ_AUTH_TOKEN``) — required when listening on a non-loopback address.
* ``nosniff`` / ``DENY`` / ``no-referrer`` on everything, ``no-store`` on the API.
"""

from __future__ import annotations

import hmac
import os
from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit

from fastapi import Request, Response
from fastapi.responses import JSONResponse

LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "[::1]", "::1"})
WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}


def _hostname(host_header: str) -> str:
    host = host_header.strip().lower()
    if host.startswith("["):
        return host[: host.find("]") + 1]
    return host.rsplit(":", 1)[0] if host.count(":") == 1 else host


def allowed_hosts() -> frozenset[str]:
    extra = {h.strip().lower() for h in os.environ.get("PZ_ALLOWED_HOSTS", "").split(",") if h.strip()}
    return LOOPBACK_HOSTS | extra


def _refuse(status: int, message: str) -> JSONResponse:
    return JSONResponse({"ok": False, "error": message}, status_code=status, headers=SECURITY_HEADERS)


async def security_middleware(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    host = _hostname(request.headers.get("host", ""))
    if host not in allowed_hosts():
        return _refuse(403, "host not allowed")
    if request.method in WRITE_METHODS:
        origin = request.headers.get("origin")
        if origin and _hostname(urlsplit(origin).netloc) != host:
            return _refuse(403, "cross-origin write refused")
        if request.headers.get("sec-fetch-site") == "cross-site":
            return _refuse(403, "cross-site write refused")
    token = os.environ.get("PZ_AUTH_TOKEN", "")
    if token and request.url.path.startswith("/api/"):
        supplied = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        if not hmac.compare_digest(supplied.encode(), token.encode()):
            return _refuse(401, "missing or wrong bearer token")
    response = await call_next(request)
    response.headers.update(SECURITY_HEADERS)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response
