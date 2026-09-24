# MCP Mock Services (`mcp-mock-services`)

This repository provides mock environments for our internal Model Context Protocol (MCP) servers (e.g., OpenShift, Lightspeed). 

It is built on top of [MockServer](https://www.mock-server.com/#why-use-mockserver) and is specifically designed to **replace live MCP servers during AI Skill evaluation pipelines**.

### 🎯 Core Purpose
* **MCP Replacement:** Simulates real MCP server responses (both static and dynamic) to evaluate AI Skills in complete isolation from external infrastructure.
* **Cost & Reliability:** Eliminates third-party API costs and prevents real-world side effects or failures during evaluation runs.
* **CI/CD Native:** Packaged as a lightweight container built by Konflux and injected as a sidecar during Tekton evaluation tasks.
