"""Kubernetes MCP server (HTTP)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from starlette.types import ASGIApp
import os
import traceback

import uvicorn
from kubernetes.client.rest import ApiException
from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from k8s_mcp import kube
from k8s_mcp.auth import BearerAuthMiddleware
from k8s_mcp.logging_config import configure_logging, get_logger

configure_logging()
logger = get_logger("server")

mcp = FastMCP(
    "kubernetes",
    instructions=(
        "Operate Kubernetes via apiVersion + kind. Use k8s_discover_resources to resolve "
        "ambiguous kinds. Namespaced resources default to namespace=default when omitted."
    ),
    host=os.environ.get("K8S_MCP_HOST", "0.0.0.0"),
    port=int(os.environ.get("K8S_MCP_PORT", "8000")),
    streamable_http_path="/mcp",
    stateless_http=True,  # 兼容 Open WebUI：无 session 校验，每次请求独立
)


@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request) -> JSONResponse:
    logger.debug("health check from %s", request.client)
    return JSONResponse({"status": "ok", "service": "k8s-mcp"})


def _json(data: object) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


def _err(exc: BaseException) -> str:
    if isinstance(exc, ApiException):
        return kube.api_exception_message(exc)
    return f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"


@mcp.tool()
def k8s_discover_resources(
    group: str | None = None,
    api_version: str | None = None,
    kind: str | None = None,
) -> str:
    """Discover API resources (plural name, namespaced flag, verbs). Filter by group / api_version / kind."""
    logger.info("tool=k8s_discover_resources group=%s api_version=%s kind=%s", group, api_version, kind)
    try:
        out = kube.discover_resources(group=group, api_version=api_version, kind=kind)
        logger.debug("discover_resources returned %d resources", len(out))
        return _json(out)
    except Exception as e:
        logger.exception("k8s_discover_resources failed: %s", e)
        return _err(e)


@mcp.tool()
def k8s_kubectl(
    args: str,
    timeout: int = 120,
) -> str:
    """Execute kubectl command. args: subcommand and flags, e.g. 'get pods -n default', 'logs nginx-xxx -n default', 'describe pod nginx', 'top nodes'."""
    logger.info("tool=k8s_kubectl args=%s", args)
    try:
        return _json(kube.exec_kubectl(args_str=args.strip(), timeout=timeout))
    except Exception as e:
        logger.exception("k8s_kubectl failed: %s", e)
        return _err(e)


@mcp.tool()
def k8s_get(
    api_version: str,
    kind: str,
    name: str,
    namespace: str | None = None,
) -> str:
    """Get a single object by name (cluster-scoped: omit namespace)."""
    logger.info("tool=k8s_get api_version=%s kind=%s name=%s namespace=%s", api_version, kind, name, namespace)
    try:
        return _json(kube.get_object(api_version=api_version, kind=kind, name=name, namespace=namespace))
    except Exception as e:
        logger.exception("k8s_get failed: %s", e)
        return _err(e)


@mcp.tool()
def k8s_list(
    api_version: str,
    kind: str,
    namespace: str | None = None,
    all_namespaces: bool = False,
    label_selector: str | None = None,
    field_selector: str | None = None,
    limit: int | None = None,
) -> str:
    """List objects. Namespaced kinds: set all_namespaces=true to list every namespace."""
    logger.info(
        "tool=k8s_list api_version=%s kind=%s namespace=%s all_ns=%s",
        api_version, kind, namespace, all_namespaces,
    )
    try:
        return _json(
            kube.list_objects(
                api_version=api_version,
                kind=kind,
                namespace=namespace,
                all_namespaces=all_namespaces,
                label_selector=label_selector,
                field_selector=field_selector,
                limit=limit,
            )
        )
    except Exception as e:
        logger.exception("k8s_list failed: %s", e)
        return _err(e)


@mcp.tool()
def k8s_create_pod(
    name: str,
    image: str,
    namespace: str = "default",
    command: str | None = None,
    args: str | None = None,
    env: str | None = None,
    restart_policy: str = "Always",
    labels: str | None = None,
) -> str:
    """Create a Pod. name and image are required. command/args/env/labels are JSON strings if provided."""
    logger.info("tool=k8s_create_pod name=%s image=%s namespace=%s", name, image, namespace)
    try:
        cmd_list: list[str] | None = json.loads(command) if command else None
        args_list: list[str] | None = json.loads(args) if args else None
        env_dict: dict[str, str] | None = json.loads(env) if env else None
        labels_dict: dict[str, str] | None = json.loads(labels) if labels else None
        return _json(
            kube.create_pod(
                name=name,
                image=image,
                namespace=namespace,
                command=cmd_list,
                args=args_list,
                env=env_dict,
                restart_policy=restart_policy,
                labels=labels_dict,
            )
        )
    except Exception as e:
        logger.exception("k8s_create_pod failed: %s", e)
        return _err(e)


@mcp.tool()
def k8s_create_svc(
    name: str,
    selector: str,
    port: int,
    namespace: str = "default",
    target_port: int | None = None,
    type: str = "ClusterIP",
) -> str:
    """Create a Service. selector is JSON object for pod labels, e.g. '{"app":"nginx"}'. port is the service port."""
    logger.info("tool=k8s_create_svc name=%s selector=%s port=%s", name, selector, port)
    try:
        selector_dict = json.loads(selector)
        if not isinstance(selector_dict, dict):
            raise ValueError("selector must be a JSON object")
        return _json(
            kube.create_service(
                name=name,
                selector=selector_dict,
                port=port,
                namespace=namespace,
                target_port=target_port,
                type=type,
            )
        )
    except Exception as e:
        logger.exception("k8s_create_svc failed: %s", e)
        return _err(e)


@mcp.tool()
def k8s_create_pod_and_svc(
    name: str,
    image: str,
    port: int,
    namespace: str = "default",
    target_port: int | None = None,
    command: str | None = None,
    args: str | None = None,
    env: str | None = None,
    restart_policy: str = "Always",
    service_type: str = "ClusterIP",
) -> str:
    """Create a Pod and Service together. Pod gets label app=name, Service selects it and exposes port."""
    logger.info("tool=k8s_create_pod_and_svc name=%s image=%s port=%s", name, image, port)
    try:
        cmd_list = json.loads(command) if command else None
        args_list = json.loads(args) if args else None
        env_dict = json.loads(env) if env else None
        return _json(
            kube.create_pod_and_service(
                name=name,
                image=image,
                port=port,
                namespace=namespace,
                target_port=target_port,
                command=cmd_list,
                args=args_list,
                env=env_dict,
                restart_policy=restart_policy,
                service_type=service_type,
            )
        )
    except Exception as e:
        logger.exception("k8s_create_pod_and_svc failed: %s", e)
        return _err(e)


@mcp.tool()
def k8s_apply(
    manifest_yaml: str,
    namespace: str | None = None,
) -> str:
    """Create or replace from one YAML/JSON document (metadata.namespace overrides namespace arg)."""
    logger.info("tool=k8s_apply namespace=%s manifest_len=%d", namespace, len(manifest_yaml))
    try:
        return _json(kube.replace_object(manifest_yaml=manifest_yaml, namespace=namespace))
    except Exception as e:
        logger.exception("k8s_apply failed: %s", e)
        return _err(e)


@mcp.tool()
def k8s_apply_multi(
    manifest_yaml: str,
) -> str:
    """Apply multiple documents separated by --- (create or replace each)."""
    docs = len([d for d in manifest_yaml.split("---") if d.strip()])
    logger.info("tool=k8s_apply_multi docs=%d", docs)
    try:
        return _json(kube.apply_manifests(manifest_yaml))
    except Exception as e:
        logger.exception("k8s_apply_multi failed: %s", e)
        return _err(e)


@mcp.tool()
def k8s_patch(
    api_version: str,
    kind: str,
    name: str,
    patch: str,
    patch_type: str = "strategic",
    namespace: str | None = None,
) -> str:
    """Patch an object. patch_type: strategic | merge | json (RFC 6902). patch is JSON string (or YAML for strategic/merge)."""
    logger.info("tool=k8s_patch api_version=%s kind=%s name=%s patch_type=%s", api_version, kind, name, patch_type)
    try:
        return _json(
            kube.patch_object(
                api_version=api_version,
                kind=kind,
                name=name,
                patch=patch,
                patch_type=patch_type,
                namespace=namespace,
            )
        )
    except Exception as e:
        logger.exception("k8s_patch failed: %s", e)
        return _err(e)


@mcp.tool()
def k8s_delete(
    api_version: str,
    kind: str,
    name: str,
    namespace: str | None = None,
    propagation_policy: str | None = "Background",
    grace_period_seconds: int | None = None,
) -> str:
    """Delete an object. propagation_policy: Orphan|Foreground|Background or null to omit."""
    logger.info("tool=k8s_delete api_version=%s kind=%s name=%s namespace=%s", api_version, kind, name, namespace)
    try:
        return _json(
            kube.delete_object(
                api_version=api_version,
                kind=kind,
                name=name,
                namespace=namespace,
                propagation_policy=propagation_policy,
                grace_period_seconds=grace_period_seconds,
            )
        )
    except Exception as e:
        logger.exception("k8s_delete failed: %s", e)
        return _err(e)


def _wrap_with_request_log(app: "ASGIApp") -> "ASGIApp":
    """包装 app，记录 HTTP 请求（DEBUG 级别）。"""
    from starlette.types import Receive, Scope, Send

    async def wrapped(scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            path = scope.get("path", "")
            method = scope.get("method", "")
            client = scope.get("client", ("?", "?"))[0]
            logger.debug("request %s %s from %s", method, path, client)
        await app(scope, receive, send)

    return wrapped


def main() -> None:
    host = os.environ.get("K8S_MCP_HOST", "0.0.0.0")
    port = int(os.environ.get("K8S_MCP_PORT", "8000"))
    auth_token = os.environ.get("K8S_MCP_AUTH_TOKEN", "").strip() or None
    log_level = os.environ.get("K8S_MCP_LOG_LEVEL", "INFO").lower()

    logger.info(
        "starting k8s-mcp host=%s port=%s auth=%s log_level=%s",
        host, port, "enabled" if auth_token else "disabled", log_level,
    )

    app = mcp.streamable_http_app()
    if auth_token:
        app = BearerAuthMiddleware(app, auth_token)
    app = _wrap_with_request_log(app)

    uvicorn.run(app, host=host, port=port, log_level=log_level)


if __name__ == "__main__":
    main()
