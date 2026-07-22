# simengine

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![OPC UA](https://img.shields.io/badge/OPC%20UA-Compliant-orange.svg)](https://opcfoundation.org/)
[![SparkplugB](https://img.shields.io/badge/Sparkplug%20B-Compliant-brightgreen.svg)](https://sparkplug.eclipse.org/)

A real-time **station simulation engine** for production lines — a PLC-replacement data source for SCADA/MES tools such as FactoryTalk Optix, Ignition, and UaExpert. A native, fixed-timestep engine (no external DES dependency) simulates serial lines of stations with health degradation, cycle stops, quality rolls, and continuous process values, and publishes the result over **OPC UA TCP**, **OPC UA PubSub over MQTT**, and **SparkplugB** simultaneously — controlled through an embedded **REST API**, a browser HMI, an **MCP server**, and an optional BYO-key **Claude chat**.

---

## What it does

- **Simulates** configurable serial lines of stations (2+, no hard upper limit) with buffers between them
- **Degrades** stations through a configurable health model — competing-risk failure modes (Weibull/exponential/lognormal MTTF/MTTR), condition-based maintenance vs. run-to-failure, short cycle stops (jams, no-picks) distinct from full failures
- **Synthesizes** continuous process values per station — force, temperature, position — via four signal profiles (`cycle_peak`, `first_order_lag`, `cycle_ramp`, `constant_noise`), with threshold alarms and hysteresis
- **Rolls** quality per completed cycle (health-correlated defect rate, optional rework) and tracks OEE (per-station and bottleneck line-level) every step
- **Publishes** the same live state on three protocols at once — OPC UA TCP (ISA-95 address space), OPC UA PubSub over MQTT (Part 14 JSON), and SparkplugB (Protobuf, delta-encoded) — with a reason-coded alarm surface (`FM_*`, `PV_*`, `CS_*`, `MT_*`) instead of flat booleans
- **Runs** multi-segment production recipes with stochastic changeovers
- **Exposes** a knowledge graph binding every metric to all of its wire addresses (OPC UA NodeId, SparkplugB coordinates, MQTT topic, REST path), consumed by an MCP server and an embedded LLM chat
- **Deterministic** by construction: `--seed N` gives a byte-identical trajectory, forever, regardless of run length

---

## Quick start

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"

# REST/UI on :8080, OPC UA on :4840, MCP on :8765/mcp
.venv/bin/python -m simengine --scenario demo_line --seed 42

# Faster than real time (10 sim-seconds per wall-second)
.venv/bin/python -m simengine --scenario press_line_8 --seed 42 --speed-ratio 10

# Multi-segment recipe
.venv/bin/python -m simengine --recipe monday_schedule --seed 42

# API/UI only — start runs later via REST, the web UI, or an MCP tool
.venv/bin/python -m simengine
```

```bash
python -m simengine --help
```
```
--scenario SCENARIO   start this scenario immediately
--recipe RECIPE       start this recipe immediately
--seed SEED
--speed-ratio SPEED_RATIO   sim seconds per wall second (1.0 = real time)
--port PORT            REST/UI port (default 8080)
--mcp-port MCP_PORT     MCP server port (default 8765)
--no-mcp                disable the MCP server
--verbose
```

Open `http://localhost:8080/` for the dashboard (material-flow strip, per-station state/health/OEE/process values), `/configure` for the scenario and recipe editor, `/comms` to toggle the three protocol outputs, and `/assistant` for the chat page (requires `pip install -e ".[chat]"` and your own Anthropic API key, entered in the browser and held only in server process memory for that session).

### Connect a client

- **OPC UA:** point UaExpert / any OPC UA client at `opc.tcp://localhost:4840/simengine/` and browse `Objects → {Enterprise} → {Site} → {Area} → {Line}_Equipment`. Full node tree in [`docs/address_space.md`](docs/address_space.md).
- **MQTT:** `mosquitto_sub -t 'opcua/#' -v` for Part 14 JSON, `mosquitto_sub -t 'spBv1.0/#' -v` for SparkplugB Protobuf — both enabled per scenario under `comms:` (see `config/scenarios.yaml`).
- **MCP:** any MCP-capable host (Claude Desktop, Claude Code, ...) — `{"mcpServers": {"simengine": {"url": "http://localhost:8765/mcp"}}}`. See [`docs/ai_interface.md`](docs/ai_interface.md).

---

## Architecture

```
                              simengine process
                    ┌──────────────────────────────────┐
OPC UA clients ─────┤ OPCUAServerPublisher       :4840  │
MQTT (Part14/SpB) ──┤ OPCUAMqttPublisher / SparkplugB   │──── Mosquitto broker
Browser UI ─────────┤ Flask: REST + UI + Chat    :8080  │
Claude Desktop/Code ┤ MCP server (FastMCP)      :8765   │──── Anthropic API
any MCP host        │        │                          │     (BYO key)
                    │  RunManager · LineEngine ·         │
                    │  Snapshot · KnowledgeGraph          │
                    └──────────────────────────────────┘
```

Everything downstream — publishers, REST, the historian event collector, MCP/chat tools — reads one frozen `LineSnapshot` built fresh by `LineEngine.snapshot()` each step. There is no separate "read model"; OPC UA, MQTT, SparkplugB, and `GET /api/v1/state` all serialize the same object.

Stations step **downstream-first** each tick (one-step-per-hop material flow), pulling from an infinite source and pushing to an infinite sink at the line ends. Each step reseeds one `random.Random` and one numpy `Generator` from `(seed + step_count) % 2**31` — no global RNG state anywhere — so a run is reproducible snapshot-for-snapshot under a fixed `--seed`, independent of how long it runs.

### Station states

Seven states with a normative detection order: `UNDER_REPAIR` → `FAILED` → cycle-stopped (reports `IDLE` with a `CS_*` alarm active) → `BLOCKED` → `STARVED` → `DEGRADED` (still processing) → `PROCESSING` → `IDLE`.

---

## Configuration

Scenarios live in `config/scenarios.yaml`. Three are shipped:

| Scenario | Stations | What it exercises |
|---|---|---|
| `two_station_minimal` | 2 | Smallest valid line — no health, no PVs |
| `demo_line` | 3 | Health/CBM, one failure mode, cycle stops, all four PV profiles, alarms |
| `press_line_8` | 8 | Full feature set at scale — health, failure modes, cycle stops, PVs, SPC, shifts |

A station config accepts `cycle_time` (or `target_ppm`, which takes precedence — `cycle_time = 60/ppm`), `defect_rate`, `health` (`h_max`, `p_degrade`, `cbm_threshold`, `mttr`), `failure_modes`, `cycle_stops`, `process_values`, and `spc.enabled`. Buffers are implicit-serial: exactly `len(stations) - 1`, connecting station *i* to *i+1*. See `CLAUDE.md` for the full schema reference and `docs/specs/clone_build_plan.md §3` for the governing spec.

```yaml
demo_line:
  stations:
    - name: Press01
      cycle_time: 12.0
      defect_rate: 0.02
      health:
        h_max: 5
        p_degrade: 0.001
        cbm_threshold: 5          # == h_max means run-to-failure
        mttr: {distribution: lognormal, mean: 120, std: 30}
      failure_modes:
        - name: bearing_wear
          type: wearout
          mttf: {distribution: weibull, shape: 2.0, scale: 20000}
          mttr: {distribution: lognormal, mean: 300, std: 60}
      cycle_stops:
        - reason: CS_JAM
          mtbe: {distribution: exponential, mean: 900}
          duration: {distribution: lognormal, mean: 25, std: 10}
      process_values:
        - name: OilTemp
          unit: degC
          profile: first_order_lag
          setpoint: 55.0
          tau: 300
          initial: 20.0
          alarm_high: 68
  buffers:
    - {name: B1, capacity: 10}
  comms:
    opcua: {enabled: true, port: 4840}
    opcua_mqtt: {enabled: true, broker: "mqtt://mosquitto:1883"}
    sparkplugb: {enabled: false, broker: "mqtt://mosquitto:1883", group_id: "Area01", edge_node_id: "Line1"}
```

### Recipes

Multi-segment production schedules with stochastic changeovers, in `config/recipes/`:

```bash
python -m simengine --recipe monday_schedule --seed 42
```

Each segment references a base scenario with optional per-station overrides and a `quantity` (batch) or `duration` (time-boxed) stop condition. During changeover, line state is `CHANGEOVER` on OPC UA.

---

## REST API

```
GET    /api/v1/state                    Full snapshot: line KPIs, per-station state/health/PVs/alarms
GET    /api/v1/state/stations/{name}    One station
GET    /api/v1/runs/current             run_id, scenario, sim_time, RUNNING/IDLE
POST   /api/v1/runs                     {scenario, seed?, speed_ratio?} -> 201 {run_id}
POST   /api/v1/runs/recipe              {recipe, seed?} -> 201 {run_id}
DELETE /api/v1/runs/current             Stop the active run

GET    /api/v1/scenarios                List / GET/PUT/POST individual scenarios
GET    /api/v1/recipes                  List / GET/PUT/POST individual recipes
GET/PUT /api/v1/comms                   Read/update a scenario's protocol outputs (applies next run)
GET    /api/v1/kg                       Knowledge graph, node-link JSON (?type=, ?station=, ?edge=)
GET    /api/v1/plugins                  Which optional historian/analysis packages are installed
GET    /healthz                         Liveness
```

All mutating endpoints reuse the same validators the CLI uses — invalid input is rejected with a 400 and the file on disk is left untouched.

---

## Publishers — three protocols, one snapshot

| Publisher | Transport | Encoding | Enabled via |
|---|---|---|---|
| OPC UA TCP | `opc.tcp://:4840/simengine/` | ISA-95 address space, batched writes | `comms.opcua` |
| OPC UA PubSub over MQTT | MQTT | Part 14 JSON NetworkMessage | `comms.opcua_mqtt` |
| SparkplugB | MQTT | Protobuf, NBIRTH/DBIRTH + delta NDATA/DDATA | `comms.sparkplugb` |

Metric names are identical across all three encodings — only transport and encoding differ, never the data model. SparkplugB uses a vendored Eclipse Tahu Protobuf definition (the `mqtt-spb-wrapper` package pins an incompatible `paho-mqtt` version, so it's not a dependency here); enable it with `pip install -e ".[sparkplug]"`.

---

## AI interface

A deterministic, stdlib-only **knowledge graph** is built at run start from the scenario config, binding every process value and metric to all four of its wire addresses (OPC UA NodeId, SparkplugB coordinates, MQTT topic, REST path). It backs:

- **`GET /api/v1/kg`** — node-link JSON for any consumer
- **MCP server** at `:8765/mcp` — 16 tools (10 read, 6 always-on control) shared with the REST API and the chat, so external hosts (Claude Desktop, Claude Code, or any MCP client) get full read/control access
- **`/assistant` chat page** — an Anthropic-only agent loop over the same tools, with the knowledge graph as a cached system prompt; your API key lives only in server process memory for the session, never on disk or in logs

Full details, connection snippet, and the security note (control tools are always on — treat `:8765` like `:8080`, a trusted-network interface) are in [`docs/ai_interface.md`](docs/ai_interface.md).

---

## Optional plugins

The core has zero analytics dependencies. Historian backends register through a name → package mapping (`config: historians: ["csv"]`, etc.):

```bash
pip install -e ".[historian-influx]"   # InfluxDB event historian
pip install -e ".[historian-neo4j]"    # Neo4j causal-graph historian
pip install -e ".[sparkplug]"          # SparkplugB publisher
pip install -e ".[chat]"               # Anthropic BYO-key assistant
pip install -e ".[analysis]"           # pandas-based post-run analysis
```

An unconfigured/uninstalled historian fails with an explicit `pip install simengine[historian-X]` hint rather than an import error.

---

## Docker

**Local dev** (builds from source):

```bash
docker compose -f docker/docker-compose.yml up --build -d          # simengine + Mosquitto
docker compose -f docker/docker-compose.yml --profile influx up -d # + InfluxDB
docker compose -f docker/docker-compose.yml --profile graph up -d  # + Neo4j
```

The Dockerfile is a multi-stage build (builder venv, slim runtime image); pass `EXTRAS` to bake in optional dependencies (`--build-arg EXTRAS=historian-influx,sparkplug`).

**Portainer / any host** (pulls a pre-built image from GHCR — no build step, no host bind mounts): use `docker/docker-compose.portainer.yml`, published by `.github/workflows/publish-image.yml`. See [`docs/deployment.md`](docs/deployment.md) for the full walk-through.

---

## Testing

```bash
pytest tests/ -v                                    # 363 tests, all local, no external services
flake8 src/ tests/ --count --select=E9,F63,F7,F82    # error-only lint pass
```

Coverage includes: engine determinism (identical snapshot JSON under a fixed seed across arbitrary run lengths), the full 7-state machine, run-to-failure and CBM health paths, quality conservation, cycle-stop firing, hand-computed OEE fixtures, all four process-value profiles, OPC UA address-space shape and write-batching, REST CRUD and run-lifecycle (409 on double-start), SparkplugB birth/delta/rebirth/seq framing, the plugin registry, MCP tool registry (including path-traversal rejection on recipe names), and BYO-key chat (SSE event shapes, key-never-persisted).

---

## Repository layout

```
src/simengine/
  engine/       snapshot.py (the system-wide contract), line.py (LineEngine),
                station.py (7-state machine), health.py, process_values.py,
                alarms.py, knowledge_graph.py
  config/       loader.py (schema + validators), distributions.py
  publishers/   OPC UA TCP, OPC UA-over-MQTT, SparkplugB, shared metric map
  runtime/      run_manager.py (lifecycle, run_id, recipes), shift_manager.py,
                spc.py, fault_injector.py
  events/       SimEvent + EventHistorian ABC, snapshot-diff event collector
  api/          rest.py, tools.py (16-tool registry), mcp_server.py, chat.py,
                ui/ (Jinja templates: dashboard, configure, comms, chat)
  plugins.py    historian registry with install-hint errors
src/simengine_historian_{csv,influx,neo4j}/   optional historian backends
config/         scenarios.yaml, recipes/*.yaml
docker/         Dockerfile, docker-compose.yml (mosquitto + influx/graph profiles)
docs/           address_space.md, ai_interface.md, specs/ (governing build-plan documents)
```

See `CLAUDE.md` for engine invariants (determinism, health/CBM semantics, KPI formulas) that should not be changed casually, and `docs/specs/` for the original architecture and build-plan documents this engine was built from.

---

## Provenance

simengine was built as a from-scratch native engine replacing an earlier Simantha (discrete-event simulation, NIST) based digital twin, carrying forward its ISA-95 address-space design, config-validation patterns, SPC/shift/failure-mode modules, and its `--seed`-based reproducibility model, while removing the DES dependency entirely in favor of a fixed-timestep engine purpose-built for this address space. See `docs/specs/clone_reuse_evaluation.md` for the module-by-module carry-over analysis.

## License

Public Domain (NIST-derived; see `LICENSE`).
