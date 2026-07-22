# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**simengine** is a real-time station simulation engine for production lines — a PLC-replacement data source for SCADA/MES tools (FactoryTalk Optix, Ignition, UaExpert). A fixed-timestep native engine (no Simantha/DES dependency) simulates serial lines of stations with health degradation, cycle stops, quality rolls, and continuous process values, publishing over **OPC UA TCP**, **OPC UA PubSub over MQTT (Part 14 JSON)**, and **SparkplugB**, controlled through an embedded **REST API** with a 3-page HMI UI, an **MCP server**, and an optional BYO-key **Anthropic chat**.

Governing specs live in `docs/specs/` (`clone_build_plan.md` is execution-grade and overrides the others where they conflict). This repo was bootstrapped from the simantha-opcua parent with history preserved; parent-only code is recoverable from git history.

## Commands

```bash
# Install (editable, with dev tools)
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
# Optional extras: sparkplug, historian-influx, historian-neo4j, analysis, chat

# Run: REST/UI :8080, OPC UA :4840, MCP :8765/mcp
python -m simengine --scenario demo_line --seed 42
python -m simengine --recipe monday_schedule --seed 42
python -m simengine --scenario demo_line --speed-ratio 10   # 10x faster than wall clock
python -m simengine                                          # API only; start runs via REST

# Tests (fast, all local)
pytest tests/ -v
pytest tests/test_station_engine.py::TestDeterminism -v

# Lint (errors-only pass)
flake8 src/ tests/ --count --select=E9,F63,F7,F82 --show-source

# Docker: simengine + mosquitto; profiles: influx, graph
docker compose -f docker/docker-compose.yml up --build -d
docker compose -f docker/docker-compose.yml --profile influx up -d
```

pyproject.toml sets `pythonpath = ["src", "tests"]` for pytest.

## Architecture

```
src/simengine/
  engine/       snapshot.py (the system-wide contract), line.py (LineEngine),
                station.py (7-state machine, Buffer, CycleStopModel),
                health.py, process_values.py, alarms.py, knowledge_graph.py
  config/       loader.py (§3 schema validators), distributions.py (DistributionFactory)
  publishers/   __init__.py (StatePublisher ABC + build_publishers factory),
                opcua_server.py + opcua_nodes.py (ISA-95, batched writes),
                opcua_mqtt.py (Part 14 JSON + flat topics), sparkplugb.py,
                metrics.py (shared snapshot->metric map), _sparkplug_pb/ (vendored Tahu pb2)
  runtime/      run_manager.py (thread lifecycle, run_id, recipes), recipe_runner.py,
                shift_manager.py, spc.py, line_state.py, fault_injector.py
  events/       __init__.py (SimEvent + EventHistorian ABC + CompositeHistorian),
                collect.py (snapshot-diff edge detection)
  api/          rest.py (+create_app), tools.py (16-tool registry), mcp_server.py,
                chat.py, config_files.py, ui/ (Jinja templates)
  plugins.py    historian registry with install-hint errors
src/simengine_historian_{csv,influx,neo4j}/   optional backends (register() hook)
config/scenarios.yaml   §3 schema; config/recipes/*.yaml
```

### The snapshot contract

Everything consumes one frozen representation: `LineEngine.snapshot()` builds a fresh `LineSnapshot` each step (`engine/snapshot.py`); publishers, REST (`asdict` = the JSON), the historian collector, and MCP/chat tools all read it. Never let a consumer reach into engine internals.

### Engine invariants (validated behavior — do not change casually)

