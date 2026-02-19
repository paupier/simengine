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
# Exclude backup file: --exclude=src/opcua_server_backup_phase7.py
flake8 src/ tests/ --count --select=E9,F63,F7,F82 --show-source --statistics --exclude=src/opcua_server_backup_phase7.py
flake8 src/ tests/ --count --exit-zero --max-complexity=10 --max-line-length=127 --exclude=src/opcua_server_backup_phase7.py

# Run Flask web UI locally (no Docker needed)
python docker/webui/app.py

# Docker stack (Web UI + InfluxDB + Grafana)
docker compose -f docker/docker-compose.yml up --build -d
```

**pytest.ini** sets `pythonpath = src tests`, so imports resolve from `src/` and `tests/` automatically.

## Architecture

### Entry Point

`src/opcua_server.py` is the main entry point. It:
1. Parses CLI args (`--scenario`, `--seed`)
2. Loads config via `config_loader.py` from `config/line_models.yaml`
3. Creates Simantha objects (Source → Buffer → Machine → Buffer → ... → Sink)
4. Builds the OPC UA address space with per-machine/buffer/alarm nodes
5. Runs the simulation loop via extracted step functions, updating OPC UA variables each step

### Main Loop Architecture

The simulation loop in `main()` delegates to extracted functions for each concern:
- `read_opcua_controls()` — read pause/interarrival from OPC UA clients
- `update_part_counter()` — monotonic sink tracking
- `check_shift_rotation()` — shift boundary detection
- `collect_system_metrics()` — WIP, maintenance status
- `process_machine_step()` — per-machine state, metrics, defects, alarms, OEE, SPC
- `write_machine_opcua_vars()` — per-machine OPC UA variable writes
- `update_buffers()` — buffer levels and alarms
- `update_scrap_tracking()` — scrap sink levels and KPIs
- `calculate_line_level_oee()` — bottleneck OEE model
- `write_system_opcua_vars()` — system/line KPIs
- `update_shift_opcua_vars()` — shift metrics
- `record_historian_events()` — event collection and recording

### Machine Class Hierarchy (Mixin Pattern)

```
QualityRoutingMixin (src/quality_machine.py) — scrap/rework via output_addon_process()
  + simantha.Machine → QualityAwareMachine
  + AdvancedMachine  → QualityAdvancedMachine

simantha.Machine
  └── AdvancedMachine (src/advanced_machine.py) — failure modes, scipy distributions
```

Features are composed via mixins. Adding a new axis (e.g., EnergyMixin) requires only the mixin class plus one-line combinations, not a class explosion. Use `isinstance(obj, QualityRoutingMixin)` to check for quality routing capability.

### Key Modules

| Module | Purpose |
|--------|---------|
| `config_loader.py` | YAML validation, topology construction, failure mode validation, `target_ppm` support |
| `failure_modes.py` | `FailureModeManager`, `DistributionFactory` (Weibull, exponential, lognormal) |
| `spc_analytics.py` | X-bar/R control charts, Cp/Cpk capability, Western Electric rules |
| `shift_manager.py` | Shift rotation, per-shift metric reset |
| `event_historian.py` | `EventHistorian` ABC → `CSVHistorian`, `InfluxDBHistorian`, `CompositeHistorian` |
| `neo4j_historian.py` | `Neo4jHistorian` (optional graph DB backend) |
| `quality_machine.py` | `QualityRoutingMixin`, scrap/rework routing, `_redirect_to()` buffer bookkeeping |

### Flask Web UI (`docker/webui/`)

The web UI runs both locally and in Docker via environment variable defaults:

| Env Var | Default (local) | Docker Override |
|---------|-----------------|-----------------|
| `SIMANTHA_CONFIG_PATH` | `<project>/config/line_models.yaml` | `/app/config/line_models_runtime.yaml` |
| `SIMANTHA_SERVER_SCRIPT` | `<project>/src/opcua_server.py` | `/app/src/opcua_server.py` |
| `SIMANTHA_OPCUA_ENDPOINT` | `opc.tcp://localhost:4840/simantha/` | (same) |

