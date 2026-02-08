# Simantha OPC UA - Complete User Manual

**Version:** Phase 11 (SPC Quality Analytics)
**Last Updated:** 2026-02-08
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
11. [Troubleshooting](#11-troubleshooting)
12. [Appendix](#12-appendix)

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
✅ **Experiment** with different scenarios (bottlenecks, failures, quality)
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
- **Python:** 3.8 or newer (3.11 recommended)
- **pip:** Python package installer
- **Git:** For cloning the repository (optional, can download ZIP)

**Optional (for visualization):**
- **UA Expert:** OPC UA client for testing (free from Unified Automation)
- **Prosys OPC UA Browser:** Alternative OPC UA client
- **Node-RED:** For custom dashboards
- **Grafana + InfluxDB:** For historical trending (future phase)

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
   - Expand: **Objects** → **Line1**
   - You'll see:
     - System
     - LineKPIs
     - Station1
     - Buffer1
     - Station2
     - Maintenance

4. **View Live Data:**
   - Drag variables to the **Data Access View** (bottom panel)
   - Try these first:
     - `Line1/System/SimTime` - Simulation time
     - `Line1/System/Throughput` - Total parts produced
     - `Line1/Station1/State` - Machine 1 state
     - `Line1/Buffer1/CurrentLevel` - Buffer level

**You should see values updating in real-time!** 🎉

#### Step 4: Control the Simulation

**In UA Expert, find the Controls node:**

1. Navigate to: `Line1/System/Controls`
2. **Pause the line:**
   - Right-click `cmdPauseLine`
   - Select **Write Value**
   - Change to `true`
   - Click **Write**
   - Watch `SimTime` stop incrementing

3. **Resume:**
   - Write `false` to `cmdPauseLine`
   - Simulation resumes

4. **Adjust arrival rate:**
   - Write a value to `setInterarrivalTime`
   - `0.0` = parts arrive as fast as possible
   - `2.0` = 2-second delay between parts
   - Watch buffer level and throughput change!

#### Step 5: Stop the Server

In the terminal where the server is running:

- Press `Ctrl+C`
- Server will gracefully shut down

**Congratulations!** You've completed your first simulation. 🎊

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

### Machine States (6 States)

| State | Description | Typical Cause |
|-------|-------------|---------------|
| **IDLE** | Waiting for work | No parts available, downstream blocked |
| **PROCESSING** | Actively working on a part | Normal operation |
| **BLOCKED** | Waiting for downstream buffer space | Buffer full, downstream slow |
| **STARVED** | Waiting for upstream parts | Buffer empty, upstream slow |
| **PAUSED** | Simulation paused | User control via OPC UA |
| **FAILED** | Machine has failed | Health degradation (Phase 4+) |
| **UNDER_REPAIR** | Being repaired by maintainer | After failure (Phase 4+) |

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

**Buffer Level:**
- Current WIP (Work-In-Progress) count
- Range: 0 to capacity (e.g., 0-10)
- High level = bottleneck downstream
- Low level = bottleneck upstream

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
   - Navigate: **Objects** → **Line1**
   - You'll see the full hierarchy

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
- **Alarms & Events:** View alarm notifications (Phase 9+)

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

    # Navigate to variables using browse path
    line1 = root.get_child(["2:Line1"])
    system = line1.get_child(["2:System"])
    sim_time = system.get_child(["2:SimTime"])
    throughput = system.get_child(["2:Throughput"])

    # Read values
    print(f"Simulation Time: {sim_time.get_value()}")
    print(f"Throughput: {throughput.get_value()}")

    # Write to control variable
    controls = system.get_child(["2:Controls"])
    pause = controls.get_child(["2:cmdPauseLine"])
    pause.set_value(True)  # Pause the line
    print("Line paused!")

finally:
    client.disconnect()
```

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

**Machine with Health Degradation (Phase 4):**
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

**Machine with Quality Modeling (Phase 8):**
```yaml
machines:
  - name: M1
    cycle_time: 1
    defect_rate: 0.02      # 2% base defect rate
    health_multiplier: 3.0 # Defect rate × 3 when failed
```

**Machine with Advanced Failures (Phase 10):**
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

**Machine with SPC Analytics (Phase 11):**
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
```

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
- `Station2/State` often shows "STARVED"
- `Station1/State` often shows "BLOCKED" (buffer full)
- `Buffer1/CurrentLevel` fluctuates near 0

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
- `Station1/State` cycles: PROCESSING → FAILED → UNDER_REPAIR → PROCESSING
- `Station1/HealthState` = 0 (healthy) or 1 (failed)
- `Maintenance/MaintenanceActive` = true during repairs
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
- `Station1/OEE/Quality` < 1.0 (defects reduce quality)
- `Station1/OEE/DefectivePartCount` increases
- `Station1/Alarms/QualityAlertActive` triggers if >5% defects

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
- `Station1/FailureModes/ActiveFailureMode` shows which mode failed
- `Station1/FailureModes/MechanicalMTBF` shows mean time between failures
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
- `Station1/SPC/Capability/Cpk` shows process capability
- `Station1/SPC/Status/InControl` = false when out of control
- `Station1/SPC/Status/Violations` lists rule violations

**Use case:** Quality control and Six Sigma analysis

---

### Scenario H: Combined Advanced + SPC

**File:** `advanced_spc_line`
**Complexity:** ⭐⭐⭐⭐⭐ Expert

**Characteristics:**
- Combines advanced failure modes with SPC
- Most realistic and complete simulation
- All Phase 1-11 features enabled

**Use case:** Comprehensive digital twin demonstration

---

## 9. OPC UA Address Space Reference

### Complete Hierarchy

```
Objects/
  Line1/
    System/
      SimTime                    [READ]  Double    - Simulation time
      Throughput                 [READ]  Int32     - Total parts produced
      Controls/
        cmdPauseLine             [WRITE] Boolean   - Pause simulation
        setInterarrivalTime      [WRITE] Double    - Part arrival delay

    LineKPIs/
      TotalWIP                   [READ]  Int32     - Total WIP in all buffers
      LineOEE/
        Availability             [READ]  Double    - Line availability
        Performance              [READ]  Double    - Line performance
        Quality                  [READ]  Double    - Line quality
        OEE                      [READ]  Double    - Overall OEE

    Station1/
      State                      [READ]  String    - Machine state
      PartCount                  [READ]  Int32     - Parts processed
      Utilisation                [READ]  Double    - Utilization (0-1)
      BlockedTime                [READ]  Double    - Time blocked
      StarvedTime                [READ]  Double    - Time starved
      DownTime                   [READ]  Double    - Time down (failed)
      ProcessingTime             [READ]  Double    - Time processing
      IdleTime                   [READ]  Double    - Time idle

      HealthState                [READ]  Int32     - 0=healthy, 1=failed
      HealthPercent              [READ]  Double    - Health %

      OEE/
        Availability             [READ]  Double    - Station availability
        Performance              [READ]  Double    - Station performance
        Quality                  [READ]  Double    - Station quality
        OEE                      [READ]  Double    - Station OEE
        GoodPartCount            [READ]  Int32     - Good parts
        DefectivePartCount       [READ]  Int32     - Defective parts
        TheoreticalOutput        [READ]  Double    - Theoretical max

      Alarms/
        ActiveAlarmCount         [READ]  Int32     - Active alarms
        LastAlarmTime            [READ]  DateTime  - Last alarm timestamp
        LastAlarmMessage         [READ]  String    - Last alarm text
        LastAlarmSeverity        [READ]  String    - CRITICAL/MEDIUM/LOW
        MachineFailureActive     [READ]  Boolean   - Failure alarm
        MaintenanceActive        [READ]  Boolean   - Maintenance alarm
        QualityAlertActive       [READ]  Boolean   - Quality alarm

      FailureModes/              (Phase 10 - if enabled)
        ActiveFailureMode        [READ]  String    - Current failure mode
        MechanicalFailureCount   [READ]  Int32     - Mechanical failures
        MechanicalMTBF           [READ]  Double    - Mean time between
        MechanicalMTTR           [READ]  Double    - Mean time to repair
        (similar for other modes)

      MaintenanceStrategy/       (Phase 10 - if enabled)
        StrategyType             [READ]  String    - corrective/preventive/predictive
        NextPMScheduled          [READ]  Double    - Next PM time
        PMCount                  [READ]  Int32     - Preventive count
        CMCount                  [READ]  Int32     - Corrective count

      SPC/                       (Phase 11 - if enabled)
        XBarChart/
          XBar                   [READ]  Double    - Current mean
          UCL                    [READ]  Double    - Upper control limit
          CL                     [READ]  Double    - Center line
          LCL                    [READ]  Double    - Lower control limit

        RChart/
          Range                  [READ]  Double    - Current range
          UCL                    [READ]  Double    - Upper control limit
          CL                     [READ]  Double    - Center line
          LCL                    [READ]  Double    - Lower control limit

        Capability/
          Cp                     [READ]  Double    - Process capability
          Cpk                    [READ]  Double    - Process capability index
          Pp                     [READ]  Double    - Process performance
          Ppk                    [READ]  Double    - Process performance index
          SigmaLevel             [READ]  Double    - Sigma quality (2-6)

        Status/
          InControl              [READ]  Boolean   - Process in control
          Violations             [READ]  String    - Rule violations
          TotalSamples           [READ]  Int32     - Sample count
          NumSubgroups           [READ]  Int32     - Subgroup count

    Buffer1/
      CurrentLevel               [READ]  Int32     - Current WIP
      Capacity                   [READ]  Int32     - Max capacity

      Alarms/
        ActiveAlarmCount         [READ]  Int32     - Active alarms
        HighLevelWarningActive   [READ]  Boolean   - >90% full
        LowLevelWarningActive    [READ]  Boolean   - <10% full

    Station2/
      (same structure as Station1)

    Maintenance/
      MaintenanceActive          [READ]  Boolean   - Maintainer busy
      QueueLength                [READ]  Int32     - Machines waiting
      TotalRepairs               [READ]  Int32     - Total repairs

    EventLog/
      TotalEventsGenerated       [READ]  Int32     - Event count
```

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
| `--seed` | Random seed (reproducibility) | None (random) | `--seed 42` |

**Examples:**

```bash
# Run specific scenario
python src/opcua_server.py --scenario bottleneck_line

# Reproducible random defects (Phase 8)
python src/opcua_server.py --scenario quality_line --seed 123

# Combined
python src/opcua_server.py --scenario spc_quality_line --seed 456
```

### Feature 2: Programmatic Control

**Python script to automate simulation:**

```python
import time
from opcua import Client

client = Client("opc.tcp://localhost:4840/simantha/")
client.connect()

try:
    root = client.get_objects_node()
    line1 = root.get_child(["2:Line1"])
    controls = line1.get_child(["2:System", "2:Controls"])

    # Get control variables
    pause = controls.get_child(["2:cmdPauseLine"])
    interarrival = controls.get_child(["2:setInterarrivalTime"])

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
line1 = root.get_child(["2:Line1"])

# Get variables to log
system = line1.get_child(["2:System"])
sim_time = system.get_child(["2:SimTime"])
throughput = system.get_child(["2:Throughput"])

station1 = line1.get_child(["2:Station1"])
state = station1.get_child(["2:State"])
util = station1.get_child(["2:Utilisation"])

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

### Feature 4: Alarm Monitoring

**Subscribe to alarm changes:**

```python
from opcua import Client

class AlarmHandler:
    def datachange_notification(self, node, val, data):
        print(f"ALARM: {node} = {val}")

client = Client("opc.tcp://localhost:4840/simantha/")
client.connect()

root = client.get_objects_node()
line1 = root.get_child(["2:Line1"])
station1 = line1.get_child(["2:Station1"])
alarms = station1.get_child(["2:Alarms"])

# Subscribe to alarm message
alarm_msg = alarms.get_child(["2:LastAlarmMessage"])
handler = AlarmHandler()
sub = client.create_subscription(1000, handler)
handle = sub.subscribe_data_change(alarm_msg)

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

---

## 11. Troubleshooting

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
   python --version  # Should be 3.8+
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

#### Issue 5: Variables Not Updating

**Symptom:** Values in OPC UA client are stuck/frozen

**Solutions:**

1. **Check simulation not paused:**
   - `cmdPauseLine` should be `false`
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
   - docs/phase11_spc_implementation_summary.md - SPC details
   - MEMORY.md - Critical lessons learned

---

## 12. Appendix

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

**SPC:** Statistical Process Control - using statistics to monitor quality

**Throughput:** Total number of parts completed

**Utilization:** Fraction of time a machine spends processing parts

**WIP:** Work-In-Progress - parts currently in the system

---

## Summary Checklist

Before closing this manual, verify you can:

✅ Install Python and dependencies
✅ Start the OPC UA server
✅ Connect with UA Expert
✅ Monitor real-time variables
✅ Write control commands (pause, interarrival)
✅ Load different scenarios
✅ Understand the OPC UA address space
✅ Troubleshoot common issues

**Next Steps:**

1. Experiment with different scenarios
2. Create custom configurations
3. Integrate with your SCADA/HMI system
4. Build dashboards in Node-RED or Grafana
5. Use data for analysis and optimization

---

**Thank you for using Simantha OPC UA Digital Twin!** 🎉

For updates and contributions:
**GitHub:** https://github.com/paupier/simantha-opcua
**Issues:** https://github.com/paupier/simantha-opcua/issues

---

*Document Version: 1.0 (Phase 11)*
*Last Updated: 2026-02-08*