- **Determinism:** each step seeds `random.Random((seed + step_count) % 2**31)` and a same-seeded numpy Generator, passed into every model. No global seeding anywhere; all distribution sampling flows through `DistributionFactory` via `_rvs(dist, random_state)`. Same seed ⇒ byte-identical snapshot JSON.
- **State detection precedence (normative, engine/station.py):** UNDER_REPAIR → FAILED → cycle-stopped (reports IDLE with CS_* alarm; time accrues to MINOR_STOP) → BLOCKED → STARVED → DEGRADED (still processes) → PROCESSING → IDLE.
- **Health model (engine/health.py):** run-to-failure only. p_degrade Bernoulli per step to h_max; failure attribution via competing-risks `FailureModeManager` (MTTF sample ÷ h_max when h_max>1); repair countdown keys on `repair_remaining > 0` (not the reported state) so it stays in sync across the step where health first reaches h_max. CBM (condition-based maintenance, an early no-downtime repair path) was removed — it silently never raised the MT_REPAIR alarm (under_repair required failed=True, which CBM never set) and let a station produce indefinitely at an elevated defect rate with no visible downtime; see `docs/superpowers/specs/2026-07-22-remove-cbm-design.md` for the removal rationale.
- **KPIs (P4.5):** Availability = 1 − down/total where down = FAILED+UNDER_REPAIR only; Performance = parts×cycle_time/(total−down) capped at 1.0 (minor stops land here); Quality = good/max(1,parts). Line OEE = bottleneck min per component. Shift rotation resets per-station KPI baselines, not counters.
- **Stations step downstream-first** (reverse order) — one-step-per-hop material flow. Scrap is discarded at the station (never moves downstream); `good + scrap == parts_made`.
- **Warm-up** (`warm_up_time`, counted in steps): mechanics run, counters and time accumulators don't.

### Config schema (§3, exhaustive for v1)

`config/scenarios.yaml`: `stations` (min 2; `cycle_time` or `target_ppm` — ppm wins), `buffers` (exactly n−1, implicit serial routing), per-station `health {h_max, p_degrade, cbm_threshold, mttr}`, `failure_modes`, `cycle_stops {reason, mtbe, duration}`, `process_values` (profiles: `cycle_peak`, `first_order_lag`, `cycle_ramp`, `constant_noise` — formulas in `engine/process_values.py`, PV alarms clear with 1%-of-limit hysteresis), `spc.enabled`, scenario-level `comms` and `historians` (plugin name list; backends configured via env vars). Don't invent config keys; unknown keys are tolerated on read.

### Publishers

All constructed per run from the `comms` block by `build_publishers()` (guarded imports). Metric names are identical across encodings (`publishers/metrics.py` is the single source). OPC UA writes go through `CachedOpcuaNode` dead-band caching into a dirty set, flushed once per publish under a single address-space RLock acquisition. SparkplugB uses the vendored Tahu pb2 (`mqtt-spb-wrapper` was rejected: it hard-pins paho 1.6.1 against our paho≥2.0); DBIRTH declares name+alias+datatype, NDATA/DDATA are delta-only by alias, NCMD rebirth is handled, seq cycles 0–255.

### Environment variables

`SIMENGINE_CONFIG_PATH` (scenario file), `SIMENGINE_RECIPE_PATH` (recipes dir), `SIMENGINE_HISTORIAN_DIR` (csv), `INFLUXDB_URL/TOKEN/ORG/BUCKET`, `NEO4J_URI/USER/PASSWORD`. Tests route the loader at `tests/fixtures/line_models_test.yaml` via an autouse conftest fixture — tests that must see the shipped `config/scenarios.yaml` call `monkeypatch.delenv("SIMENGINE_CONFIG_PATH")`.

### AI interface

Knowledge graph (`engine/knowledge_graph.py`, stdlib-only, deterministic, built at run start, owned by run_manager) binds every metric to all four wire addresses. `api/tools.py` is the one 16-tool registry behind both the MCP server (FastMCP, `:8765/mcp`, streamable HTTP, control tools always on — treat the port like :8080) and the `/assistant` chat (Anthropic tool_runner, key in process memory only). See `docs/ai_interface.md`.

## Known deferred items