Routes:
- `/` — Main dashboard with live KPIs, per-machine OEE/PPM/SPC, shift progress
- `/config` — Visual scenario editor with CRUD and YAML preview
- `/api/scenarios` — List scenarios
- `/api/scenario/<name>` — GET/PUT single scenario config
- `/api/scenario` — POST to create new scenario
- `/api/start`, `/api/stop`, `/api/control` — Simulation lifecycle
- `/api/status` — Live status with OPC UA values (OEE, PPM, SPC, shifts, scrap)
- `/api/logs` — Recent simulation log lines

### Test Infrastructure

Shared test factories live in `tests/factories.py`:
- `make_event()` — SimEvent with sensible defaults
- `make_part()` — Mock Part with quality routing attributes
- `make_machine_metrics()` — Machine metrics dict
- `make_quality_machine()` — QualityAwareMachine with mocked internals

### Configuration

`config/line_models.yaml` defines 16 scenarios (balanced, bottleneck, failure, SPC, shifts, historian, scrap, rework, full_feature, etc.). Each scenario specifies machines, buffers, optional maintainer, failure_modes, quality_routing, shifts, historian backends, and SPC config.

Per-machine options include:
- `cycle_time` — direct cycle time in seconds
- `target_ppm` — parts per minute target (derives `cycle_time = 60 / target_ppm`; takes precedence if both given)
- `spc.measurement_noise` — coefficient of variation for SPC measurement noise (default: 0.02)

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

### Sink.level_data memory leak (monkey-patched)
Simantha's `Sink.initialize()` does not reset `level_data`, so it grows quadratically across `system.simulate()` calls (K*(K+1)/2 entries after K steps), causing MemoryError after ~4000 steps. A monkey-patch in `opcua_server.py` resets `level_data = []` in `Sink.initialize()` to match the pattern used by Buffer and Machine.

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

### OEE uses Simantha's authoritative data, not time accumulators
OEE is calculated via `calculate_oee_from_sim()` using `machine.downtime` and `machine.parts_made` — Simantha's whole-run summaries. It is **not** derived from the per-step time accumulators (`processing_time`, `down_time`, etc.) which are noisy due to simulate() reinitialization. OEE recalculates every `OEE_BUCKET_INTERVAL` (600 seconds / 10 minutes) and holds constant between updates. The `oee_cached` dict in `machine_metrics` stores the last result.

### File paths — anchor to script location
```python
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
```

## OPC UA Address Space

OPC UA node names use `Machine{i}` (e.g., `Machine1`, `Machine2`). The address space tree:

```
Line1/
  Machine{i}/              State, PartCount, Utilisation, TargetPPM, ActualPPM
    OEE/                   Availability, Performance, Quality, OEE, GoodPartCount, DefectivePartCount
    Alarms/                MachineFailedActive, MaintenanceActive, QualityAlertActive
    SPC/Capability/        Cp, Cpk (if enable_spc)
    FailureModes/          ActiveFailureMode (if enable_advanced_failures)
    QualityRouting/        ScrapCount, ReworkCount (if quality_routing enabled)
  Buffer{i}/               Level, Capacity
  System/
    Controls/              cmdPauseLine (writable), setInterarrivalTime (writable)
    SimTime, Throughput, WIP
  LineKPIs/
    LineOEE/               Availability, Performance, Quality, OEE
    TotalScrap, ScrapRate
  Shift/CurrentShift/      CurrentShiftName, ShiftElapsedTime, ShiftDuration
```

Only two variables are writable by OPC UA clients:
- `cmdPauseLine` (bool) — global pause/resume
- `setInterarrivalTime` (float) — part arrival rate on the source

## Randomness and Reproducibility

The `--seed` CLI argument seeds both `random` (Python stdlib) and `numpy.random` (used by scipy distributions). This makes defect generation, SPC measurement noise, quality routing decisions, and MTTF/MTTR distributions reproducible. Simantha's internal RNG is not controllable.

## CI

GitHub Actions runs on Python 3.9, 3.10, 3.11 (3.12 dropped due to dependency compat). CI excludes `test_advanced_scenarios.py` and `test_opcua_integration.py` (long-running).
