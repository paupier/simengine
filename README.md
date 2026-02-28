# Simantha OPC UA Integration

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: Public Domain](https://img.shields.io/badge/License-Public%20Domain-green.svg)](https://github.com/usnistgov/simantha/blob/master/LICENSE)
[![OPC UA](https://img.shields.io/badge/OPC%20UA-Compliant-orange.svg)](https://opcfoundation.org/)

A real-time **digital twin** of a manufacturing production line using [Simantha](https://github.com/usnistgov/simantha) discrete-event simulation exposed via OPC UA for monitoring and control.

---

## 📋 Project Status

**Status:** Feature-complete manufacturing digital twin
**Last Updated:** 2026-02-28

### Key Capabilities

| Area | Features |
|------|----------|
| **Simulation** | N-machine serial lines (2-10+), config-driven topologies, 20 built-in scenarios, run recipes |
| **OPC UA** | ISA-95/ISO 23247 aligned address space, bidirectional control (pause, arrival rate) |
| **Reliability** | Multi-state health degradation, advanced failure modes (Weibull, exponential, lognormal), competing risks |
| **Maintenance** | Corrective/preventive/predictive strategies, priority maintainer (FIFO, SPT, priority, bottleneck) |
| **Quality** | Health-correlated defects, scrap/rework routing, SPC (X-bar/R, Cp/Cpk, Western Electric rules) |
| **Production** | OEE (per-machine & line-level), shift management, warm-up periods, target PPM tracking |
| **Data** | Event historians (CSV/InfluxDB/Neo4j), Grafana dashboards, dynamic Telegraf config generation |
| **Web UI** | Flask dashboard with live KPIs, config editor, reports, and pipeline validation |

---

## 🎯 What This Project Does

This project creates a **realistic manufacturing digital twin** that:

- **Simulates** configurable production lines (2-10+ machines in serial topology)
- **Exposes** real-time KPIs via industry-standard OPC UA protocol
- **Models** realistic variability through health degradation, advanced failures, and quality defects
- **Routes** defective parts to scrap sinks or attempts virtual rework before scrapping
- **Tracks** shift-based production with automatic rotation and per-shift OEE
- **Logs** events to CSV, InfluxDB, and Neo4j with Grafana visualization
- **Responds** to external control inputs (pause/resume, arrival rate adjustment)
- **Schedules** multi-segment production recipes with stochastic changeover analysis
- **Demonstrates** buffer dynamics, bottlenecks, failure impacts, and SPC analytics

### Real-World Behavior Modeled

- ✅ **Health Degradation** - Machines degrade over time with configurable failure rates
- ✅ **Advanced Failure Modes** - Weibull, exponential, lognormal distributions with competing risks
- ✅ **Maintenance Strategies** - Corrective, preventive, and predictive maintenance
- ✅ **Buffer Dynamics** - WIP accumulates/drains based on machine states
- ✅ **Quality Defects** - Health-correlated defect rates with individual part tracking
- ✅ **OEE Calculation** - Availability x Performance x Quality per machine and line-level, updated every simulation step using shift-relative counters
- ✅ **SPC Analytics** - X-bar/R control charts, Cp/Cpk capability, Western Electric rules
- ✅ **Shift Management** - Configurable shift rotation with per-shift metrics and OEE
- ✅ **Alarms & Events** - Machine failure, quality, maintenance, and buffer alerts
- ✅ **Enhanced State Detection** - 8 states: IDLE, PROCESSING, BLOCKED, STARVED, PAUSED, FAILED, UNDER_REPAIR, DEGRADED
- ✅ **Time Tracking** - Per-step time accumulation by machine state (see [How KPIs Are Derived](#how-kpis-are-derived))
- ✅ **Event Historian** - CSV, InfluxDB 2.x, Neo4j backends with edge-detection logging
- ✅ **Grafana Dashboards** - Manufacturing overview, state timeline, alarm log, shift comparison
- ✅ **Scrap & Rework Routing** - Defective parts routed to scrap sinks, virtual rework at machine
- ✅ **Quality Routing** - Per-part defect decisions inside simulation with health correlation

---

## 🚀 Quick Start

### Prerequisites

- **Python 3.9+** with pip (tested on 3.9, 3.10, 3.11)
- **OPC UA Client** for testing (e.g., [UA Expert](https://www.unified-automation.com/products/development-tools/uaexpert.html))

### Installation

```bash
# Clone the repository
git clone https://github.com/YOUR-USERNAME/simantha-opcua.git
cd simantha-opcua

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### Run the OPC UA Server

**Default (2-machine balanced line):**
```bash
python src/opcua_server.py
```

**Choose a scenario:**
```bash
# 3-machine line with degradation
python src/opcua_server.py --scenario extended_line

# Quality monitoring with SPC
python src/opcua_server.py --scenario spc_quality_line

# 3-shift production tracking
python src/opcua_server.py --scenario shift_line

# Scrap & rework routing with defect sinks
python src/opcua_server.py --scenario scrap_line

# Warm-up period (skip transient phase for steady-state metrics)
python src/opcua_server.py --scenario warm_up_line

# Priority maintenance with bottleneck-first repair scheduling
python src/opcua_server.py --scenario priority_maintenance_line

# ALL features combined (failures, SPC, shifts, historian, scrap/rework)
# --seed seeds both Python random and numpy for full reproducibility
python src/opcua_server.py --scenario full_feature_line --seed 42

# 8-machine max-scale scenario
python src/opcua_server.py --scenario full_feature_8_machine_line --seed 42

# Enable DES event tracing (outputs environment_trace.pkl)
python src/opcua_server.py --scenario failure_line --trace
```

**Run a recipe (multi-segment production schedule):**
```bash
# 3-segment recipe: Product A → changeover → Product B → changeover → Product A
python src/opcua_server.py --recipe monday_schedule --seed 42

# Quick recipe for testing (2 segments with 10s changeover)
python src/opcua_server.py --recipe quick_test --seed 1
```

Recipes define ordered production segments with changeover periods, enabling planned-vs-actual changeover analysis and multi-product scheduling. See [Run Recipes](#-run-recipes) below.

**Expected output:**
```
[OK] Configuration validated: 2 machines, 1 buffers
Loading scenario: balanced_line
OPC UA server started at opc.tcp://localhost:4840/simantha/
Scenario: balanced_line (2 machines, 1 buffers)
Press Ctrl+C to stop.
```

### Web UI

A Flask-based web dashboard is available as an alternative to OPC UA clients:

**Local mode (no Docker):**
```bash
python docker/webui/app.py
# Open http://localhost:8080
```

Features: scenario selection, live dashboard (per-machine OEE/PPM/SPC/shifts/scrap), config editor at `/config`, post-run reports at `/reports`, and pipeline validation at `/validation`.

**Docker mode (full stack):**
```bash
docker compose -f docker/docker-compose.yml up --build -d
```

Includes the Web UI, InfluxDB for time-series storage, and Grafana for dashboards.

### Connect with UA Expert

1. Open UA Expert
2. Add Server: `opc.tcp://localhost:4840/simantha/`
3. Connect and browse to `Objects → Line1`
4. Drag variables to Data Access View to monitor live values

**What to watch:**

The address space follows an ISA-95/ISO 23247 hierarchy. Browse to:
`Objects → WeylandIndustries → LV426_Colony → AtmosphereProcessor01 → Nostromo_BioProductPakaging_Equipment`

Under the Equipment node:
- `Resources/Machine1/OperationsState/HealthPercent` drops from 100 → 0 when M1 fails
- `SupportFunctions/Maintenance/MaintenanceActive` becomes True during repairs
- `Resources/Buffer1/Level` drains when M1 is down
- `OperationsPerformance/Throughput` pauses during failures, resumes after repair
- `SupportFunctions/ShiftManagement/CurrentShiftName` changes at shift boundaries
- `SupportFunctions/ShiftManagement/ShiftTimeRemaining` counts down to next shift change

> **Note:** The enterprise/site/area/line names are configurable in your scenario YAML. The defaults above are playful placeholders.

---

## 🏗️ Architecture

```
┌─────────────────┐     ┌──────────────┐
│  OPC UA Client  │     │   Flask UI   │  http://localhost:8080
│ (UA Expert, MES)│     │ (Dashboard,  │  /config, /reports, /validation
└────────┬────────┘     │  Config, etc)│
         │ OPC UA       └──────┬───────┘
         │ Protocol            │ OPC UA Client API
         ▼                     ▼
┌──────────────────────────────────────┐
│         OPC UA Server (ISA-95)       │  (python-opcua)
│  Enterprise/Site/Area/Line hierarchy │
│  Writable: cmdPauseLine,             │
│            setInterarrivalTime       │
└────────────────┬─────────────────────┘
                 │ Python API
                 ▼
┌──────────────────────────────────────┐
│         Simantha Simulation          │  Discrete-Event Simulation
│  Source → M1 → B1 → M2 → ... → Sink│  N-machine serial topology
│  Health degradation, failures, SPC   │  Quality routing, shifts
│  Maintenance, run recipes            │  Multi-segment changeovers
└──────────────┬───────────────────────┘
               │ Events
               ▼
┌──────────────────────────────────────┐
│  Event Historian (CSV/InfluxDB/Neo4j)│
│  Telegraf → InfluxDB → Grafana       │  (Docker stack)
└──────────────────────────────────────┘
```

---

## 📊 OPC UA Address Space (ISA-95/ISO 23247)

The address space follows the ISA-95 (IEC 62264) equipment hierarchy. Enterprise/Site/Area/Line names are configurable in your scenario YAML.

### Hierarchy Overview

```
Objects/
  └─ {Enterprise}/                          # e.g. WeylandIndustries
      └─ {Site}/                            # e.g. LV426_Colony
          └─ {Area}/                        # e.g. AtmosphereProcessor01
              ├─ {Line}_Equipment/          # Equipment model (live process data)
              │   ├─ Identification/        # Line name, description, RunID
              │   ├─ OperationsState/       # SimTime, LineState, controls
              │   │   └─ Recipe/            # Recipe tracking (segment, changeover)
              │   ├─ OperationsPerformance/ # Throughput, WIP, scrap KPIs, line OEE
              │   ├─ Resources/
              │   │   ├─ Machine1/ ... MachineN/    # Per-machine nodes
              │   │   ├─ Buffer1/ ... BufferN/      # Per-buffer nodes
              │   │   └─ ScrapBin1/ ... ScrapBinN/  # Scrap sinks (if configured)
              │   └─ SupportFunctions/
              │       ├─ Maintenance/               # Maintainer status
              │       └─ ShiftManagement/           # Shift tracking (if configured)
              │
              └─ {Line}_Asset/              # Physical asset model (static metadata)
                  ├─ Identification/        # Model, manufacturer, serial
                  ├─ M1_Asset/ ... MN_Asset/# Per-machine physical specs
                  └─ MaintenanceLog/        # Total repairs
```

### Per-Machine Node Structure

Each `MachineN/` under Resources contains:

```
MachineN/
  ├─ Identification/          Name, CycleTime, TargetPPM
  ├─ OperationsState/         State, HealthState, HealthPercent, BlockedTime, StarvedTime,
  │                           DownTime, ProcessingTime, IdleTime
  ├─ OperationsPerformance/   PartCount, Utilisation, ActualPPM
  ├─ OEE/                     Availability, Performance, Quality, OEE,
  │                           GoodPartCount, DefectivePartCount, TheoreticalOutput
  ├─ Alarms/                  ActiveAlarmCount, MachineFailedActive, MaintenanceActive, QualityAlertActive
  ├─ FailureModes/            ActiveFailureMode, {Mode}FailureCount/TotalDowntime/MTBF/MTTR  (if advanced failures)
  ├─ MaintenanceStrategy/     StrategyType, NextPMScheduled, PMCount, CMCount               (if advanced failures)
  ├─ QualityRouting/          ScrapCount, ReworkCount, ReworkSuccessCount/Rate, GoodCount    (if quality routing)
  └─ SPC/                     XBarChart/, RChart/, Capability/, Status/                     (if SPC)
```

**Machine States (8):** IDLE, PROCESSING, BLOCKED, STARVED, PAUSED, FAILED, UNDER_REPAIR, DEGRADED

### Writable Variables (Control)

Only two variables accept writes from OPC UA clients:
- `OperationsState/Controls/cmdPauseLine` (Boolean) - Pause/resume entire line
- `OperationsState/Controls/setInterarrivalTime` (Double) - Part arrival delay (0 = fast as possible)

All other variables are read-only.

---

## 🧪 Testing & Scenarios

### Available Scenarios (20 total)

| Scenario | Machines | Features | Complexity |
|----------|----------|----------|------------|
| `balanced_line` (default) | 2 | Basic balanced line | Beginner |
| `bottleneck_line` | 2 | M1 bottleneck (2s cycle) | Beginner |
| `failure_line` | 2 | M1 degradation + maintenance | Intermediate |
| `extended_line` | 3 | 3-machine serial line | Intermediate |
| `long_line` | 4 | 4-machine scalability test | Intermediate |
| `quality_line` | 2 | Health-correlated defects | Intermediate |
| `advanced_failure_line` | 2 | Weibull/exponential failures | Advanced |
| `spc_quality_line` | 2 | SPC control charts + capability | Advanced |
| `advanced_spc_line` | 2 | Advanced failures + SPC | Expert |
| `shift_line` | 2 | 3-shift rotation tracking | Beginner |
| `advanced_shift_line` | 2 | Shifts + failures + SPC | Expert |
| `historian_line` | 2 | CSV event logging + failures + shifts | Intermediate |
| `scrap_line` | 2 | Scrap sinks + health-correlated routing | Intermediate |
| `rework_line` | 2 | Virtual rework before scrapping | Intermediate |
| `full_feature_line` | 2 | **All features combined** (failures, SPC, shifts, historian, scrap/rework) | Expert |
| `full_feature_8_machine_line` | 8 | Max-scale: all features on 8 machines | Expert |
| `warm_up_line` | 2 | Warm-up period for steady-state metrics | Intermediate |
| `priority_maintenance_line` | 3 | Priority maintainer with bottleneck-first strategy | Advanced |
| `priority_user_line` | 3 | Priority maintainer with user-defined priorities | Advanced |
| `multi_state_degradation_line` | 2 | Multi-state health degradation (5 states) | Advanced |

### Run Tests

```bash
# All tests (excludes slow integration tests)
pytest tests/ -v --ignore=tests/test_advanced_scenarios.py --ignore=tests/test_opcua_integration.py

# Specific test suites
pytest tests/test_new_features.py -v          # Warm-up, degradation, MTTF scaling (57 tests)
pytest tests/test_config_validation.py -v     # Config validation (48 tests)
pytest tests/test_telegraf_generator.py -v    # Telegraf config gen (49 tests)
pytest tests/test_event_historian.py -v       # Event historian (38 tests)
pytest tests/test_quality_routing.py -v       # Scrap, rework, warm-up guard (37 tests)
pytest tests/test_report_engine.py -v         # Report engine (36 tests)
pytest tests/test_failure_modes.py -v         # Failure modes (29 tests)
pytest tests/test_spc_analytics.py -v         # SPC (23 tests)
pytest tests/test_recipe_runner.py -v          # Recipe runner (76 tests)
pytest tests/test_neo4j_historian.py -v       # Neo4j historian (23 tests)
pytest tests/test_opcua_integration.py -v     # OPC UA integration (long-running)
```

### Verify Real-Time OPC UA Server

1. **Start server:** `python src/opcua_server.py --scenario failure_line`
2. **Connect UA Expert** to `opc.tcp://localhost:4840/simantha/`
3. **Test controls:**
   - Set `cmdPauseLine = True` → Simulation freezes
   - Set `setInterarrivalTime = 5.0` → Parts arrive every 5 seconds (slower)
4. **Observe failures:**
   - Watch `Machine1/HealthPercent` drop to 0 when M1 fails
   - See `Maintenance/MaintenanceActive = True` during repair
   - Buffer drains while M1 is down

---

## 🔬 Key Technical Lessons

### Critical: DO NOT Modify `machine.cycle_time` at Runtime

**Issue:** Setting `machine.cycle_time` after simulation starts causes "Failed event: time 0" errors.

**Root Cause:** Simantha reschedules events when cycle_time changes, creating invalid time-0 events.

**Solution:** Set cycle_time only in Machine constructor. Use **health degradation** for runtime variability instead.

### Realistic Manufacturing Variability

Real machines don't have their "ideal" cycle time change dynamically. Instead, **effective throughput** varies due to:

- ✅ Health degradation (wear, fouling, calibration drift)
- ✅ Unplanned downtime (failures, jams)
- ✅ Quality issues (rework, scrap)
- ✅ Speed losses (running below design speed)

This naturally creates bottlenecks, buffer utilization, and WIP fluctuations.

### Safe Runtime Modifications

✅ **CAN modify:**
- `source.interarrival_time` - Arrival rate control (works safely)

❌ **CANNOT modify:**
- `machine.cycle_time` - Causes time-0 errors
- Routing after simulation starts - Breaks event queue

### Golden Stepping Pattern

```python
sim_time = 0.0
warm_up_time = int(config.get("warm_up_time", 0))
while True:
    # Read controls, modify source.interarrival_time if needed
    if not paused:
        sim_time += sim_step  # ALWAYS increment before simulate()
        system.simulate(warm_up_time=warm_up_time, simulation_time=sim_time)
```

**Never call `system.simulate(simulation_time=0)` or with time ≤ 0.** The `warm_up_time` parameter causes Simantha to skip data collection during the transient phase, producing more accurate steady-state metrics.

### Monotonic Counter Pattern

**Issue:** `sink.level` can decrease during maintenance events, causing part counts to jump around.

**Solution:** Implement manual counter that only increases:

```python
if current_sink_level > prev_sink_level:
    delta_parts = current_sink_level - prev_sink_level
    total_parts_produced += delta_parts  # Only increases!
```

### How KPIs Are Derived

Understanding where each metric comes from is critical for interpreting OPC UA values.

**Time Accumulators (per machine)**

Each simulation step, the main loop calls `accumulate_time(metrics, prev_state, sim_step)` which adds `sim_step` (1 second) to the bucket matching the machine's **previous** state:

| OPC UA Variable | Accumulator Key | Incremented When Previous State Is |
|-----------------|-----------------|-------------------------------------|
| `ProcessingTime` | `processing_time` | PROCESSING or DEGRADED |
| `BlockedTime` | `blocked_time` | BLOCKED |
| `StarvedTime` | `starved_time` | STARVED |
| `DownTime` | `down_time` | FAILED or UNDER_REPAIR |
| `IdleTime` | `idle_time` | IDLE or PAUSED |

These accumulators are local to the main loop (not from Simantha internals). They naturally **exclude warm-up time** because the loop only runs after warm-up completes. `Utilisation = ProcessingTime / (ProcessingTime + BlockedTime + StarvedTime + DownTime + IdleTime)`.

**OEE (per machine, every step)**

OEE uses **shift-relative deltas** so it resets at shift boundaries:

| Component | Formula | Data Source |
|-----------|---------|-------------|
| **Availability** | `(shift_elapsed - shift_downtime) / shift_elapsed` | `shift_downtime` = `metrics["down_time"]` delta since shift start (our accumulator, excludes warm-up) |
| **Performance** | `shift_parts / theoretical_max` | `shift_parts` = `machine.parts_made` delta (Simantha's authoritative counter, post-warm-up) |
| **Quality** | `good_parts / (good_parts + defective_parts)` | For quality-routing machines: `_good_count`, `_scrap_count`, `_defective_count` (post-warm-up only). For others: statistical defect counters in metrics. |
| **OEE** | `A x P x Q` | Capped at [0, 1] per component |

**Health and Degradation**

| OPC UA Variable | Source | Range |
|-----------------|--------|-------|
| `HealthState` | `machine.health` (Simantha Markov chain) | 0 = healthy, `failed_health` = failed |
| `HealthPercent` | `100 * (1 - health / failed_health)` | 100% = healthy, 0% = failed |
| `failed_health` | Standard: 1. Multi-state: `h_max` from config (e.g., 5 for 6-state degradation) | Integer |

With multi-state degradation (`health_states` config), the machine transitions through intermediate health states (0 &rarr; 1 &rarr; 2 &rarr; ... &rarr; h_max) before failing. States between 0 and `failed_health` are reported as DEGRADED.

**MTTF Scaling:** When advanced failure modes combine with multi-state degradation, the sampled MTTF is divided by `failed_health` so each degradation step takes `MTTF / failed_health` time. Total expected time to failure equals the configured MTTF.

**Quality Counters (with warm-up)**

Quality routing counters (`_good_count`, `_scrap_count`, `_defective_count`) only increment after `env.now > warm_up_time`, matching Simantha's `parts_made` behavior. This ensures `Quality = good / (good + defective)` produces correct values (not inflated by warm-up parts). Scrap/rework **routing** still happens during warm-up for realistic simulation.

**Throughput**

`sink.level` after each `simulate()` call is the authoritative total parts produced (post-warm-up). The main loop tracks this monotonically to handle edge cases where `sink.level` can temporarily decrease during maintenance events.

---

## 📁 Repository Structure

```
simantha-opcua/
├─ src/
│   ├─ opcua_server.py            # Main entry point: OPC UA server + simulation loop
│   ├─ config_loader.py           # YAML configuration loader + validation
│   ├─ advanced_machine.py        # AdvancedMachine class (failure mode integration)
│   ├─ quality_machine.py         # QualityRoutingMixin + scrap/rework routing
│   ├─ priority_maintainer.py     # PriorityMaintainer (FIFO/SPT/priority/bottleneck)
│   ├─ failure_modes.py           # Statistical failure distributions (Weibull, etc.)
│   ├─ spc_analytics.py           # SPC control charts & capability analysis
│   ├─ shift_manager.py           # Shift tracking & rotation
│   ├─ event_historian.py         # CSV/InfluxDB event historian
│   ├─ neo4j_historian.py         # Neo4j graph DB historian
│   ├─ recipe_runner.py           # Multi-segment recipe orchestration & changeovers
│   └─ simantha_baseline.py       # Standalone baseline scenarios (batch mode)
│
├─ config/
│   ├─ line_models.yaml           # Scenario definitions (20 scenarios)
│   └─ recipes/                   # Recipe YAML files (multi-segment schedules)
│       ├─ monday_schedule.yaml   # 3-segment: Product A → B → A with changeovers
│       ├─ single_product.yaml    # 1-segment batch
│       └─ quick_test.yaml        # 2-segment short recipe for testing
│
├─ tests/                          # 511 tests (excluding integration)
│   ├─ factories.py               # Shared test factories (make_event, make_part, etc.)
│   ├─ test_new_features.py       # Warm-up, priority maintainer, degradation, MTTF scaling (57 tests)
│   ├─ test_config_validation.py  # Configuration validation (48 tests)
│   ├─ test_telegraf_generator.py # Dynamic Telegraf config generation (49 tests)
│   ├─ test_webui.py              # Flask web UI tests (44 tests)
│   ├─ test_event_historian.py    # Event historian tests (38 tests)
│   ├─ test_topology.py           # N-machine topology tests (38 tests)
│   ├─ test_quality_routing.py    # Scrap & rework routing + warm-up guard (37 tests)
│   ├─ test_report_engine.py      # Report engine tests (36 tests)
│   ├─ test_failure_modes.py      # Failure mode unit tests (29 tests)
│   ├─ test_spc_analytics.py      # SPC analytics (23 tests)
│   ├─ test_neo4j_historian.py    # Neo4j historian (23 tests)
│   ├─ test_recipe_runner.py       # Recipe loading, validation, changeover, overrides (76 tests)
│   ├─ test_distribution_validation.py  # Statistical distribution tests (12 tests)
│   └─ ...                        # Integration, scenario, advanced isolation tests
│
├─ docker/
│   ├─ webui/
│   │   ├─ app.py                 # Flask web dashboard (local + Docker)
│   │   └─ templates/             # HTML: dashboard, config editor, reports, validation
│   ├─ telegraf/
│   │   ├─ generate_telegraf_conf.py  # Dynamic Telegraf config from scenario YAML
│   │   └─ telegraf.conf              # Generated/fallback Telegraf config
│   ├─ docker-compose.yml         # Full stack: Web UI + InfluxDB + Telegraf + Grafana
│   └─ entrypoint.sh              # Container startup (generates Telegraf config)
│
├─ tools/
│   ├─ report_engine.py           # Post-run analysis: OEE, throughput, anomalies
│   └─ analyze_historian.py       # InfluxDB/Telegraf pipeline validation
│
├─ grafana/
│   ├─ dashboards/                # Grafana dashboard JSON templates
│   └─ README.md                  # InfluxDB + Grafana setup guide
│
├─ docs/
│   ├─ user_manual.md             # Comprehensive user manual
│   ├─ spc_analytics.md           # SPC analytics reference
│   └─ address_space.md           # OPC UA address space reference
│
├─ requirements.txt               # Python dependencies
├─ CLAUDE.md                      # Developer guidance for AI assistants
└─ README.md
```

---

## 🐛 Troubleshooting

### "Failed event: time 0, location M1, action get_part"

**Cause:** Modifying `machine.cycle_time` after simulation started, or calling `simulate(0)`.

**Fix:** Remove all runtime `cycle_time` modifications. Use health degradation instead.

### Part counts jumping around (e.g., 144 → 122 → 150)

**Cause:** `sink.level` decreases during maintenance events.

**Fix:** Implemented monotonic counter (already fixed in current version).

### Simulation freezes/doesn't advance

**Cause:** `cmdPauseLine = True` in OPC UA, or time not incrementing in loop.

**Fix:** Set `cmdPauseLine = False` via OPC UA client, or check loop logic.

### MemoryError during long simulation runs

**Cause:** Simantha's `Sink.initialize()` does not reset `level_data` between `system.simulate()` calls. Since each call reinitializes and runs from time 0 to N, the list grows quadratically (K*(K+1)/2 entries after K steps), exhausting memory after ~4000 steps.

**Fix:** Already patched in the current version. A monkey-patch in `opcua_server.py` resets `Sink.level_data` during initialization, matching the pattern used by Buffer and Machine.

---

## 🍳 Run Recipes

Recipes define multi-segment production schedules with stochastic changeovers, enabling planned-vs-actual changeover analysis and multi-product scheduling.

### Recipe YAML Format

Store recipes in `config/recipes/`. Each segment references the base scenario topology with optional machine-level overrides:

```yaml
name: "Monday Production Schedule"
base_scenario: full_feature_line   # topology source

segments:
  - name: "Product A Morning"
    quantity: 500                   # batch mode: stop after 500 parts
    max_duration: 18000            # safety timeout (5h)
    overrides:
      machines:
        - name: M1
          cycle_time: 10
          defect_rate: 0.02
    changeover:
      target: 300                  # planned changeover (seconds)
      distribution: lognormal
      mean: 300
      std: 60

  - name: "Product B Afternoon"
    duration: 7200                 # time-boxed mode: stop after 2h

  - name: "Product A Evening"
    quantity: 300                   # no changeover on last segment
```

### Stop Conditions

- **`quantity: N`** — Batch mode with optional `max_duration` safety timeout
- **`duration: N`** — Time-boxed mode (sim-seconds)

### Changeover Distributions

Changeover durations use the same `DistributionFactory` as failure modes: `constant`, `exponential`, `normal`, `lognormal`, `weibull`, `uniform`. The `target` is the planned time; actual is sampled from the distribution. During changeover, `LineState = "CHANGEOVER"` on OPC UA.

### Running

```bash
python src/opcua_server.py --recipe monday_schedule --seed 42
```

Console output shows per-segment progress and changeover analysis:
```
--- Segment 1/3: Product A Morning ---
    Target: 500 parts (max 18000s)
    Completed: 500 parts in 5230s (quantity_reached)
    Changeover: planned=300s actual=287s (delta=-13s)
--- Segment 2/3: Product B Afternoon ---
    Duration: 7200s
    Completed: 412 parts in 7200s (duration_reached)
```

### Available Example Recipes

| Recipe | Segments | Description |
|--------|----------|-------------|
| `monday_schedule` | 3 | Product A → changeover → Product B → changeover → Product A |
| `single_product` | 1 | Simple single-segment batch (200 parts) |
| `quick_test` | 2 | Short recipe for CI testing |

### Recipe OPC UA Variables

Under `OperationsState/Recipe/`: RecipeName, SegmentName, SegmentIndex, TotalSegments, SegmentTimeRemaining, SegmentQuantityTarget, SegmentQuantityProduced, SegmentStopMode, ChangeoverState, LastChangeoverPlanned, LastChangeoverActual.

### Recipe Historian Events

New event types: `SEGMENT_START`, `SEGMENT_END`, `CHANGEOVER`, `RECIPE_COMPLETE` — all logged with recipe context in the `extra` JSON field.

---

## 🗺️ Roadmap

### Recent Changes (2026-02-28)

- **Run Recipes** — Multi-segment production scheduling with stochastic changeovers (`--recipe` CLI arg)
- **`run_segment()` extraction** — Core simulation loop extracted into reusable function for both single-scenario and recipe modes
- **Recipe OPC UA nodes** — 12 new variables under `OperationsState/Recipe/` for segment tracking and changeover state
- **Recipe historian events** — `SEGMENT_START`, `SEGMENT_END`, `CHANGEOVER`, `RECIPE_COMPLETE` event types
- **Recipe Web UI** — `/api/recipes`, `/api/start-recipe` endpoints for recipe management
- **Report engine** — `analyze_recipe_segments()` and `analyze_changeovers()` for post-run analysis

### Previous Additions

- **OEE every step** — A, P, Q recalculate every simulation step using shift-relative deltas
- **MTTF scaling** — Multi-state degradation: per-step MTTF = configured MTTF / `failed_health`
- **Warm-up periods** — `warm_up_time` config parameter skips transient data collection
- **Priority Maintainer** — `PriorityMaintainer` with FIFO, SPT, priority, and bottleneck-first scheduling
- **Multi-state degradation** — `health_states` config with configurable h_max, p_degrade, and CBM thresholds
- **DEGRADED state** — New machine state for health > 0 but not yet failed
- **ISA-95 address space** — OPC UA hierarchy aligned to IEC 62264 / ISO 23247
- **Dynamic Telegraf config** — Auto-generated from scenario YAML for any number of machines
- **Web UI** — Flask dashboard with live KPIs, config editor, reports, pipeline validation
- **8-machine scenario** — `full_feature_8_machine_line` for max-scale testing
- **Per-shift OEE** — A/P/Q enrichment in historian events, shift-relative OEE snapshots
- **RunID** — Unique per-run identifier propagated through OPC UA, Telegraf, historian, and web UI
- **Event tracing** — `--trace` CLI flag for DES event trace output

### Future

- **Planned Failures** — `Machine(planned_failure=(time, duration))` for scheduled downtime windows
- **Parallel Replications** — `iterate_simulation(replications=30)` batch analysis with confidence intervals
- **Part Type Customization** — Custom Part subclass with product_family, order_id for product-mix modeling
- **Parallel Lines & Assembly** — Multi-line coordination, merge/split topologies
- **Energy/Sustainability Modeling** — Power consumption per machine state, carbon footprint KPIs

See the [User Manual](docs/user_manual.md) for detailed documentation.

---

## 📚 References

- **Simantha:** https://github.com/usnistgov/simantha
- **OPC UA Specification:** https://opcfoundation.org/
- **python-opcua:** https://github.com/FreeOpcUa/python-opcua

---

## 📄 License

Public Domain (following Simantha's license)

---

## 🙏 Acknowledgments

Built on the [Simantha](https://github.com/usnistgov/simantha) discrete-event simulation library by NIST.
