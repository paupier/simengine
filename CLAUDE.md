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
python src/opcua_server.py --scenario warm_up_line --trace  # with warm-up and event tracing

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
1. Parses CLI args (`--scenario`, `--seed`, `--trace`)
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

simantha.Maintainer
  └── PriorityMaintainer (src/priority_maintainer.py) — FIFO/SPT/priority/bottleneck scheduling
```

Features are composed via mixins. Adding a new axis (e.g., EnergyMixin) requires only the mixin class plus one-line combinations, not a class explosion. Use `isinstance(obj, QualityRoutingMixin)` to check for quality routing capability. `PriorityMaintainer` extends `Maintainer` with `choose_maintenance_action()` override supporting configurable repair scheduling.

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
| `priority_maintainer.py` | `PriorityMaintainer` with FIFO, SPT, priority, and bottleneck-first scheduling |

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
- `/reports` — Post-run analysis (OEE charts, throughput, anomaly detection, run comparison)
- `/validation` — Data pipeline health check (OPC UA → Telegraf → InfluxDB)
- `/api/scenarios` — List scenarios
- `/api/scenario/<name>` — GET/PUT single scenario config
- `/api/scenario` — POST to create new scenario
- `/api/start`, `/api/stop`, `/api/control` — Simulation lifecycle
- `/api/status` — Live status with OPC UA values (OEE, PPM, SPC, shifts, scrap)
- `/api/logs` — Recent simulation log lines
- `/api/reports/analyze`, `/api/reports/runs` — Report generation and run history
- `/api/validation/run`, `/api/validation/influxdb/status` — Pipeline validation
- `/api/historian/files`, `/api/historian/download` — CSV historian file access

### Test Infrastructure

Shared test factories live in `tests/factories.py`:
- `make_event()` — SimEvent with sensible defaults
- `make_part()` — Mock Part with quality routing attributes
- `make_machine_metrics()` — Machine metrics dict
- `make_quality_machine()` — QualityAwareMachine with mocked internals

### Configuration

`config/line_models.yaml` defines 20 scenarios (balanced, bottleneck, failure, SPC, shifts, historian, scrap, rework, full_feature, warm_up, priority_maintenance, multi_state_degradation, full_feature_8_machine, etc.). Each scenario specifies machines, buffers, optional maintainer, failure_modes, quality_routing, shifts, historian backends, and SPC config.

Per-machine options include:
- `cycle_time` — direct cycle time in seconds
- `target_ppm` — parts per minute target (derives `cycle_time = 60 / target_ppm`; takes precedence if both given)
- `spc.measurement_noise` — coefficient of variation for SPC measurement noise (default: 0.02)
- `health_states` — multi-state degradation config: `h_max` (number of failed state), `p_degrade` (per-step probability), `cbm_threshold`

Per-scenario options include:
- `warm_up_time` — seconds of warm-up before data collection starts (default: 0)
- `maintainer.strategy` — repair scheduling: `fifo` (default), `spt`, `priority`, `bottleneck`
- `maintainer.machine_priorities` — dict of machine name → priority number (for `priority` strategy)
- `enterprise`, `site`, `area`, `line_name` — ISA-95 hierarchy naming (all optional with defaults)

### Event Historian Design

Events are logged only on **state transitions** (edge detection), not every simulation step. The `historian_state` dict used for edge detection is **separate** from `metrics["prev_state"]` — this is critical to avoid deduplication bugs. InfluxDB and Neo4j use lazy imports so they're optional dependencies.

## Critical Rules

### Never modify `machine.cycle_time` after simulation starts
Setting it dynamically causes "Failed event: time 0" errors. Set in constructor only.

### Simantha stepping pattern
```python
sim_time = 0.0
warm_up_time = int(config.get("warm_up_time", 0))
while True:
    if not paused:
        sim_time += sim_step  # ALWAYS increment before simulate()
        system.simulate(warm_up_time=warm_up_time, simulation_time=sim_time)
