# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Simantha-OPC UA is a manufacturing digital twin that wraps the [Simantha](https://github.com/usnistgov/simantha) discrete-event simulation library with an OPC UA server. It models serial production lines with machines, buffers, quality routing, SPC analytics, shift management, and event historians — all exposed via OPC UA for SCADA/MES integration.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run the OPC UA server (default: balanced_line scenario)
python src/opcua_server.py
python src/opcua_server.py --scenario full_feature_line --seed 42

# Run all tests (CI-equivalent, excludes slow integration tests)
pytest tests/ -v --ignore=tests/test_advanced_scenarios.py --ignore=tests/test_opcua_integration.py

# Run a single test file or test
pytest tests/test_config_validation.py -v
pytest tests/test_quality_routing.py::test_scrap_routing_basic -v

# Run with coverage
pytest tests/ --ignore=tests/test_advanced_scenarios.py --ignore=tests/test_opcua_integration.py --cov=src --cov-report=html

# Lint (CI uses two passes: errors-only then warnings)
flake8 src/ tests/ --count --select=E9,F63,F7,F82 --show-source --statistics
flake8 src/ tests/ --count --exit-zero --max-complexity=10 --max-line-length=127

# Docker stack (Web UI + InfluxDB + Grafana)
docker compose -f docker/docker-compose.yml up --build -d
```

**pytest.ini** sets `pythonpath = src`, so imports resolve from `src/` automatically.

## Architecture

### Entry Point

`src/opcua_server.py` (~1600 lines) is the main entry point. It:
1. Parses CLI args (`--scenario`, `--seed`)
2. Loads config via `config_loader.py` from `config/line_models.yaml`
3. Creates Simantha objects (Source → Buffer → Machine → Buffer → ... → Sink)
4. Builds the OPC UA address space with per-machine/buffer/alarm nodes
5. Runs the simulation loop, updating OPC UA variables each step

### Machine Inheritance Hierarchy

```
simantha.Machine
  └── AdvancedMachine (src/advanced_machine.py) — failure modes, scipy distributions
        ├── QualityAdvancedMachine (src/quality_machine.py) — scrap/rework routing
        └── (plain AdvancedMachine for lines without quality routing)

simantha.Machine
  └── QualityAwareMachine (src/quality_machine.py) — scrap/rework without advanced failures
```

Each subclass adds features via `output_addon_process(part)` hooks without modifying Simantha internals.

### Key Modules

| Module | Purpose |
|--------|---------|
| `config_loader.py` + `config_loader_phase10.py` | YAML validation, topology construction |
| `failure_modes.py` | `FailureModeManager`, `DistributionFactory` (Weibull, exponential, lognormal) |
| `spc_analytics.py` | X-bar/R control charts, Cp/Cpk capability, Western Electric rules |
| `shift_manager.py` | Shift rotation, per-shift metric reset |
| `event_historian.py` | `EventHistorian` ABC → `CSVHistorian`, `InfluxDBHistorian`, `CompositeHistorian` |
| `neo4j_historian.py` | `Neo4jHistorian` (optional graph DB backend) |
| `quality_machine.py` | Scrap sinks, rework routing, `_redirect_to()` buffer bookkeeping fix |

### Configuration

`config/line_models.yaml` defines 16 scenarios (balanced, bottleneck, failure, SPC, shifts, historian, scrap, rework, full_feature, etc.). Each scenario specifies machines, buffers, optional maintainer, failure_modes, quality_routing, shifts, historian backends, and SPC config.

### Event Historian Design

Events are logged only on **state transitions** (edge detection), not every simulation step. The `historian_state` dict used for edge detection is **separate** from `metrics["prev_state"]` — this is critical to avoid deduplication bugs. InfluxDB and Neo4j use lazy imports so they're optional dependencies.

## Critical Rules

### Never modify `machine.cycle_time` after simulation starts
Setting it dynamically causes "Failed event: time 0" errors. Set in constructor only.

### Simantha stepping pattern
```python
sim_time = 0.0
while True:
    if not paused:
        sim_time += sim_step  # ALWAYS increment before simulate()
        system.simulate(simulation_time=sim_time)  # First call at time=1.0
```
Never call `system.simulate(simulation_time=0)` or with time <= 0.

### Monotonic counter pattern for sink.level
`sink.level` can **decrease** during maintenance. Always track monotonically:
```python
if current_sink_level > prev_sink_level:
    total_parts_produced += (current_sink_level - prev_sink_level)
    prev_sink_level = current_sink_level
elif current_sink_level < prev_sink_level:
    prev_sink_level = current_sink_level  # Resync without losing count
```

### Scrap sinks are NOT in machine.downstream
Scrap sinks are stored as `_scrap_sink` attribute to avoid random routing by Simantha. Parts are diverted inside `output_addon_process()` using `_redirect_to()` which fixes buffer `reserved_vacancy` bookkeeping.

### State detection order (7 states)
```python
if pause_line: "PAUSED"
elif m.health == 1: "FAILED" / "UNDER_REPAIR"
elif m.blocked: "BLOCKED"
elif m.starved: "STARVED"
elif m.has_part: "PROCESSING"
else: "IDLE"
```

### File paths — anchor to script location
```python
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
```

## OPC UA Writable Controls

Only two variables are writable by OPC UA clients:
- `PauseLine` (bool) — global pause/resume
- `InterarrivalTime` (float) — part arrival rate on the source

## CI

GitHub Actions runs on Python 3.9, 3.10, 3.11 (3.12 dropped due to dependency compat). CI excludes `test_advanced_scenarios.py` and `test_opcua_integration.py` (long-running).