- Parent Telegraf generator + Grafana dashboards (target the parent address space; events reach InfluxDB directly via the historian backend).
- The `historian-csv` install-hint error path can't fire in this single-distribution repo (the package is always importable); hints apply to missing third-party deps (influx/neo4j).

`ProcessMonitor` keeps Welford running aggregates (`_mean`/`_m2`), not raw
samples — capability indices are O(1) in run length. Do not reintroduce an
unbounded sample list (it failed the memory-flatness acceptance run at
~95 MB/hour with just 4 monitors); `tests/test_spc_analytics.py::TestBoundedMemory`
guards this.

## Candidate feature: i3X interface (under consideration — do not build without sign-off)

**Status:** evaluated, high-alignment, deferred pending owner decision. The org is
looking to adopt i3X to some degree, so **if built, build the whole thing**
(read + write + subscriptions + conformance), not a partial read-only projection.

**What i3X is:** a CESMII (US DOE Smart Manufacturing institute) standard — a
REST+JSON API (with SSE streaming and poll-with-ack subscriptions) that presents
an industrial data source as a typed **object/relationship graph** with live
**Value-Quality-Timestamp** values. Spec lives at github.com/cesmii/i3X (use the
`1.0-Beta` branch — `IMPLEMENTATION_GUIDE.md` + `UNDERSTANDING_RELATIONSHIPS.md`
are the substance; the OpenAPI is at `api.i3x.dev/v1/openapi.json`). It has a
`conformance-tests/` suite to validate against. Note the spec is still
stabilizing — pin against a snapshot, don't track the moving branch.

**Why it fits simengine (the pieces are ~80–90% already here):** i3X's model is
almost exactly the KG + snapshot we already built for the AI interface.
Architecturally it is a *pull* REST+SSE API, so it's a new Flask blueprint
(`api/i3x.py`) reading the KG + snapshot + run_manager + historians — **not** a
`StatePublisher` push class, and **no engine changes**.

Concrete mapping (i3X ← simengine):
- object ← KG node; `elementId`←node id, `displayName`←name, `typeId`←node type,
  `parentId`←`CONTAINS` parent, `isComposition`←`HAS_PV` edge, `relationships`←edges
- `/objecttypes` ← KG node types; `/relationshiptypes` ← KG edge types
- `/objects/related` ← `KnowledgeGraph.neighbors()`
- `/objects/value` (VQT) ← `LineSnapshot` (PV/metric value + unit); quality =
  Good while RUNNING, GoodNoData when IDLE/no run
- `/objects/history` ← historian plugins (**only meaningful with `historian-influx`**
  — core keeps no value history by design; see the SPC memory note above)
- `/subscriptions/stream` (SSE) ← SSE already implemented for chat; run_manager
  already emits a fresh snapshot every step
- `namespaceUri` projection ← the KG already binds every metric to OPC UA /
  SparkplugB / MQTT / REST addresses; i3X is a fifth projection over the same
  registry (i3X explicitly supports `?projection=i3X` namespace URIs)

**Full-implementation scope (what "the whole thing" means here):**
- Read surface: `/info`, `/namespaces`, `/objecttypes`(+`/query`),
  `/relationshiptypes`(+`/query`), `/objects`(+`/list`), `/objects/related`,
  `/objects/value` (with `maxDepth` composition recursion), `/objects/history`
- Subscriptions: create/register/unregister/list/delete, `/stream` (SSE) and
  `/sync` (sequence-numbered poll-with-ack)
- Writes (`PUT /objects/{id}/value|history`): the hard part — simengine *computes*
  values, it doesn't accept them. For a full impl this means deciding what a write
  means (config/setpoint override applied at next step? a scenario edit? rejected
  as read-only with 501?). Resolve this before starting; it's the main design
  question, not the endpoints.
- Enable via the `comms` block (like the other protocols) + a `[i3x]` extra if any
  new dep is needed; validate against the CESMII `conformance-tests/` suite.
