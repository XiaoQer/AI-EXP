# k8s-mcp

基于 [Model Context Protocol](https://modelcontextprotocol.io/) 的 Kubernetes 工具服务：用 **Python** + 官方 `kubernetes` **动态客户端**，按 `apiVersion` / `kind` 操作集群内资源（含 CRD）。

## 依赖

```bash
pip install -r requirements.txt
# 或可编辑安装
pip install -e .
```

依赖定义见 `pyproject.toml` 与 `requirements.txt`。

## 集群凭据

- 本机：默认读取 `~/.kube/config`（与 `kubectl` 一致）。
- Pod 内：若存在 `KUBERNETES_SERVICE_HOST`，则使用 **in-cluster** 配置。

服务端进程继承当前环境的 RBAC；请为运行 MCP 的身份配置合适 `Role` / `ClusterRole`。

## 运行

以 **HTTP** 方式启动（Streamable HTTP，默认 `0.0.0.0:8000`）：

```bash
./run.sh
# 或（需先 pip install -e .）
.venv/bin/python -m k8s_mcp
```

环境变量：

| 变量 | 默认 | 说明 |
|------|------|------|
| `K8S_MCP_HOST` | `0.0.0.0` | 监听地址（默认对外可访问，便于 Docker/Open WebUI 连接） |
| `K8S_MCP_PORT` | `8000` | 监听端口 |
| `K8S_MCP_AUTH_TOKEN` | 无 | 若设置，则要求 `Authorization: Bearer <token>` |
| `K8S_MCP_LOG_LEVEL` | `INFO` | 日志级别：`DEBUG` / `INFO` / `WARNING` / `ERROR`，排查时用 `DEBUG` |
| `K8S_MCP_KUBECTL_ALLOWED` | `get,describe,logs,...` | kubectl 白名单子命令（逗号分隔） |
| `K8S_MCP_KUBECTL_TIMEOUT` | `120` | kubectl 超时秒数 |

MCP 端点：`http://<host>:<port>/mcp`，健康检查：`http://<host>:<port>/health`，Prometheus 指标：`http://<host>:<port>/metrics`

### Cursor 配置示例

服务需先单独启动，再在 Cursor 的 MCP 设置中配置 HTTP 连接：

```json
{
  "mcpServers": {
    "k8s-mcp": {
      "url": "http://127.0.0.1:8000/mcp"
    }
  }
}
```

若启用了 `K8S_MCP_AUTH_TOKEN`，需在 Cursor 的 MCP 配置中增加 `Authorization: Bearer <token>`（具体方式视 Cursor 版本而定）。

### Open WebUI 配置

1. 管理后台 → 设置 → 连接器 → 工具服务器 → 添加
2. 类型选择 **MCP (Streamable HTTP)**
3. URL 填写：`http://<host>:<port>/mcp`

**若 Open WebUI 在 Docker 内运行**，k8s-mcp 在宿主机时，URL 使用：
- macOS/Windows：`http://host.docker.internal:8000/mcp`
- Linux：`http://172.17.0.1:8000/mcp` 或宿主机实际 IP

服务已启用 `stateless_http`，以兼容 Open WebUI 的 verify 流程（避免 400）。

**若出现 "Failed to connect to MCP server"：**

```bash
# 运行诊断脚本（k8s-mcp 需先启动）
./scripts/diagnose.sh
```

常见原因与处理：

| 现象 | 处理 |
|------|------|
| 本机 `curl localhost:8000/health` 失败 | 先执行 `./run.sh` 启动服务 |
| Open WebUI 在 Docker，k8s-mcp 在宿主机 | URL 用 `http://host.docker.internal:8000/mcp`（macOS/Windows），Linux 用 `http://172.17.0.1:8000/mcp` 或宿主机 IP |
| 设置了 `K8S_MCP_AUTH_TOKEN` | Open WebUI 可能无法传 token，暂时 `unset K8S_MCP_AUTH_TOKEN` 后重启 k8s-mcp |
| 仍无法定位 | `K8S_MCP_LOG_LEVEL=DEBUG ./run.sh` 观察是否有请求到达 |

## Docker 部署

Docker 相关文件在 `docker/` 目录：`Dockerfile`、`docker-compose.yml`、`.env.example`。

根目录的 `.dockerignore` 供 **构建上下文（仓库根）** 使用，Docker 会从这里读取，请勿删除。

```bash
# 1. 复制环境变量模板（与 compose 同目录，便于加载 .env）
cp docker/.env.example docker/.env
# 编辑 docker/.env，设置 K8S_MCP_AUTH_TOKEN（必填）和 KUBECONFIG_PATH（可选，默认 ~/.kube/config）

# 2. 构建并启动（在仓库根目录执行）
docker compose -f docker/docker-compose.yml up -d --build

# 或在 docker 目录下：cp .env.example .env 后
# docker compose up -d --build

# 3. 验证
curl http://localhost:8000/health
curl -H "Authorization: Bearer <your-token>" http://localhost:8000/mcp
```

Docker 部署时**强烈建议**设置 `K8S_MCP_AUTH_TOKEN`，否则服务对局域网内任意客户端开放。

## 功能概览

k8s-mcp 通过多个 MCP 工具，对 Kubernetes 集群内**任意资源**（含 CRD）进行增删改查。所有操作基于 `apiVersion` + `kind`，与 `kubectl` 一致。

### 工具列表

| 工具 | 功能 |
|------|------|
| `k8s_discover_resources` | 发现集群内 API 资源类型（含 CRD） |
| `k8s_kubectl` | 执行任意 kubectl 命令（排查、logs、describe、top 等） |
| `k8s_get` | 按名称获取单个资源 |
| `k8s_list` | 列出资源，支持筛选与分页 |
| `k8s_create_pod` | 快速创建 Pod（指定 name、image 等） |
| `k8s_create_svc` | 快速创建 Service（selector、port） |
| `k8s_create_pod_and_svc` | 同时创建 Pod 和 Service |
| `k8s_apply` | 创建或替换单个资源（YAML/JSON） |
| `k8s_apply_multi` | 批量 apply 多文档（`---` 分隔） |
| `k8s_patch` | 对资源做 strategic/merge/json 补丁 |
| `k8s_delete` | 删除资源 |

### 工具详解

#### k8s_discover_resources

发现集群支持的 API 资源，返回 `api_version`、`kind`、`name`（复数）、`namespaced`、`verbs` 等。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `group` | str | 否 | API 组过滤，如 `apps` |
| `api_version` | str | 否 | 如 `v1`、`apps/v1` |
| `kind` | str | 否 | 如 `Pod`、`Deployment` |

**示例**：`k8s_discover_resources(kind="Pod")` → 返回 Pod 相关 API 信息。

---

#### k8s_kubectl

执行 kubectl 子命令（白名单限制），用于排查、查看日志、describe、top 等。默认允许：`get`、`describe`、`logs`、`top`、`version`、`api-resources`、`cluster-info`、`explain`；可通过 `K8S_MCP_KUBECTL_ALLOWED` 覆盖。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `args` | str | 是 | kubectl 子命令及参数，如 `get pods -n default`、`logs nginx-xxx -n default`、`describe pod nginx`、`top nodes` |
| `timeout` | int | 否 | 超时秒数（默认 120） |

返回 `{returncode, stdout, stderr, success}`。使用当前 KUBECONFIG。

**示例**：
- `k8s_kubectl(args="get pods -n default")`
- `k8s_kubectl(args="logs nginx-xxx -n default --tail=100")`
- `k8s_kubectl(args="describe pod nginx -n default")`
- `k8s_kubectl(args="top nodes")`
（`exec`、`apply`、`delete` 等写操作不在默认白名单内）

---

#### k8s_get

按名称获取单个资源。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `api_version` | str | 是 | 如 `v1`、`apps/v1` |
| `kind` | str | 是 | 如 `Pod`、`Deployment` |
| `name` | str | 是 | 资源名称 |
| `namespace` | str | 否 | 命名空间（集群级资源可省略，默认 `default`） |

---

#### k8s_list

列出资源，支持命名空间、标签、字段筛选和数量限制。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `api_version` | str | 是 | 如 `v1`、`apps/v1` |
| `kind` | str | 是 | 如 `Pod`、`Deployment` |
| `namespace` | str | 否 | 命名空间（默认 `default`） |
| `all_namespaces` | bool | 否 | `true` 时列出所有命名空间 |
| `label_selector` | str | 否 | 标签选择器，如 `app=nginx` |
| `field_selector` | str | 否 | 字段选择器，如 `status.phase=Running` |
| `limit` | int | 否 | 返回数量上限 |

---

#### k8s_create_pod

快速创建 Pod，无需手写完整 YAML。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `name` | str | 是 | Pod 名称 |
| `image` | str | 是 | 容器镜像，如 `nginx:latest` |
| `namespace` | str | 否 | 命名空间（默认 `default`） |
| `command` | str | 否 | 启动命令，JSON 数组，如 `["sleep", "3600"]` |
| `args` | str | 否 | 启动参数，JSON 数组 |
| `env` | str | 否 | 环境变量，JSON 对象，如 `{"KEY":"value"}` |
| `restart_policy` | str | 否 | `Always`（默认）/ `OnFailure` / `Never` |
| `labels` | str | 否 | 标签，JSON 对象，如 `{"app":"nginx"}` |

**示例**：`k8s_create_pod(name="nginx", image="nginx:alpine", namespace="default")`

---

#### k8s_create_svc

快速创建 Service，用于暴露 Pod。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `name` | str | 是 | Service 名称 |
| `selector` | str | 是 | Pod 标签选择器，JSON 对象，如 `{"app":"nginx"}` |
| `port` | int | 是 | Service 暴露端口 |
| `namespace` | str | 否 | 命名空间（默认 `default`） |
| `target_port` | int | 否 | Pod 端口（默认与 port 相同） |
| `type` | str | 否 | `ClusterIP`（默认）/ `NodePort` / `LoadBalancer` |

**示例**：`k8s_create_svc(name="nginx", selector='{"app":"nginx"}', port=80)`

---

#### k8s_create_pod_and_svc

一次性创建 Pod 和 Service。Pod 自动带 `app=<name>` 标签，Service 用相同 selector 暴露端口。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `name` | str | 是 | Pod 与 Service 名称 |
| `image` | str | 是 | 容器镜像 |
| `port` | int | 是 | Service 暴露端口 |
| `namespace` | str | 否 | 命名空间（默认 `default`） |
| `target_port` | int | 否 | Pod 端口（默认与 port 相同，如应用监听 3000 可设 3000） |
| `command` | str | 否 | 启动命令，JSON 数组 |
| `args` | str | 否 | 启动参数，JSON 数组 |
| `env` | str | 否 | 环境变量，JSON 对象 |
| `restart_policy` | str | 否 | `Always`（默认）/ `OnFailure` / `Never` |
| `service_type` | str | 否 | `ClusterIP`（默认）/ `NodePort` / `LoadBalancer` |

**示例**：`k8s_create_pod_and_svc(name="nginx", image="nginx:alpine", port=80)`

---

#### k8s_apply

根据 YAML/JSON 创建或替换单个资源。不存在则创建，存在则整体替换。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `manifest_yaml` | str | 是 | 单文档 YAML 或 JSON |
| `namespace` | str | 否 | 默认命名空间（manifest 内 `metadata.namespace` 优先） |

---

#### k8s_apply_multi

批量 apply，多个文档用 `---` 分隔，逐个执行 create/replace。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `manifest_yaml` | str | 是 | 多文档 YAML（`---` 分隔） |

---

#### k8s_patch

对已有资源做补丁更新。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `api_version` | str | 是 | 如 `v1`、`apps/v1` |
| `kind` | str | 是 | 如 `Pod`、`Deployment` |
| `name` | str | 是 | 资源名称 |
| `patch` | str | 是 | 补丁内容（JSON 或 YAML） |
| `patch_type` | str | 否 | `strategic`（默认）/ `merge` / `json` |
| `namespace` | str | 否 | 命名空间 |

---

#### k8s_delete

删除资源。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `api_version` | str | 是 | 如 `v1`、`apps/v1` |
| `kind` | str | 是 | 如 `Pod`、`Deployment` |
| `name` | str | 是 | 资源名称 |
| `namespace` | str | 否 | 命名空间 |
| `propagation_policy` | str | 否 | `Background`（默认）/ `Foreground` / `Orphan` |
| `grace_period_seconds` | int | 否 | 优雅删除等待秒数 |

### 支持的资源类型

- **内置资源**：Pod、Deployment、Service、ConfigMap、Secret、Namespace、Node 等
- **CRD**：任意已安装的 CustomResourceDefinition，如 `VirtualService`、`Gateway` 等
- 不确定 `api_version` 或 `kind` 时，先用 `k8s_discover_resources` 查询

### 使用示例（自然语言 → 工具调用）

| 用户意图 | 推荐工具与参数 |
|----------|----------------|
| 查看 Pod 日志 | `k8s_kubectl(args="logs <pod-name> -n default --tail=100")` |
| 查看 Pod 详情 | `k8s_kubectl(args="describe pod <name> -n default")` |
| 查看节点资源 | `k8s_kubectl(args="top nodes")` |
| 创建 nginx Pod 并暴露 80 端口 | `k8s_create_pod_and_svc(name="nginx", image="nginx:alpine", port=80)` |
| 仅创建 Pod | `k8s_create_pod(name="nginx", image="nginx:alpine")` |
| 为已有 Pod 创建 Service | `k8s_create_svc(name="nginx", selector='{"app":"nginx"}', port=80)` |
| 创建带环境变量的 Pod | `k8s_create_pod(name="app", image="myapp:1.0", env='{"DEBUG":"1"}')` |
| 列出 default 命名空间下的 Pod | `k8s_list(api_version="v1", kind="Pod", namespace="default")` |
| 查看名为 nginx 的 Deployment | `k8s_get(api_version="apps/v1", kind="Deployment", name="nginx", namespace="default")` |
| 创建 ConfigMap | `k8s_apply(manifest_yaml="...")` |
| 扩容 Deployment 副本数 | `k8s_patch(..., patch='{"spec":{"replicas":3}}', patch_type="strategic")` |
| 删除 Pod | `k8s_delete(api_version="v1", kind="Pod", name="xxx", namespace="default")` |

## RBAC 配置建议

生产环境中，k8s-mcp 以 Pod 或 DaemonSet 运行时，应为其 ServiceAccount 配置最小权限。以下为示例，可按需裁剪。

### 单命名空间只读

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: k8s-mcp
  namespace: default
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: k8s-mcp-reader
  namespace: default
rules:
  - apiGroups: ["", "apps", "batch"]
    resources: ["pods", "services", "deployments", "jobs", "configmaps", "secrets"]
    verbs: ["get", "list", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: k8s-mcp-reader
  namespace: default
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: k8s-mcp-reader
subjects:
  - kind: ServiceAccount
    name: k8s-mcp
    namespace: default
```

### 单命名空间读写（含 Pod/Service 创建）

在 `Role` 的 `rules` 中增加：

```yaml
  - apiGroups: [""]
    resources: ["pods", "services"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
```

### 集群级只读（含 Node、APIGroup 等）

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: k8s-mcp-cluster-reader
rules:
  - apiGroups: [""]
    resources: ["nodes", "namespaces"]
    verbs: ["get", "list", "watch"]
  - apiGroups: ["", "apps", "batch"]
    resources: ["pods", "services", "deployments", "jobs"]
    verbs: ["get", "list", "watch"]
  - apiGroups: ["apiregistration.k8s.io"]
    resources: ["apiservices"]
    verbs: ["get", "list"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: k8s-mcp-cluster-reader
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: k8s-mcp-cluster-reader
subjects:
  - kind: ServiceAccount
    name: k8s-mcp
    namespace: default
```

部署时通过 `serviceAccountName: k8s-mcp` 挂载该 ServiceAccount。

## 说明

- **任意资源**依赖正确的 `apiVersion` 与 `kind`；不确定时先用 `k8s_discover_resources`。
- `k8s_apply` 使用服务端 **replace**，不是 server-side apply；复杂字段所有权场景请用 `k8s_patch`。
- 所有工具返回 JSON 字符串；错误时返回 HTTP 状态与 API 消息。
