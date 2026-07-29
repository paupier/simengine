# AI Interface — Knowledge Graph, MCP Server, Assistant Chat, i3X

simengine exposes four AI/integration-facing surfaces, all backed by the same
tool registry and knowledge graph (spec: `docs/specs/clone_ai_interface_spec.md`
for the first three; `docs/superpowers/specs/2026-07-28-i3x-interface-design.md`
for i3X):

| Surface | Where | For |
|---|---|---|
| Knowledge graph | `GET /api/v1/kg` (`?type=`, `?station=`, `?edge=`) | Address binding + topology, human or machine consumers |
| MCP server | `http://<host>:8765/mcp` (streamable HTTP) | Any MCP host: Claude Desktop, Claude Code, other LLM stacks |
| Assistant chat | UI page `/assistant` (BYO Anthropic key) | Operators, in the browser |
| i3X interface | `http://<host>:8080/i3x/v1/*` | i3X-conformant test/reference clients |

## Knowledge graph

Built deterministically at run start from the scenario config. Every
ProcessValue and Metric node carries all of its wire addresses — OPC UA
NodeId, SparkplugB `{group, edge_node, device, metric}` coordinates, flat MQTT
topic, and REST JSON path — so "OilTemp on Press01" resolves to every protocol
address plus the live value. This is what grounds the LLM tools
(`resolve_metric`, `query_knowledge_graph`, `explain_alarm`) and doubles as
integration documentation: an Optix engineer can look up the SparkplugB metric
for a value they found via OPC UA.

## Connecting an external MCP host

The MCP server runs in the engine process on port **8765**, path `/mcp`
(change with `--mcp-port`; disable with `--no-mcp`). Configuration snippet for
Claude Desktop / Claude Code (`mcpServers` in the host's config):

```json
{
  "mcpServers": {
    "simengine": { "url": "http://<host>:8765/mcp" }
  }
}
```

The server exposes 12 tools:

- **Read:** `get_line_state`, `get_station`, `get_run_status`,
  `query_knowledge_graph`, `resolve_metric`, `list_scenarios`,
  `get_scenario`, `explain_alarm`
- **Control (always on):** `start_run`, `stop_run`, `update_scenario`, `set_comms`

Config writes go through the same validators as the REST API — invalid input
returns a tool error and the file is untouched.

## Assistant chat

The `/assistant` UI page runs an Anthropic-only agent loop (SDK tool runner)
over the same 12 tools, with the knowledge graph summary as a cached system
prefix. Requires the optional extra:

```bash
pip install simengine[chat]
```

The API key is entered in the browser, held **only in server process memory**
for the UI session, and never written to disk, config files, logs, or the
historian. The status endpoint reports only `{"chat_key_set": true|false}`.
Other LLM providers are not supported in the embedded chat by design — bring
any MCP-capable host and point it at `:8765/mcp` instead.

## i3X interface

A [CESMII i3X](https://github.com/cesmii/i3X) 1.0 read+subscriptions REST/SSE
API — presents the same knowledge graph as an i3X object/relationship graph
with live Value-Quality-Timestamp values, for validating against i3X
conformance suites and reference clients rather than as a production path.
Enable per scenario with:

```yaml
comms:
  i3x:
    enabled: true
```

(default off; the shipped `demo_line` scenario has it on). When enabled, the
surface is mounted at `/i3x/v1/` on the same port as the REST API (`:8080`):
`/info`, `/namespaces`, `/objecttypes`, `/relationshiptypes`, `/objects`,
`/objects/related`, `/objects/value`, `/objects/history`, and the
`/subscriptions/*` family (create/register/unregister/list/delete, plus
`/subscriptions/sync` poll-with-ack and `/subscriptions/stream` SSE).

**No writes, no auth.** `/info` reports `update.current` and
`update.history` as `false` — `PUT`-style value/history writes are not
implemented; simengine computes values, it doesn't accept them. There is no
authentication layer, same as the REST and MCP surfaces: treat `:8080/i3x/v1`
as trusted-network, not internet-facing. `/objects/history` always returns
an empty `values` array — core simengine keeps no in-process value history
by design (see the SPC/Welford memory-flatness note in `CLAUDE.md`); it only
becomes meaningful once a `historian-influx` backend is wired in.

The vendored spec snapshot (OpenAPI + the two implementation guides, pinned
against i3X tag `1.0.0`) lives in `docs/specs/i3x/`.

## Security note

**Control tools are always on.** Anything that can reach port 8765 can start
and stop runs and edit scenario files — exactly like anything that can reach
the REST port 8080. Treat both as trusted-network interfaces:

- do not expose 8080 or 8765 beyond the intended network;
- for anything else, put a reverse proxy with authentication in front of both;
- the chat API key travels from browser to Flask over the same channel as
  everything else — serve the UI behind TLS if it leaves localhost or a
  trusted LAN.
