# Clone AI Interface Spec — Knowledge Graph, MCP Server, BYO-Key Chat

**Status:** Proposed
**Extends:** `clone_target_architecture.md` (lean core + optional plugins) and `clone_build_plan.md` (adds Phase 7).
**Decisions baked in:** MCP tools have **full control always** (read + run control + config edits, no gating flag); embedded chat is **Anthropic-only** (other LLM providers reach the system through external MCP hosts); the MCP server is exposed **both** as a network endpoint for external hosts and as the tool registry behind the built-in UI chat.

---

## 1. Knowledge Graph of the Data Model

### What it is

A dependency-free, in-process graph (`engine/knowledge_graph.py`, plain dict adjacency — no networkx, honoring the lean-core rule) built **deterministically at run start** from the scenario config + comms config. It is the semantic registry of everything the engine models and publishes.

### Node types

`Enterprise, Site, Area, Line, Station, Buffer, ProcessValue, FailureMode, AlarmCode, CycleStopReason, Scenario, Recipe, Metric`

### Edge types

| Edge | Meaning |
|---|---|
| `CONTAINS` | ISA-95 hierarchy: Enterprise → Site → Area → Line → Station/Buffer |
| `FEEDS` | Material flow: Source → M1 → B1 → M2 → … → Sink (mirrors the Neo4j plugin's existing topology) |
| `HAS_PV` | Station → ProcessValue |
| `HAS_FAILURE_MODE` | Station → FailureMode |
| `CAN_RAISE` | Station → AlarmCode (from the alarm catalog + configured PVs/failure modes/cycle stops) |
| `MEASURED_BY` | ProcessValue → SPC monitor (when `spc.enabled`) |
| `RUNS` | Line → Scenario / Recipe (active run) |

### The load-bearing feature: protocol address binding

Every `Metric` / `ProcessValue` node carries **all of its wire addresses**:

```json
{
  "id": "pv:Press01.OilTemp",
  "type": "ProcessValue",
  "name": "OilTemp", "station": "Press01", "unit": "degC",
  "addresses": {
    "opcua_node_id": "ns=2;s=Acme.Plant1.Area01.Line1_Equipment.Press01_Equipment.ProcessValues.OilTemp",
    "sparkplug_metric": {"group": "Area01", "edge_node": "Line1", "device": "Press01", "metric": "PV/OilTemp"},
    "mqtt_flat_topic": "simengine/Line1/Press01/pv/oiltemp",
    "rest_path": "stations.Press01.process_values[name=OilTemp].value"
  },
  "alarm_codes": ["PV_OILTEMP_HIGH"]
}
```

The same data content is published on three protocols with three addressing schemes; the KG is the **single place that binds them**. "OilTemp on Press01" resolves to every address plus the live value. This is what makes LLM grounding work — the model asks by meaning, the KG resolves to addresses — and it doubles as integration documentation for human consumers (an Optix engineer can look up the SparkplugB metric for a value they found via OPC UA).

### Access

- `GET /api/v1/kg` — JSON node-link format; filters `?type=`, `?station=`, `?edge=`
- MCP tools `query_knowledge_graph` / `resolve_metric` (§2)
- Optional export to the `historian-neo4j` plugin: the plugin's existing FEEDS topology creation is re-pointed to consume the KG rather than re-deriving from config — one source of truth

The KG is static per run and rebuilt at run start; it is config-derived and deterministic (same scenario → identical graph).

---

## 2. MCP Server

### Placement and transport

- `api/mcp_server.py`, **core** (new core dependency: `mcp>=1.0`, the official Python MCP SDK, FastMCP style)
- **Streamable HTTP** transport on its own port, default **8765**, path `/mcp`, started alongside REST/UI in `simengine.__main__`
- Same process as the engine → direct access to `run_manager`, the live snapshot, the KG, and the config validators — no OPC UA round-trips, no polling

### Tool registry — one implementation, three surfaces

Every tool is a thin wrapper over the same functions the REST API calls. REST, MCP, and the embedded chat expose identical behavior; a bug fix lands in all three at once.

**Read tools:**

| Tool | Returns |
|---|---|
| `get_line_state()` | Full `LineSnapshot` as JSON (same shape as `GET /api/v1/state`) |
| `get_station(name)` | One `StationSnapshot` |
| `get_run_status()` | run_id, scenario, sim_time, stop conditions, RUNNING/IDLE |
| `query_knowledge_graph(node_type?, name?, relation?)` | Matching KG nodes/edges |
| `resolve_metric(query)` | Semantic lookup ("oil temperature on the press") → KG node with all protocol addresses + current live value |
| `list_scenarios()` / `get_scenario(name)` | Scenario configs |
| `list_recipes()` / `get_recipe(name)` | Recipe configs |
| `explain_alarm(code)` | Alarm catalog entry + KG context (which station, which PV/failure mode raises it, thresholds) |

**Control tools (always available — design decision):**

| Tool | Behavior |
|---|---|
| `start_run(scenario, seed?, speed_ratio?)` | 409-equivalent tool error if a run is active |
| `start_recipe(recipe, seed?)` | Recipe mode |
| `stop_run()` | Graceful stop, publishers' `on_run_end` fires |
| `update_scenario(name, yaml_text)` | Runs the full `config_loader` validator suite **before** writing; validation failure → tool error with the validator message, file untouched |
| `update_recipe(name, yaml_text)` | Same pattern via recipe validators |
| `set_comms(config)` | Validates, persists, returns `{"applies": "next_run"}` |

**Security note (explicit in docs):** control tools are always on. The MCP port must be treated exactly like the REST port — a trusted-network interface. Anything that can reach :8765 can start/stop runs and edit configs, same as anything that can reach :8080. Do not expose either beyond the intended network without a reverse proxy adding auth.

### External MCP hosts

Any MCP-capable host connects directly — Claude Desktop, Claude Code, or other MCP clients:

```json
{
  "mcpServers": {
    "simengine": { "url": "http://<host>:8765/mcp" }
  }
}
```

This is the path for non-Anthropic LLM stacks too: bring any MCP host, point it at the endpoint.

---

## 3. BYO-Key Chat in the Flask UI

### UI

A fourth page, **Assistant** (`ui/chat.html`):
- API-key input (password field) with an explicit "held in memory for this session only" label
- Model picker, default **`claude-opus-4-8`**
- Chat pane with streamed responses and rendered tool-call traces (`→ get_station("Press01")` … `→ start_run("demo_line", seed=42)`) so the operator sees exactly what the model did
- Chat disabled with an install hint if the `chat` extra isn't installed, and with a "enter your API key" hint if no key is set

### Backend (`api/chat.py`)

- **Anthropic Python SDK only** (`anthropic[mcp]`, optional `chat` extra in pyproject; lazy-imported)
- Agent loop via **`client.beta.messages.tool_runner(...)`** with adaptive thinking (`thinking={"type": "adaptive"}`) over the **same tool registry** the MCP server exposes. In-process the tools are called as direct function references (no MCP round-trip); the SDK's `anthropic.lib.tools.mcp` conversion helpers (`mcp_tool`/`async_mcp_tool`) are the documented fallback wiring if the registry is ever moved out of process.
- **System prompt assembled from the KG** at conversation start: line topology summary (FEEDS chain), station list with cycle times, PV names/units/limits, active alarm catalog — the model is grounded in this specific line before its first tool call. Keep the KG summary as the stable cached prefix; per-turn state goes through tools, not the prompt.
- Routes:
  - `POST /api/v1/chat` — body `{message, api_key?, model?}`; responds with SSE stream of `{type: "text"|"tool_use"|"tool_result"|"done", ...}` events
  - `DELETE /api/v1/chat` — clears conversation history
- Multi-turn: history held server-side (in-memory, per Flask session); assistant `content` (including tool_use blocks) and tool_result messages appended per the Messages API contract
- Error mapping: Anthropic 401 → "check your API key"; `RateLimitError` → surfaced with retry-after; refusal stop reason surfaced as a plain message

### Key handling (hard requirements)

1. The API key lives **only** in server process memory, keyed to the UI session; never written to disk, config files, YAML, logs, or the historian.
2. The key is sent from browser to Flask over the same channel as everything else — the docs state plainly that a TLS reverse proxy is required if the UI is served beyond localhost/trusted LAN.
3. `GET` endpoints never echo the key; the status endpoint reports only `{"chat_key_set": true|false}`.

---

## 4. GraphQL vs REST — Evaluation

**Verdict: keep REST as the control plane; do not migrate. MCP is the LLM interface. GraphQL earns a place only later, as an optional plugin over the knowledge graph, if a real external consumer demands graph querying.**

Reasoning:

1. **The API is command-shaped, not query-shaped.** Start/stop/configure are RPCs; GraphQL models them as mutations with no benefit over `POST /api/v1/runs`. GraphQL's core value — client-shaped selection over deep object graphs to avoid over-fetching — doesn't apply when the whole `LineSnapshot` serializes to a few kilobytes and every consumer wants most of it.

2. **LLMs interact through MCP tools, not query languages.** A typed tool schema (`get_station(name: str)`) is validated at the protocol layer and impossible to malform; asking a model to author GraphQL query strings reintroduces exactly the failure mode MCP was designed to remove (syntax errors, invalid selections, injection surface, retry loops). With MCP in place, GraphQL would be a *third* read surface with no unique consumer.

3. **The one graph-shaped thing is the KG — and it's served.** `query_knowledge_graph` + `resolve_metric` tools and `GET /api/v1/kg?type=&station=&edge=` cover topology and semantic-lookup needs. If a future external system genuinely needs arbitrary graph traversal queries, add GraphQL **scoped to the KG only** as an optional `[graphql]` plugin (strawberry or ariadne) — additive, no control-plane migration, consistent with the plugin architecture.

4. **Cost of migrating now:** a new dependency in the lean core, a resolver layer duplicating the validator plumbing REST already owns, invalidating the REST spec already written into `clone_build_plan.md` §6 — for zero identified consumers.

---

## 5. Architecture Fit

```
                                ┌──────────────────────────────┐
                                │        simengine process     │
                                │                              │
  OPC UA clients ── :4840 ──────┤ OPCUAServerPublisher         │
  MQTT (Part14/SpB) ─ broker ───┤ OPCUAMqtt / SparkplugB pubs  │
                                │        ▲                     │
  Browser UI ────── :8080 ──────┤ Flask: │REST + UI + Chat     │
                                │        │      │              │
  Claude Desktop /              │        │  tool registry ─────┼── Anthropic API
  Claude Code /     :8765/mcp ──┤ MCP server (FastMCP)         │   (user's key,
  any MCP host                  │        │                     │    tool_runner)
                                │  RunManager · Snapshot · KG  │
                                └──────────────────────────────┘
```

- KG, tool registry, MCP server, chat backend are all **core** (the chat's `anthropic` dep is the one optional extra — the page degrades gracefully without it)
- No change to publishers, engine, or the historian plugin contract; the Neo4j plugin optionally consumes the KG
- Port map: REST/UI **8080**, OPC UA **4840**, MCP **8765**, MQTT broker external

---

## 6. Documentation Layer — CAG-First with GraphRAG Structure (Future, decided now)

Decision record for adding line SOPs / technical documentation later. Nothing in this section is built in Phase 7; it is specified now so the KG design keeps the door open and the implementation pass doesn't re-litigate the approach.

### 6.1 Three knowledge planes, one entity spine

| Plane | Nature | Lives in | Requires historian? |
|---|---|---|---|
| Live state | what is happening now | Snapshot → MCP tools | No |
| SOPs / tech docs | static reference — how the line is meant to run | KG + cached chat prefix | **No** |
| Historical record | what happened in run X | CSV/InfluxDB historian plugins | Yes |

The planes are independently addable. Documentation does **not** re-open historian integration: docs attach to the KG and the chat prefix with zero historian involvement. The historical plane arrives separately, as one additive MCP tool (`query_run_history(run_id, ...)`) backed by the existing historian plugins and scoped by `run_id`. **The KG is the join point** — `Press01` is the same node whether the model reads its live temperature, its maintenance SOP, or last week's failure count. That shared entity spine is what makes an eventual three-plane assistant coherent.

### 6.2 Document nodes in the KG

- New node types: `Document`, `DocSection`; new edges: `DOCUMENTS` (Document → Line/Station), `APPLIES_TO` (DocSection → Station | AlarmCode | FailureMode | ProcessValue | Recipe).
- Corpus: `docs/sops/*.md` per scenario, chunked by heading at ingestion (run start, same determinism rule as the rest of the KG).
- **Entity linking is lexical, not embedding-based.** The KG already holds a controlled vocabulary with stable IDs (`Press01`, `PV_OILTEMP_HIGH`, `FM_BEARING_WEAR`) — matching those strings in doc text is deterministic, stdlib-only, and high-precision precisely because the names are controlled. Optional YAML front matter (`applies_to: [Press01, PV_OILTEMP_HIGH]`) for explicit links. This removes the hardest problem in typical GraphRAG (entity extraction/canonicalization) because the entities pre-exist the documents.
- MCP tool additions when built: `get_documentation(entity)` (KG traversal → linked sections), `search_docs(query)` (lexical).
- Scenario bundles (perf spec R1) include the scenario's doc corpus.

### 6.3 CAG specification (the chosen first mechanism)

**Decision: CAG-first.** For a line-scoped SOP corpus (bounded, small — typically 20–80k tokens), the full corpus is placed in the chat's cached system prefix rather than retrieved per query.

Prompt structure (extends §3's existing design):

```
[system prefix — byte-identical across requests]        ← cache_control breakpoint here
  KG topology summary (already specced)
  Full SOP corpus, section-tagged: <sop id="SOP-12" section="4.2" applies_to="Press01">…</sop>
[volatile — after the breakpoint]
  conversation history, tool_use/tool_result blocks, user turn
```

Mechanics and economics (recorded so expectations are calibrated):

- The corpus is **in context on every request** — the model sees all of it, every time; there is no retrieval step and therefore no retrieval-miss failure mode. This is the defining CAG property.
- It is **processed only once per cache lifetime**: the first request pays a cache-write premium (1.25× for 5-min TTL, 2× for 1-h TTL); subsequent requests bill the prefix at ~0.1× input price. Order-of-magnitude at Opus-tier pricing: a 50k-token corpus ≈ $0.25 cold, ≈ $0.03/query warm. An active multi-turn chat keeps the cache warm by construction (the conversation re-sends the prefix every turn anyway).
- **Worst case** (queries always farther apart than the TTL): every query is a cache write ≈ 1.25× plain input cost — no savings, not catastrophic.
- **Cache invalidation rules** (must be respected by the implementation): the prefix must stay byte-identical — editing any SOP invalidates it (one cold re-read, then warm); each scenario with a distinct doc set is its own cache entry; the SOP block sits *before* anything volatile. Use 1-h TTL for the doc-bearing prefix.
- Why CAG beats retrieval at this scale: retrieval is the only RAG component that can silently fail, and "why did the process do this?" answers routinely need **cross-document synthesis** (live alarm from a tool call + limits table in one SOP + maintenance note in another) — exactly where top-k retrieval is weakest. Adding a vector pipeline here would add a failure mode to save context space that isn't scarce.
- Document nodes are kept even under CAG — not for retrieval but for **citation and traceability**: the model cites `SOP-12 §4.2` (the section tags make this reliable), and the UI links the citation to the source file.

### 6.4 Graduation path (when CAG stops fitting)

Trigger conditions: corpus grows past ~100–200k tokens; or many scenarios with distinct large corpora share one instance; or queries are too infrequent to keep any cache warm.

1. **Stage 2 — GraphRAG proper:** flip from "all sections in prefix" to per-query `get_documentation(entity)` **graph-traversal retrieval** — only sections linked to the entities in play enter context. Same `Document`/`DocSection` nodes and `APPLIES_TO` edges; the retrieval mechanism changes from *nothing* to *KG traversal*. No re-ingestion, no new dependencies.
2. **Stage 3 — vector search, plugin only:** if free-text semantic search over a large corpus is ever genuinely needed, add embeddings as an optional `[rag]` plugin (consistent with §4's GraphQL verdict: heavy retrieval infra never enters the lean core).

---

## 7. Build Plan Integration (Phase 7)

Appended to `clone_build_plan.md` as Phase 7 — same execution-grade format (numbered tasks, exact files, Gate). Summary:

- **P7.1** `engine/knowledge_graph.py` + `GET /api/v1/kg` + `tests/test_knowledge_graph.py` (node/edge counts for the `demo_line` fixture; address-binding round-trip: every PV in config appears with all four addresses; determinism: two builds → identical JSON)
- **P7.2** `api/mcp_server.py` + tool registry + `tests/test_mcp_tools.py` (every tool against a mocked run_manager; control tools reject invalid YAML without writing; `start_run` while running → tool error)
- **P7.3** `api/chat.py` + `ui/chat.html` + `tests/test_chat.py` (mocked Anthropic client; SSE event shape; key-never-persisted test: run a chat turn, then assert the key string appears nowhere under `config/`, `results/`, or the log capture)
- **P7.4** Docs: external-host connection guide, security note, KG reference

**Gate P7:** engine running `demo_line` → Claude Code (or `mcp` CLI) connects to `http://localhost:8765/mcp`, lists 16 tools, `get_line_state` returns the live snapshot, `start_run`/`stop_run` round-trip works; UI chat answers "what's the oil temperature on Press01?" via `resolve_metric` with a real key (manual check); `pytest tests/test_knowledge_graph.py tests/test_mcp_tools.py tests/test_chat.py -v` green.

**Dependency changes** (pyproject): core adds `mcp>=1.0`; new extra `chat = ["anthropic[mcp]>=0.50"]`.
