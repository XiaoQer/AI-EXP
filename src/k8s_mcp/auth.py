"""Simple Bearer token auth middleware."""

from __future__ import annotations

import hmac

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from k8s_mcp.logging_config import get_logger

logger = get_logger("auth")


class BearerAuthMiddleware:
    """ASGI middleware that requires Authorization: Bearer <token> when expected_token is set."""

    def __init__(self, app: ASGIApp, expected_token: str | None) -> None:
        self.app = app
        self.expected_token = expected_token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        if not self.expected_token:
            await self.app(scope, receive, send)
            return

        path = (scope.get("path") or "").rstrip("/") or "/"
        if path == "/health":
            await self.app(scope, receive, send)
            return

        auth: str | None = None
        for k, v in scope.get("headers") or []:
            if k.lower() == b"authorization":
                auth = v.decode() if isinstance(v, bytes) else str(v)
                break

        token: str | None = None
        if auth and auth.lower().startswith("bearer "):
            token = auth[7:].strip()

        if not token or not hmac.compare_digest(token, self.expected_token):
            logger.warning("auth rejected path=%s has_token=%s", path, bool(token))
            response = JSONResponse(
                {"error": "invalid_token", "error_description": "Authentication required"},
                status_code=401,
                headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)
