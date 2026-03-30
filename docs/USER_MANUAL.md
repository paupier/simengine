# Simantha OPC UA - Complete User Manual

**Version:** 2.7
**Last Updated:** 2026-03-26
**Difficulty:** Beginner to Advanced

---

## Table of Contents

1. [Introduction](#1-introduction)
2. [System Requirements](#2-system-requirements)
3. [Installation](#3-installation)
4. [Quick Start Guide](#4-quick-start-guide)
5. [Understanding the System](#5-understanding-the-system)
6. [Connecting with OPC UA Clients](#6-connecting-with-opc-ua-clients)
7. [Configuration Guide](#7-configuration-guide)
8. [Available Scenarios](#8-available-scenarios)
9. [OPC UA Address Space Reference](#9-opc-ua-address-space-reference)
10. [Advanced Features](#10-advanced-features)
11. [Run Recipes](#11-run-recipes)
12. [Troubleshooting](#12-troubleshooting)
13. [Appendix](#13-appendix)

---

## 1. Introduction

### What is Simantha OPC UA?

Simantha OPC UA is a **manufacturing digital twin** that simulates a production line and exposes real-time data through the industry-standard OPC UA protocol. It combines:

- **Simantha** - A discrete-event simulation library by NIST
- **OPC UA** - Industrial communication protocol for real-time data exchange
- **Python** - Easy-to-modify and extend codebase

### What Can You Do With It?

✅ **Simulate** realistic manufacturing lines with 2-10+ machines
✅ **Monitor** real-time KPIs (throughput, OEE, quality, SPC metrics)
✅ **Configure** arrival rate and other parameters at run start via the Web UI or OPC UA
✅ **Track** shift-based production with automatic rotation and per-shift OEE
✅ **Route** defective parts to scrap sinks or attempt virtual rework
✅ **Record** event history to CSV, InfluxDB, or Neo4j for post-analysis
✅ **Experiment** with different scenarios (bottlenecks, failures, quality, scrap/rework)
✅ **Learn** about manufacturing systems, OPC UA, and digital twins
✅ **Integrate** with SCADA systems, HMIs, Grafana, InfluxDB, etc.

### Who Is This For?

- **Students** learning about manufacturing systems and Industry 4.0
- **Engineers** prototyping digital twin architectures
- **Researchers** experimenting with production line optimization
- **Developers** learning OPC UA integration
- **Anyone** interested in smart manufacturing

---

## 2. System Requirements

### Hardware Requirements

**Minimum:**
- **CPU:** Dual-core processor
- **RAM:** 2 GB
- **Disk:** 100 MB free space

**Recommended:**
- **CPU:** Quad-core processor
- **RAM:** 4 GB+
- **Disk:** 500 MB free space

### Software Requirements

**Required:**
- **Python:** 3.9 or newer (3.11 recommended; 3.12 not yet supported)
- **pip:** Python package installer
- **Git:** For cloning the repository (optional, can download ZIP)

**Optional (for visualization):**
- **UA Expert:** OPC UA client for testing (free from Unified Automation)
- **Prosys OPC UA Browser:** Alternative OPC UA client
- **Node-RED:** For custom dashboards
- **Grafana + InfluxDB:** For historical trending (included in Docker stack)

### Supported Operating Systems

✅ **Windows** (10, 11, Server 2019+)
✅ **Linux** (Ubuntu 20.04+, Debian, CentOS, RHEL)
✅ **macOS** (10.15 Catalina or newer)

---

## 3. Installation

### Step 1: Install Python

**Windows:**
1. Download Python from [python.org](https://www.python.org/downloads/)
2. Run installer and **check "Add Python to PATH"**
3. Verify installation:
   ```cmd
   python --version
   ```
   Expected output: `Python 3.11.x` or similar

**Linux (Ubuntu/Debian):**
```bash
sudo apt update
sudo apt install python3 python3-pip python3-venv
python3 --version
```

**macOS:**
```bash
# Using Homebrew
brew install python@3.11
python3 --version
```

### Step 2: Clone the Repository

**Option A: Using Git (Recommended)**

```bash
# Clone the repository
git clone https://github.com/paupier/simantha-opcua.git
cd simantha-opcua
```

**Option B: Download ZIP**

1. Go to https://github.com/paupier/simantha-opcua
2. Click **Code** → **Download ZIP**
3. Extract to a folder (e.g., `C:\Projects\simantha-opcua`)
4. Open terminal/command prompt in that folder

### Step 3: Create Virtual Environment

**Why?** Isolates dependencies from other Python projects.

**Windows:**
```cmd
python -m venv venv
venv\Scripts\activate
```

**Linux/macOS:**
```bash
python3 -m venv venv
source venv/bin/activate
```

**You should see `(venv)` prefix in your terminal.**

### Step 4: Install Dependencies

```bash
pip install -r requirements.txt
```

**Expected output:**
```
Installing collected packages: simantha, opcua, numpy, scipy, pyyaml
Successfully installed ...
```

**Installation time:** ~1-2 minutes depending on internet speed.

### Step 5: Verify Installation

```bash
# Run tests to verify everything works
pytest tests/test_spc_analytics.py -v
```

**Expected output:**
```
============================= 23 passed in 0.27s ==============================
```

✅ **Installation Complete!** You're ready to run the server.

---

## 4. Quick Start Guide

### Your First Simulation (5 Minutes)

#### Step 1: Start the OPC UA Server

**Open a terminal in the project directory** and run:

```bash
python src/opcua_server.py
```

**Expected output:**
```
Loading scenario: balanced_line
OPC UA server started at opc.tcp://localhost:4840/simantha/
Scenario: balanced_line (2 machines, 1 buffers)
Press Ctrl+C to stop.
```

✅ **Server is running!** It will continue until you press `Ctrl+C`.

#### Step 2: Install an OPC UA Client

**UA Expert (Recommended for beginners):**

1. Download from [Unified Automation](https://www.unified-automation.com/downloads/opc-ua-clients.html)
2. Install and launch UA Expert
3. You'll see a blank workspace

#### Step 3: Connect to the Server

**In UA Expert:**

1. **Add Server:**
   - Click **Server** → **Add**
   - Enter URL: `opc.tcp://localhost:4840/simantha/`
   - Click **OK**

2. **Connect:**
   - Double-click the server in the left panel
   - Server should connect (green icon)

3. **Browse Address Space:**
   - Expand: **Objects** → **WeylandIndustries** → **LV426_Colony** → **AtmosphereProcessor01** → **Nostromo_BioProductPakaging_Equipment**
   - You'll see ISA-95 structure:
     - `Identification/` — line metadata (EquipmentID, RunID)
     - `OperationsState/` — SimTime, LineState, Controls (writable)
     - `OperationsPerformance/` — Throughput, TotalWIP, TotalScrap, ScrapRate
     - `OEE/` — Line-level Availability, Performance, Quality, OEE
     - `Resources/` — M1_Equipment, B1_StorageUnit, M2_Equipment, etc.
     - `SupportFunctions/` — Maintenance, ShiftManagement

4. **View Live Data:**
   - Drag variables to the **Data Access View** (bottom panel)
   - Try these first (under the Equipment node):
     - `OperationsState/SimTime` - Simulation time
     - `OperationsPerformance/Throughput` - Total parts produced
     - `Resources/M1_Equipment/OperationsState/State` - Machine 1 state
     - `Resources/B1_StorageUnit/CurrentLevel` - Buffer level

**You should see values updating in real-time!** 🎉

#### Step 4: Observe the Simulation

**In UA Expert, watch the Controls node:**

1. Navigate to: `Nostromo_BioProductPakaging_Equipment/OperationsState/Controls`
2. `SetInterarrivalTime` shows the inter-arrival delay set at run start (read-only during the run).
3. Watch `SimTime` incrementing — one sim-second equals approximately one wall-clock second.

> **Note:** Runtime pause and mid-run interarrival adjustment have been removed. Use the Web UI to set `SetInterarrivalTime` before starting a run, or stop and restart with a different value.

#### Step 5: Stop the Server

In the terminal where the server is running:

- Press `Ctrl+C`
- Server will gracefully shut down

**Congratulations!** You've completed your first simulation. 🎊

### Web UI (Alternative to OPC UA Clients)

Instead of using UA Expert, you can use the built-in Flask web dashboard:

**Local mode (no Docker needed):**
```bash
python docker/webui/app.py
```

Open `http://localhost:8080` in your browser. The dashboard provides:

- **Scenario selection** and simulation start/stop
- **Live dashboard** with per-machine OEE bars, PPM, Cp/Cpk, shift progress, line OEE, and scrap metrics
- **Config editor** at `/config` for creating and editing scenarios with YAML preview and validation
- **Reports page** at `/reports` for post-run analysis (OEE charts, throughput trends, time-in-state, anomaly detection, run comparison from CSV historian data)
- **Validation page** at `/validation` for checking the data pipeline health (OPC UA → Telegraf → InfluxDB)

**Docker mode (full stack):**
```bash
docker compose -f docker/docker-compose.yml up --build -d
```

The Docker stack includes: Web UI (:8080), OPC UA (:4840), InfluxDB (:8086), Grafana (:3000), Telegraf (OPC UA → InfluxDB pipeline), Mosquitto MQTT broker (:1883/:9001), Neo4j (:7474/:7687), and NeoDash (:5005).

### Quick Start with Recipes

Recipes let you run multi-segment production schedules with automatic changeovers between products:

```bash
# Run a multi-segment production recipe
python src/opcua_server.py --recipe monday_schedule --seed 42

# Short recipe for testing
python src/opcua_server.py --recipe quick_test --seed 1
```

See [Section 11: Run Recipes](#11-run-recipes) for full details on recipe configuration and usage.

---

## 5. Understanding the System

### System Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    OPC UA Server                        │
│                  (opcua_server.py)                      │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ┌──────────┐    ┌────────┐    ┌──────────┐          │
│  │  Source  │───▶│   M1   │───▶│ Buffer1  │───▶...   │
│  │ (Parts   │    │(Machine│    │ (WIP     │          │
│  │  arrive) │    │   1)   │    │ Storage) │          │
│  └──────────┘    └────────┘    └──────────┘          │
│                       │                                 │
│                       ▼                                 │
│                 ┌──────────┐                           │
│                 │Maintainer│                           │
│                 │ (Repairs)│                           │
│                 └──────────┘                           │
│                                                         │
├─────────────────────────────────────────────────────────┤
│                  OPC UA Protocol                        │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐            │
│  │UA Expert │  │ Grafana  │  │  SCADA   │            │
│  │ (Browse) │  │ (Charts) │  │  System  │            │
│  └──────────┘  └──────────┘  └──────────┘            │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

### Production Line Flow

```
Source  →  M1  →  Buffer1  →  M2  →  Sink
 (∞)      (1s)      (10)     (1s)    (∞)
```

**Explanation:**
- **Source:** Generates parts infinitely
- **M1:** First machine (1 second cycle time)
- **Buffer1:** Holds up to 10 parts (WIP storage)
- **M2:** Second machine (1 second cycle time)
- **Sink:** Collects finished parts

### Machine States (8 States)

| State | Description | Typical Cause |
|-------|-------------|---------------|
| **IDLE** | Waiting for work | No parts available, downstream blocked |
| **PROCESSING** | Actively working on a part | Normal operation |
| **BLOCKED** | Waiting for downstream buffer space | Buffer full, downstream slow |
| **STARVED** | Waiting for upstream parts | Buffer empty, upstream slow |
| **PAUSED** | Simulation paused | User control via OPC UA |
| **FAILED** | Machine has failed | Health degradation (with degradation enabled) |
| **UNDER_REPAIR** | Being repaired by maintainer | After failure (with maintainer) |
| **DEGRADED** | Machine operational but degrading | Health > 0 but not yet failed (multi-state degradation) |

### Key Performance Indicators (KPIs)

**Throughput:**
- Total parts completed by the line
- Monotonic counter (never decreases)

**Utilization:**
- `ProcessingTime / TotalTime`
- 0.0 = 0%, 1.0 = 100%
- Shows how busy the machine is

**OEE (Overall Equipment Effectiveness):**
- `Availability × Performance × Quality`
- Industry-standard metric
- Target: >85% for world-class manufacturing
- Recalculated every simulation step using shift-relative deltas
- Availability uses the main loop's downtime accumulator (excludes warm-up)
- Quality uses per-part routing counters (post-warm-up only, matching `parts_made`)

**Buffer Level:**
- Current WIP (Work-In-Progress) count
- Range: 0 to capacity (e.g., 0-10)
- High level = bottleneck downstream
- Low level = bottleneck upstream

### How Metrics Are Derived

Understanding where each value comes from helps you interpret the OPC UA variables correctly.

#### Time Accumulators

Each simulation step (1 second), the server inspects the machine's **previous state** and adds 1 second to the matching time bucket:

| Previous State | Accumulator | OPC UA Variable |
|----------------|-------------|-----------------|
| PROCESSING, DEGRADED | `processing_time` | `ProcessingTime` |
| BLOCKED | `blocked_time` | `BlockedTime` |
| STARVED | `starved_time` | `StarvedTime` |
| FAILED, UNDER_REPAIR | `down_time` | `DownTime` |
| IDLE, PAUSED | `idle_time` | `IdleTime` |

These accumulators are maintained by the main loop, **not** by Simantha internals. This means they naturally exclude warm-up time (the loop only runs after warm-up completes).

**Utilisation** = `ProcessingTime / (ProcessingTime + BlockedTime + StarvedTime + DownTime + IdleTime)`

#### OEE Components

OEE recalculates every simulation step using **shift-relative deltas** (counters reset at shift boundaries):

| Component | Formula | Notes |
|-----------|---------|-------|
| **Availability** | `(shift_elapsed - shift_downtime) / shift_elapsed` | `shift_downtime` comes from the main loop's `down_time` accumulator (excludes warm-up), not Simantha's `machine.downtime` |
| **Performance** | `shift_parts / (available_time / cycle_time)` | `shift_parts` = `machine.parts_made` delta since shift start. Simantha's `parts_made` only counts post-warm-up parts. |
| **Quality** | `good / (good + defective)` | For quality-routing machines: `_good_count`, `_scrap_count`, `_defective_count`. These counters only increment after warm-up. |

#### Health and Degradation

| Variable | Source | Description |
|----------|--------|-------------|
| `HealthState` | `machine.health` | Simantha's Markov chain state (0 = healthy, N = degrading/failed) |
| `HealthPercent` | `100 * (1 - health / failed_health)` | 100% = healthy, 0% = failed |
| `failed_health` | Standard: 1 (2-state). Multi-state: `h_max` from config. | Determines at which health state the machine is considered failed |

With multi-state degradation, the machine transitions 0 &rarr; 1 &rarr; 2 &rarr; ... &rarr; h_max. States between 0 and `failed_health` report as DEGRADED. The time between each degradation step is sampled from the configured failure distribution and divided by `failed_health`, so total expected time to failure matches the configured MTTF.

#### Quality Counters and Warm-Up

Quality routing counters (`_good_count`, `_scrap_count`, `_defective_count`) only increment when `env.now > warm_up_time`. This matches Simantha's `parts_made` behavior, which also excludes warm-up. Without this alignment, Quality would erroneously report 100% because the denominator (`parts_made`) would be smaller than the numerator (`_good_count`).

Scrap/rework **routing** (physical diversion of parts to scrap sinks) still happens during warm-up so the simulation state is realistic when data collection begins.

---

## 6. Connecting with OPC UA Clients

### UA Expert (Detailed Guide)

**Step-by-Step Connection:**

1. **Launch UA Expert**

2. **Add Server Configuration:**
   - Click **Server** → **Add** (or press `Ctrl+A`)
   - In the dialog:
     - **URL:** `opc.tcp://localhost:4840/simantha/`
     - **Name:** Simantha Digital Twin (optional)
     - **Security:** None (for testing)
   - Click **OK**

3. **Connect to Server:**
   - Find "Simantha Digital Twin" in the left **Project** panel
   - Double-click or right-click → **Connect**
   - Icon turns green when connected

4. **Browse Address Space:**
   - Expand the server node
   - Navigate: **Objects** → **WeylandIndustries** → **LV426_Colony** → **AtmosphereProcessor01**
   - You'll see the Equipment and Asset nodes for the line

5. **Monitor Variables:**
   - **Drag and drop** variables to the **Data Access View** (bottom panel)
   - Variables update in real-time
   - Right-click column headers to customize display

6. **Write to Variables (Control):**
   - Find writable variables (usually in `Controls` folder)
   - Right-click variable → **Write Value**
   - Enter new value → **Write**

**Useful UA Expert Features:**

- **Data Access View:** Real-time value monitoring
- **Data Logger:** Record historical values to CSV
- **Trends:** Plot values over time (live charts)
- **Alarms & Events:** View alarm notifications

### Prosys OPC UA Browser

**Alternative OPC UA client with similar features.**

1. Download from [Prosys](https://www.prosysopc.com/products/opc-ua-browser/)
2. Install and launch
3. **Connect:**
   - Click **Connect to Server**
   - Enter: `opc.tcp://localhost:4840/simantha/`
   - Click **OK**
4. Browse and monitor similar to UA Expert

### Python Client (Programmatic Access)

**Example script to read values:**

```python
from opcua import Client

# Connect to server
client = Client("opc.tcp://localhost:4840/simantha/")
client.connect()

try:
    # Get root objects node
    root = client.get_objects_node()

    # Navigate ISA-95 hierarchy to the Equipment node
    enterprise = root.get_child(["2:WeylandIndustries"])
    site = enterprise.get_child(["2:LV426_Colony"])
    area = site.get_child(["2:AtmosphereProcessor01"])
    equip = area.get_child(["2:Nostromo_BioProductPakaging_Equipment"])

    # Read system variables
    ops_state = equip.get_child(["2:OperationsState"])
    sim_time = ops_state.get_child(["2:SimTime"])
    ops_perf = equip.get_child(["2:OperationsPerformance"])
    throughput = ops_perf.get_child(["2:Throughput"])

    print(f"Simulation Time: {sim_time.get_value()}")
    print(f"Throughput: {throughput.get_value()}")

    # Read the current interarrival time (set at run start, read-only during run)
    controls = ops_state.get_child(["2:Controls"])
    interarrival = controls.get_child(["2:SetInterarrivalTime"])
    print(f"Interarrival time: {interarrival.get_value():.2f}s")

finally:
    client.disconnect()
```

> **Note:** The ISA-95 hierarchy names (`WeylandIndustries`, `LV426_Colony`, etc.) are configurable in the scenario YAML via `enterprise`, `site`, `area`, and `line_name` keys.

**Save as `test_client.py` and run:**
```bash
python test_client.py
```

### Node-RED Integration

**Create custom dashboards with Node-RED.**

1. Install Node-RED: `npm install -g node-red`
2. Install OPC UA node: `npm install node-red-contrib-opcua`
3. Start Node-RED: `node-red`
4. Open browser: `http://localhost:1880`
5. Add OPC UA nodes and connect to `opc.tcp://localhost:4840/simantha/`

---

## 7. Configuration Guide

### Overview

All scenarios are defined in **`config/line_models.yaml`**. This file uses YAML syntax to configure:

- Number of machines
- Machine parameters (cycle time, failure modes, SPC settings)
- Buffer capacities
- Maintenance settings
- Quality parameters

### Basic Configuration Structure

```yaml
scenario_name:
  description: "Human-readable description"

  machines:
    - name: M1
      cycle_time: 1.0        # Seconds per part
      # Additional parameters...

    - name: M2
      cycle_time: 1.0

  buffers:
    - name: B1
      capacity: 10           # Max WIP
      upstream: M1           # Feeds from M1
      downstream: M2         # Feeds to M2

  maintainer:
    enabled: false           # true = maintenance modeling
    capacity: 1              # Number of repair technicians
```

### Machine Count Limits

| Constraint | Value | Notes |
|-----------|-------|-------|
| **Minimum** | 2 machines | Enforced by `validate_serial_topology()` in `config_loader.py` |
| **Maximum** | No hard limit | Simantha, OPC UA address space, Telegraf generator, and topology validation all use dynamic loops |
| **Tested** | Up to 8 machines | `full_feature_8_machine_line` scenario; `test_add_machines_up_to_8` in test suite |
| **Web UI soft limit** | 19 machines | The dashboard OPC UA reader scans `M1` through `M19` and stops on the first miss. Lines with 20+ machines work via OPC UA clients and CLI but won't display all machines on the dashboard. |

The serial topology requires exactly N-1 buffers for N machines (e.g., 8 machines need 7 buffers). Each buffer connects consecutive machines via `upstream` and `downstream` fields.

### Machine Configuration Options

**Basic Machine:**
```yaml
machines:
  - name: M1
    cycle_time: 1          # Processing time (seconds)
```

**Machine with Target PPM:**
```yaml
machines:
  - name: M1
    target_ppm: 60         # Parts per minute target (derives cycle_time = 60/target_ppm = 1.0s)
```

`target_ppm` takes precedence over `cycle_time` if both are specified.

**Machine with Health Degradation:**
```yaml
machines:
  - name: M1
    cycle_time: 1
    enable_degradation: true
    degradation_matrix:
      - [0.99, 0.01]       # Healthy → Failed (1% chance)
      - [0.0, 1.0]         # Failed (absorbing state)
    cbm_threshold: 1       # Request maintenance when state=1
```

### Condition-Based Maintenance (CBM)

**CBM** is a maintenance strategy where the maintainer is called based on the *observed health state* of a machine, rather than waiting for a hard failure or following a fixed time schedule. The goal is to intervene early — while the machine is degrading but still producing — to prevent the costlier outcome of a full breakdown.

#### How it works in this simulator

Each machine with degradation enabled has a health state that steps from `0` (healthy) upward. The `cbm_threshold` setting tells Simantha at which health state to request the maintainer:

```
Health 0 ──► 1 ──► 2 ──► ... ──► h_max  (= full failure, machine stops)
                ▲
         cbm_threshold
         maintainer called here,
         machine continues producing
         while waiting for repair
```

When `health >= cbm_threshold`, Simantha queues a maintenance request. The machine keeps running in a degraded state until the maintainer arrives. Once repaired, health resets to 0.

If `cbm_threshold == h_max`, the maintainer is only called at full failure — this is **corrective maintenance** (run-to-failure), not CBM.

#### Enabling and disabling CBM

**CBM enabled** — maintainer intervenes before failure:
```yaml
machines:
  - name: M1
    cycle_time: 1
    health_states:
      h_max: 4          # States: 0 (healthy) → 1 → 2 → 3 → 4 (failed)
      p_degrade: 0.01   # 1% chance of degrading one step per simulation step
      cbm_threshold: 2  # Call maintainer when health reaches state 2
                        # Machine never reaches state 4 if maintained promptly

maintainer:
  enabled: true
  capacity: 1
```

**CBM disabled** (run-to-failure) — maintainer only called at full failure:
```yaml
machines:
  - name: M1
    cycle_time: 1
    health_states:
      h_max: 4
      p_degrade: 0.01
      cbm_threshold: 4  # Only call maintainer at full failure (= h_max)
                        # Machine will reach FAILED state and stop producing
```

**No degradation at all** — machine is perfectly reliable:
```yaml
machines:
  - name: M1
    cycle_time: 1
    # No health_states block = no degradation, no failures
```

#### The threshold trade-off

| `cbm_threshold` | Behaviour | Trade-off |
|-----------------|-----------|-----------|
| Low (e.g. 1) | Very early intervention | More frequent maintenance, less production impact |
| Mid (e.g. h_max / 2) | Balanced CBM | Moderate downtime, moderate maintenance cost |
| Equal to `h_max` | Run-to-failure | Fewer repairs, but failures cause full production stops |

#### What you observe in the simulation

With CBM active (`cbm_threshold < h_max`):
- The machine cycles through `PROCESSING → DEGRADED → (maintenance) → PROCESSING`
- The `FAILED` state rarely or never occurs — **this is correct CBM behaviour, not a data gap**
- `HealthPercent` in OPC UA drops gradually, then resets to 100% after each repair
- The Run Reports page "Failure & Maintenance Timeline" chart shows **Degraded** and **Maintenance** events instead of hard failures

With run-to-failure (`cbm_threshold == h_max`):
- The machine cycles through `PROCESSING → DEGRADED → FAILED → UNDER_REPAIR → PROCESSING`
- Hard failures appear in the timeline chart
- MTTF and MTTR are calculable from the failure events

> **Note:** If `total_failures = 0` in your run report for a CBM scenario, that indicates CBM is working as intended — the maintainer is intervening before the machine reaches `h_max`. Degradation and maintenance event counts are the meaningful KPIs in this case, not failure counts.

---

**Machine with Quality Modeling:**
```yaml
machines:
  - name: M1
    cycle_time: 1
    defect_rate: 0.02      # 2% base defect rate
    health_multiplier: 3.0 # Defect rate × 3 when failed
```

**Machine with Advanced Failures (optional):**
```yaml
machines:
  - name: M1
    cycle_time: 1
    enable_advanced_failures: true

    failure_modes:
      - name: mechanical
        type: wearout       # Weibull distribution
        mttf:
          distribution: weibull
          shape: 2.5        # Beta > 1 = increasing hazard
          scale: 500        # Characteristic life
        mttr:
          distribution: lognormal
          mean: 15
          std: 5

      - name: electrical
        type: random        # Exponential distribution
        mttf:
          distribution: exponential
          mean: 1000
        mttr:
          distribution: lognormal
          mean: 10
          std: 3

    maintenance_strategy:
      type: predictive      # corrective, preventive, predictive
      cbm_threshold: 1
```

**Machine with SPC Analytics (optional):**
```yaml
machines:
  - name: M1
    cycle_time: 1
    enable_spc: true

    spc:
      characteristic: "cycle_time"
      subgroup_size: 5      # Samples per subgroup
      num_subgroups: 25     # For control limit calculation
      usl: 1.2              # Upper spec limit
      lsl: 0.8              # Lower spec limit
      target: 1.0           # Nominal value
      enable_western_electric: true
      measurement_noise: 0.02   # Coefficient of variation for measurement noise
```

### Quality Routing Configuration

Add a `quality_routing` block to any machine to enable scrap/rework routing:

```yaml
machines:
  - name: M1
    cycle_time: 1
    quality_routing:
      enabled: true
      mode: scrap_and_rework       # "scrap", "rework", or "scrap_and_rework"
      defect_rate: 0.05             # 5% base defect rate
      health_multiplier: 3.0        # Defect rate multiplier when degraded
      enable_health_correlation: true
      rework_success_rate: 0.7      # 70% chance rework fixes the part
      max_rework: 3                 # Max rework attempts per part
      scrap_sink: ScrapBin1         # Name of scrap sink to route to
```

**Scrap Sinks:** Define at the scenario level (not inside machines):

```yaml
scrap_sinks:
  - name: ScrapBin1
  - name: ScrapBin2
```

**Routing Modes:**

| Mode | Behavior |
|------|----------|
| `scrap` | Defective parts go directly to scrap sink |
| `rework` | Attempt virtual rework; if all attempts fail, part flows normally |
| `scrap_and_rework` | Attempt rework first; if all attempts fail, route to scrap |

**Architecture:**
```
Source → M1 → B1 → M2 → Sink   (main serial chain unchanged)
              │              │
              ↓              ↓
          ScrapBin1      ScrapBin2  (optional scrap sinks)
```

Scrap sinks are side branches - they do **not** affect the main serial chain. Parts only go to scrap when quality routing explicitly diverts them.

### Event Historian Configuration

Add a `historian` block to enable event logging to CSV, InfluxDB, or Neo4j:

```yaml
historian:
  backend: csv                     # "csv", "influxdb", or "neo4j"
  output_dir: results/historian    # CSV output directory
  events:
    state_changes: true            # Machine state transitions
    maintenance: true              # Repair start/end events
    quality: true                  # Quality alerts, scrap, rework
    buffer_levels: true            # Buffer high/low warnings
    shift_changes: true            # Shift rotation events
    spc_violations: true           # SPC rule violations
```

**Output:** CSV files are written to `results/historian/` relative to the project root. Each run creates a timestamped file.

**Event Types Logged:**

| Event | Description |
|-------|-------------|
| STATE_CHANGE | Machine state transitions (IDLE→PROCESSING, etc.) |
| MAINTENANCE_START | Repair begins on a machine |
| MAINTENANCE_END | Repair completed |
| QUALITY_ALERT | Defect rate exceeds threshold |
| BUFFER_HIGH | Buffer exceeds 90% capacity |
| BUFFER_LOW | Buffer below 10% capacity |
| SHIFT_CHANGE | Shift rotation boundary |
| SPC_VIOLATION | Western Electric rule violation |
| SCRAP | Part scrapped (with quality routing) |
| REWORK | Rework attempted on defective part (with quality routing) |

### Shift Configuration

Add a `shifts` block to any scenario to enable shift tracking:

```yaml
shifts:
  schedule:
    - name: "Day Shift"
      duration: 28800        # 8 hours in seconds (sim time units)
      start_offset: 0

    - name: "Evening Shift"
      duration: 28800
      start_offset: 28800

    - name: "Night Shift"
      duration: 28800
      start_offset: 57600
```

**Configuration Options:**

- **duration:** Shift length in simulation time units. Common values:
  - `28800` = 8 hours (typical 3-shift system)
  - `43200` = 12 hours (rotating 2-shift system)
  - Any custom value
- **schedule:** Repeats cyclically. After the last shift ends, rotates back to the first.
- **Number of shifts:** Unlimited. Define 2-shift, 3-shift, or any custom rotation.
- **Custom names:** Use any naming convention ("Shift A", "06:00-14:00", "Morning", etc.)

**Shift tracking is optional.** If the `shifts` block is omitted, the scenario runs without shift tracking.

### Creating Custom Scenarios

**Step 1: Open the configuration file:**

```bash
# Windows
notepad config\line_models.yaml

# Linux/macOS
nano config/line_models.yaml
```

**Step 2: Add a new scenario:**

```yaml
# At the end of the file
my_custom_line:
  description: "My custom production line"

  machines:
    - name: FastMachine
      cycle_time: 0.5      # Twice as fast

    - name: SlowMachine
      cycle_time: 2.0      # Bottleneck

  buffers:
    - name: DecouplingBuffer
      capacity: 20         # Larger buffer
      upstream: FastMachine
      downstream: SlowMachine

  maintainer:
    enabled: false
```

**Step 3: Save and run:**

```bash
python src/opcua_server.py --scenario my_custom_line
```

### Configuration Validation

**The server validates your configuration on startup:**

✅ **Valid configuration:**
```
[OK] Configuration validated: 2 machines, 1 buffers
Loading scenario: my_custom_line
OPC UA server started...
```

❌ **Invalid configuration:**
```
[ERROR] Configuration validation failed:
Machine 'M1' missing required field 'cycle_time'
```

**Common validation errors:**

1. **Missing required fields:**
   - All machines need `name` and `cycle_time`
   - All buffers need `name`, `capacity`, `upstream`, `downstream`

2. **Invalid topology:**
   - Buffer must connect existing machines
   - No cycles allowed (must be serial)

3. **Invalid parameters:**
   - `cycle_time` must be positive
   - `capacity` must be positive integer
   - Distribution parameters must be valid

**Run validation without starting server:**
```python
python -c "from src.config_loader import load_line_config; load_line_config('my_scenario')"
```

---

## 8. Available Scenarios

### Scenario A: Balanced Line (Default)

**File:** `balanced_line`
**Complexity:** ⭐ Beginner

```yaml
machines:
  - name: M1
    cycle_time: 1.0
  - name: M2
    cycle_time: 1.0

buffers:
  - name: B1
    capacity: 10
```

**Characteristics:**
- Both machines same speed (1 second)
- No bottleneck
- Buffer stays ~empty (balanced flow)
- Throughput: ~1 part/second

**Use case:** Learning basic OPC UA connection and monitoring

---

### Scenario B: Bottleneck Line

**File:** `bottleneck_line`
**Complexity:** ⭐⭐ Beginner

```yaml
machines:
  - name: M1
    cycle_time: 2.0    # Slow (bottleneck)
  - name: M2
    cycle_time: 1.0    # Fast

buffers:
  - name: B1
    capacity: 10
```

**Characteristics:**
- M1 is bottleneck (2× slower)
- M2 is often starved (waiting for parts)
- Buffer stays ~empty
- Throughput: ~0.5 parts/second (limited by M1)

**Observations:**
- `M2_Equipment/OperationsState/State` often shows "STARVED"
- `M1_Equipment/OperationsState/State` often shows "BLOCKED" (buffer full)
- `B1_StorageUnit/CurrentLevel` fluctuates near 0

**Use case:** Understanding bottlenecks and buffer dynamics

---

### Scenario C: Failure Line

**File:** `failure_line`
**Complexity:** ⭐⭐⭐ Intermediate

```yaml
machines:
  - name: M1
    cycle_time: 1
    enable_degradation: true
    degradation_matrix: [[0.99, 0.01], [0.0, 1.0]]
    cbm_threshold: 1

  - name: M2
    cycle_time: 1
    enable_degradation: false

maintainer:
  enabled: true
  capacity: 1
```

**Characteristics:**
- M1 can fail (1% chance per step)
- Maintainer repairs M1 when failed
- M2 is reliable (no failures)
- Throughput drops during M1 failures

**Observations:**
- `M1_Equipment/OperationsState/State` cycles: PROCESSING → FAILED → UNDER_REPAIR → PROCESSING
- `M1_Equipment/OperationsState/HealthState` = 0 (healthy) or 1 (failed)
- `SupportFunctions/Maintenance/MaintenanceActive` = true during repairs
- Buffer drains when M1 is down

**Use case:** Learning failure/maintenance modeling

---

### Scenario D: Extended Line

**File:** `extended_line`
**Complexity:** ⭐⭐⭐ Intermediate

```yaml
machines: [M1, M2, M3]  # 3 machines
buffers: [B1, B2]       # 2 buffers
```

**Characteristics:**
- 3-machine serial line
- Two decoupling buffers
- More complex dynamics

**Use case:** Multi-buffer systems, longer production lines

---

### Scenario E: Quality Line

**File:** `quality_line`
**Complexity:** ⭐⭐⭐ Intermediate

```yaml
machines:
  - name: M1
    cycle_time: 1
    defect_rate: 0.03           # 3% defects
    health_multiplier: 5.0      # 15% when failed
    enable_degradation: true
```

**Characteristics:**
- Machines produce defects
- Defect rate increases when machine health degrades
- Real Quality OEE calculation

**Observations:**
- `M1_Equipment/OEE/Quality` < 1.0 (defects reduce quality)
- `M1_Equipment/OEE/DefectivePartCount` increases
- `M1_Equipment/Alarms/QualityAlertActive` triggers if >5% defects

**Use case:** Quality modeling and OEE analysis

---

### Scenario F: Advanced Failure Line

**File:** `advanced_failure_line`
**Complexity:** ⭐⭐⭐⭐ Advanced

```yaml
machines:
  - name: M1
    enable_advanced_failures: true
    failure_modes:
      - name: mechanical
        type: wearout
        mttf: {distribution: weibull, shape: 2.5, scale: 500}
      - name: electrical
        type: random
        mttf: {distribution: exponential, mean: 1000}
```

**Characteristics:**
- Multiple failure modes (competing risks)
- Realistic MTTF/MTTR distributions
- Weibull for wear-out, exponential for random failures
- MTBF/MTTR tracking per failure mode

**Observations:**
- `M1_Equipment/FailureModes/ActiveFailureMode` shows which mode failed
- `M1_Equipment/FailureModes/MechanicalMTBF` shows mean time between failures
- More realistic failure patterns than simple degradation

**Use case:** Realistic reliability modeling

---

### Scenario G: SPC Quality Line

**File:** `spc_quality_line`
**Complexity:** ⭐⭐⭐⭐ Advanced

```yaml
machines:
  - name: M1
    enable_spc: true
    spc:
      subgroup_size: 5
      usl: 1.2
      lsl: 0.8
```

**Characteristics:**
- Statistical Process Control (SPC) analytics
- X-bar and R control charts
- Cp/Cpk capability analysis
- Western Electric rules

**Observations:**
- `M1_Equipment/SPC/Capability/Cpk` shows process capability
- `M1_Equipment/SPC/Status/InControl` = false when out of control
- `M1_Equipment/SPC/Status/Violations` lists rule violations

**Use case:** Quality control and Six Sigma analysis

---

### Scenario H: Combined Advanced + SPC

**File:** `advanced_spc_line`
**Complexity:** ⭐⭐⭐⭐⭐ Expert

**Characteristics:**
- Combines advanced failure modes with SPC
- Most realistic and complete simulation
- All advanced features enabled

**Use case:** Comprehensive digital twin demonstration

---

### Scenario I: Shift Line

**File:** `shift_line`
**Complexity:** ⭐⭐ Beginner

```yaml
machines:
  - name: M1
    cycle_time: 1
    defect_rate: 0.02
  - name: M2
    cycle_time: 1
    defect_rate: 0.01

shifts:
  schedule:
    - name: "Day Shift"
      duration: 28800
    - name: "Evening Shift"
      duration: 28800
    - name: "Night Shift"
      duration: 28800
```

**Characteristics:**
- 2-machine line with 3-shift rotation (8 hours each)
- Per-shift production metrics (parts, defects, OEE)
- Automatic shift rotation with console notifications
- Cumulative totals preserved across shifts

**Observations:**
- `ShiftManagement/CurrentShiftName` changes at each boundary (Day → Evening → Night → Day)
- `ShiftManagement/CurrentShift/PartsProduced` resets to 0 at each shift change
- `ShiftManagement/Totals/TotalPartsProduced` always increases (never resets)
- `ShiftManagement/ShiftTimeRemaining` counts down to next shift change

**Use case:** Learning shift-based production tracking and reporting

---

### Scenario J: Advanced Shift Line

**File:** `advanced_shift_line`
**Complexity:** ⭐⭐⭐⭐⭐ Expert

**Characteristics:**
- 2-machine line with shift tracking + advanced failures + SPC + quality
- All features enabled simultaneously
- Per-shift failure tracking and OEE
- Predictive maintenance strategy

**Observations:**
- Shift OEE varies as failures occur within shifts
- `ShiftManagement/CurrentShift/Availability` reflects per-shift uptime
- Failure counts tracked per machine per shift
- Previous shift summary available for comparison

**Use case:** Full-featured digital twin with shift management

---

### Scenario K: Scrap Line

**File:** `scrap_line`
**Complexity:** ⭐⭐⭐ Intermediate

```yaml
machines:
  - name: M1
    cycle_time: 1
    enable_degradation: true
    quality_routing:
      enabled: true
      mode: scrap
      defect_rate: 0.05
      scrap_sink: ScrapBin1
  - name: M2
    cycle_time: 1
    quality_routing:
      enabled: true
      mode: scrap
      defect_rate: 0.02
      scrap_sink: ScrapBin2

scrap_sinks:
  - name: ScrapBin1
  - name: ScrapBin2
```

**Characteristics:**
- Defective parts diverted to dedicated scrap sinks
- Each machine routes to its own scrap bin
- Main serial chain unaffected by scrap routing
- Scrap rate visible in OPC UA

**Observations:**
- `M1_Equipment/QualityRouting/ScrapCount` increases as defects occur
- `OperationsPerformance/TotalScrap` shows total scrapped parts
- `OperationsPerformance/ScrapRate` shows overall scrap percentage
- Buffer levels unaffected (scrap goes to side bins, not downstream)

**Use case:** Quality-based routing with scrap tracking

---

### Scenario L: Rework Line

**File:** `rework_line`
**Complexity:** ⭐⭐⭐⭐ Advanced

```yaml
machines:
  - name: M1
    cycle_time: 1
    quality_routing:
      enabled: true
      mode: scrap_and_rework
      defect_rate: 0.08
      rework_success_rate: 0.7
      max_rework: 3
      scrap_sink: ScrapBin1

scrap_sinks:
  - name: ScrapBin1
```

**Characteristics:**
- Defective parts get rework attempts before scrapping
- 70% chance each rework attempt fixes the part
- Up to 3 rework attempts per part
- Failed rework routes to scrap sink

**Observations:**
- `M1_Equipment/QualityRouting/ReworkCount` shows total rework attempts
- `M1_Equipment/QualityRouting/ReworkSuccessCount` shows successful reworks
- `M1_Equipment/QualityRouting/ReworkSuccessRate` shows success percentage
- Many defective parts are "saved" by rework, reducing scrap

**Use case:** Virtual rework modeling and scrap reduction analysis

---

### Scenario M: Full Feature Line

**File:** `full_feature_line`
**Complexity:** ⭐⭐⭐⭐⭐ Expert

**Characteristics:**
- Combines ALL features
- Advanced failures (Weibull mechanical + exponential electrical)
- SPC analytics with Western Electric rules
- Quality routing with scrap and rework
- 3-shift rotation with per-shift metrics
- CSV event historian logging all event types
- Predictive maintenance strategy

**Run it:**
```bash
python src/opcua_server.py --scenario full_feature_line --seed 42
```

**Observations:**
- Full OPC UA address space with all node types
- CSV event log at `results/historian/` tracks all events
- Shift OEE varies as failures and scrap occur within shifts
- SCRAP and REWORK events appear in historian alongside state changes

**Use case:** Complete digital twin demonstration with every feature enabled

---

### Scenario N: Full Feature 8-Machine Line

**File:** `full_feature_8_machine_line`
**Complexity:** Expert

**Characteristics:**
- 8 machines in serial with 7 buffers
- All features: advanced failures, SPC on all 8 machines, quality routing, 3-shift rotation, CSV historian
- Scrap sinks per machine, rework on selected machines
- Predictive and corrective maintenance strategies

**Run it:**
```bash
python src/opcua_server.py --scenario full_feature_8_machine_line --seed 42
```

**Use case:** Full-scale digital twin at production line scale. Stress-testing OPC UA address space, Telegraf polling, and Grafana dashboards with many machines.

---

### Scenario O: Warm-Up Line

**File:** `warm_up_line`
**Complexity:** Intermediate

**Characteristics:**
- 2-machine line with `warm_up_time: 300` (5 minutes)
- Simantha runs the simulation for `warm_up_time + sim_time` but only collects data (sink.level, parts_made, quality counters) after the warm-up period
- Produces more accurate steady-state metrics by discarding the transient start-up phase

**Run it:**
```bash
python src/opcua_server.py --scenario warm_up_line --seed 42
```

**Use case:** Understanding the warm-up feature and steady-state analysis

---

### Additional Scenarios

The following scenarios are also available in `config/line_models.yaml`:

| Scenario | Description |
|----------|-------------|
| `priority_maintenance_line` | PriorityMaintainer with configurable scheduling (FIFO, SPT, priority, bottleneck) |
| `multi_state_degradation_line` | Multi-state health degradation (0 → 1 → 2 → ... → h_max) with DEGRADED state |
| `historian_line` | Basic CSV historian without other advanced features |
| `influxdb_historian_line` | InfluxDB historian backend |
| `neo4j_historian_line` | Neo4j graph database historian |

---

## 9. OPC UA Address Space Reference

### ISA-95/ISO 23247 Hierarchy

The address space follows the ISA-95 (IEC 62264) equipment hierarchy:

```
Objects / {Enterprise} / {Site} / {Area} / {Line}_Equipment /
```

Default names: `WeylandIndustries / LV426_Colony / AtmosphereProcessor01 / Nostromo_BioProductPakaging_Equipment`. These are configurable via YAML keys (`enterprise`, `site`, `area`, `line_name`).

### Top-Level Structure

Under the Equipment node:

| Node | Description |
|------|-------------|
| `Identification/` | Line metadata (EquipmentID, Class, Description) |
| `OperationsState/` | SimTime, LineState, LineMode, Controls (writable) |
| `OperationsPerformance/` | Throughput, TotalWIP, TotalScrap, ScrapRate |
| `OEE/` | Line-level Availability, Performance, Quality, OEE |
| `Resources/` | Machine, Buffer, and ScrapBin nodes |
| `SupportFunctions/` | Maintenance, ShiftManagement |
| `EventLog/` | TotalEventsGenerated |

**Controls (under `OperationsState/Controls/`):**

| Variable | Access | Type | Description |
|----------|--------|------|-------------|
| `SetInterarrivalTime` | **READ** | Double | Inter-arrival delay set at run start. Read-only during the run. |

> **Note:** `CmdPauseLine` (runtime pause) was removed in v2.6. `SetInterarrivalTime` is now a start-time parameter only — set it via the Web UI before starting a run.

---

### `Resources / M{i}_Equipment /` *(per machine)*

Each machine node (e.g., `M1_Equipment`, `M2_Equipment`) has ISA-95 sub-groups:

| Sub-group | Variable | Type | Description |
|-----------|----------|------|-------------|
| `Identification/` | `EquipmentID`, `EquipmentClass` | String | Machine identity |
| `OperationsState/` | `State` | String | IDLE, PROCESSING, BLOCKED, STARVED, PAUSED, FAILED, UNDER_REPAIR, DEGRADED |
| | `HealthState` | Int32 | 0 = healthy, N = failed |
| | `HealthPercent` | Double | Health percentage |
| | `BlockedTime`, `StarvedTime`, `DownTime`, `ProcessingTime`, `IdleTime` | Double | Cumulative state times |
| `OperationsPerformance/` | `PartCount` | Int32 | Parts processed (monotonic) |
| | `Utilisation` | Double | ProcessingTime / TotalTime |
| | `TargetPPM`, `ActualPPM` | Double | Target and actual parts per minute |

**`M{i}_Equipment / OEE /`**

| Variable | Access | Type | Description |
|----------|--------|------|-------------|
| `Availability` | READ | Double | (TotalTime - DownTime) / TotalTime |
| `Performance` | READ | Double | ActualOutput / TheoreticalOutput |
| `Quality` | READ | Double | GoodParts / TotalParts |
| `OEE` | READ | Double | Availability x Performance x Quality |
| `GoodPartCount` | READ | Int32 | Parts without defects |
| `DefectivePartCount` | READ | Int32 | Defective parts |
| `TheoreticalOutput` | READ | Double | Theoretical max output |

**`M{i}_Equipment / Alarms /`**

| Variable | Access | Type | Description |
|----------|--------|------|-------------|
| `ActiveAlarmCount` | READ | Int32 | Number of active alarms |
| `MachineFailedActive` | READ | Boolean | Failure alarm active |
| `MaintenanceActive` | READ | Boolean | Maintenance alarm active |
| `QualityAlertActive` | READ | Boolean | Quality alert active |

**`M{i}_Equipment / QualityRouting /`** *(if `quality_routing.enabled: true`)*

| Variable | Access | Type | Description |
|----------|--------|------|-------------|
| `ScrapCount` | READ | Int32 | Total parts sent to scrap sink |
| `ReworkCount` | READ | Int32 | Total rework attempts |
| `ReworkSuccessCount` | READ | Int32 | Successful reworks (part became good) |
| `ReworkSuccessRate` | READ | Double | ReworkSuccessCount / ReworkCount |
| `GoodCount` | READ | Int32 | Total good parts (including successful reworks) |

**`M{i}_Equipment / FailureModes /`** *(if `enable_advanced_failures: true`)*

| Variable | Access | Type | Description |
|----------|--------|------|-------------|
| `ActiveFailureMode` | READ | String | Current failure mode or "none" |
| `{Mode}FailureCount` | READ | Int32 | Total failures for this mode |
| `{Mode}TotalDowntime` | READ | Double | Cumulative downtime |
| `{Mode}MTBF` | READ | Double | Mean time between failures |
| `{Mode}MTTR` | READ | Double | Mean time to repair |

**`M{i}_Equipment / MaintenanceStrategy /`** *(if `enable_advanced_failures: true`)*

| Variable | Access | Type | Description |
|----------|--------|------|-------------|
| `StrategyType` | READ | String | corrective / preventive / predictive |
| `NextPMScheduled` | READ | Double | Next preventive maintenance time |
| `PMCount` | READ | Int32 | Preventive maintenance count |
| `CMCount` | READ | Int32 | Corrective maintenance count |

**`M{i}_Equipment / SPC /`** *(if `enable_spc: true`)*

| Group | Variable | Type | Description |
|-------|----------|------|-------------|
| `XBarChart/` | `XBar` | Double | Current subgroup mean |
| | `UCL` | Double | Upper control limit |
| | `CL` | Double | Center line |
| | `LCL` | Double | Lower control limit |
| `RChart/` | `Range` | Double | Current subgroup range |
| | `UCL` | Double | Upper control limit |
| | `CL` | Double | Center line |
| | `LCL` | Double | Lower control limit |
| `Capability/` | `Cp` | Double | Process capability |
| | `Cpk` | Double | Process capability index |
| | `Pp` | Double | Process performance |
| | `Ppk` | Double | Process performance index |
| | `SigmaLevel` | Double | Sigma quality level (2-6) |
| `Status/` | `InControl` | Int32 | Process in statistical control (1=in control, 0=out of control; stored as int so Telegraf/InfluxDB receives a numeric field) |
| | `ViolationCount` | Int32 | Number of active Western Electric rule violations (use this for Grafana/InfluxDB) |
| | `Violations` | String | Human-readable violation descriptions, e.g. `"Rule1: Point beyond 3σ"` (string — not forwarded by Telegraf's OPC UA plugin into InfluxDB) |
| | `TotalSamples` | Int32 | Total measurements |
| | `NumSubgroups` | Int32 | Complete subgroups analyzed |

---

### `Resources / B{i}_StorageUnit /` *(per buffer)*

Each buffer node (e.g., `B1_StorageUnit`, `B2_StorageUnit`):

| Variable | Access | Type | Description |
|----------|--------|------|-------------|
| `CurrentLevel` | READ | Int32 | Current WIP count |
| `Capacity` | READ | Int32 | Max buffer capacity |

**`B{i}_StorageUnit / Alarms /`**

| Variable | Access | Type | Description |
|----------|--------|------|-------------|
| `ActiveAlarmCount` | READ | Int32 | Number of active alarms |
| `HighLevelWarningActive` | READ | Boolean | Buffer >90% full |
| `LowLevelWarningActive` | READ | Boolean | Buffer <10% full |

---

### `Resources / {ScrapName}_StorageUnit /` *(per scrap sink, if configured)*

Each scrap sink (e.g., `ScrapBin1_StorageUnit`, `ScrapBin2_StorageUnit`):

| Variable | Access | Type | Description |
|----------|--------|------|-------------|
| `CurrentLevel` | READ | Int32 | Number of scrapped parts in this bin |

---

### `SupportFunctions / Maintenance /`

| Variable | Access | Type | Description |
|----------|--------|------|-------------|
| `MaintenanceActive` | READ | Boolean | Maintainer currently busy |
| `QueueLength` | READ | Int32 | Machines waiting for repair |
| `TotalRepairs` | READ | Int32 | Completed repairs count |

---

### `SupportFunctions / ShiftManagement /` *(if `shifts` configured)*

| Variable | Access | Type | Description |
|----------|--------|------|-------------|
| `CurrentShiftNumber` | READ | Int32 | Sequential shift counter (1, 2, 3...) |
| `CurrentShiftName` | READ | String | "Day Shift", "Evening Shift", etc. |
| `ShiftStartTime` | READ | Double | Sim time when shift started |
| `ShiftEndTime` | READ | Double | Sim time when shift ends |
| `ShiftDuration` | READ | Double | Shift length in time units |
| `ShiftElapsedTime` | READ | Double | Time spent in current shift |
| `ShiftTimeRemaining` | READ | Double | Countdown to next shift |

**`ShiftManagement / CurrentShift /`** *(resets at each shift boundary)*

| Variable | Access | Type | Description |
|----------|--------|------|-------------|
| `PartsProduced` | READ | Int32 | Parts produced this shift |
| `GoodParts` | READ | Int32 | Good parts this shift |
| `DefectiveParts` | READ | Int32 | Defective parts this shift |
| `DefectRate` | READ | Double | Defect rate this shift (0.0-1.0) |
| `Availability` | READ | Double | Shift availability (0.0-1.0) |
| `Performance` | READ | Double | Shift performance (0.0-1.0) |
| `Quality` | READ | Double | Shift quality (0.0-1.0) |
| `OEE` | READ | Double | Shift OEE = A x P x Q |

**`ShiftManagement / PreviousShift /`** *(snapshot of last completed shift)*

| Variable | Access | Type | Description |
|----------|--------|------|-------------|
| `ShiftNumber` | READ | Int32 | Number of previous shift |
| `ShiftName` | READ | String | Name of previous shift |
| `PartsProduced` | READ | Int32 | Parts in previous shift |
| `GoodParts` | READ | Int32 | Good parts in previous shift |
| `DefectiveParts` | READ | Int32 | Defective parts in previous shift |
| `DefectRate` | READ | Double | Defect rate of previous shift |
| `OEE` | READ | Double | OEE of previous shift |

**`ShiftManagement / Totals /`** *(cumulative across all shifts, NEVER reset)*

| Variable | Access | Type | Description |
|----------|--------|------|-------------|
| `TotalPartsProduced` | READ | Int32 | Sum of parts across all shifts |
| `TotalGoodParts` | READ | Int32 | Sum of good parts across all shifts |
| `TotalDefectiveParts` | READ | Int32 | Sum of defects across all shifts |
| `TotalDefectRate` | READ | Double | Overall defect rate |
| `TotalShiftsCompleted` | READ | Int32 | Number of completed shifts |

---

### `EventLog /`

| Variable | Access | Type | Description |
|----------|--------|------|-------------|
| `TotalEventsGenerated` | READ | Int32 | Total event count |

### Data Types Reference

| OPC UA Type | Python Type | Range | Example |
|-------------|-------------|-------|---------|
| Boolean | bool | true/false | PauseLine = true |
| Int32 | int | -2³¹ to 2³¹-1 | PartCount = 142 |
| Double | float | ±1.7e±308 | SimTime = 351.0 |
| String | str | Text | State = "PROCESSING" |
| DateTime | datetime | Timestamp | 2026-02-08T14:30:00Z |

---

## 10. Advanced Features

### Feature 1: Command Line Arguments

**Usage:**
```bash
python src/opcua_server.py [OPTIONS]
```

**Options:**

| Argument | Description | Default | Example |
|----------|-------------|---------|---------|
| `--scenario` | Scenario name from YAML | balanced_line | `--scenario failure_line` |
| `--recipe` | Recipe name from `config/recipes/` (mutually exclusive with `--scenario`) | — | `--recipe monday_schedule` |
| `--seed` | Random seed (see below) | Auto-generated | `--seed 42` |
| `--trace` | Enable DES event tracing (pickle output) | off | `--trace` |

**Examples:**

```bash
# Run specific scenario
python src/opcua_server.py --scenario bottleneck_line

# Reproducible run with fixed seed
python src/opcua_server.py --scenario quality_line --seed 123

# Full-feature 8-machine line with reproducibility
python src/opcua_server.py --scenario full_feature_8_machine_line --seed 42

# Warm-up line with tracing
python src/opcua_server.py --scenario warm_up_line --seed 42 --trace
```

#### Understanding `--seed` (Randomness and Reproducibility)

The `--seed` argument controls all random behavior in the simulation. This is essential for reproducible experiments.

**What `--seed` affects:**
- Defect generation (which parts are defective)
- Quality routing decisions (scrap vs. rework outcome)
- SPC measurement noise (the Gaussian noise added to cycle time measurements)
- MTTF/MTTR sampling (when machines fail and how long repairs take, via scipy distributions)
- Degradation transitions (Markov chain state changes)

**How it works:**

The seed is applied to both Python's `random` module and NumPy's `numpy.random` before **every** simulation step. This is necessary because Simantha re-runs the entire simulation from time 0 on each step (see Section 5 architecture). Without re-seeding, the RNG state would differ between steps, causing KPIs like throughput and scrap count to fluctuate unpredictably.

```
Step 1: seed(42) → simulate(0..1)   → sink.level = 1
Step 2: seed(42) → simulate(0..2)   → sink.level = 2  (events in 0..1 identical)
Step 3: seed(42) → simulate(0..3)   → sink.level = 3  (events in 0..2 identical)
```

**Auto-generated seeds:**

If `--seed` is omitted, a seed is automatically generated from the current timestamp and printed to the console at startup:

```
Auto-generated seed: 1740512345
```

You can copy this seed value and use it with `--seed 1740512345` to reproduce the exact same run later.

**Limitations:**

Simantha's internal RNG (used for its Markov chain transitions) is not directly controllable. However, since both `random` and `numpy.random` are re-seeded, the vast majority of random behavior is reproducible. Minor variations may occur in Simantha's internal scheduling.

**Practical tips:**
- Use `--seed 42` (or any fixed value) when comparing scenarios or debugging
- Omit `--seed` for realistic "random each time" behavior
- Record the auto-generated seed from the console if you want to reproduce an interesting run

### Feature 2: Programmatic Monitoring

**Python script to read simulation data:**

```python
import time
from opcua import Client

client = Client("opc.tcp://localhost:4840/simantha/")
client.connect()

try:
    root = client.get_objects_node()
    enterprise = root.get_child(["2:WeylandIndustries"])
    site = enterprise.get_child(["2:LV426_Colony"])
    area = site.get_child(["2:AtmosphereProcessor01"])
    equip = area.get_child(["2:Nostromo_BioProductPakaging_Equipment"])

    # Read line KPIs
    ops_perf = equip.get_child(["2:OperationsPerformance"])
    throughput = ops_perf.get_child(["2:Throughput"])

    # Read interarrival time set at run start (read-only during run)
    controls = equip.get_child(["2:OperationsState", "2:Controls"])
    interarrival = controls.get_child(["2:SetInterarrivalTime"])
    print(f"Interarrival time: {interarrival.get_value()}")

    # Poll throughput
    print("Monitoring throughput...")
    for _ in range(10):
        print(f"Throughput: {throughput.get_value()}")
        time.sleep(5)

finally:
    client.disconnect()
```

> **Note (v2.6+):** All OPC UA variables are read-only during a run. `SetInterarrivalTime` is set before starting via the Web UI. `CmdPauseLine` was removed — use the Web UI Stop button to end a run.

### Feature 3: Data Logging

**Log data to CSV using Python:**

```python
import csv
import time
from opcua import Client

client = Client("opc.tcp://localhost:4840/simantha/")
client.connect()

root = client.get_objects_node()
enterprise = root.get_child(["2:WeylandIndustries"])
site = enterprise.get_child(["2:LV426_Colony"])
area = site.get_child(["2:AtmosphereProcessor01"])
equip = area.get_child(["2:Nostromo_BioProductPakaging_Equipment"])

# Get variables to log
ops_state = equip.get_child(["2:OperationsState"])
sim_time = ops_state.get_child(["2:SimTime"])
ops_perf = equip.get_child(["2:OperationsPerformance"])
throughput = ops_perf.get_child(["2:Throughput"])

resources = equip.get_child(["2:Resources"])
m1 = resources.get_child(["2:M1_Equipment"])
state = m1.get_child(["2:OperationsState", "2:State"])
util = m1.get_child(["2:OperationsPerformance", "2:Utilisation"])

# Open CSV file
with open('simulation_log.csv', 'w', newline='') as csvfile:
    writer = csv.writer(csvfile)
    writer.writerow(['Timestamp', 'SimTime', 'Throughput', 'M1_State', 'M1_Util'])

    try:
        while True:
            row = [
                time.time(),
                sim_time.get_value(),
                throughput.get_value(),
                state.get_value(),
                util.get_value()
            ]
            writer.writerow(row)
            csvfile.flush()  # Write to disk
            time.sleep(1)  # Sample every second
    except KeyboardInterrupt:
        print("Logging stopped")

client.disconnect()
```

### Feature 4: Shift Monitoring

**Monitor shift changes and per-shift KPIs:**

```python
import time
from opcua import Client

client = Client("opc.tcp://localhost:4840/simantha/")
client.connect()

try:
    root = client.get_objects_node()
    enterprise = root.get_child(["2:WeylandIndustries"])
    site = enterprise.get_child(["2:LV426_Colony"])
    area = site.get_child(["2:AtmosphereProcessor01"])
    equip = area.get_child(["2:Nostromo_BioProductPakaging_Equipment"])
    support = equip.get_child(["2:SupportFunctions"])
    shift = support.get_child(["2:ShiftManagement"])

    # Current shift info
    shift_name = shift.get_child(["2:CurrentShiftName"])
    shift_remaining = shift.get_child(["2:ShiftTimeRemaining"])
    shift_number = shift.get_child(["2:CurrentShiftNumber"])

    # Current shift production
    current = shift.get_child(["2:CurrentShift"])
    parts = current.get_child(["2:PartsProduced"])
    oee = current.get_child(["2:OEE"])

    # Totals across all shifts
    totals = shift.get_child(["2:Totals"])
    total_parts = totals.get_child(["2:TotalPartsProduced"])
    total_shifts = totals.get_child(["2:TotalShiftsCompleted"])

    prev_shift_num = shift_number.get_value()

    while True:
        current_num = shift_number.get_value()
        if current_num != prev_shift_num:
            print(f"\n--- SHIFT CHANGE ---")
            prev_shift_num = current_num

        print(f"Shift {current_num}: {shift_name.get_value()} | "
              f"Parts: {parts.get_value()} | "
              f"OEE: {oee.get_value():.1%} | "
              f"Remaining: {shift_remaining.get_value():.0f}s | "
              f"Total: {total_parts.get_value()} ({total_shifts.get_value()} shifts)")
        time.sleep(5)

except KeyboardInterrupt:
    pass
finally:
    client.disconnect()
```

### Feature 5: Alarm Monitoring

**Subscribe to alarm changes:**

```python
import time
from opcua import Client

class AlarmHandler:
    def datachange_notification(self, node, val, data):
        print(f"ALARM: {node} = {val}")

client = Client("opc.tcp://localhost:4840/simantha/")
client.connect()

root = client.get_objects_node()
enterprise = root.get_child(["2:WeylandIndustries"])
site = enterprise.get_child(["2:LV426_Colony"])
area = site.get_child(["2:AtmosphereProcessor01"])
equip = area.get_child(["2:Nostromo_BioProductPakaging_Equipment"])
resources = equip.get_child(["2:Resources"])
m1 = resources.get_child(["2:M1_Equipment"])
alarms = m1.get_child(["2:Alarms"])

# Subscribe to failure alarm
failure_alarm = alarms.get_child(["2:MachineFailedActive"])
handler = AlarmHandler()
sub = client.create_subscription(1000, handler)
handle = sub.subscribe_data_change(failure_alarm)

print("Monitoring alarms... Press Ctrl+C to stop")
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    pass

sub.unsubscribe(handle)
sub.delete()
client.disconnect()
```

### Feature 6: Event Historian (CSV / InfluxDB / Neo4j)

The built-in event historian records simulation events to files or databases for post-analysis.

**Enable CSV historian** (simplest - no external dependencies):

```yaml
# In line_models.yaml, add to your scenario:
full_feature_line:
  historian:
    backend: csv
    output_dir: results/historian
    events:
      - STATE_CHANGE
      - MAINTENANCE_START
      - MAINTENANCE_END
      - QUALITY_ALERT
      - BUFFER_HIGH
      - BUFFER_LOW
      - SHIFT_CHANGE
      - SPC_VIOLATION
      - SCRAP
      - REWORK
```

**Run and find output:**

```bash
python src/opcua_server.py --scenario full_feature_line --seed 42

# CSV output is stored at:
#   results/historian/events_YYYYMMDD_HHMMSS.csv
```

**CSV columns:**

| Column | Description | Example |
|--------|-------------|---------|
| `run_id` | Unique run identifier | full_feature_line_20260226_143000 |
| `timestamp` | Simulation time (seconds) | 351.0 |
| `wall_clock` | Real wall-clock time | 2026-02-09T14:30:00 |
| `event_type` | Event category | STATE_CHANGE |
| `source` | Equipment name | M1 |
| `source_type` | Equipment type | machine |
| `severity` | LOW / MEDIUM / HIGH / CRITICAL | CRITICAL |
| `message` | Human-readable description | M1 failed |
| `old_state` | Previous state (for STATE_CHANGE) | PROCESSING |
| `new_state` | New state (for STATE_CHANGE) | FAILED |
| `partcount` | Part count at event time | 142 |
| `oee` | OEE at event time | 0.85 |
| `extra_json` | Additional event data (JSON) | {"cpk": 0.85} |

**InfluxDB historian** (for Grafana dashboards):

```yaml
historian:
  backend: influxdb
  influxdb:
    url: http://localhost:8086
    token: ${INFLUXDB_TOKEN}   # Reads from environment variable
    org: my-org
    bucket: simantha
  events:
    - STATE_CHANGE
    - SCRAP
```

**Neo4j historian** (for topology graphs):

```yaml
historian:
  backend: neo4j
  neo4j:
    uri: bolt://localhost:7687
    user: neo4j
    password: ${NEO4J_PASSWORD}
  events:
    - STATE_CHANGE
    - MAINTENANCE_START
```

**Grafana Integration:**

The Docker stack auto-provisions 10 pre-built dashboards:

| Dashboard | Purpose |
|-----------|---------|
| Manufacturing Overview | Line OEE, throughput, WIP, scrap rate, buffer levels |
| OEE Detail | Availability, Performance, Quality breakdown per machine |
| Machine KPIs | Per-machine PPM, cycle time, utilisation, SPC summary |
| Machine State Timeline | State-transition Gantt chart (IDLE/PROCESSING/BLOCKED/STARVED/DEGRADED/FAILED/UNDER_REPAIR) |
| Downtime & Reliability | MTBF/MTTR/FailureCount per failure mode per machine |
| SPC Control Charts | X-bar/R charts, capability indices (Cp/Cpk), violation count per machine |
| SPC Machine Detail | Deep-dive SPC for a selected machine |
| Shift Comparison | Current vs previous shift (A/P/Q/OEE bar gauges), completed-shift history step charts |
| Alarm Event Log | Live machine failure status, alarm rate over time, colour-coded event log |
| Line Balance | Bottleneck identification, throughput and utilisation comparison across machines |

All dashboards are scoped by `run_id` (top-left dropdown) so multiple runs can be stored and compared in the same InfluxDB instance. Custom dashboards can query the `manufacturing` bucket filtering on `event_type`:

```flux
from(bucket: "manufacturing")
  |> range(start: -1h)
  |> filter(fn: (r) => r._measurement == "sim_events")
  |> filter(fn: (r) => r.event_type == "SCRAP")
```

---

### Feature 7: Real-Time Simulation Architecture

#### The Quadratic Growth Problem (and Why It Matters)

Simantha's simulation engine always runs from time 0. A call to `system.simulate(simulation_time=N)` creates a fresh SimPy environment, reinitialises all objects, and replays the entire production line from the start up to time N.

If the server calls `simulate(N)` at step N, the compute cost is O(N) per step and O(N²) total:

```
Step 1:   simulate(0 → 1)     — 1 unit of work
Step 2:   simulate(0 → 2)     — 2 units of work
Step 3:   simulate(0 → 3)     — 3 units of work
...
Step K:   simulate(0 → K)     — K units of work
Total:    1 + 2 + 3 + ... + K = K(K+1)/2 ≈ K²/2
```

**This is why a run showing "4h 48m sim time" might have taken "16h 55m wall time"** — the sim clock started near-real-time and then fell behind as the quadratic cost accumulated. The Run History page shows both durations so you can see the divergence.

For short experiments (minutes of factory time) the growth is invisible. For multi-shift or continuous simulations it eventually makes the process impractically slow and would exhaust memory.

#### The Per-Step Architecture (Current)

The server now calls `system.simulate(simulation_time=1)` once per loop iteration — always simulating one second of factory time from a fresh environment. Compute cost is O(1) per step and O(N) total:

```
Wall second 1:   simulate(0 → 1)   — 1 unit of work always
Wall second 2:   simulate(0 → 1)   — 1 unit of work always
...
Wall second K:   simulate(0 → 1)   — 1 unit of work always
Total:           K units (linear, not quadratic)
```

The wall-clock pacer at the top of each loop iteration measures how much time the simulate + OPC UA work consumed, then sleeps only for the remainder of the 1-second budget:

```python
elapsed = time.time() - step_wall_start
time.sleep(max(0.0, real_step - elapsed))
```

This keeps sim-time and wall-clock tightly in sync throughout a run — one sim-second equals approximately one wall-clock second, indefinitely.

#### Reproducibility

With the previous O(N²) architecture, reproducibility was guaranteed by replaying the entire history with the same seed. With per-step simulate, reproducibility works differently but is equally strong:

- The seed **advances per step**: `step_seed = (base_seed + step_count) % 2³¹`
- The same `--seed` value always produces the same sequence of per-step RNG states
- Same seed → same defect decisions, same MTTF draws, same quality routing outcomes at every step

**The key insight:** you don't need to replay history to get a reproducible trajectory. A fixed seed gives a fixed sequence of per-step seeds, which gives a fixed sequence of outcomes, which gives a reproducible trajectory.

```bash
# These two runs produce identical KPI curves:
python src/opcua_server.py --scenario full_feature_line --seed 42
python src/opcua_server.py --scenario full_feature_line --seed 42
```

#### Machine Health State Continuity

One challenge with per-step simulation is that Simantha's `initialize()` resets `machine.health` to 0 at the start of every `simulate()` call. Without a fix, machines would never accumulate degradation across steps.

The server monkey-patches each `machine.initialize()` to restore the saved health value immediately after Simantha's reset:

```
Step N:   machine.health = H (from previous step)
          → simulate(1): Simantha calls initialize() → health resets to 0
             → patched initialize restores health = H
             → machine runs from health H for 1 second
          → after simulate: save new health = machine.health
Step N+1: repeat with new health
```

This means degradation and CBM/failure cycles accumulate correctly across the run, matching the intended physics of the `health_states` configuration.

#### Architecture Options Considered

Three approaches were evaluated before settling on the per-step architecture:

| Option | Cost | Wall-clock sync | Reproducibility |
|--------|------|-----------------|-----------------|
| **O(N²) cumulative** (previous) | Grows to unusable | Degrades on long runs | Exact, by replaying history |
| **Per-step O(1)** (current) | Constant forever | Tight, indefinitely | Per-step seeding |
| **Lookahead buffer** (considered) | O(1) producer + consumer | Consumer paced at real-time | Per-step seeding |

The lookahead buffer (producer runs simulate fast into a bounded queue; consumer publishes to OPC UA at real-time rate) was considered but deferred: the per-step architecture already achieves real-time sync with O(1) cost, and the additional threading complexity is only warranted if the simulate step itself becomes a bottleneck (which it does not for current scenario sizes).

#### What Was Removed

In the migration to the per-step architecture, two runtime controls were removed:

- **`CmdPauseLine`** — Boolean OPC UA write that paused the simulation. Removed because it required invalidating the simulation state mid-run, which is incompatible with the per-step health continuity model. Use the Web UI Stop button instead.
- **`SetInterarrivalTime` as a writable node** — Reduced to a read-only node showing the value set at run start. Set it via the Web UI before starting; it cannot be changed while the simulation is running.
- **`--mode` CLI flag** — The `reproducible` vs `realtime` choice is gone; there is now one unified architecture.

---

### Feature 8: OPC UA PubSub over MQTT

The simulation can publish live data to an MQTT broker alongside the OPC UA server. This enables lightweight subscribers (Node-RED, browser clients, SCADA adapters) to consume data without a full OPC UA stack.

#### Enabling MQTT PubSub

```bash
# Enable with default broker (mqtt://mosquitto:1883 — Docker internal)
python src/opcua_server.py --mqtt

# Specify a custom broker
python src/opcua_server.py --mqtt --mqtt-broker mqtt://localhost:1883

# Works with any scenario or recipe
python src/opcua_server.py --scenario full_feature_line --seed 42 --mqtt
python src/opcua_server.py --recipe monday_schedule --seed 42 --mqtt
```

The MQTT publisher is **non-blocking** — if the broker is unreachable, the simulation continues normally and missed steps are silently dropped.

#### Topic Layout

Two topic trees are published per simulation step:

| Topic | Format | Content |
|-------|--------|---------|
| `opcua/simantha/{run_id}/machines/M{i}` | OPC UA Part 14 JSON | Per-machine state snapshot |
| `opcua/simantha/{run_id}/system` | OPC UA Part 14 JSON | Line-level KPIs |
| `simantha/{run_id}/machines/M{i}` | Flat JSON | Per-machine state snapshot |
| `simantha/{run_id}/system` | Flat JSON | Line-level KPIs |

#### Message Formats

**OPC UA Part 14 JSON Network Message** (opcua/ topics):
```json
{
  "MessageId": "step-42-M1",
  "MessageType": "ua-data",
  "PublisherId": "simantha-opcua",
  "DataSetWriterId": 1,
  "Timestamp": "2026-03-26T10:00:00+00:00",
  "Payload": { "State": "PROCESSING", "OEE": 0.87, ... }
}
```

**Flat JSON** (simantha/ topics):
```json
{
  "run_id": "full_feature_line_20260326_100000",
  "sim_time": 42.0,
  "source": "M1",
  "State": "PROCESSING",
  "OEE": 0.87, ...
}
```

#### Web UI Toggle

The dashboard start panel includes an **MQTT PubSub** toggle. Enable it and optionally set a custom broker URL before starting a simulation. The toggle is disabled while a simulation is running.

#### Mosquitto Broker (Docker Stack)

The Docker stack includes Eclipse Mosquitto 2.0:
- **MQTT:** port 1883
- **WebSocket:** port 9001 (for browser clients)
- Anonymous connections allowed (development default)

```bash
# Subscribe to all machine topics for a run
mosquitto_sub -h localhost -t "simantha/+/machines/#" -v

# Subscribe to system KPIs
mosquitto_sub -h localhost -t "simantha/+/system" -v
```

---

## 11. Run Recipes

Recipes define ordered production segments with changeover periods, enabling multi-product scheduling without modifying scenario configs.

### 11.1 Recipe YAML Format

Recipe files are stored in `config/recipes/`. Example:

```yaml
name: "Monday Production Schedule"
description: "Product A morning, changeover to Product B, then back"
base_scenario: full_feature_line

segments:
  - name: "Product A Morning"
    quantity: 500           # stop after 500 parts
    max_duration: 18000     # safety timeout (5h)
    overrides:
      machines:
        - name: M1
          cycle_time: 10
          defect_rate: 0.02
    changeover:
      target: 300           # planned changeover (seconds)
      distribution: lognormal
      mean: 300
      std: 60

  - name: "Product B Afternoon"
    duration: 7200          # time-boxed (2 hours)
    overrides:
      machines:
        - name: M1
          cycle_time: 15
    changeover:
      target: 900
      distribution: normal
      mean: 900
      std: 120

  - name: "Product A Evening"
    quantity: 300
    max_duration: 14400
```

### 11.2 Stop Conditions

Each segment requires exactly one stop mode:
- **`quantity: N`** -- Batch mode: stop after N parts produced. Optional `max_duration` safety timeout.
- **`duration: N`** -- Time-boxed mode: stop after N sim-time seconds.

### 11.3 Segment Overrides

Overrides modify machine parameters for that segment only. Only these parameters can be overridden:
- `cycle_time`, `defect_rate`, `target_ppm`, `health_multiplier`

The topology (machine count, buffers, scrap sinks) stays identical across all segments.

Since `cycle_time` cannot change after Simantha init, the system is rebuilt between segments. This is seamless because `simulate()` always runs from time 0.

### 11.4 Changeover Configuration

Changeovers use the same `DistributionFactory` as failure modes:
- `constant`, `exponential`, `normal`, `lognormal`, `weibull`, `uniform`

The `target` field is the planned changeover time. The actual duration is sampled from the distribution. During changeover, `LineState = "CHANGEOVER"` on OPC UA.

Changeover seeds are deterministic: `sim_seed + (segment_index + 1) * 10000`.

### 11.5 Running a Recipe

```bash
# --recipe and --scenario are mutually exclusive
python src/opcua_server.py --recipe monday_schedule --seed 42
```

The console shows progress per segment and changeover planned-vs-actual:
```
--- Segment 1/3: Product A Morning ---
    Target: 500 parts (max 18000s)
    Completed: 500 parts in 5230s (quantity_reached)
    Changeover: planned=300s actual=287s (delta=-13s)
--- Segment 2/3: Product B Afternoon ---
    Duration: 7200s
    Completed: 412 parts in 7200s (duration_reached)
```

### 11.6 Recipe OPC UA Variables

Under `OperationsState/Recipe/`:

| Variable | Type | Description |
|----------|------|-------------|
| RecipeName | String | Active recipe name |
| SegmentName | String | Current segment name |
| SegmentIndex | Int32 | Current segment (1-based) |
| TotalSegments | Int32 | Total segments in recipe |
| SegmentTimeRemaining | Double | Countdown for duration-based segments |
| SegmentQuantityTarget | Int32 | Target parts (0 if time-based) |
| SegmentQuantityProduced | Int32 | Parts in current segment |
| SegmentStopMode | String | "quantity" or "duration" |
| ChangeoverState | Boolean | True during changeover |
| LastChangeoverPlanned | Double | Last changeover planned seconds |
| LastChangeoverActual | Double | Last changeover actual seconds |

### 11.7 Recipe Events in Historian

New event types logged to CSV/InfluxDB/Neo4j:
- `SEGMENT_START` -- Logged when a segment begins
- `SEGMENT_END` -- Logged with parts produced, OEE, and stop reason
- `CHANGEOVER` -- Logged with planned, actual, and delta times
- `RECIPE_COMPLETE` -- Logged with total parts and segment summary

### 11.8 Available Example Recipes

| Recipe | Segments | Description |
|--------|----------|-------------|
| `monday_schedule` | 3 | Product A -> changeover -> Product B -> changeover -> Product A |
| `single_product` | 1 | Simple single-segment batch |
| `quick_test` | 2 | Short recipe for CI testing |

### 11.9 Web UI Recipe Support

The Flask web UI supports recipes:
- **`/api/recipes`** -- List available recipes
- **`/api/recipe/<name>`** -- GET/PUT recipe configuration
- **`/api/recipe`** (POST) -- Create new recipe
- **`/api/start-recipe`** -- Start simulation in recipe mode

---

## 12. Troubleshooting

### Common Issues

#### Issue 1: Server Won't Start

**Symptom:**
```
Address already in use: bind failed
```

**Cause:** Port 4840 is already in use (another OPC UA server running)

**Solution:**
```bash
# Find process using port 4840
# Windows:
netstat -ano | findstr :4840
taskkill /PID <process_id> /F

# Linux/macOS:
lsof -i :4840
kill -9 <process_id>
```

---

#### Issue 2: Client Can't Connect

**Symptom:**
```
Connection refused
Timeout
```

**Solutions:**

1. **Check server is running:**
   - Look for "OPC UA server started at..." message

2. **Check URL:**
   - Must be exactly: `opc.tcp://localhost:4840/simantha/`
   - Note the trailing `/`

3. **Firewall:**
   - Windows: Allow Python through firewall
   - Linux: Check `ufw` or `iptables`

4. **Test with telnet:**
   ```bash
   telnet localhost 4840
   ```
   Should connect (Ctrl+C to exit)

---

#### Issue 3: ImportError or ModuleNotFoundError

**Symptom:**
```
ModuleNotFoundError: No module named 'opcua'
ModuleNotFoundError: No module named 'simantha'
```

**Solutions:**

1. **Activate virtual environment:**
   ```bash
   # Windows
   venv\Scripts\activate

   # Linux/macOS
   source venv/bin/activate
   ```

2. **Reinstall dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Check Python version:**
   ```bash
   python --version  # Should be 3.9+
   ```

---

#### Issue 4: Configuration Validation Failed

**Symptom:**
```
[ERROR] Configuration validation failed
```

**Solutions:**

1. **Read error message carefully** - it tells you exactly what's wrong

2. **Check YAML syntax:**
   - Indentation must be consistent (use spaces, not tabs)
   - Colons must have space after them: `name: M1` not `name:M1`

3. **Validate YAML online:**
   - Copy your scenario to http://www.yamllint.com/

4. **Common mistakes:**
   ```yaml
   # WRONG - inconsistent indentation
   machines:
     - name: M1
        cycle_time: 1  # Too much indent

   # RIGHT
   machines:
     - name: M1
       cycle_time: 1
   ```

---

#### Issue 5: Sim Clock Falls Behind Wall Clock on Long Runs

**Symptom:** The simulation starts at approximately real-time speed, but after several hours of wall time the sim clock lags noticeably — advancing only a fraction of a second for each wall second. OEE and throughput charts in Grafana show data points becoming increasingly sparse.

**Cause (two separate root causes):**

- *Old O(N²) architecture (pre-v2.6):* Each step K called `system.simulate(simulation_time=K)`, replaying the entire history. After thousands of steps each iteration consumed seconds.
- *OPC UA write overhead (pre-v2.7):* With ~600 OPC UA nodes, every `set_value()` call over the loopback socket takes 2–3 ms even when the value hasn't changed. 600 writes × 2.5 ms = 1.5 s per step, pushing the budget over the 1-second target.

**The current server (v2.7+) does not have either problem.** It uses per-step `simulate(1)` (O(1)) and `CachedOpcuaNode` write caching (skips `set_value()` when the value is unchanged, reducing ~600 writes to ~150 per step). If you see this issue you are likely running an old Docker image.

**Solutions:**

1. **Pull and rebuild the Docker image** to get both fixes:
   ```bash
   docker compose -f docker/docker-compose.yml pull
   docker compose -f docker/docker-compose.yml up --build -d
   ```

2. **Use Recipes with bounded segments** if you need to cap individual segment run lengths for reporting purposes. See [Section 11](#11-run-recipes).

3. **Reduce scenario complexity** — fewer machines, fewer failure modes, and no SPC each reduce the constant factor inside Simantha's event loop if you observe any CPU pressure.

---

#### Issue 6: MemoryError During Long Runs

**Symptom:**
```
MemoryError
```
Or the process is killed by the OS after running for thousands of simulation steps.

**Cause:** Simantha's `Sink.initialize()` does not reset `level_data` between `system.simulate()` calls. Since each call reinitializes and runs from time 0 to N, the list grows quadratically, exhausting memory after ~4000 steps.

**Solution:** This is already fixed in the current version via a monkey-patch in `opcua_server.py` that resets `Sink.level_data` during initialization. If you are running an older version, update to the latest.

---

#### Issue 7: Variables Not Updating

**Symptom:** Values in OPC UA client are stuck/frozen

**Solutions:**

1. **Check simulation is running:**
   - `SimTime` should be incrementing in the OPC UA address space
   - `LineState` should be `"RUNNING"` (not `"STOPPED"` or `"CHANGEOVER"`)

2. **Refresh client:**
   - Disconnect and reconnect in UA Expert
   - Refresh subscription

3. **Check update rate:**
   - In UA Expert, right-click variable → **Properties**
   - Sampling Interval: 1000ms (1 second)

---

### Getting Help

**If you're still stuck:**

1. **Check logs:**
   - Server prints errors to console
   - Look for stack traces

2. **Run tests:**
   ```bash
   pytest tests/ -v
   ```
   All tests should pass

3. **GitHub Issues:**
   - https://github.com/paupier/simantha-opcua/issues
   - Search existing issues first
   - Provide error messages and configuration

4. **Documentation:**
   - README.md - Overview and quick start
   - docs/spc_analytics.md - SPC details
   - docs/user_manual.md - This comprehensive manual

---

## 13. Appendix

### A. Keyboard Shortcuts (UA Expert)

| Action | Shortcut |
|--------|----------|
| Add Server | Ctrl+A |
| Connect | Double-click server |
| Refresh | F5 |
| Write Value | Right-click → Write |
| Copy Value | Ctrl+C |
| Clear Data View | Ctrl+L |

### B. OPC UA Security (Production Deployment)

**This server uses NO security by default** (for ease of testing).

**For production, enable:**

1. **Encryption:** TLS/SSL
2. **Authentication:** Username/password or certificates
3. **Authorization:** Access control lists

**Configuration:**
```python
# In opcua_server.py, modify:
server.set_security_policy([
    ua.SecurityPolicyType.Basic256Sha256_SignAndEncrypt
])
server.load_certificate("server-cert.pem")
server.load_private_key("server-key.pem")
```

### C. Performance Tuning

**Simulation Speed:**

Default: 1 simulation step = 1 second real time

**Speed up:**
```python
# In opcua_server.py, modify:
real_step = 0.1  # 10x faster than real-time
```

**Slow down (for debugging):**
```python
real_step = 2.0  # 2x slower than real-time
```

**No delay (run as fast as possible):**
```python
real_step = 0.0  # WARNING: Very CPU intensive
```

### D. Extending the System

**Add a new machine to a scenario:**

```yaml
# In line_models.yaml
my_line:
  machines:
    - name: M1
      cycle_time: 1
    - name: M2
      cycle_time: 1
    - name: M3        # NEW MACHINE
      cycle_time: 1.5

  buffers:
    - name: B1
      capacity: 10
      upstream: M1
      downstream: M2
    - name: B2        # NEW BUFFER
      capacity: 15
      upstream: M2
      downstream: M3
```

**Add a custom KPI:**

Edit `opcua_server.py`, add variable in main loop:

```python
# Calculate custom KPI
custom_kpi = throughput / sim_time if sim_time > 0 else 0

# Add to OPC UA (add variable creation in build_opcua_server)
var_custom = system_node.add_variable(idx, "CustomKPI", 0.0)

# Update in loop
var_custom.set_value(custom_kpi)
```

### E. Glossary

**Bottleneck:** The slowest machine in a line, limiting overall throughput

**Buffer:** Temporary storage between machines (WIP = Work-In-Progress)

**CBM (Condition-Based Maintenance):** A maintenance strategy where the maintainer is triggered by the machine's observed health state rather than waiting for hard failure (`cbm_threshold < h_max`) or following a fixed schedule. In this simulator, `cbm_threshold` sets the health state at which the maintainer is called. A machine with `cbm_threshold: 2` and `h_max: 4` will never reach the FAILED state under normal CBM operation — the absence of FAILED events is the success condition, not a missing data. Contrast with run-to-failure (`cbm_threshold == h_max`) where machines stop producing before maintenance is triggered.

**Cp/Cpk:** Process capability indices measuring how well a process meets specifications

**Cycle Time:** Time a machine takes to process one part

**DPMO:** Defects Per Million Opportunities

**Interarrival Time:** Delay between consecutive parts arriving at the source

**MTBF:** Mean Time Between Failures

**MTTR:** Mean Time To Repair

**OEE:** Overall Equipment Effectiveness = Availability × Performance × Quality

**OPC UA:** Open Platform Communications Unified Architecture (industrial protocol)

**Shift:** A defined time period for production (e.g., 8-hour Day/Evening/Night rotation)

**SPC:** Statistical Process Control - using statistics to monitor quality

**Throughput:** Total number of parts completed

**Utilization:** Fraction of time a machine spends processing parts

**Event Historian:** System that records simulation events to CSV, InfluxDB, or Neo4j

**First Pass Yield:** Percentage of parts that pass through without rework

**Quality Routing:** Per-part defect detection that diverts bad parts to scrap or rework

**Rework:** Attempting to fix a defective part before scrapping (virtual, probabilistic)

**Scrap Sink:** Destination for parts that fail quality checks and cannot be reworked

**WIP:** Work-In-Progress - parts currently in the system

**Per-Step Architecture:** The simulation engine calls `system.simulate(simulation_time=1)` once per loop iteration. Compute cost is O(1) per step and O(N) total. The seed advances per step (`step_seed = base_seed + step_count`) so a fixed `--seed` gives a reproducible trajectory. Machine health state is carried across steps via a monkey-patch on `machine.initialize()`.

**LineState:** Internal accumulator object (`src/line_state.py`) that holds counters (`total_parts_produced`, per-machine `MachineTotals`) across `system.simulate()` calls. Accumulates per-step deltas from each 1-second Simantha run. Designed as the foundation for future converge/diverge (fork-merge) topology support.

---

## Summary Checklist

Before closing this manual, verify you can:

- Install Python and dependencies
- Start the OPC UA server with `--scenario` and `--seed`
- Connect with UA Expert and browse the ISA-95 address space
- Monitor real-time variables
- Set `SetInterarrivalTime` before starting a run and verify it in the Controls node
- Load different scenarios (including shift, SPC, and quality routing scenarios)
- Understand the OPC UA address space hierarchy
- Use the Web UI dashboard, config editor, reports page, and validation page
- Configure scrap sinks and quality routing for machines
- Enable event historian (CSV, InfluxDB, or Neo4j)
- Run `full_feature_8_machine_line` with all features at scale
- Troubleshoot common issues

**Next Steps:**

1. Try `full_feature_8_machine_line` scenario — full-scale digital twin with 8 machines
2. Experiment with scrap/rework routing (`scrap_line`, `rework_line` scenarios)
3. Enable CSV historian and analyze event logs via the reports page (`/reports`)
4. Deploy the Docker stack (InfluxDB + Grafana + Web UI) for historical trending
5. Validate the data pipeline via the validation page (`/validation`)
6. Create custom configurations with quality routing, SPC, and shift schedules
7. Integrate with your SCADA/HMI system
8. Use shift-level and quality data for production analysis and optimization

---

**Thank you for using Simantha OPC UA Digital Twin!** 🎉

For updates and contributions:
**GitHub:** https://github.com/paupier/simantha-opcua
**Issues:** https://github.com/paupier/simantha-opcua/issues

---

*Document Version: 2.4*
*Last Updated: 2026-02-28*
