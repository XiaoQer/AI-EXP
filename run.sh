#!/bin/bash
# 启动 k8s-mcp 服务（监听 0.0.0.0:8000，供 Docker/Open WebUI 连接）
# 排查时: K8S_MCP_LOG_LEVEL=DEBUG ./run.sh
cd "$(dirname "$0")"
export PYTHONPATH="${PWD}/src:${PYTHONPATH}"
exec .venv/bin/python -m k8s_mcp