```
Never call `system.simulate(simulation_time=0)` or with time <= 0. The `warm_up_time` parameter (from YAML config) causes Simantha to skip data collection during the warm-up phase, producing more accurate steady-state metrics.

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

### State detection order (8 states)
```python
failed_health = getattr(machine, "failed_health", 1)
if pause_line: "PAUSED"
elif health_state >= failed_health: "FAILED" / "UNDER_REPAIR"
elif m.blocked: "BLOCKED"
elif m.starved: "STARVED"
elif health_state > 0: "DEGRADED"
elif m.has_part: "PROCESSING"
else: "IDLE"
```
With multi-state degradation, `failed_health = len(degradation_matrix) - 1`. The DEGRADED state indicates the machine is operational but has begun degrading (health > 0 but not yet failed).

### OEE uses Simantha's authoritative data, not time accumulators
OEE is calculated via `calculate_oee_from_sim()` using `machine.downtime` and `machine.parts_made` — Simantha's whole-run summaries. It is **not** derived from the per-step time accumulators (`processing_time`, `down_time`, etc.) which are noisy due to simulate() reinitialization. OEE recalculates every `OEE_BUCKET_INTERVAL` (600 seconds / 10 minutes) and holds constant between updates. The `oee_cached` dict in `machine_metrics` stores the last result.

### File paths — anchor to script location
```python
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
```

## OPC UA Address Space (ISA-95/ISO 23247 Aligned)

The address space follows ISA-95/IEC 62264 hierarchy with ISO 23247 digital twin identification. Hierarchy names are configurable via YAML config keys (`enterprise`, `site`, `area`, `line_name`).

```
Enterprise (WeylandIndustries)/
  Site (LV426_Colony)/
    Area (AtmosphereProcessor01)/
      {line_name}_Equipment/
        Identification/           EquipmentID, EquipmentClass, Description
        OperationsState/          SimTime, LineState, LineMode
          Controls/               CmdPauseLine (writable), SetInterarrivalTime (writable)
        OperationsPerformance/    Throughput, TotalWIP, TotalScrap, ScrapRate
        OEE/                      Availability, Performance, Quality, OEE, GoodPartCount, DefectivePartCount
        Resources/
          M{i}_Equipment/
            Identification/       EquipmentID, EquipmentClass
            OperationsState/      State, HealthState, HealthPercent
            OperationsPerformance/ PartCount, Utilisation, TargetPPM, ActualPPM, *Time
            OEE/                  Availability, Performance, Quality, OEE, ...
            Alarms/               MachineFailureActive, MaintenanceActive, QualityAlertActive
            FailureModes/         (if enable_advanced_failures)
            SPC/                  (if enable_spc)
            QualityRouting/       (if quality_routing enabled)
          M{i}_Asset/
            Identification/       PhysicalAssetID, AssetClass, Vendor, Model, SerialNumber
          B{i}_StorageUnit/       CurrentLevel, Capacity, Alarms/
          {ScrapName}_StorageUnit/ CurrentLevel
        SupportFunctions/
          Maintenance/            MaintenanceActive, QueueLength, TotalRepairs
          ShiftManagement/        (if shifts configured)
        EventLog/                 TotalEventsGenerated
      {line_name}_Asset/
        Identification/           PhysicalAssetID, AssetClass, Description
```

Only two variables are writable by OPC UA clients:
- `CmdPauseLine` (bool) — global pause/resume (under OperationsState/Controls)
- `SetInterarrivalTime` (float) — part arrival rate on the source (under OperationsState/Controls)

The `opcua_vars` dict serves as an abstraction layer — internal keys (e.g., `opcua_vars["machines"]["M1"]["state"]`) are unchanged from the main loop's perspective. Only the OPC UA NodeId strings changed.

## Telegraf Config Generation

`docker/telegraf/generate_telegraf_conf.py` dynamically generates `telegraf.conf` from scenario config. It mirrors the same conditionals used in `build_opcua_server()` to create matching Telegraf OPC UA input nodes. Field names use abbreviated prefixes (`M{i}_`, `B{i}_`, `Scrap{i}_`, `Shift_`) for InfluxDB. Run standalone:

```bash
python docker/telegraf/generate_telegraf_conf.py --config config/line_models.yaml --scenario full_feature_line --output docker/telegraf/telegraf.conf
```

## Randomness and Reproducibility

The `--seed` CLI argument seeds both `random` (Python stdlib) and `numpy.random` (used by scipy distributions). This makes defect generation, SPC measurement noise, quality routing decisions, and MTTF/MTTR distributions reproducible. Simantha's internal RNG is not controllable.

## CI

GitHub Actions runs on Python 3.9, 3.10, 3.11 (3.12 dropped due to dependency compat). CI excludes `test_advanced_scenarios.py` and `test_opcua_integration.py` (long-running).
