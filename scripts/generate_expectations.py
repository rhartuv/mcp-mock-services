#!/usr/bin/env python3
"""Generate MockServer initialization JSON from MCP schemas and fixtures.

Each entry in MCP_SERVERS becomes one expectations/<id>.json file,
loaded by MockServer via MOCKSERVER_INITIALIZATION_JSON_PATH=/config/*.json.
Add OpenShift, Lightspeed, or any future MCP by appending to MCP_SERVERS.

  python3 scripts/generate_expectations.py
"""

from __future__ import annotations

import json
from collections import Counter
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "schemas"
OUT = ROOT / "expectations"

JSONRPC_ID = "{{#jsonPath}}$.id{{/jsonPath}}{{jsonPathResult}}"
ID_SENTINEL = "__MCP_JSONRPC_ID__"

# Higher priority is matched first (MockServer default is 0).
PRIORITY_HEALTH = 100
PRIORITY_FIXTURE = 50
PRIORITY_DYNAMIC = 40
PRIORITY_STATIC = 30
PRIORITY_PROTOCOL = 20
PRIORITY_CATCHALL = 0

# JsonPath helper used inside Mustache templates.
JP = "{{#jsonPath}}%s{{/jsonPath}}{{jsonPathResult}}"


def jp(path: str) -> str:
    return JP % path


# Tools whose responses echo request arguments (Mustache).
OPENSHIFT_DYNAMIC: dict[str, dict[str, Any]] = {
    "pods_delete": {
        "name": jp("$.params.arguments.name"),
        "namespace": jp("$.params.arguments.namespace"),
        "status": "deleted",
    },
    "pods_run": {
        "name": jp("$.params.arguments.name"),
        "namespace": jp("$.params.arguments.namespace"),
        "image": jp("$.params.arguments.image"),
        "status": "Pending",
    },
    "pods_get": {
        "name": jp("$.params.arguments.name"),
        "namespace": jp("$.params.arguments.namespace"),
        "status": "Running",
        "node": "worker-0.ocp-lab.example.com",
        "ip": "10.128.2.45",
        "containers": [
            {
                "name": "api-server",
                "image": "registry.example.com/myapp/api-server:v2.3.1",
                "ready": True,
                "restart_count": 0,
                "state": "running",
                "last_termination_reason": "",
            }
        ],
        "labels": {"app": "api-server", "version": "v2.3.1"},
        "created_at": "2026-09-07T08:00:00Z",
    },
    "pods_log": {
        "pod": jp("$.params.arguments.name"),
        "container": "api-server",
        "logs": (
            "2026-09-07T10:14:55Z INFO  Starting api-server v2.3.1\n"
            "2026-09-07T10:14:56Z INFO  Connected to database\n"
            "2026-09-07T10:14:57Z INFO  Listening on :8080\n"
        ),
    },
    "nodes_log": {
        "node": jp("$.params.arguments.name"),
        "query": jp("$.params.arguments.query"),
        "logs": (
            "Sep 07 09:00:01 kubelet[1523]: I0907 09:00:01.123456 1523 "
            "kubelet.go:2345] SyncLoop (PLEG): pod in running state\n"
        ),
    },
    "nodes_stats_summary": {
        "node_name": jp("$.params.arguments.name"),
        "cpu": {"usage_nano_cores": 1250000000, "usage_core_nano_seconds": 45678901234567},
        "memory": {
            "available_bytes": 8589934592,
            "usage_bytes": 25769803776,
            "working_set_bytes": 24696061952,
        },
        "fs": {
            "available_bytes": 107374182400,
            "capacity_bytes": 214748364800,
            "used_bytes": 96636764160,
        },
        "pods_count": 42,
    },
    "resources_delete": {
        "kind": jp("$.params.arguments.kind"),
        "name": jp("$.params.arguments.name"),
        "namespace": jp("$.params.arguments.namespace"),
        "status": "deleted",
    },
    "resources_scale": {
        "kind": jp("$.params.arguments.kind"),
        "name": jp("$.params.arguments.name"),
        "namespace": jp("$.params.arguments.namespace"),
        "current_replicas": 2,
        "desired_replicas": 2,
    },
}

