# Simantha OPC UA Integration

[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![License: Public Domain](https://img.shields.io/badge/License-Public%20Domain-green.svg)](https://github.com/usnistgov/simantha/blob/master/LICENSE)
[![OPC UA](https://img.shields.io/badge/OPC%20UA-Compliant-orange.svg)](https://opcfoundation.org/)

A real-time **digital twin** of a manufacturing production line using [Simantha](https://github.com/usnistgov/simantha) discrete-event simulation exposed via OPC UA for monitoring and control.

---

## 📋 Project Status

**Current Phase:** Phase 12 Complete – Shift Tracking & Management
**Last Updated:** 2026-02-08

### Phase Completion Status

| Phase | Status | Features |
|-------|--------|----------|
| **Phase 1:** Simantha Baseline | ✅ **Complete** | 2-machine serial line with 3 scenarios (balanced, bottleneck, failures) |
| **Phase 2:** OPC UA Read-Only | ✅ **Complete** | Real-time KPI monitoring via OPC UA |
| **Phase 3:** Bidirectional Control | ✅ **Complete** | Global pause, arrival rate control |
| **Phase 4:** Health & Degradation | ✅ **Complete** | Machine health tracking, maintenance modeling, failure events |
| **Phase 5:** Enhanced State Logic | ✅ **Complete** | 6-state machine (IDLE/PROCESSING/BLOCKED/STARVED/FAILED/UNDER_REPAIR/PAUSED), real utilization, time tracking |
| **Phase 6:** OEE Calculation | ✅ **Complete** | Per-station and line-level OEE (Availability × Performance × Quality) |
| **Phase 7:** Multi-Buffer Lines | ✅ **Complete** | 3+ machines, config-driven topologies |
| **Phase 8:** Quality Modeling | ✅ **Complete** | Health-correlated defect tracking, real Quality OEE |
| **Phase 9:** OPC UA Alarms & Events | ✅ **Complete** | Real-time alarm generation (failure, maintenance, quality alerts) |
| **Phase 10:** Advanced Failure Modes | ✅ **Complete** | Multiple failure modes with scipy distributions (Weibull, exponential, lognormal), competing risks, MTBF/MTTR tracking |
| **Phase 11:** SPC Quality Analytics | ✅ **Complete** | X-bar/R control charts, Cp/Cpk capability analysis, Western Electric rules, Six Sigma quality levels |
| **Phase 12:** Shift Tracking | ✅ **Complete** | 8-hour shift patterns, per-shift metrics reset, shift-based OEE, automatic rotation |

---

## 🎯 What This Project Does

This project creates a **realistic manufacturing digital twin** that:

- **Simulates** a 2-machine serial production line (Source → M1 → Buffer → M2 → Sink)
- **Exposes** real-time KPIs via industry-standard OPC UA protocol
- **Models** realistic variability through machine health degradation and maintenance
- **Responds** to external control inputs (pause/resume, arrival rate adjustment)
- **Demonstrates** buffer dynamics, bottlenecks, and failure impacts on throughput

### Real-World Behavior Modeled

✅ **Health Degradation** - Machines degrade over time (1% chance per simulation step)
✅ **Failure Events** - M1 can fail, triggering maintenance requests
✅ **Maintenance Intervention** - Maintainer repairs failed machines
✅ **Buffer Dynamics** - WIP accumulates/drains based on machine states
✅ **Throughput Variability** - Production rate fluctuates during failures
✅ **Enhanced State Detection** - 6 states: IDLE, PROCESSING, BLOCKED, STARVED, PAUSED, FAILED, UNDER_REPAIR
✅ **Time Tracking** - Cumulative time in each state (BlockedTime, StarvedTime, DownTime, ProcessingTime, IdleTime)
✅ **Real Utilization** - Calculated as ProcessingTime / TotalTime (not binary 0/1)

---

## 🚀 Quick Start

### Prerequisites

- **Python 3.8+** with pip
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

**Choose a scenario (Phase 7):**
```bash
# 3-machine line with degradation
python src/opcua_server.py --scenario extended_line

# 4-machine scalability test
python src/opcua_server.py --scenario long_line
```

**Expected output:**
```
[OK] Configuration validated: 2 machines, 1 buffers
Loading scenario: balanced_line
OPC UA server started at opc.tcp://localhost:4840/simantha/
Scenario: balanced_line (2 machines, 1 buffers)
Press Ctrl+C to stop.
```

### Connect with UA Expert

1. Open UA Expert
2. Add Server: `opc.tcp://localhost:4840/simantha/`
3. Connect and browse to `Objects → Line1`
4. Drag variables to Data Access View to monitor live values

**What to watch:**
- `Station1/HealthPercent` drops from 100 → 0 when M1 fails
- `Maintenance/MaintenanceActive` becomes True during repairs
- `Buffer1/CurrentLevel` drains when M1 is down
- `System/Throughput` pauses during failures, resumes after repair

---

## 🏗️ Architecture

```
┌─────────────────┐
│  OPC UA Client  │  (UA Expert, SCADA, MES)
│   (Monitor &    │
│    Control)     │
└────────┬────────┘
         │ OPC UA Protocol (opc.tcp://)
         ▼
┌─────────────────┐
│  OPC UA Server  │  (python-opcua)
│  Address Space  │  - Read-only: KPIs, states, health
│  & Handlers     │  - Writable: cmdPauseLine, setInterarrivalTime
└────────┬────────┘
         │ Python API
         ▼
┌─────────────────┐
│    Simantha     │  Discrete-Event Simulation
│   Simulation    │  - Source → M1 → Buffer → M2 → Sink
│     Engine      │  - Health degradation modeling
│                 │  - Maintenance intervention
└─────────────────┘
```

---

## 📊 OPC UA Address Space

### Current Structure (Phase 5)

```
Objects/
  └─ Line1/
      ├─ System/
      │    ├─ SimTime (double, READ-ONLY)           # Simulation time in seconds
      │    ├─ Throughput (int, READ-ONLY)           # Total parts produced (monotonic)
      │    └─ Controls/
      │         ├─ cmdPauseLine (bool, WRITABLE)    # Pause entire line
      │         └─ setInterarrivalTime (double, WRITABLE)  # Part arrival rate (0=fast, >0=delay)
      │
      ├─ LineKPIs/
      │    ├─ TotalWIP (int, READ-ONLY)             # Work-in-process (buffer level)
      │    └─ LineOEE/                              # Phase 6: Line-level OEE metrics
      │         ├─ Availability (double, READ-ONLY) # Min of all stations (bottleneck)
      │         ├─ Performance (double, READ-ONLY)  # Min of all stations (bottleneck)
      │         ├─ Quality (double, READ-ONLY)      # Min of all stations (1.0 in Phase 6)
      │         └─ OEE (double, READ-ONLY)          # Availability × Performance × Quality
      │
      ├─ Station1/ (M1)
      │    ├─ State (string, READ-ONLY)             # IDLE, PROCESSING, BLOCKED, STARVED, PAUSED, FAILED, UNDER_REPAIR
      │    ├─ PartCount (int, READ-ONLY)            # Parts processed (monotonic)
      │    ├─ Utilisation (double, READ-ONLY)       # ProcessingTime / TotalTime (range: 0.0-1.0)
      │    ├─ HealthState (int, READ-ONLY)          # 0=healthy, 1=failed
      │    ├─ HealthPercent (double, READ-ONLY)     # 100=healthy, 0=failed
      │    ├─ BlockedTime (double, READ-ONLY)       # Time spent waiting for downstream
      │    ├─ StarvedTime (double, READ-ONLY)       # Time spent waiting for upstream
      │    ├─ DownTime (double, READ-ONLY)          # Time spent failed or under repair
      │    ├─ ProcessingTime (double, READ-ONLY)    # Time spent actively processing parts
      │    ├─ IdleTime (double, READ-ONLY)          # Time spent idle (waiting for work)
      │    └─ OEE/                                  # Phase 6: OEE metrics
      │         ├─ Availability (double, READ-ONLY) # (TotalTime - DownTime) / TotalTime
      │         ├─ Performance (double, READ-ONLY)  # ActualOutput / TheoreticalOutput
      │         ├─ Quality (double, READ-ONLY)      # GoodParts / TotalParts (1.0 in Phase 6)
      │         ├─ OEE (double, READ-ONLY)          # Availability × Performance × Quality
      │         ├─ GoodPartCount (int, READ-ONLY)   # Parts without defects (Phase 8 prep)
      │         ├─ DefectivePartCount (int, READ-ONLY) # Defective parts (Phase 8 prep)
      │         └─ TheoreticalOutput (double, READ-ONLY) # Diagnostic: max possible output
      │
      ├─ Buffer1/
      │    ├─ CurrentLevel (int, READ-ONLY)         # Current WIP count
      │    └─ Capacity (int, READ-ONLY)             # Max buffer capacity (10)
      │
      ├─ Station2/ (M2)
      │    ├─ State (string, READ-ONLY)             # IDLE, PROCESSING, BLOCKED, STARVED, PAUSED
      │    ├─ PartCount (int, READ-ONLY)            # Parts processed (monotonic)
      │    ├─ Utilisation (double, READ-ONLY)       # ProcessingTime / TotalTime (range: 0.0-1.0)
      │    ├─ BlockedTime (double, READ-ONLY)       # Time spent waiting for downstream
      │    ├─ StarvedTime (double, READ-ONLY)       # Time spent waiting for upstream
      │    ├─ DownTime (double, READ-ONLY)          # Time spent down (M2 has no degradation, so always 0)
      │    ├─ ProcessingTime (double, READ-ONLY)    # Time spent actively processing parts
      │    ├─ IdleTime (double, READ-ONLY)          # Time spent idle (waiting for work)
      │    └─ OEE/                                  # Phase 6: OEE metrics
      │         ├─ Availability (double, READ-ONLY) # (TotalTime - DownTime) / TotalTime
      │         ├─ Performance (double, READ-ONLY)  # ActualOutput / TheoreticalOutput
      │         ├─ Quality (double, READ-ONLY)      # GoodParts / TotalParts (1.0 in Phase 6)
      │         ├─ OEE (double, READ-ONLY)          # Availability × Performance × Quality
      │         ├─ GoodPartCount (int, READ-ONLY)   # Parts without defects (Phase 8 prep)
      │         ├─ DefectivePartCount (int, READ-ONLY) # Defective parts (Phase 8 prep)
      │         └─ TheoreticalOutput (double, READ-ONLY) # Diagnostic: max possible output
      │
      └─ Maintenance/
           ├─ MaintenanceActive (bool, READ-ONLY)   # True when repairing
           ├─ QueueLength (int, READ-ONLY)          # Machines waiting for repair
           └─ TotalRepairs (int, READ-ONLY)         # Completed repairs count
```

### Variable Access Rights

**Read-Only (Monitoring):**
All KPIs, states, health metrics, buffer levels, maintenance status

**Writable (Control):**
- `System/Controls/cmdPauseLine` - Pause/resume entire line (binary command)
- `System/Controls/setInterarrivalTime` - Adjust part arrival rate (setpoint)

---

## 🧪 Testing & Scenarios

### Run Baseline Scenarios (Batch Mode)

```bash
python src/simantha_baseline.py
```

**Generates CSV results in `results/phase4/`:**
- `scenario_A_balanced.csv` - M1=1s, M2=1s (balanced line)
- `scenario_B_bottleneck_M1.csv` - M1=2s, M2=1s (M1 bottleneck)
- `scenario_C_failures_M1.csv` - M1 degrades/fails, maintainer repairs

### Verify Real-Time OPC UA Server

1. **Start server:** `python src/opcua_server.py`
2. **Connect UA Expert** to `opc.tcp://localhost:4840/simantha/`
3. **Test controls:**
   - Set `cmdPauseLine = True` → Simulation freezes
   - Set `setInterarrivalTime = 5.0` → Parts arrive every 5 seconds (slower)
4. **Observe failures:**
   - Watch `Station1/HealthPercent` drop to 0 when M1 fails
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
- ✅ Quality issues (rework, scrap) - *Phase 8*
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
while True:
    # Read controls, modify source.interarrival_time if needed
    if not paused:
        sim_time += sim_step  # ALWAYS increment before simulate()
        system.simulate(simulation_time=sim_time)  # First call at time=1.0
```

**Never call `system.simulate(simulation_time=0)` or with time ≤ 0**

### Monotonic Counter Pattern

**Issue:** `sink.level` can decrease during maintenance events, causing part counts to jump around.

**Solution:** Implement manual counter that only increases:

```python
if current_sink_level > prev_sink_level:
    delta_parts = current_sink_level - prev_sink_level
    total_parts_produced += delta_parts  # Only increases!
```

---

## 📁 Repository Structure

```
simantha-opcua/
├─ src/
│   ├─ simantha_baseline.py     # Phase 1: Baseline scenarios (batch mode)
│   └─ opcua_server.py           # Phase 2-4: Real-time OPC UA server
│
├─ results/
│   └─ phase4/                   # CSV outputs from baseline scenarios
│
├─ tests/                        # Unit tests (to be added)
│
├─ docs/                         # Additional documentation
│
├─ requirements.txt              # Python dependencies
├─ LICENSE
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

---

## 🗺️ Roadmap

### Phase 5: Enhanced State Logic
- BLOCKED/STARVED detection (machine waiting for buffer space/parts)
- Event-driven metrics from Simantha internal state
- Per-station downtime tracking (BlockedTime, StarvedTime, DownTime)

### Phase 6: OEE Calculation ✅

**Status:** Complete (2026-02-06)

Implements industry-standard OEE (Overall Equipment Effectiveness) metrics:

- **Availability** = (TotalTime - DownTime) / TotalTime (machine uptime)
- **Performance** = ActualOutput / TheoreticalOutput (processing speed efficiency)
- **Quality** = GoodParts / TotalParts (Phase 6: 100%, Phase 8: real defect tracking)
- **OEE** = Availability × Performance × Quality

**Exposed via OPC UA:**

- **Per-Station OEE**: `Station1/OEE/` and `Station2/OEE/` (diagnostics - which machine limits performance?)
- **Line-Level OEE**: `LineKPIs/LineOEE/` (business metric - overall line effectiveness)
- **Bottleneck Logic**: Line OEE uses min() of station metrics (weakest link determines line performance)

**Variables per station:**

- Availability, Performance, Quality, OEE (all range 0.0-1.0)
- GoodPartCount, DefectivePartCount (Phase 8 prep)
- TheoreticalOutput (diagnostic)

### Phase 7: Multi-Buffer & Extended Topologies ✅

**Status:** Complete (2026-02-07)

Extends the system from hardcoded 2-machine lines to configuration-driven N-machine topologies:

**Key Features:**
- **Configuration-Driven**: Load line topology from `config/line_models.yaml`
- **Dynamic Node Creation**: OPC UA nodes (Station1, Station2, Station3...) created automatically
- **Scalable Architecture**: Supports 2, 3, 4, or more machines in serial topology
- **Command-Line Selection**: `python src/opcua_server.py --scenario <name>`
- **Backward Compatible**: Existing 2-machine scenarios still work unchanged

**Available Scenarios:**
- `balanced_line`: 2 machines, 1 buffer (default)
- `bottleneck_line`: 2 machines with M1 bottleneck (cycle_time=2s)
- `failure_line`: 2 machines with M1 degradation/failures
- `extended_line`: 3 machines, 2 buffers, with M1 degradation (NEW)
- `long_line`: 4 machines, 3 buffers, scalability test (NEW)

**Code Improvements:**
- Reduced code from 704 to 570 lines (eliminated ~130 lines of duplication)
- Extracted 5 reusable helper functions
- Replaced hardcoded m1/m2 logic with loops over machine dictionaries
- Added topology validation (N machines require N-1 buffers for serial lines)

**Future Extensions (Phase 8+):**
- Parallel lines, assembly/disassembly stations
- Non-serial topologies (merge/split points)

### Phase 8: Quality & Reject Modeling ✅

**Status:** Complete (2026-02-07)

Implements realistic quality tracking with health-correlated defect rates and individual part traceability.

**Key Features:**

- **Health-Correlated Defects**: Defect rate increases as machine health degrades
- **Configurable Base Rates**: Set per-machine `defect_rate` in YAML (0.0-1.0)
- **Real Quality Calculation**: Quality = GoodParts / TotalParts (no longer hardcoded 1.0)
- **OEE Integration**: Quality metric now reflects actual manufacturing performance
- **Backward Compatible**: Existing scenarios default to 0.0 defect rate (100% quality)
- **Individual Part Tracking** (Phase 8b): Per-part attributes enable traceability and First Pass Yield analysis

**Configuration:**

```yaml
machines:
  - name: M1
    defect_rate: 0.02          # 2% when healthy, 8% when failed
    health_multiplier: 3.0     # Optional (default 3.0)
    enable_degradation: true
```

**Defect Rate Formula:**

- **Without degradation**: `defect_rate` (fixed)
- **With degradation**: `defect_rate × (1 + multiplier × health_state)`

**Example:**

- M1 healthy (state=0): 2% defect rate
- M1 failed (state=1): 2% × (1 + 3×1) = 8% defect rate

**Usage:**

```bash
# Run quality scenario with reproducible random seed
python src/opcua_server.py --scenario quality_line --seed 42

# Press Ctrl+C to see quality analysis report
```

**OPC UA Variables (now functional):**

- `Station1/OEE/Quality` - Good parts / Total parts (0.0-1.0)
- `Station1/OEE/GoodPartCount` - Parts without defects
- `Station1/OEE/DefectivePartCount` - Parts with defects

**Phase 8b: Individual Part Tracking**

- Each part has `is_defective`, `failed_at_machine`, `defect_type` attributes
- End-of-simulation report shows First Pass Yield
- Enables future scrap/rework routing (Phase 9+)
- Press Ctrl+C to see quality analysis:

  ```text
  === Part Quality Analysis ===
  Total Parts: 287
  Good Parts: 267
  Defective Parts: 20
  First Pass Yield: 93.03%

  Defects by Machine:
    M1: 15 defects
    M2: 5 defects
  ```

**Invariants Maintained:**

- `good_parts + defective_parts == partcount` (always)
- Counters are monotonic (never decrease)
- Quality ∈ [0.0, 1.0]

### Phase 9: OPC UA Alarms & Events ✅

**Status:** Complete (2026-02-07)

Implements industry-standard OPC UA alarms and events for proactive monitoring.

**Key Features:**

- **Machine Failure Alarms**: Trigger when health degrades to FAILED state
- **Maintenance Events**: Notify when maintenance starts/completes
- **Quality Alerts**: Warn when defect rate exceeds 5% threshold
- **Buffer Warnings**: Alert when buffers are >90% full or <10% full
- **Edge Detection**: Alarms only trigger on state transitions (no spam)
- **Backward Compatible**: All Phase 8 tests pass unchanged

**OPC UA Variables (per station):**

- `Station1/Alarms/ActiveAlarmCount` - Number of active alarms (Int32, READ-ONLY)
- `Station1/Alarms/LastAlarmTime` - Timestamp of most recent alarm (DateTime, READ-ONLY)
- `Station1/Alarms/LastAlarmMessage` - Human-readable alarm message (String, READ-ONLY)
- `Station1/Alarms/LastAlarmSeverity` - Alarm severity level (String, READ-ONLY)
- `Station1/Alarms/MachineFailureActive` - Boolean flag for failure alarm (Boolean, READ-ONLY)
- `Station1/Alarms/MaintenanceActive` - Boolean flag for maintenance (Boolean, READ-ONLY)
- `Station1/Alarms/QualityAlertActive` - Boolean flag for quality alert (Boolean, READ-ONLY)

**Buffer Alarms (per buffer):**

- `Buffer1/Alarms/ActiveAlarmCount` - Number of active buffer alarms
- `Buffer1/Alarms/HighLevelWarningActive` - Buffer >90% full (Boolean, READ-ONLY)
- `Buffer1/Alarms/LowLevelWarningActive` - Buffer <10% full (Boolean, READ-ONLY)

**Alarm Severity Levels:**

- **CRITICAL** (1000): Machine failures
- **MEDIUM** (500): Quality alerts
- **LOW** (300): Buffer warnings
- **INFO** (100): State changes, maintenance events

**Usage:**

```bash
# Run with any scenario - alarms work automatically
python src/opcua_server.py --scenario failure_line

# Monitor alarms in UA Expert
# Browse to: Line1/Station1/Alarms/
# Watch: MachineFailureActive, LastAlarmMessage
```

**Testing:**

```bash
# Run alarm tests
pytest tests/test_opcua_integration.py::TestAlarmsAndEvents -v

# Expected: 4/4 tests passing
```

**Implementation Details:**

- **Edge Detection**: Tracks previous alarm states to only trigger on transitions
- **Anti-Spam**: Alarms activate once when entering bad state, clear once when exiting
- **Metadata Tracking**: Stores timestamp, message, and severity for latest alarm
- **Active Count**: Reflects current number of active alarms (not cumulative)

**Future Enhancement (Phase 9b):**

- True OPC UA event generation (push notifications to SCADA clients)
- Event subscriptions for real-time monitoring
- Event filtering and acknowledgment

### Phase 10: Advanced Failure Modes & Maintenance ✅

Replaces simple degradation matrices with realistic statistical distributions and multiple failure modes per machine.

**Key Features:**
- **Statistical Distributions:** Weibull (wear-out), Exponential (random), Lognormal (repairs), Normal, Uniform
- **Multiple Failure Modes:** Competing risks model - multiple failure types compete, minimum time-to-failure wins
- **MTBF/MTTR Tracking:** Real-time calculation from historical failure data
- **Maintenance Strategies:** Corrective (reactive), Preventive (time-based), Predictive (condition-based)

**Configuration Example (`config/line_models.yaml`):**

```yaml
advanced_failure_line:
  machines:
    - name: M1
      cycle_time: 1
      enable_advanced_failures: true  # Phase 10 flag

      # Multiple failure modes with competing risks
      failure_modes:
        - name: mechanical
          type: wearout              # Weibull distribution
          mttf:
            distribution: weibull
            shape: 2.5               # Beta > 1 = increasing hazard rate
            scale: 500               # Characteristic life
          mttr:
            distribution: lognormal
            mean: 15                 # Mean repair time
            std: 5

        - name: electrical
          type: random               # Exponential distribution
          mttf:
            distribution: exponential
            mean: 1000               # MTTF in time units
          mttr:
            distribution: lognormal
            mean: 10
            std: 3

      # Maintenance strategy
      maintenance_strategy:
        type: predictive           # corrective | preventive | predictive
        cbm_threshold: 1           # For predictive: health threshold
        # pm_interval: 100         # For preventive: time between PM
```

**OPC UA Variables (Phase 10):**

```
Station1/
  FailureModes/
    ActiveFailureMode            (String)    Current failure mode or "none"
    MechanicalFailureCount       (Int32)     Total failures for this mode
    MechanicalTotalDowntime      (Double)    Cumulative downtime (seconds)
    MechanicalMTBF               (Double)    Mean time between failures (calculated)
    MechanicalMTTR               (Double)    Mean time to repair (calculated)
    ElectricalFailureCount       (Int32)
    ElectricalTotalDowntime      (Double)
    ElectricalMTBF               (Double)
    ElectricalMTTR               (Double)

  MaintenanceStrategy/
    StrategyType                 (String)    "corrective" | "preventive" | "predictive"
    NextPMScheduled              (Double)    Sim time of next preventive maintenance
    PMCount                      (Int32)     Preventive maintenance count
    CMCount                      (Int32)     Corrective maintenance count
```

**Distribution Types:**

| Distribution | Use Case | Parameters | Example |
|-------------|----------|------------|---------|
| **constant** | Deterministic | value | `{distribution: constant, value: 100}` |
| **exponential** | Random failures (constant hazard) | mean | `{distribution: exponential, mean: 500}` |
| **weibull** | Wear-out failures (increasing hazard) | shape, scale | `{distribution: weibull, shape: 2.5, scale: 500}` |
| **lognormal** | Repair times (right-skewed) | mean, std | `{distribution: lognormal, mean: 15, std: 5}` |
| **normal** | General purpose (truncated at 0) | mean, std | `{distribution: normal, mean: 50, std: 10}` |
| **uniform** | Bounded variation | min, max | `{distribution: uniform, min: 10, max: 20}` |

**Competing Risks Model:**

When multiple failure modes exist, the failure that occurs first wins:

```python
time_to_failure = min([mode.sample_time_to_failure() for mode in failure_modes])
active_mode = mode_with_minimum_time
```

**Run Advanced Scenario:**

```bash
python src/opcua_server.py --scenario advanced_failure_line
```

**Testing:**

```bash
# Unit tests (29 tests)
pytest tests/test_failure_modes.py -v

# Configuration validation (39 tests)
pytest tests/test_config_validation.py -v

# Statistical validation (12 tests, slow)
pytest tests/test_distribution_validation.py -v -m slow

# Integration tests (5 tests)
pytest tests/test_advanced_scenarios.py::TestAdvancedFailureScenario -v
```

**Backward Compatibility:**

All Phase 1-9 scenarios continue to work unchanged. Advanced failures are opt-in via `enable_advanced_failures: true`.

### Phase 11: SPC Quality Analytics ✅

**Statistical Process Control (SPC)** for real-time quality monitoring with control charts and capability analysis.

**Features:**
- **X-bar and R Control Charts** - Monitor process mean and variability
- **Process Capability Indices** - Cp, Cpk, Pp, Ppk calculations
- **Western Electric Rules** - Automatic out-of-control detection (4 rules)
- **Six Sigma Quality Levels** - Sigma level estimation (2σ to 6σ)
- **Real-Time OPC UA Integration** - All metrics exposed via OPC UA

**Configuration Example:**

```yaml
# Scenario: spc_quality_line
machines:
  - name: M1
    cycle_time: 1
    enable_spc: true  # Enable SPC analytics

    spc:
      characteristic: "cycle_time"      # What to measure
      subgroup_size: 5                  # Samples per subgroup
      num_subgroups: 25                 # Subgroups for control limits
      usl: 1.2                          # Upper specification limit
      lsl: 0.8                          # Lower specification limit
      target: 1.0                       # Target value
      enable_western_electric: true     # Enable out-of-control rules

    defect_rate: 0.02  # 2% base defect rate
```

**Run SPC Scenarios:**

```bash
# Basic SPC quality monitoring
python src/opcua_server.py --scenario spc_quality_line

# Combined advanced failures + SPC
python src/opcua_server.py --scenario advanced_spc_line
```

**OPC UA Variables (Phase 11):**

```plaintext
Station1/
  SPC/
    XBarChart/
      XBar           - Current subgroup mean
      UCL            - Upper control limit (μ + A2×R̄)
      CL             - Center line (μ)
      LCL            - Lower control limit (μ - A2×R̄)

    RChart/
      Range          - Current subgroup range
      UCL            - D4 × R̄
      CL             - R̄
      LCL            - D3 × R̄

    Capability/
      Cp             - Process capability
      Cpk            - Process capability index
      Pp             - Process performance
      Ppk            - Process performance index
      SigmaLevel     - Estimated sigma quality (2σ to 6σ)

    Status/
      InControl      - Process in statistical control (bool)
      Violations     - Active rule violations (string)
      TotalSamples   - Total measurements collected
      NumSubgroups   - Complete subgroups analyzed
```

**Capability Interpretation:**

| Cpk Value | Sigma Level | Quality     | DPMO    |
|-----------|-------------|-------------|---------|
| Cpk ≥ 2.0 | 6σ          | World Class | 3.4     |
| Cpk ≥ 1.67 | 5σ         | Excellent   | 233     |
| Cpk ≥ 1.33 | 4σ         | Acceptable  | 6,210   |
| Cpk ≥ 1.0 | 3σ          | Marginal    | 66,807  |
| Cpk < 1.0 | <3σ         | Poor        | >66,807 |

**Western Electric Rules:**

- **Rule 1:** Point beyond 3σ control limits (sudden shift/outlier)
- **Rule 2:** 2 of 3 points beyond 2σ on same side (process mean shift)
- **Rule 3:** 4 of 5 points beyond 1σ on same side (trending/drift)
- **Rule 4:** 8 consecutive points on same side of centerline (sustained shift)

**Tests:** 23 unit tests covering control charts, capability analysis, and Western Electric rules (all passing)

**Documentation:** See [docs/phase11_spc_implementation_summary.md](docs/phase11_spc_implementation_summary.md) for complete details.

---

### Phase 12: Historical Data & Visualization (Future)
- Time-series database integration (InfluxDB/TimescaleDB)
- Web dashboard for control chart visualization
- Grafana dashboards for trend analysis
- Historical capability studies
- CSV export for offline analysis

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
