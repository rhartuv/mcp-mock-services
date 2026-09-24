# MCP Mock Services

Mock [Model Context Protocol](https://modelcontextprotocol.io/) servers for AI Skill evaluation, built on [MockServer](https://www.mock-server.com/#why-use-mockserver).

Replaces live MCP servers (OpenShift, Lightspeed, and any additional MCPs you register) during evaluation. Skills call the same JSON-RPC methods as in production; responses are static, fixture-driven, or argument-echoing mocks — no cluster access, credentials, or side effects.

## How it works

We mock MCP over HTTP with [MockServer](https://www.mock-server.com/): each MCP JSON-RPC method (`initialize`, `tools/list`, `tools/call`, …) is a MockServer expectation on `POST /mcp/<name>`.

| MCP method | MockServer feature | Where |
|---|---|---|
| `initialize`, `ping`, `tools/list`, `tools/call` | [JSON body matching](https://www.mock-server.com/mock_server/creating_expectations.html) with `matchType: ONLY_MATCHING_FIELDS` on `method` / `params.name` | `expectations/*.json` |
| Echo JSON-RPC `id` and tool args | [Mustache response templates](https://www.mock-server.com/mock_server/response_templates.html) + JsonPath | `httpResponseTemplate` |
| Scenario sequences | Expectation priority + `times.remainingTimes` | fixture expectations |
| Load mocks at startup | [Initialization JSON](https://www.mock-server.com/mock_server/initializing_expectations.html) glob `/config/*.json` | `Dockerfile` / Compose |

One MockServer process loads every `/config/*.json` file and listens on **port 1080**. Each MCP has its own path:

```
GET  /health
POST /mcp/openshift
POST /mcp/lightspeed
POST /mcp/<name>
```

| Path | Expectation file | Schema source |
|---|---|---|
| `/mcp/openshift` | `expectations/openshift-mcp.json` | `schemas/openshift-mcp-server/` |
| `/mcp/lightspeed` | `expectations/lightspeed-mcp.json` | `schemas/lightspeed-mcp/` |
| `/mcp/<name>` | `expectations/<name>-mcp.json` | `schemas/<name>/` |

```
initialize  →  serverInfo + Mcp-Session-Id
notifications/initialized  →  HTTP 202
tools/list  →  catalog from schema.json
tools/call  →  fixture (priority 50) / Mustache dynamic (40) / static example (30)
```

`tools/call` returns MCP `CallToolResult` (`content[0].text` = tool JSON). Mustache templates echo the request JSON-RPC `id`. Dynamic examples include OpenShift `pods_delete` / `pods_run` (echo name, namespace, image).

## Repository layout

```
.
├── Dockerfile
├── docker-compose.yml
├── expectations/          # generated MockServer expectations
├── schemas/               # tool catalogs + scenario fixtures
├── scripts/generate_expectations.py
├── SCHEMA.md              # contract for adding an MCP
├── .tekton/skill-eval-mcp-sidecar.yaml
└── README.md
```

## Run locally

```bash
docker compose up --build
# or: docker build -t mcp-mock-services:local . && docker run --rm -p 1080:1080 mcp-mock-services:local
```

Prefer `127.0.0.1` over `localhost` if only IPv4 is published (common with Podman).

### Smoke test

```bash
curl -s http://127.0.0.1:1080/health

curl -s -X POST http://127.0.0.1:1080/mcp/openshift \
  -H 'Content-Type: application/json' \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
      "protocolVersion": "2024-11-05",
      "capabilities": {},
      "clientInfo": {"name": "curl-test", "version": "1.0"}
    }
  }'

curl -s -X POST http://127.0.0.1:1080/mcp/openshift \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'

curl -s -X POST http://127.0.0.1:1080/mcp/openshift \
  -H 'Content-Type: application/json' \
  -d '{
    "jsonrpc": "2.0",
    "id": 3,
    "method": "tools/call",
    "params": {
      "name": "pods_delete",
      "arguments": {"name": "web-1", "namespace": "myapp"}
    }
  }'
```

### MCP client config

```json
{
  "mcpServers": {
    "openshift-mcp-server": {
      "type": "http",
      "url": "http://127.0.0.1:1080/mcp/openshift"
    },
    "lightspeed-mcp": {
      "type": "http",
      "url": "http://127.0.0.1:1080/mcp/lightspeed"
    }
  }
}
```

## Static vs dynamic expectations

Matchers use `ONLY_MATCHING_FIELDS` on the JSON-RPC body:

```json
{
  "httpRequest": {
    "method": "POST",
    "path": "/mcp/openshift",
    "body": {
      "type": "JSON",
      "json": {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": { "name": "namespaces_list" }
      },
      "matchType": "ONLY_MATCHING_FIELDS"
    }
  }
}
```

**Static** — return schema `outputExample` (Mustache only substitutes `id`).

**Dynamic** — Mustache + JsonPath copy request args into the response (e.g. `pods_delete` echoes `params.arguments.name` / `namespace`).

**Fixtures** — higher priority (`50`); one-shot when needed for multi-step scenarios (OOMKilled, CVE flows). Restart the container to replay consumed fixtures.

Shipped fixture files:

| File | Scenario |
|---|---|
| `schemas/openshift-mcp-server/fixtures-oomkilled.json` | OOMKilled / CrashLoopBackOff then fix |
| `schemas/lightspeed-mcp/fixtures-cve-validation.json` | CVE remediable vs not |
| `schemas/lightspeed-mcp/fixtures-cve-impact.json` | CVE impact analysis flow |

## Add a tool or another MCP

Field rules, static vs dynamic vs fixtures, and a full example are in [SCHEMA.md](SCHEMA.md).

1. Add or edit `schemas/<mcp>/schema.json`. For a new server, also append an `McpServerSpec` in `scripts/generate_expectations.py` (`path` must be unique, for example `/mcp/example`).
2. Optional: echo request arguments via that entry's `dynamic_map` (`jp("$.params.arguments.<field>")`).
3. Optional: add `schemas/<mcp>/fixtures-<scenario>.json` and list it on `fixture_paths`.
4. Regenerate:

```bash
python3 scripts/generate_expectations.py
docker compose up --build
```

Do not hand-edit `expectations/*.json`; the generator overwrites them. Clients call `http://127.0.0.1:1080/mcp/<name>`.

## Konflux / OpenShift Tekton

Evaluation pipelines (e.g. [Agentic Eval Flow](https://github.com/RHEcosystemAppEng/agentic_eval_flow)) typically pass an **`MCP_URL`** to the evaluate step. Point that URL at this mock.

**Sidecar** — mock and eval share the Task pod network:

```text
MCP_URL=http://127.0.0.1:1080/mcp/openshift
```

See [`.tekton/skill-eval-mcp-sidecar.yaml`](.tekton/skill-eval-mcp-sidecar.yaml).

**Service** — deploy the image in-cluster, then set:

```text
MCP_URL=http://mcp-mock-services.<namespace>.svc:1080/mcp/<name>
```

After changing expectations, rebuild the image so pipeline runs pick up new JSON. Local Compose bind-mounts `expectations/` for iteration.

## Regenerating expectations

```bash
python3 scripts/generate_expectations.py
```

## License

Apache License 2.0. See [LICENSE](LICENSE).