LIGHTSPEED_DYNAMIC: dict[str, dict[str, Any]] = {
    "inventory__find_host_by_name": {
        "results": [
            {
                "id": "68ce32aa-57da-49b7-8ded-dc4ad54e520a",
                "display_name": jp("$.params.arguments.display_name"),
                "fqdn": jp("$.params.arguments.display_name"),
                "os_version": "RHEL 9.4",
            }
        ],
        "total": 1,
    },
    "inventory__get_host_details": {
        "id": jp("$.params.arguments.host_id"),
        "display_name": "prod-webserver-01.example.com",
        "fqdn": "prod-webserver-01.example.com",
        "os_version": "RHEL 9.4",
        "arch": "x86_64",
        "last_check_in": "2026-09-07T08:30:00Z",
        "installed_packages": [
            "openssl-3.0.7-24.el9.x86_64",
            "openssl-libs-3.0.7-24.el9.x86_64",
            "kernel-5.14.0-427.el9.x86_64",
            "httpd-2.4.57-8.el9.x86_64",
        ],
        "running_services": ["httpd.service", "sshd.service", "insights-client.timer"],
        "tags": [
            {"namespace": "insights-client", "key": "env", "value": "production"},
            {"namespace": "insights-client", "key": "team", "value": "platform"},
        ],
        "subscription_status": "valid",
    },
    "inventory__get_host_system_profile": {
        "id": jp("$.params.arguments.host_id"),
        "system_profile": {
            "os_release": "9.4",
            "os_kernel_version": "5.14.0-427.el9.x86_64",
            "arch": "x86_64",
            "number_of_cpus": 4,
            "cores_per_socket": 2,
            "system_memory_bytes": 17179869184,
            "infrastructure_type": "virtual",
            "cloud_provider": "aws",
        },
    },
    "vulnerability__get_cve": {
        "id": jp("$.params.arguments.cve_id"),
        "attributes": {
            "cvss_score": 9.8,
            "impact": "Critical",
            "synopsis": "RHSA-2026:4501: openssl security update",
            "description": (
                "A critical vulnerability in OpenSSL allows remote code "
                "execution via crafted TLS handshake."
            ),
            "public_date": "2026-08-15T00:00:00Z",
            "advisory_available": True,
            "remediation": 2,
            "systems_affected": 12,
            "affected_packages": [
                "openssl-3.0.7-24.el9.x86_64",
                "openssl-libs-3.0.7-24.el9.x86_64",
            ],
            "advisories_list": [
                {
                    "id": "RHSA-2026:4501",
                    "synopsis": "Important: openssl security update",
                    "type": "security",
                    "public_date": "2026-08-16T00:00:00Z",
                }
            ],
            "errata": "RHSA-2026:4501",
            "cwe": "CWE-122",
            "cvss3_vector": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",
            "rules": [],
        },
    },
    "vulnerability__explain_cves": {
        "explanations": [
            {
                "cve_id": jp("$.params.arguments.cve_ids[0]"),
                "affected_package": "openssl",
                "installed_version": "3.0.7-24.el9",
                "fixed_version": "3.0.7-25.el9",
                "explanation": (
                    "System has openssl-3.0.7-24.el9.x86_64 installed. "
                    "Advisory RHSA-2026:4501 provides the fix."
                ),
            }
        ],
    },
    "remediations__create_vuln_playbook": {
        "playbook": (
            "---\n"
            "- name: Remediate requested CVEs\n"
            "  hosts: \"" + jp("$.params.arguments.system_uuid") + "\"\n"
            "  become: true\n"
            "  tasks:\n"
            "    - name: Apply security updates\n"
            "      ansible.builtin.dnf:\n"
            "        name: '*'\n"
            "        security: true\n"
            "        state: latest\n"
        ),
        "cves_addressed": [jp("$.params.arguments.cve_ids[0]")],
        "packages_updated": [
            "openssl-3.0.7-25.el9.x86_64",
            "openssl-libs-3.0.7-25.el9.x86_64",
        ],
    },
}


def load_json(path: Path) -> Any:
    with path.open() as handle:
        return json.load(handle)


def json_body(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "JSON",
        "json": payload,
        "matchType": "ONLY_MATCHING_FIELDS",
    }


