"""统一配置，从环境变量读取。"""

from __future__ import annotations

import os


def _env(key: str, default: str) -> str:
    return os.environ.get(key, default)


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, str(default)))
    except ValueError:
        return default


def _env_bool(key: str, default: bool) -> bool:
    v = os.environ.get(key, "").lower()
    if v in ("1", "true", "yes"):
        return True
    if v in ("0", "false", "no"):
        return False
    return default


class Settings:
    """运行配置。"""

    host: str = ""
    port: int = 8000
    auth_token: str | None = None
    log_level: str = "INFO"

    # kubectl
    kubectl_timeout: int = 120
    kubectl_allowed_commands: frozenset[str] = frozenset()

    @classmethod
    def from_env(cls) -> "Settings":
        s = cls()
        s.host = _env("K8S_MCP_HOST", "0.0.0.0")
        s.port = _env_int("K8S_MCP_PORT", 8000)
        s.auth_token = (_env("K8S_MCP_AUTH_TOKEN", "").strip() or None)
        s.log_level = _env("K8S_MCP_LOG_LEVEL", "INFO").lower()

        s.kubectl_timeout = _env_int("K8S_MCP_KUBECTL_TIMEOUT", 120)
        whitelist = _env(
            "K8S_MCP_KUBECTL_ALLOWED",
            "get,describe,logs,top,version,api-resources,cluster-info,explain",
        )
        s.kubectl_allowed_commands = frozenset(c.strip() for c in whitelist.split(",") if c.strip())
        return s


def get_settings() -> Settings:
    return Settings.from_env()
