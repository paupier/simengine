# simengine

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![OPC UA](https://img.shields.io/badge/OPC%20UA-Compliant-orange.svg)](https://opcfoundation.org/)
[![SparkplugB](https://img.shields.io/badge/Sparkplug%20B-Compliant-brightgreen.svg)](https://sparkplug.eclipse.org/)

A real-time **station simulation engine** for production lines — a PLC-replacement data source for SCADA/MES tools such as FactoryTalk Optix, Ignition, and UaExpert. A native, fixed-timestep engine (no external DES dependency) simulates serial lines of stations with health degradation, cycle stops, quality rolls, and continuous process values, and publishes the result over **OPC UA TCP**, **OPC UA PubSub over MQTT**, and **SparkplugB** simultaneously — controlled through an embedded **REST API**, a browser HMI, an **MCP server**, and an optional BYO-key **Claude chat**.

---

## What it does

- **Simulates** configurable serial lines of stations (2+, no hard upper limit) with buffers between them
- **Degrades** stations through a run-to-failure health model — competing-risk failure modes (Weibull/exponential/lognormal MTTF/MTTR), short cycle stops (jams, no-picks) distinct from full failures
- **Synthesizes** continuous process values per station — force, temperature, position — via four signal profiles (`cycle_peak`, `first_order_lag`, `cycle_ramp`, `constant_noise`), with threshold alarms and hysteresis
- **Rolls** quality per completed cycle (health-correlated defect rate, optional rework) and tracks OEE (per-station and bottleneck line-level) every step
- **Publishes** the same live state on three protocols at once — OPC UA TCP (ISA-95 address space, `StationType`/`BufferStorageUnitType` ObjectTypes, `AnalogItemType` process values), OPC UA PubSub over MQTT (Part 14 JSON), and SparkplugB (Protobuf, delta-encoded) — with a reason-coded alarm surface (`FM_*`, `PV_*`, `CS_*`, `MT_*`) instead of flat booleans
- **Varies by shift** — a scenario's shift schedule can make a shift run proportionally slower (`cycle_time_factor`, hits Performance) and/or less reliable (`health_degrade_factor`, hits Availability), independently, line-wide
- **Exposes** a knowledge graph binding every metric to all of its wire addresses (OPC UA NodeId, SparkplugB coordinates, MQTT topic, REST path), consumed by an MCP server and an embedded LLM chat, plus a wire-schema export (including OPC UA NodeSet2 XML) so an integrator can see or import the exact address space without a live run
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

# API/UI only — start runs later via REST, the web UI, or an MCP tool
.venv/bin/python -m simengine
```

```bash
python -m simengine --help
```
```
--scenario SCENARIO   start this scenario immediately
--seed SEED
--speed-ratio SPEED_RATIO   sim seconds per wall second (1.0 = real time)
--port PORT            REST/UI port (default 8080)
--mcp-port MCP_PORT     MCP server port (default 8765)
--no-mcp                disable the MCP server
--verbose
```

Open `http://localhost:8080/` for the dashboard (material-flow strip, per-station state/health/OEE/process values), `/configure` for the scenario editor (plant-model view/edit, station and shift editing, wire-schema export), `/comms` to toggle the three protocol outputs, `/diagnostics` for a raw MQTT publish / REST scratch-value probe with no engine coupling, and `/assistant` for the chat page (requires `pip install -e ".[chat]"` and your own Anthropic API key, entered in the browser and held only in server process memory for that session).

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
Claude Desktop/Code ┤ MCP server (MCPServer)    :8765   │──── Anthropic API
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
| `demo_line` | 3 | Health degradation, one failure mode, cycle stops, all four PV profiles, alarms |
| `press_line_8` | 8 | Full feature set at scale — health, failure modes, cycle stops, PVs, SPC, per-shift performance factors |

A station config accepts `cycle_time` (or `target_ppm`, which takes precedence — `cycle_time = 60/ppm`), `defect_rate`, `health` (`h_max`, `p_degrade`, `mttr` — run-to-failure only, no condition-based-maintenance path), `failure_modes`, `cycle_stops`, `process_values`, and `spc.enabled`. Buffers are implicit-serial: exactly `len(stations) - 1`, connecting station *i* to *i+1*. A scenario can also carry a `shifts.schedule` — each entry may set `cycle_time_factor` and/or `health_degrade_factor` to make that shift run slower and/or less reliable, line-wide. See `CLAUDE.md` for the full schema reference and `docs/specs/clone_build_plan.md §3` for the original governing spec (superseded in places — see the note at the top of that document).

```yaml
demo_line:
  stations:
    - name: Press01
      cycle_time: 12.0
      defect_rate: 0.02
      health:
        h_max: 5
        p_degrade: 0.001
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

---

## REST API

```
GET    /api/v1/state                    Full snapshot: line KPIs, per-station state/health/PVs/alarms
GET    /api/v1/state/stations/{name}    One station
GET    /api/v1/runs/current             run_id, scenario, sim_time, RUNNING/IDLE
POST   /api/v1/runs                     {scenario, seed?, speed_ratio?} -> 201 {run_id}
DELETE /api/v1/runs/current             Stop the active run

GET    /api/v1/scenarios                List / GET/PUT/POST individual scenarios; POST .../validate for a draft
GET/PUT /api/v1/comms                   Read/update a scenario's protocol outputs (applies next run)
GET    /api/v1/kg                       Knowledge graph, node-link JSON (?type=, ?station=, ?edge=); POST /preview for a draft config
GET    /api/v1/schema                   OPC UA/MQTT/SparkplugB wire schema for a saved scenario, no run required
GET    /api/v1/schema/nodeset2.xml      Same address space as an OPC UA NodeSet2 document (importable offline)
GET/PUT /api/v1/diagnostics/value       Raw REST scratch-value probe; POST /mqtt-publish for a one-shot MQTT publish
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
- **MCP server** at `:8765/mcp` — 12 tools (8 read, 4 always-on control) shared with the REST API and the chat, so external hosts (Claude Desktop, Claude Code, or any MCP client) get full read/control access
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
pytest tests/ -v                                    # 408 tests, all local, no external services
flake8 src/ tests/ --count --select=E9,F63,F7,F82    # error-only lint pass
```

Coverage includes: engine determinism (identical snapshot JSON under a fixed seed across arbitrary run lengths), the full 7-state machine, run-to-failure health paths, quality conservation, cycle-stop firing, hand-computed OEE fixtures, all four process-value profiles, per-shift `cycle_time_factor`/`health_degrade_factor` (deterministic edge-case probabilities, not statistical sampling), OPC UA address-space shape/ObjectTypes/write-batching, wire-schema and NodeSet2 export (no-drift checks against the live publishers), REST CRUD and run-lifecycle (409 on double-start), SparkplugB birth/delta/rebirth/seq framing, the plugin registry, the MCP tool registry, and BYO-key chat (SSE event shapes, key-never-persisted).

---

## Repository layout

```
src/simengine/
  engine/       snapshot.py (the system-wide contract), line.py (LineEngine),
                station.py (7-state machine), health.py, process_values.py,
                alarms.py, knowledge_graph.py
  config/       loader.py (schema + validators), distributions.py
  publishers/   OPC UA TCP (asyncua; ObjectTypes + AnalogItemType PVs),
                OPC UA-over-MQTT, SparkplugB, shared metric map
  runtime/      run_manager.py (lifecycle, run_id, shift-factor wiring),
                shift_manager.py, spc.py
  events/       SimEvent + EventHistorian ABC, snapshot-diff event collector
  api/          rest.py, tools.py (12-tool registry), mcp_server.py, chat.py,
                config_files.py, diagnostics.py (MQTT/REST connectivity probe,
                no engine coupling), schema.py (wire-schema + NodeSet2 export),
                ui/ (Jinja templates: dashboard, configure, comms, diagnostics, chat)
  plugins.py    historian registry with install-hint errors
src/simengine_historian_{csv,influx,neo4j}/   optional historian backends
config/         scenarios.yaml
docker/         Dockerfile, docker-compose.yml (mosquitto + influx/graph profiles)
docs/           address_space.md, ai_interface.md, deployment.md,
                fleet_deployment.md, specs/ (original build-plan documents,
                since superseded in places — see notes at the top of each)
```

See `CLAUDE.md` for engine invariants (determinism, health/run-to-failure semantics, KPI formulas) that should not be changed casually, and `docs/specs/` for the original architecture and build-plan documents this engine was built from (superseded in places — see the note at the top of each).

---

## Provenance

simengine was built as a from-scratch native engine replacing an earlier Simantha (discrete-event simulation, NIST) based digital twin, carrying forward its ISA-95 address-space design, config-validation patterns, SPC/shift/failure-mode modules, and its `--seed`-based reproducibility model, while removing the DES dependency entirely in favor of a fixed-timestep engine purpose-built for this address space. See `docs/specs/clone_reuse_evaluation.md` for the module-by-module carry-over analysis.

## License

Public Domain (NIST-derived; see `LICENSE`).