def post_rpc(path: str, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
    if params is not None:
        body["params"] = params
    return {
        "method": "POST",
        "path": path,
        "body": json_body(body),
    }


def call_tool_request(
    path: str, tool_name: str, arguments: dict[str, Any] | None = None
) -> dict[str, Any]:
    params: dict[str, Any] = {"name": tool_name}
    if arguments:
        params["arguments"] = arguments
    return post_rpc(path, "tools/call", params)


def mustache_template(result: Any, extra_headers: dict[str, list[str]] | None = None) -> str:
    headers = {"Content-Type": ["application/json"]}
    if extra_headers:
        headers.update(extra_headers)
    http = {
        "statusCode": 200,
        "headers": headers,
        "body": {
            "jsonrpc": "2.0",
            "id": ID_SENTINEL,
            "result": result,
        },
    }
    dumped = json.dumps(http, ensure_ascii=False)
    return dumped.replace(f'"{ID_SENTINEL}"', JSONRPC_ID)


def tool_result(output: Any) -> dict[str, Any]:
    text = (
        output
        if isinstance(output, str)
        else json.dumps(output, indent=2, ensure_ascii=False)
    )
    return {
        "content": [{"type": "text", "text": text}],
        "isError": False,
    }


def templated_expectation(
    *,
    exp_id: str,
    http_request: dict[str, Any],
    result: Any,
    priority: int,
    extra_headers: dict[str, list[str]] | None = None,
    times: dict[str, Any] | None = None,
) -> dict[str, Any]:
    expectation: dict[str, Any] = {
        "id": exp_id,
        "priority": priority,
        "httpRequest": http_request,
        "httpResponseTemplate": {
            "templateType": "MUSTACHE",
            "template": mustache_template(result, extra_headers),
        },
    }
    if times:
        expectation["times"] = times
    return expectation


def once() -> dict[str, Any]:
    return {"remainingTimes": 1, "unlimited": False}


def health_expectation() -> dict[str, Any]:
    return {
        "id": "liveness-health",
        "priority": PRIORITY_HEALTH,
        "httpRequest": {"method": "GET", "path": "/health"},
        "httpResponse": {
            "statusCode": 200,
            "headers": {"Content-Type": ["application/json"]},
            "body": {"status": "ok", "service": "mcp-mock-services"},
        },
    }


def protocol_expectations(path: str, schema: dict[str, Any]) -> list[dict[str, Any]]:
    server_name = schema.get("name", "mock-mcp-server")
    version = schema.get("version", "1.0.0")
    tools_list = [
        {
            "name": tool["name"],
            "description": tool.get("description", ""),
            "inputSchema": tool.get(
                "inputSchema", {"type": "object", "properties": {}}
            ),
        }
        for tool in schema.get("tools", [])
    ]
    slug = path.strip("/").replace("/", "-")
    session_headers = {"Mcp-Session-Id": [f"{slug}-session"]}
    return [
        templated_expectation(
            exp_id=f"{slug}-initialize",
            http_request=post_rpc(path, "initialize"),
            result={
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": server_name, "version": version},
            },
            priority=PRIORITY_PROTOCOL,
            extra_headers=session_headers,
        ),
        {
            "id": f"{slug}-notifications-initialized",
            "priority": PRIORITY_PROTOCOL,
            "httpRequest": post_rpc(path, "notifications/initialized"),
            "httpResponse": {"statusCode": 202},
        },
        templated_expectation(
            exp_id=f"{slug}-ping",
            http_request=post_rpc(path, "ping"),
            result={},
            priority=PRIORITY_PROTOCOL,
        ),
        templated_expectation(
            exp_id=f"{slug}-tools-list",
            http_request=post_rpc(path, "tools/list"),
            result={"tools": tools_list},
            priority=PRIORITY_PROTOCOL,
        ),
    ]


def fixture_key(step: dict[str, Any]) -> tuple[str, str]:
    return step["tool"], json.dumps(step.get("input") or {}, sort_keys=True)


def fixture_expectations(
    path: str, fixtures_files: list[Path], schema_tools: set[str]
) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    for fixture_path in fixtures_files:
        data = load_json(fixture_path)
        for step in data.get("sequence", []):
            if not isinstance(step, dict) or not step.get("tool"):
                continue
            annotated = deepcopy(step)
            annotated["_source"] = fixture_path.stem
            steps.append(annotated)

    counts = Counter(fixture_key(step) for step in steps)
    seen: Counter[tuple[str, str]] = Counter()
    expectations: list[dict[str, Any]] = []
    slug = path.strip("/").replace("/", "-")

    for index, step in enumerate(steps, start=1):
        tool = step["tool"]
        if tool not in schema_tools:
            continue
        arguments = step.get("input") or {}
        key = fixture_key(step)
        seen[key] += 1
        empty_input = not arguments
        sequential = counts[key] > 1
        times = once() if empty_input or sequential else None
        source = step["_source"]
        expectations.append(
            templated_expectation(
                exp_id=f"{slug}-fixture-{source}-{index:02d}-{tool}",
                http_request=call_tool_request(
                    path, tool, arguments if arguments else None
                ),
                result=tool_result(step.get("output", {})),
                priority=PRIORITY_FIXTURE,
                times=times,
            )
        )
    return expectations


def tool_expectations(
    path: str,
    schema: dict[str, Any],
    dynamic_map: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    slug = path.strip("/").replace("/", "-")
    expectations: list[dict[str, Any]] = []
    for tool in schema.get("tools", []):
        name = tool["name"]
        if name in dynamic_map:
            output = dynamic_map[name]
            priority = PRIORITY_DYNAMIC
            kind = "dynamic"
        else:
            output = tool.get("outputExample")
            if output is None:
                output = {"message": f"{name} completed successfully"}
            priority = PRIORITY_STATIC
            kind = "static"
        expectations.append(
            templated_expectation(
                exp_id=f"{slug}-{kind}-{name}",
                http_request=call_tool_request(path, name),
                result=tool_result(output),
                priority=priority,
            )
        )
    return expectations


def catchall_expectation(path: str) -> dict[str, Any]:
    slug = path.strip("/").replace("/", "-")
    unknown = {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {"error": "Unknown tool", "hint": f"Call tools/list on {path}"},
                    indent=2,
                ),
            }
        ],
        "isError": True,
    }
    return templated_expectation(
        exp_id=f"{slug}-catchall-tools-call",
        http_request=post_rpc(path, "tools/call"),
        result=unknown,
        priority=PRIORITY_CATCHALL,
    )


