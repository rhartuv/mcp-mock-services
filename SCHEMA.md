# Schema contract

This is what to publish so `scripts/generate_expectations.py` can mock another MCP on this image. One MockServer process serves every registered MCP at `POST /mcp/<name>` on port 1080.

OpenShift (`/mcp/openshift`) and Lightspeed (`/mcp/lightspeed`) are examples. Adding a server does not require a Dockerfile change.

## Ownership

| File | Owner | Role |
|---|---|---|
| `schemas/<mcp>/schema.json` | MCP developers | Tool catalog. `tools/list` and the default `tools/call` body come from here. |
| `schemas/<mcp>/fixtures-<scenario>.json` | Skill authors | One file per evaluation story. Specific payloads, not the default catalog. |
| `dynamic_map` on `McpServerSpec` | Mock authors | Tools whose response must echo request arguments (Mustache). |

Do not edit `expectations/*.json` by hand. The generator overwrites those files.

## Add an MCP

1. Create `schemas/<mcp>/schema.json` (and optional `fixtures-*.json`).
2. Append an entry to `MCP_SERVERS` in `scripts/generate_expectations.py`:

```python
McpServerSpec(
    id="example-mcp",                 # expectations/example-mcp.json
    path="/mcp/example",              # must be unique
    schema_path=SCHEMAS / "example-mcp" / "schema.json",
    fixture_paths=[
        SCHEMAS / "example-mcp" / "fixtures-health-check.json",
    ],
    dynamic_map={
        "get_status": {
            "name": jp("$.params.arguments.name"),
            "status": "ok",
        },
    },
    include_health=False,             # only one server in the list should be True
),
```

3. Regenerate and restart:

```bash
python3 scripts/generate_expectations.py
docker compose up --build
```

4. Call `http://127.0.0.1:1080/mcp/example`.

`include_health=True` emits `GET /health`. Set it on exactly one entry (today: OpenShift).

## `schema.json`

A JSON object with a `tools` array. Each tool needs a non-empty `name`.

| Field | Required | Used for |
|---|---|---|
| `name` | Recommended | `initialize` → `serverInfo.name`. Default `mock-mcp-server`. |
| `version` | Recommended | `initialize` → `serverInfo.version`. Default `1.0.0`. |
| `description` | No | Documentation only. |
| `tools` | Yes | Tool catalog. |

| Tool field | Required | Used for |
|---|---|---|
| `name` | Yes | `tools/list` and `tools/call` matcher (`params.name`). Unique in the file. |
| `description` | Recommended | Shown on `tools/list`. |
| `inputSchema` | Recommended | Shown on `tools/list`. Not enforced at call time. |
| `outputSchema` | Recommended | Documentation for authors. The generator does not read it. |
| `outputExample` | Recommended | Static `tools/call` body. If omitted: `{"message": "<name> completed successfully"}`. |

`outputExample` is the happy-path payload. Keep scenario-specific data (a broken pod, a particular CVE) in fixtures. Do not put secrets or customer data in examples.

`tools/call` returns that payload as MCP `CallToolResult`: pretty-printed JSON inside `result.content[0].text`. Newlines in that string appear as `\n` in the raw HTTP body.

### Minimal `schema.json`

```json
{
  "name": "example-mcp-server",
  "version": "1.0.0",
  "description": "Minimal catalog.",
  "tools": [
    {
      "name": "get_status",
      "description": "Return service health.",
      "inputSchema": {
        "type": "object",
        "properties": {
          "name": { "type": "string", "description": "Caller label." }
        },
        "required": []
      },
      "outputSchema": {
        "type": "object",
        "properties": {
          "name": { "type": "string" },
          "status": { "type": "string" }
        }
      },
      "outputExample": {
        "name": "example",
        "status": "ok"
      }
    }
  ]
}
```

With no `dynamic_map` entry, every `get_status` call returns `outputExample`. The JSON-RPC `id` is still copied from the request.

## Static, dynamic, fixtures

For each `tools/call`, the generator writes matchers. Highest priority that matches wins.

| Kind | Priority | Body |
|---|---|---|
| Fixture step | 50 | `output` from `fixtures-*.json` |
| Dynamic | 40 | `dynamic_map` entry; JsonPath copies request fields |
| Static | 30 | `outputExample` |
| Unknown tool | 0 | `isError: true` |

Matchers use `ONLY_MATCHING_FIELDS`: extra JSON-RPC fields (`id`, unused arguments) do not need to match.

### Dynamic tools

Put the tool name in `dynamic_map`. Values may be plain JSON or `jp("$.params.arguments.<field>")`, which becomes a Mustache JsonPath tag.

```python
"get_status": {
    "name": jp("$.params.arguments.name"),
    "status": "ok",
}
```

A call with `"arguments": {"name": "web-1"}` returns `"name": "web-1"`. A tool listed here does not use `outputExample`.

### `fixtures-<scenario>.json`

```json
{
  "description": "Health check returns degraded once, then ok.",
  "recorded_from": "example-mcp-server schema v1.0.0",
  "sequence": [
    {
      "tool": "get_status",
      "input": { "name": "web-1" },
      "output": { "name": "web-1", "status": "degraded" }
    },
    {
      "tool": "get_status",
      "input": {},
      "output": { "name": "example", "status": "ok" }
    }
  ]
}
```

| Field | Required | Meaning |
|---|---|---|
| `sequence` | Yes | Ordered steps. |
| `description` | No | What the story covers. |
| `recorded_from` | No | Schema the fixtures were written against. |
| `sequence[].tool` | Yes | A `name` from `schema.json`. Unknown tools are skipped. |
| `sequence[].input` | No | Argument subset to match. `{}` or omitted matches any arguments for that tool. |
| `sequence[].output` | Yes | Payload placed in `content[0].text`. |

Empty `input`, and any repeated `(tool, input)` pair, is one-shot (`remainingTimes: 1`). That is how a story can return "degraded" on the first call and "ok" on the next. Restart the container to replay consumed steps. A step with a non-empty `input` stays available and beats the static/dynamic matcher whenever those arguments are present.

List every fixtures file on `McpServerSpec.fixture_paths`. All of them are loaded together; there is no runtime switch between scenario files inside one image.

## Checklist

- [ ] `schemas/<mcp>/schema.json` lists every tool, with the same `name` strings as the real MCP.
- [ ] Each tool has `description`, `inputSchema`, and an `outputExample` that matches the real response shape.
- [ ] Scenario data lives in `fixtures-<scenario>.json`, not in `outputExample`.
- [ ] Tools that must echo arguments are in `dynamic_map`.
- [ ] `path` is unique (`/mcp/<name>`).
- [ ] `python3 scripts/generate_expectations.py` writes `expectations/<id>.json`.
- [ ] `POST /mcp/<name>` with `tools/list` returns the catalog, and a sample `tools/call` returns the expected static, dynamic, or fixture body.
