"""统一日志配置，支持 K8S_MCP_LOG_LEVEL 环境变量。"""

from __future__ import annotations

import logging
import os
import sys

LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
DEFAULT_LEVEL = "INFO"


def configure_logging() -> logging.Logger:
    """配置项目日志，返回根 logger。"""
    level_name = os.environ.get("K8S_MCP_LOG_LEVEL", DEFAULT_LEVEL).upper()
    level = getattr(logging, level_name, logging.INFO)
    if level_name not in LOG_LEVELS:
        level = logging.INFO

    fmt = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(fmt, datefmt=datefmt))

    root = logging.getLogger("k8s_mcp")
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(handler)

    # 降低第三方库的日志噪音
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    return root


def get_logger(name: str) -> logging.Logger:
    """获取 k8s_mcp 子模块的 logger。"""
    return logging.getLogger(f"k8s_mcp.{name}")
