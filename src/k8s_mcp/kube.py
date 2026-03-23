"""Kubernetes dynamic client helpers (kubeconfig or in-cluster)."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
from functools import lru_cache
from typing import Any

import yaml
from kubernetes import client, config
from kubernetes.client.rest import ApiException
from kubernetes.dynamic import DynamicClient
from kubernetes.dynamic.resource import ResourceInstance

from k8s_mcp.logging_config import get_logger

logger = get_logger("kube")


def _configure_from_env() -> None:
    if os.environ.get("KUBERNETES_SERVICE_HOST"):
        logger.info("using in-cluster kubeconfig")
        config.load_incluster_config()
    else:
        kubeconfig = os.environ.get("KUBECONFIG", "~/.kube/config")
        logger.info("using kubeconfig: %s", kubeconfig)
        config.load_kube_config()


@lru_cache(maxsize=1)
def get_dynamic_client() -> DynamicClient:
    _configure_from_env()
    return DynamicClient(client.ApiClient())


def api_exception_message(exc: ApiException) -> str:
    body = exc.body or ""
    return f"HTTP {exc.status} {exc.reason}: {body}"


def resolve_resource(api_version: str, kind: str):
    dyn = get_dynamic_client()
    res = dyn.resources.get(api_version=api_version, kind=kind)
    logger.debug("resolved resource %s/%s -> %s", api_version, kind, res.name)
    return res


def _serialize(obj: Any) -> Any:
    if isinstance(obj, ResourceInstance):
        return obj.to_dict()
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    return obj


def discover_resources(
    *,
    group: str | None = None,
    api_version: str | None = None,
    kind: str | None = None,
) -> list[dict[str, Any]]:
    dyn = get_dynamic_client()
    kwargs: dict[str, str] = {}
    if group is not None:
        kwargs["group"] = group
    if api_version is not None:
        kwargs["api_version"] = api_version
    if kind is not None:
        kwargs["kind"] = kind

    out: list[dict[str, Any]] = []
    for r in dyn.resources.search(**kwargs):
        g = getattr(r, "group", None) or ""
        ver = getattr(r, "version", None) or ""
        av = f"{g}/{ver}" if g else ver
        out.append(
            {
                "api_version": av,
                "group": g or None,
                "version": ver or None,
                "kind": getattr(r, "kind", None),
                "name": getattr(r, "name", None),
                "singular": getattr(r, "singular_name", None),
                "namespaced": bool(getattr(r, "namespaced", False)),
                "verbs": list(getattr(r, "verbs", []) or []),
            }
        )
    return out


def get_object(
    *,
    api_version: str,
    kind: str,
    name: str,
    namespace: str | None = None,
) -> dict[str, Any]:
    logger.debug("get_object api_version=%s kind=%s name=%s namespace=%s", api_version, kind, name, namespace)
    res = resolve_resource(api_version, kind)
    kwargs: dict[str, Any] = {"name": name}
    if res.namespaced:
        kwargs["namespace"] = namespace or "default"
    inst = res.get(**kwargs)
    return _serialize(inst)


def list_objects(
    *,
    api_version: str,
    kind: str,
    namespace: str | None = None,
    all_namespaces: bool = False,
    label_selector: str | None = None,
    field_selector: str | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    res = resolve_resource(api_version, kind)
    kwargs: dict[str, Any] = {}
    if res.namespaced:
        if all_namespaces:
            kwargs["namespace"] = None
        else:
            kwargs["namespace"] = namespace or "default"
    if label_selector:
        kwargs["label_selector"] = label_selector
    if field_selector:
        kwargs["field_selector"] = field_selector
    if limit is not None:
        kwargs["limit"] = limit

    inst = res.get(**kwargs)
    return _serialize(inst)


def delete_object(
    *,
    api_version: str,
    kind: str,
    name: str,
    namespace: str | None = None,
    propagation_policy: str | None = "Background",
    grace_period_seconds: int | None = None,
) -> dict[str, Any]:
    res = resolve_resource(api_version, kind)
    kwargs: dict[str, Any] = {"name": name}
    if res.namespaced:
        kwargs["namespace"] = namespace or "default"
    if propagation_policy:
        kwargs["propagation_policy"] = propagation_policy
    if grace_period_seconds is not None:
        kwargs["grace_period_seconds"] = grace_period_seconds
    inst = res.delete(**kwargs)
    return _serialize(inst)


_PATCH_TYPES = {
    "strategic": "application/strategic-merge-patch+json",
    "merge": "application/merge-patch+json",
    "json": "application/json-patch+json",
}


def patch_object(
    *,
    api_version: str,
    kind: str,
    name: str,
    patch: str,
    patch_type: str = "strategic",
    namespace: str | None = None,
) -> dict[str, Any]:
    content_type = _PATCH_TYPES.get(patch_type)
    if not content_type:
        allowed = ", ".join(_PATCH_TYPES)
        raise ValueError(f"patch_type must be one of: {allowed}")

    body: Any
    if patch_type == "json":
        body = json.loads(patch)
    else:
        body = json.loads(patch) if patch.strip().startswith("{") else yaml.safe_load(patch)

    res = resolve_resource(api_version, kind)
    kwargs: dict[str, Any] = {"name": name, "body": body, "content_type": content_type}
    if res.namespaced:
        kwargs["namespace"] = namespace or "default"
    inst = res.patch(**kwargs)
    return _serialize(inst)


def replace_object(
    *,
    manifest_yaml: str,
    namespace: str | None = None,
) -> dict[str, Any]:
    obj = yaml.safe_load(manifest_yaml)
    if not isinstance(obj, dict):
        raise ValueError("manifest must be a single YAML/JSON object")

    api_version = obj.get("apiVersion")
    kind = obj.get("kind")
    metadata = obj.get("metadata") or {}
    name = metadata.get("name")
    if not api_version or not kind or not name:
        raise ValueError("manifest must include apiVersion, kind, and metadata.name")

    res = resolve_resource(api_version, kind)
    ns: str | None
    if res.namespaced:
        ns = metadata.get("namespace") or namespace or "default"
        metadata.setdefault("namespace", ns)
    else:
        ns = None
        metadata.pop("namespace", None)

    kwargs_get: dict[str, Any] = {"name": name}
    if res.namespaced:
        kwargs_get["namespace"] = ns

    try:
        res.get(**kwargs_get)
    except ApiException as e:
        if e.status == 404:
            logger.info("replace_object: creating %s/%s name=%s", api_version, kind, name)
            create_kw: dict[str, Any] = {"body": obj}
            if res.namespaced:
                create_kw["namespace"] = ns
            inst = res.create(**create_kw)
            return {"action": "created", "object": _serialize(inst)}
        logger.warning("replace_object get failed: %s", api_exception_message(e))
        raise

    logger.info("replace_object: replacing %s/%s name=%s", api_version, kind, name)
    replace_kw: dict[str, Any] = {"body": obj, "name": name}
    if res.namespaced:
        replace_kw["namespace"] = ns
    inst = res.replace(**replace_kw)
    return {"action": "replaced", "object": _serialize(inst)}


def create_pod(
    *,
    name: str,
    image: str,
    namespace: str = "default",
    command: list[str] | None = None,
    args: list[str] | None = None,
    env: dict[str, str] | None = None,
    restart_policy: str = "Always",
    labels: dict[str, str] | None = None,
) -> dict[str, Any]:
    """创建 Pod。若已存在同名 Pod 则报错。"""
    res = resolve_resource("v1", "Pod")
    env_list: list[dict[str, Any]] = []
    if env:
        env_list = [{"name": k, "value": str(v)} for k, v in env.items()]

    container: dict[str, Any] = {
        "name": name,
        "image": image,
    }
    if command:
        container["command"] = command
    if args:
        container["args"] = args
    if env_list:
        container["env"] = env_list

    metadata: dict[str, Any] = {"name": name}
    if labels:
        metadata["labels"] = labels

    body: dict[str, Any] = {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": metadata,
        "spec": {
            "restartPolicy": restart_policy,
            "containers": [container],
        },
    }

    logger.info("create_pod name=%s image=%s namespace=%s", name, image, namespace)
    inst = res.create(body=body, namespace=namespace)
    return {"action": "created", "object": _serialize(inst)}


def create_service(
    *,
    name: str,
    selector: dict[str, str],
    port: int,
    namespace: str = "default",
    target_port: int | None = None,
    type: str = "ClusterIP",
) -> dict[str, Any]:
    """创建 Service。selector 用于选择 Pod（如 {"app":"nginx"}）。"""
    res = resolve_resource("v1", "Service")
    target = target_port if target_port is not None else port
    body: dict[str, Any] = {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {"name": name},
        "spec": {
            "type": type,
            "selector": selector,
            "ports": [{"port": port, "targetPort": target, "protocol": "TCP"}],
        },
    }
    logger.info("create_service name=%s selector=%s port=%s namespace=%s", name, selector, port, namespace)
    inst = res.create(body=body, namespace=namespace)
    return {"action": "created", "object": _serialize(inst)}


def create_pod_and_service(
    *,
    name: str,
    image: str,
    port: int,
    namespace: str = "default",
    target_port: int | None = None,
    selector_label: str = "app",
    command: list[str] | None = None,
    args: list[str] | None = None,
    env: dict[str, str] | None = None,
    restart_policy: str = "Always",
    service_type: str = "ClusterIP",
) -> dict[str, Any]:
    """创建 Pod 和 Service。Pod 使用 labels={selector_label: name}，Service 用相同 selector 暴露 port。"""
    labels = {selector_label: name}
    pod_result = create_pod(
        name=name,
        image=image,
        namespace=namespace,
        command=command,
        args=args,
        env=env,
        restart_policy=restart_policy,
        labels=labels,
    )
    svc_result = create_service(
        name=name,
        selector=labels,
        port=port,
        namespace=namespace,
        target_port=target_port,
        type=service_type,
    )
    return {"pod": pod_result, "service": svc_result}


# 默认允许的 kubectl 子命令（读操作、排查类），可通过 K8S_MCP_KUBECTL_ALLOWED 覆盖
KUBECTL_ALLOWED_DEFAULT = frozenset(
    {"get", "describe", "logs", "top", "version", "api-resources", "cluster-info", "explain"}
)


def exec_kubectl(
    args_str: str,
    timeout: int = 120,
    allowed_commands: frozenset[str] | None = None,
) -> dict[str, Any]:
    """执行 kubectl 命令。allowed_commands 为空则使用默认白名单；仅允许白名单内的子命令。"""
    parts = shlex.split(args_str.strip())
    if not parts:
        return {"returncode": -1, "stdout": "", "stderr": "Empty kubectl args", "success": False}

    subcmd = parts[0].lower()
    allowed = allowed_commands or KUBECTL_ALLOWED_DEFAULT
    if subcmd not in allowed:
        return {
            "returncode": -1,
            "stdout": "",
            "stderr": f"kubectl subcommand '{subcmd}' not allowed. Allowed: {sorted(allowed)}",
            "success": False,
        }

    args = ["kubectl"] + parts
    logger.info("exec_kubectl: %s", " ".join(args))
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ},
        )
        return {
            "returncode": result.returncode,
            "stdout": result.stdout or "",
            "stderr": result.stderr or "",
            "success": result.returncode == 0,
        }
    except subprocess.TimeoutExpired:
        logger.warning("exec_kubectl timeout after %ds: %s", timeout, args_str)
        return {
            "returncode": -1,
            "stdout": "",
            "stderr": f"Command timed out after {timeout} seconds",
            "success": False,
        }
    except FileNotFoundError:
        logger.warning("kubectl not found")
        return {
            "returncode": -1,
            "stdout": "",
            "stderr": "kubectl not found in PATH",
            "success": False,
        }
    except Exception as e:
        logger.exception("exec_kubectl failed: %s", e)
        return {
            "returncode": -1,
            "stdout": "",
            "stderr": str(e),
            "success": False,
        }


def apply_manifests(manifest_yaml: str) -> list[dict[str, Any]]:
    docs = list(yaml.safe_load_all(manifest_yaml))
    results: list[dict[str, Any]] = []
    for i, doc in enumerate(docs):
        if doc is None:
            continue
        if not isinstance(doc, dict):
            raise ValueError(f"document {i} must be a mapping")
        chunk = yaml.safe_dump(doc, sort_keys=False)
        results.append(replace_object(manifest_yaml=chunk))
    return results