def build_server(
    *,
    path: str,
    schema_path: Path,
    fixture_paths: list[Path],
    dynamic_map: dict[str, dict[str, Any]],
    include_health: bool,
) -> list[dict[str, Any]]:
    schema = load_json(schema_path)
    tool_names = {tool["name"] for tool in schema.get("tools", [])}
    expectations: list[dict[str, Any]] = []
    if include_health:
        expectations.append(health_expectation())
    expectations.extend(protocol_expectations(path, schema))
    expectations.extend(fixture_expectations(path, fixture_paths, tool_names))
    expectations.extend(tool_expectations(path, schema, dynamic_map))
    expectations.append(catchall_expectation(path))
    return expectations


def write_expectations(path: Path, expectations: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(expectations, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {path.relative_to(ROOT)} ({len(expectations)} expectations)")


@dataclass(frozen=True)
class McpServerSpec:
    """One mocked MCP behind a unique path on the shared MockServer port."""

    id: str
    path: str
    schema_path: Path
    fixture_paths: list[Path] = field(default_factory=list)
    dynamic_map: dict[str, dict[str, Any]] = field(default_factory=dict)
    include_health: bool = False


# Append new servers here (OpenShift, Lightspeed, …).
MCP_SERVERS: list[McpServerSpec] = [
    McpServerSpec(
        id="openshift-mcp",
        path="/mcp/openshift",
        schema_path=SCHEMAS / "openshift-mcp-server" / "schema.json",
        fixture_paths=[SCHEMAS / "openshift-mcp-server" / "fixtures-oomkilled.json"],
        dynamic_map=OPENSHIFT_DYNAMIC,
        include_health=True,
    ),
    McpServerSpec(
        id="lightspeed-mcp",
        path="/mcp/lightspeed",
        schema_path=SCHEMAS / "lightspeed-mcp" / "schema.json",
        fixture_paths=[
            SCHEMAS / "lightspeed-mcp" / "fixtures-cve-validation.json",
            SCHEMAS / "lightspeed-mcp" / "fixtures-cve-impact.json",
        ],
        dynamic_map=LIGHTSPEED_DYNAMIC,
        include_health=False,
    ),
]


def main() -> None:
    for server in MCP_SERVERS:
        write_expectations(
            OUT / f"{server.id}.json",
            build_server(
                path=server.path,
                schema_path=server.schema_path,
                fixture_paths=server.fixture_paths,
                dynamic_map=server.dynamic_map,
                include_health=server.include_health,
            ),
        )


if __name__ == "__main__":
    main()
