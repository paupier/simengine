# Simantha OPC UA Integration

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: Public Domain](https://img.shields.io/badge/License-Public%20Domain-green.svg)](https://github.com/usnistgov/simantha/blob/master/LICENSE)
[![OPC UA](https://img.shields.io/badge/OPC%20UA-Compliant-orange.svg)](https://opcfoundation.org/)

A real-time **digital twin** of a manufacturing production line using [Simantha](https://github.com/usnistgov/simantha) discrete-event simulation exposed via OPC UA for monitoring and control.

---

## 📋 Project Status

**Status:** Feature-complete manufacturing digital twin
**Last Updated:** 2026-04-03

### Key Capabilities

| Area | Features |
|------|----------|
| **Simulation** | N-machine serial lines (2-10+), config-driven topologies, 25 built-in scenarios, run recipes, per-step real-time architecture (O(1)/step, sim clock locked to wall clock) |
| **OPC UA** | ISA-95/ISO 23247 aligned address space; `SetInterarrivalTime` configurable at run start |
| **Reliability** | Multi-state health degradation, advanced failure modes (Weibull, exponential, lognormal), competing risks |
| **Maintenance** | Corrective/preventive/predictive strategies, priority maintainer (FIFO, SPT, priority, bottleneck) |
| **Quality** | Health-correlated defects, scrap/rework routing, SPC (X-bar/R, Cp/Cpk, Western Electric rules) |
| **Production** | OEE (per-machine & line-level), shift management, warm-up periods, target PPM tracking |
| **Data** | Event historians (CSV/InfluxDB/Neo4j), Grafana dashboards, dynamic Telegraf config generation, OPC UA PubSub over MQTT (Part 14 JSON + flat JSON) |
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
- **Publishes** live data via MQTT (OPC UA Part 14 JSON + flat JSON) to Eclipse Mosquitto
- **Responds** to external control inputs (arrival rate adjustment configurable at run start)
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
- ✅ **Enhanced State Detection** - 7 states: IDLE, PROCESSING, BLOCKED, STARVED, DEGRADED, FAILED, UNDER_REPAIR
- ✅ **Time Tracking** - Per-step time accumulation by machine state (see [How KPIs Are Derived](#how-kpis-are-derived))
- ✅ **Event Historian** - CSV, InfluxDB 2.x, Neo4j backends with edge-detection logging
- ✅ **Grafana Dashboards** - Manufacturing overview, OEE detail, machine KPIs, state timeline, downtime/reliability, SPC, shift comparison, alarm log, line balance/bottleneck, SPC machine detail (10 dashboards)
- ✅ **MQTT PubSub** - OPC UA Part 14 JSON Network Messages + flat JSON published to Eclipse Mosquitto every simulation step (`--mqtt` CLI flag)
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

# Publish live data to MQTT broker (OPC UA Part 14 JSON + flat JSON)
python src/opcua_server.py --mqtt
python src/opcua_server.py --scenario full_feature_line --seed 42 --mqtt --mqtt-broker mqtt://localhost:1883
```

**Run a recipe (multi-segment production schedule):**
```bash
# 3-segment recipe: Product A → changeover → Product B → changeover → Product A
python src/opcua_server.py --recipe monday_schedule --seed 42

# Quick recipe for testing (2 segments with 10s changeover)
python src/opcua_server.py --recipe quick_test --seed 1
```

**Reproducible runs** — same `--seed` always gives the same trajectory:
```bash
# The per-step architecture seeds per step: step_seed = (seed + step_count) % 2³¹
# Same seed → same step outcomes → same trajectory, O(1) per step, indefinitely
python src/opcua_server.py --scenario full_feature_line --seed 42
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

Includes: Web UI (:8080), OPC UA (:4840), InfluxDB (:8086), Grafana (:3000), Telegraf, Mosquitto MQTT broker (:1883/:9001), Neo4j (:7474/:7687), NeoDash (:5005).

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
┌─────────────────┐     ┌──────────────┐     ┌───────────────────┐
│  OPC UA Client  │     │   Flask UI   │     │  MQTT Subscriber  │
│ (UA Expert, MES)│     │ (Dashboard,  │     │ (Node-RED, browser│
└────────┬────────┘     │  Config, etc)│     │  SCADA adapter)   │
         │ OPC UA       └──────┬───────┘     └────────┬──────────┘
         │ Protocol            │ OPC UA               │ MQTT
         ▼                     ▼                      ▼
┌──────────────────────────────────────┐    ┌─────────────────────┐
│         OPC UA Server (ISA-95)       │    │  Eclipse Mosquitto  │
│  Enterprise/Site/Area/Line hierarchy │    │  :1883 (MQTT)       │
│  All variables read-only during run  │    │  :9001 (WebSocket)  │
│  (SetInterarrivalTime set at start)  │    └─────────────────────┘
└────────────────┬─────────────────────┘             ▲
                 │ Python API                         │ --mqtt flag
                 ▼                                    │
┌─────────────────────────────────────────────────────┤
│         Simantha Simulation                         │  Discrete-Event Simulation
│  Source → M1 → B1 → M2 → ... → Sink                │  N-machine serial topology
│  Health degradation, failures, SPC                  │  Quality routing, shifts
│  Maintenance, run recipes                           │  Multi-segment changeovers
└──────────────┬──────────────────────────────────────┘
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

**Machine States (7):** IDLE, PROCESSING, BLOCKED, STARVED, DEGRADED, FAILED, UNDER_REPAIR

### Read-Only Operation

All OPC UA variables are **read-only** during a run. `SetInterarrivalTime` (under `OperationsState/Controls/`) reflects the value set when the run started and cannot be changed via OPC UA clients at runtime. Use the Web UI Stop button to end a run.

---

## 🧪 Testing & Scenarios

### Available Scenarios (25 total)

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
| `full_feature_8_machine_line` | 8 | Max-scale: all features on 8 machines with CBM — **balanced reference** | Expert |
| `full_feature_8_machine_line_rtf` | 8 | Balanced 8-machine line, run-to-failure (no CBM) — MTTR/downtime analysis | Expert |
| `8m_cbm_poor_quality` | 8 | Good reliability, high defect rate (12% base, ×6 health multiplier) with CBM | Expert |
| `8m_rtf_poor_quality` | 8 | Same quality profile as above, run-to-failure (no CBM) | Expert |
| `8m_cbm_high_downtime` | 8 | Frequent failures, long MTTR (~65s), good quality with CBM | Expert |
| `8m_rtf_high_downtime` | 8 | Same downtime profile as above, run-to-failure (no CBM) | Expert |
| `warm_up_line` | 2 | Warm-up period for steady-state metrics | Intermediate |
| `priority_maintenance_line` | 3 | Priority maintainer with bottleneck-first strategy | Advanced |
| `priority_user_line` | 3 | Priority maintainer with user-defined priorities | Advanced |
| `multi_state_degradation_line` | 2 | Multi-state health degradation (5 states) | Advanced |

#### 8-Machine Comparative Matrix

All six 8-machine scenarios share identical cycle times and buffer layout so metrics are directly comparable:

| Scenario | Maintenance | Target Availability | Target Quality | Target OEE | What drives the loss |
|----------|-------------|--------------------:|---------------:|----------:|---------------------|
| `full_feature_8_machine_line` | CBM | ~85% | ~97% | ~82% | Balanced reference |
| `full_feature_8_machine_line_rtf` | RTF | ~80% | ~95% | ~76% | Balanced reference |
| `8m_cbm_poor_quality` | CBM | ~88% | ~70% | ~62% | Quality (high defects, low rework success) |
| `8m_rtf_poor_quality` | RTF | ~84% | ~70% | ~59% | Quality + unplanned downtime |
| `8m_cbm_high_downtime` | CBM | ~65% | ~97% | ~63% | Availability (frequent failures, long MTTR) |
| `8m_rtf_high_downtime` | RTF | ~55% | ~97% | ~53% | Availability (longer FAILED events, no early intervention) |

### Run Tests

```bash
# All tests (excludes slow integration tests)
pytest tests/ -v --ignore=tests/test_advanced_scenarios.py --ignore=tests/test_opcua_integration.py

# Specific test suites
pytest tests/test_new_features.py -v          # Warm-up, degradation, dead-band, shift OEE, repair counting (72 tests)
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
3. **Observe read-only variables:**
   - All OPC UA variables are read-only during a run
   - `SetInterarrivalTime` reflects the value configured at run start
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
| `IdleTime` | `idle_time` | IDLE |

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
│   ├─ mqtt_publisher.py          # OPC UA PubSub over MQTT (Part 14 JSON + flat JSON)
│   └─ simantha_baseline.py       # Standalone baseline scenarios (batch mode)
│
├─ config/
│   ├─ line_models.yaml           # Scenario definitions (25 scenarios)
│   └─ recipes/                   # Recipe YAML files (multi-segment schedules)
│       ├─ monday_schedule.yaml   # 3-segment: Product A → B → A with changeovers
│       ├─ single_product.yaml    # 1-segment batch
│       └─ quick_test.yaml        # 2-segment short recipe for testing
│
├─ tests/                          # 598 tests (excluding integration)
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
│   ├─ test_mqtt_publisher.py     # MQTT publisher unit tests (11 tests)
│   └─ ...                        # Integration, scenario, advanced isolation tests
│
├─ docker/
│   ├─ webui/
│   │   ├─ app.py                 # Flask web dashboard (local + Docker)
│   │   └─ templates/             # HTML: dashboard, config editor, reports, validation
│   ├─ telegraf/
│   │   ├─ generate_telegraf_conf.py  # Dynamic Telegraf config from scenario YAML
│   │   └─ telegraf.conf              # Generated/fallback Telegraf config
│   ├─ mosquitto/
│   │   └─ mosquitto.conf             # Eclipse Mosquitto 2.0 config (MQTT + WebSocket)
│   ├─ docker-compose.yml         # Full stack: Web UI + InfluxDB + Telegraf + Grafana + Mosquitto
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

**Cause:** Time not incrementing in loop.

**Fix:** Use the Web UI Stop button to end the run, then restart. Check loop logic if running from CLI.

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

## 📡 MQTT PubSub

The `--mqtt` flag enables OPC UA PubSub over MQTT (Part 14 JSON), publishing a snapshot every simulation step to Eclipse Mosquitto.

### Usage

```bash
# Default broker (mqtt://mosquitto:1883 — Docker internal hostname)
python src/opcua_server.py --mqtt

# Custom broker
python src/opcua_server.py --scenario full_feature_line --seed 42 \
    --mqtt --mqtt-broker mqtt://localhost:1883

# Works with recipes too
python src/opcua_server.py --recipe monday_schedule --mqtt
```

The Web UI dashboard also includes an MQTT toggle and broker URL input in the start panel.

### Topic Layout

Per step, two messages are published for each machine and one for the system (line KPIs):

| Topic | Format |
|-------|--------|
| `opcua/simantha/{run_id}/machines/M{i}` | OPC UA Part 14 JSON Network Message |
| `opcua/simantha/{run_id}/system` | OPC UA Part 14 JSON Network Message |
| `simantha/{run_id}/machines/M{i}` | Flat JSON (`run_id`, `sim_time`, `source` + payload) |
| `simantha/{run_id}/system` | Flat JSON |

### Mosquitto (Docker)

The Docker stack includes Eclipse Mosquitto 2.0 on ports 1883 (MQTT) and 9001 (WebSocket).

```bash
# Subscribe to all flat machine data
mosquitto_sub -h localhost -t "simantha/+/machines/#" -v

# Subscribe to line KPIs only
mosquitto_sub -h localhost -t "simantha/+/system" -v
```

### Behaviour

- **QoS 0** (fire-and-forget) — never blocks the simulation step clock
- **Non-blocking connect** — if the broker is unreachable, simulation continues normally; dropped steps are logged at close
- **Auto-reconnect** with exponential backoff (1s to 30s)
- Requires `paho-mqtt>=2.0.0` (already in `requirements.txt`)

---

## Neo4j Graph Analytics (Optional)

Neo4j stores manufacturing events as a causal graph alongside InfluxDB. Where InfluxDB answers "what happened and when", Neo4j answers "what caused what" — tracing failure cascades, starvation propagation, and SPC-to-quality chains.

### Setup

Enabled by default in `docker-compose.yml`. Access points:
- **Neo4j Browser**: http://localhost:7474 (login: neo4j / simantha)
- **NeoDash dashboards**: http://localhost:5005
- **Flask Graph tab**: http://localhost:8080/graph

### Enabling for a scenario

In the web UI config editor, scenarios with a `historian:` block show a **Neo4j Historian** checkbox.
Toggle it on to insert the `neo4j:` historian block into the scenario YAML. Toggle off to remove it.

Or edit the scenario YAML directly:

```yaml
historian:
  csv:
    output_dir: results/historian
    rotate_on_shift: true
  neo4j:
    uri: ${NEO4J_URI}
    user: ${NEO4J_USER}
    password: ${NEO4J_PASSWORD}
```

Environment variables (`NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`) are set in `.env` and injected into the simantha container.

### NeoDash Dashboards

Five pre-built dashboards seeded into Neo4j on first start:

| Dashboard | Purpose |
|---|---|
| Causal Chain Explorer | Browse CAUSED paths up to 6 hops deep |
| Failure Pattern Finder | Which machines fail most, in which shifts |
| SPC → Quality Impact | SPC violations to scrap/rework chains |
| Shift Breakdown | Events and counts per shift |
| Cross-Run Comparison | Structural stats across multiple runs |

### Future Extensions

The following are identified for future phases (out of scope for current implementation):

- **Part-level traceability** — `:Part` nodes linked via `:PROCESSED_BY`, tracking each part's line journey including rework attempts
- **Neo4j Bloom** — richer graph exploration with saved perspectives and visual query building (requires Enterprise or AuraDB)
- **Grafana → Neo4j panels** — community plugin to surface Cypher results in Grafana dashboards alongside InfluxDB panels
- **Anomaly pattern library** — store known failure subgraph signatures and query new runs for structural similarity
- **Multi-line topology** — extend schema for converging/diverging topologies (parallel lines feeding shared assembly)

---

## 🗺️ Roadmap

### Recent Changes (2026-04-04)

- **4 comparative 8-machine scenarios** — `8m_cbm_poor_quality`, `8m_rtf_poor_quality`, `8m_cbm_high_downtime`, `8m_rtf_high_downtime`. All share the same cycle times and buffer layout as the balanced reference for direct OEE comparison across availability-loss vs quality-loss profiles and CBM vs RTF maintenance strategies.
- **`Sys_TotalRepairs` fix** — `collect_system_metrics()` now reads `total_cm_count` from machines regardless of whether a Simantha `Maintainer` object is configured. Previously the no-maintainer branch hardcoded `total_repairs = 0`, so RTF and no-CBM scenarios always showed 0 repairs in the Grafana Maintenance panel.
- **Current shift OEE live computation** — `ShiftManager.get_current_shift_metrics()` now computes Availability, Quality, and OEE live from accumulated time counters on every call instead of returning the stale 0.0 stored in `ShiftMetrics.oee` (only written at shift rotation). Fixes Grafana Shift Comparison "No data" / 0% OEE for the active shift.
- **Dead-band OPC UA writes** — `CachedOpcuaNode` extended with per-key tolerance bands (OEE floats: 0.001, time accumulators: 1.0 s, ActualPPM: 0.5). Suppresses `set_value()` calls when the new value hasn't moved enough to matter, reducing per-step writes from ~600 to ~150 and keeping sim-clock and wall-clock in tight 1:1 sync on long runs.

### Previous Changes (2026-03-30)

- **OPC UA write caching** — `CachedOpcuaNode` wrapper skips `set_value()` when value is unchanged since last write.
- **Grafana dashboard redesigns** — Shift Comparison rebuilt (Current vs Previous, bar gauges, step charts). Alarm Event Log rebuilt with live failure status, timeline, and colour-coded event table.
- **SPC ViolationCount fix** — `M{N}_SPC_ViolationCount` (integer) restored in `telegraf.conf`.

### Previous Changes (2026-03-26)

- **OPC UA PubSub over MQTT** — `--mqtt` CLI flag enables publishing per-step snapshots to Eclipse Mosquitto in OPC UA Part 14 JSON and flat JSON formats. `--mqtt-broker` sets the broker URL. Web UI dashboard includes MQTT toggle. `src/mqtt_publisher.py` (non-blocking, QoS 0, paho-mqtt 2.0 / MQTTv5).
- **Downtime & Reliability fix** — MTBF, MTTR, FailureCount and TotalDowntime per failure mode were all zero when using the external repair countdown loop (all realistic MTTR > 1s cases). Root cause: `AdvancedMachine.restore()` (which calls `record_failure()`) was never triggered by the per-step repair countdown. Fix: `_record_external_repair()` is now called when the repair countdown reaches zero, recording the failure into the `FailureModeManager` so all Grafana Downtime & Reliability panels display correctly.
- **Mosquitto WebSocket listener** — Docker Mosquitto config now includes an explicit `listener 9001 / protocol websockets` block alongside the MQTT listener on 1883.

### Previous Changes (2026-03-17)

- **Per-step real-time architecture** — `simulate(1)` per loop iteration, O(1)/step forever
  - Eliminates the O(N²) quadratic compute growth of the previous cumulative `simulate(N)` pattern
  - Wall-clock pacer measures actual step cost and sleeps only for the remainder of the 1-second budget, keeping sim-time and wall-clock tightly in sync
  - Per-step seeding (`step_seed = (base_seed + step_count) % 2³¹`) gives fully reproducible trajectories with a fixed `--seed`
  - `LineState` accumulates per-step deltas; `MachineTotals` per-machine counters
- **Machine health state continuity** — `machine.initialize()` monkey-patched to restore saved health after Simantha's per-step reset, so degradation and CBM/failure cycles accumulate correctly across steps
- **Removed `CmdPauseLine`** — runtime pause removed; use Web UI Stop button instead
- **`SetInterarrivalTime` is now read-only during a run** — set via Web UI before starting
- **`--mode` CLI flag removed** — single unified architecture replaces `reproducible`/`realtime` choice
- **Web UI improvements** — Run History page with run_id visibility and Grafana integration; contrast fixes across all pages; wall-clock duration display alongside sim duration in reports
- **Grafana** — `run_id` filter integration for per-run scoping in dashboards

### Previous Changes (2026-02-28)

- **Run Recipes** — Multi-segment production scheduling with stochastic changeovers (`--recipe` CLI arg)
- **`run_segment()` extraction** — Core simulation loop extracted into reusable function for both single-scenario and recipe modes
- **Recipe OPC UA nodes** — 12 new variables under `OperationsState/Recipe/` for segment tracking and changeover state
- **Recipe historian events** — `SEGMENT_START`, `SEGMENT_END`, `CHANGEOVER`, `RECIPE_COMPLETE` event types
- **Recipe Web UI** — `/api/recipes`, `/api/start-recipe` endpoints for recipe management
- **Report engine** — `analyze_recipe_segments()` and `analyze_changeovers()` for post-run analysis

### Earlier Additions

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
- **Energy/Sustainability Modeling** — Power consumption per machine state, carbon footprint KPIs
- **Converge/Diverge Topologies** — Fork-merge production layouts (e.g., 5 serial machines splitting to M6+M7+M8 sharing a downstream buffer, or two lines converging into one). The `LineState`/`MachineTotals` architecture introduced for simulation modes is explicitly designed to support this: counters are per-machine and topology-agnostic, so multi-path lines would only require changes to Simantha object construction and OPC UA node registration — not the KPI accounting layer. Scope limit: maximum one merge or split point between machines 2 and 7 within a single line. True multi-line federation (independent OPC UA servers) is out of scope.

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
