# k8s-mcp - Kubernetes MCP server (HTTP + Bearer auth)
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    K8S_MCP_HOST=0.0.0.0 \
    K8S_MCP_PORT=8000

WORKDIR /app

# Install dependencies
COPY pyproject.toml .
COPY src/ src/
RUN pip install --no-cache-dir -e .

# Non-root user
RUN adduser --disabled-password --gecos "" mcp && chown -R mcp:mcp /app
USER mcp

EXPOSE 8000

# K8S_MCP_AUTH_TOKEN must be set for auth; KUBECONFIG or in-cluster for k8s
CMD ["python", "-m", "k8s_mcp"]
