# Simantha OPC UA - Complete User Manual

**Version:** 2.4
**Last Updated:** 2026-02-28
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
✅ **Control** the simulation via OPC UA (pause, adjust arrival rate)
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

#### Step 4: Control the Simulation

**In UA Expert, find the Controls node:**

1. Navigate to: `Nostromo_BioProductPakaging_Equipment/OperationsState/Controls`
2. **Pause the line:**
   - Right-click `CmdPauseLine`
   - Select **Write Value**
   - Change to `true`
   - Click **Write**
   - Watch `SimTime` stop incrementing

3. **Resume:**
   - Write `false` to `CmdPauseLine`
   - Simulation resumes

4. **Adjust arrival rate:**
   - Write a value to `SetInterarrivalTime`
   - `0.0` = parts arrive as fast as possible
   - `2.0` = 2-second delay between parts
   - Watch buffer level and throughput change!

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

**Docker mode (full stack with InfluxDB + Grafana):**
```bash
docker compose -f docker/docker-compose.yml up --build -d
```

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

    # Write to control variable
    controls = ops_state.get_child(["2:Controls"])
    pause = controls.get_child(["2:CmdPauseLine"])
    pause.set_value(True)  # Pause the line
    print("Line paused!")

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

**Writable Variables (under `OperationsState/Controls/`):**

| Variable | Access | Type | Description |
|----------|--------|------|-------------|
| `CmdPauseLine` | **WRITE** | Boolean | Pause/resume entire line |
| `SetInterarrivalTime` | **WRITE** | Double | Part arrival delay (0 = fast as possible) |

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
| `Status/` | `InControl` | Boolean | Process in statistical control |
| | `Violations` | String | Active rule violations |
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

### Feature 2: Programmatic Control

**Python script to automate simulation:**

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
    controls = equip.get_child(["2:OperationsState", "2:Controls"])

    # Get control variables
    pause = controls.get_child(["2:CmdPauseLine"])
    interarrival = controls.get_child(["2:SetInterarrivalTime"])

    # Experiment: Vary arrival rate
    print("Starting experiment...")
    for rate in [0.0, 1.0, 2.0, 3.0]:
        print(f"Setting arrival rate to {rate}...")
        interarrival.set_value(rate)
        time.sleep(30)  # Run for 30 seconds

    print("Pausing line...")
    pause.set_value(True)

finally:
    client.disconnect()
```

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

1. Connect Grafana to InfluxDB (or use CSV plugin)
2. Query events by type: `SELECT * FROM events WHERE event_type = 'SCRAP'`
3. Build dashboards for:
   - Scrap rate over time
   - Maintenance frequency per machine
   - SPC violation history
   - Shift-by-shift production comparison

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

#### Issue 5: MemoryError During Long Runs

**Symptom:**
```
MemoryError
```
Or the process is killed by the OS after running for thousands of simulation steps.

**Cause:** Simantha's `Sink.initialize()` does not reset `level_data` between `system.simulate()` calls. Since each call reinitializes and runs from time 0 to N, the list grows quadratically, exhausting memory after ~4000 steps.

**Solution:** This is already fixed in the current version via a monkey-patch in `opcua_server.py` that resets `Sink.level_data` during initialization. If you are running an older version, update to the latest.

---

#### Issue 6: Variables Not Updating

**Symptom:** Values in OPC UA client are stuck/frozen

**Solutions:**

1. **Check simulation not paused:**
   - `CmdPauseLine` should be `false`
   - `SimTime` should be incrementing

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

**CBM:** Condition-Based Maintenance - repair when condition threshold reached

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

---

## Summary Checklist

Before closing this manual, verify you can:

- Install Python and dependencies
- Start the OPC UA server with `--scenario` and `--seed`
- Connect with UA Expert and browse the ISA-95 address space
- Monitor real-time variables
- Write control commands (`CmdPauseLine`, `SetInterarrivalTime`)
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
