"""MCP 工具定义，统一错误处理与 metrics。"""

from __future__ import annotations

import json
import traceback
from typing import Any, Callable

from kubernetes.client.rest import ApiException

from k8s_mcp import kube
from k8s_mcp.config import get_settings
from k8s_mcp.logging_config import get_logger
from k8s_mcp.metrics import record_tool_call

logger = get_logger("tools")


def _json(data: object) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


def _err(exc: BaseException) -> str:
    if isinstance(exc, ApiException):
        return kube.api_exception_message(exc)
    return f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"


def handle_tool(name: str) -> Callable[[Callable[..., str]], Callable[..., str]]:
    """装饰器：统一 try/except、metrics、logger。被装饰函数应返回 str。"""

    def decorator(fn: Callable[..., str]) -> Callable[..., str]:
        def wrapper(*args: Any, **kwargs: Any) -> str:
            try:
                result = fn(*args, **kwargs)
                record_tool_call(name, error=False)
                return result
            except Exception as e:
                record_tool_call(name, error=True)
                logger.exception("tool=%s failed: %s", name, e)
                return _err(e)

        return wrapper

    return decorator


def register_tools(mcp: Any) -> None:
    """向 FastMCP 注册所有工具。"""

    settings = get_settings()

    @mcp.tool()
    @handle_tool("k8s_discover_resources")
    def k8s_discover_resources(
        group: str | None = None,
        api_version: str | None = None,
        kind: str | None = None,
    ) -> str:
        """Discover API resources (plural name, namespaced flag, verbs). Filter by group / api_version / kind."""
        logger.info("tool=k8s_discover_resources group=%s api_version=%s kind=%s", group, api_version, kind)
        out = kube.discover_resources(group=group, api_version=api_version, kind=kind)
        logger.debug("discover_resources returned %d resources", len(out))
        return _json(out)

    @mcp.tool()
    @handle_tool("k8s_kubectl")
    def k8s_kubectl(args: str, timeout: int = 120) -> str:
        """Execute kubectl command. args: subcommand and flags. Allowed: get, describe, logs, top, version, api-resources, cluster-info, explain."""
        logger.info("tool=k8s_kubectl args=%s", args)
        t = timeout if timeout > 0 else settings.kubectl_timeout
        return _json(kube.exec_kubectl(args_str=args.strip(), timeout=t, allowed_commands=settings.kubectl_allowed_commands))

    @mcp.tool()
    @handle_tool("k8s_get")
    def k8s_get(
        api_version: str,
        kind: str,
        name: str,
        namespace: str | None = None,
    ) -> str:
        """Get a single object by name (cluster-scoped: omit namespace)."""
        logger.info("tool=k8s_get api_version=%s kind=%s name=%s namespace=%s", api_version, kind, name, namespace)
        return _json(kube.get_object(api_version=api_version, kind=kind, name=name, namespace=namespace))

    @mcp.tool()
    @handle_tool("k8s_list")
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
        logger.info("tool=k8s_list api_version=%s kind=%s namespace=%s all_ns=%s", api_version, kind, namespace, all_namespaces)
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

    @mcp.tool()
    @handle_tool("k8s_create_pod")
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
        cmd_list = json.loads(command) if command else None
        args_list = json.loads(args) if args else None
        env_dict = json.loads(env) if env else None
        labels_dict = json.loads(labels) if labels else None
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

    @mcp.tool()
    @handle_tool("k8s_create_svc")
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

    @mcp.tool()
    @handle_tool("k8s_create_pod_and_svc")
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

    @mcp.tool()
    @handle_tool("k8s_apply")
    def k8s_apply(manifest_yaml: str, namespace: str | None = None) -> str:
        """Create or replace from one YAML/JSON document (metadata.namespace overrides namespace arg)."""
        logger.info("tool=k8s_apply namespace=%s manifest_len=%d", namespace, len(manifest_yaml))
        return _json(kube.replace_object(manifest_yaml=manifest_yaml, namespace=namespace))

    @mcp.tool()
    @handle_tool("k8s_apply_multi")
    def k8s_apply_multi(manifest_yaml: str) -> str:
        """Apply multiple documents separated by --- (create or replace each)."""
        logger.info("tool=k8s_apply_multi docs=%d", len([d for d in manifest_yaml.split("---") if d.strip()]))
        return _json(kube.apply_manifests(manifest_yaml))

    @mcp.tool()
    @handle_tool("k8s_patch")
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

    @mcp.tool()
    @handle_tool("k8s_delete")
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
