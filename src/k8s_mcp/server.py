"""Kubernetes MCP server (HTTP)."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from starlette.types import ASGIApp

import uvicorn
from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from k8s_mcp.auth import BearerAuthMiddleware
from k8s_mcp.config import get_settings
from k8s_mcp.logging_config import configure_logging, get_logger
from k8s_mcp.metrics import prometheus_text
from k8s_mcp.tools import register_tools

configure_logging()
logger = get_logger("server")

_settings = get_settings()
mcp = FastMCP(
    "kubernetes",
    instructions=(
        "Operate Kubernetes via apiVersion + kind. Use k8s_discover_resources to resolve "
        "ambiguous kinds. Namespaced resources default to namespace=default when omitted."
    ),
    host=_settings.host,
    port=_settings.port,
    streamable_http_path="/mcp",
    stateless_http=True,
)

register_tools(mcp)


@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request) -> JSONResponse:
    logger.debug("health check from %s", request.client)
    return JSONResponse({"status": "ok", "service": "k8s-mcp"})


@mcp.custom_route("/metrics", methods=["GET"])
async def metrics(_request: Request) -> Response:
    return Response(prometheus_text(), media_type="text/plain; charset=utf-8")


def _wrap_with_request_log(app: "ASGIApp") -> "ASGIApp":
    """Wrap app: add request_id to scope/state, log requests with request_id."""
    from starlette.types import Receive, Scope, Send

    async def wrapped(scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            request_id = scope.get("headers") and next(
                (v.decode() for k, v in scope["headers"] if k.lower() == b"x-request-id"),
                None,
            ) or str(uuid.uuid4())
            scope.setdefault("state", {})["request_id"] = request_id
            path = scope.get("path", "")
            method = scope.get("method", "")
            client = scope.get("client", ("?", "?"))[0]
            logger.debug("request_id=%s %s %s from %s", request_id, method, path, client)
        await app(scope, receive, send)

    return wrapped


def main() -> None:
    s = get_settings()
    logger.info(
        "starting k8s-mcp host=%s port=%s auth=%s log_level=%s",
        s.host, s.port, "enabled" if s.auth_token else "disabled", s.log_level,
    )

    app = mcp.streamable_http_app()
    if s.auth_token:
        app = BearerAuthMiddleware(app, s.auth_token)
    app = _wrap_with_request_log(app)

    uvicorn.run(app, host=s.host, port=s.port, log_level=s.log_level)


if __name__ == "__main__":
    main()
