#!/bin/bash
# Open WebUI 连接 k8s-mcp 失败时的诊断脚本
# 用法: ./scripts/diagnose.sh [端口，默认8000]

set -e
PORT="${1:-8000}"
BASE="http://127.0.0.1:${PORT}"
HOST_DOCKER="http://host.docker.internal:${PORT}"

echo "=== k8s-mcp 连接诊断 (端口 ${PORT}) ==="
echo ""

echo "1. 检查 k8s-mcp 进程"
if pgrep -f "k8s_mcp" > /dev/null; then
  echo "   [OK] k8s-mcp 进程在运行"
  ps aux | grep -E "[k]8s_mcp" | head -1
else
  echo "   [FAIL] 未找到 k8s-mcp 进程，请先执行 ./run.sh"
  exit 1
fi
echo ""

echo "2. 本机访问 /health"
if curl -sf --connect-timeout 3 "${BASE}/health" > /dev/null; then
  echo "   [OK] curl ${BASE}/health 成功"
  curl -s "${BASE}/health" | head -1
else
  echo "   [FAIL] curl ${BASE}/health 失败，服务可能未监听或端口错误"
  exit 1
fi
echo ""

echo "3. 本机访问 /mcp (POST 初始化)"
HTTP=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 3 -X POST "${BASE}/mcp" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -H "mcp-protocol-version: 2024-11-05" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"diagnose","version":"1.0"}}}' 2>/dev/null || echo "000")
if [[ "$HTTP" == "200" || "$HTTP" == "202" ]]; then
  echo "   [OK] POST /mcp 返回 HTTP $HTTP"
elif [[ "$HTTP" =~ ^[0-9]{3}$ ]]; then
  echo "   [INFO] POST /mcp 返回 HTTP $HTTP"
else
  echo "   [WARN] POST /mcp 请求失败 (code=$HTTP)"
fi
echo ""

echo "4. host.docker.internal 解析 (macOS/Windows Docker 用此访问宿主机)"
if ping -c 1 host.docker.internal &>/dev/null; then
  echo "   [OK] host.docker.internal 可解析"
  echo "   Open WebUI 中 MCP URL 建议: ${HOST_DOCKER}/mcp"
else
  echo "   [INFO] host.docker.internal 无法 ping（Linux 上常见）"
  echo "   Linux 下 Open WebUI 请用: http://172.17.0.1:${PORT}/mcp 或宿主机 IP"
fi
echo ""

echo "5. 监听地址检查"
if netstat -an 2>/dev/null | grep -q "\.${PORT}.*LISTEN"; then
  echo "   [OK] 端口 ${PORT} 在监听"
  netstat -an 2>/dev/null | grep "\.${PORT}" | grep LISTEN || true
elif ss -tln 2>/dev/null | grep -q ":${PORT}"; then
  echo "   [OK] 端口 ${PORT} 在监听"
  ss -tln 2>/dev/null | grep ":${PORT}" || true
else
  echo "   [WARN] 未检测到端口 ${PORT} 监听（可能权限不足）"
fi
echo ""

echo "=== 诊断完成 ==="
echo ""
echo "若本机测试均通过，Open WebUI 仍报错，请检查："
echo "  - Open WebUI 是否在 Docker 内？URL 必须用 host.docker.internal 或宿主机 IP，不能用 localhost"
echo "  - 是否设置了 K8S_MCP_AUTH_TOKEN？若有，Open WebUI 可能无法传 token，可暂时取消"
echo "  - 运行 K8S_MCP_LOG_LEVEL=DEBUG ./run.sh 查看详细请求日志"
