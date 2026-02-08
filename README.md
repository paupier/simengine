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

- **Simulates** configurable production lines (2-10+ machines in serial topology)
- **Exposes** real-time KPIs via industry-standard OPC UA protocol
- **Models** realistic variability through health degradation, advanced failures, and quality defects
- **Tracks** shift-based production with automatic rotation and per-shift OEE
- **Responds** to external control inputs (pause/resume, arrival rate adjustment)
- **Demonstrates** buffer dynamics, bottlenecks, failure impacts, and SPC analytics

### Real-World Behavior Modeled

✅ **Health Degradation** - Machines degrade over time with configurable failure rates
✅ **Advanced Failure Modes** - Weibull, exponential, lognormal distributions with competing risks
✅ **Maintenance Strategies** - Corrective, preventive, and predictive maintenance
✅ **Buffer Dynamics** - WIP accumulates/drains based on machine states
✅ **Quality Defects** - Health-correlated defect rates with individual part tracking
✅ **OEE Calculation** - Availability x Performance x Quality per station and line-level
✅ **SPC Analytics** - X-bar/R control charts, Cp/Cpk capability, Western Electric rules
✅ **Shift Management** - Configurable shift rotation with per-shift metrics and OEE
✅ **Alarms & Events** - Machine failure, quality, maintenance, and buffer alerts
✅ **Enhanced State Detection** - 7 states: IDLE, PROCESSING, BLOCKED, STARVED, PAUSED, FAILED, UNDER_REPAIR
✅ **Time Tracking** - Cumulative time in each state per machine

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

**Choose a scenario:**
```bash
# 3-machine line with degradation
python src/opcua_server.py --scenario extended_line

# Quality monitoring with SPC
python src/opcua_server.py --scenario spc_quality_line

# 3-shift production tracking
python src/opcua_server.py --scenario shift_line
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
- `Shift/CurrentShiftName` changes at shift boundaries (if using shift scenarios)
- `Shift/ShiftTimeRemaining` counts down to next shift change

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

### Current Structure (Phase 12)

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
      ├─ Maintenance/
      │    ├─ MaintenanceActive (bool, READ-ONLY)   # True when repairing
      │    ├─ QueueLength (int, READ-ONLY)          # Machines waiting for repair
      │    └─ TotalRepairs (int, READ-ONLY)         # Completed repairs count
      │
      └─ Shift/                                     # Phase 12 (if shifts configured)
           ├─ CurrentShiftNumber (int, READ-ONLY)   # Sequential counter (1, 2, 3...)
           ├─ CurrentShiftName (string, READ-ONLY)  # "Day Shift", "Evening Shift", etc.
           ├─ ShiftElapsedTime (double, READ-ONLY)  # Time in current shift
           ├─ ShiftTimeRemaining (double, READ-ONLY)# Countdown to next shift
           ├─ CurrentShift/                          # Resets each shift boundary
           │    ├─ PartsProduced (int, READ-ONLY)
           │    ├─ DefectRate (double, READ-ONLY)
           │    └─ OEE (double, READ-ONLY)
           ├─ PreviousShift/                         # Last completed shift snapshot
           │    ├─ ShiftName (string, READ-ONLY)
           │    ├─ PartsProduced (int, READ-ONLY)
           │    └─ OEE (double, READ-ONLY)
           └─ Totals/                                # Cumulative, never reset
                ├─ TotalPartsProduced (int, READ-ONLY)
                └─ TotalShiftsCompleted (int, READ-ONLY)
```

### Variable Access Rights

**Read-Only (Monitoring):**
All KPIs, states, health metrics, buffer levels, maintenance status

**Writable (Control):**
- `System/Controls/cmdPauseLine` - Pause/resume entire line (binary command)
- `System/Controls/setInterarrivalTime` - Adjust part arrival rate (setpoint)

---

## 🧪 Testing & Scenarios

### Available Scenarios (11 total)

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

### Run Tests

```bash
# All tests
pytest tests/ -v

# Specific test suites
pytest tests/test_spc_analytics.py -v        # SPC (23 tests)
pytest tests/test_failure_modes.py -v         # Failure modes (29 tests)
pytest tests/test_config_validation.py -v     # Config validation (39 tests)
pytest tests/test_opcua_integration.py -v     # OPC UA integration
pytest tests/test_scenarios.py -v             # Scenario validation
```

### Run Baseline Scenarios (Batch Mode)

```bash
python src/simantha_baseline.py
```

Generates CSV results in `results/` for offline analysis.

### Verify Real-Time OPC UA Server

1. **Start server:** `python src/opcua_server.py --scenario failure_line`
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
│   ├─ opcua_server.py            # Main OPC UA server (Phase 2-12)
│   ├─ simantha_baseline.py       # Phase 1: Baseline scenarios (batch mode)
│   ├─ config_loader.py           # YAML configuration loader
│   ├─ config_loader_phase10.py   # Advanced failure config validation
│   ├─ failure_modes.py           # Phase 10: Statistical failure distributions
│   ├─ advanced_machine.py        # Phase 10: AdvancedMachine class
│   ├─ spc_analytics.py           # Phase 11: SPC control charts & capability
│   └─ shift_manager.py           # Phase 12: Shift tracking & rotation
│
├─ config/
│   └─ line_models.yaml           # Scenario definitions (11 scenarios)
│
├─ tests/
│   ├─ test_opcua_integration.py  # OPC UA integration tests
│   ├─ test_scenarios.py          # Scenario validation tests
│   ├─ test_config_validation.py  # Configuration validation (39 tests)
│   ├─ test_failure_modes.py      # Failure mode unit tests (29 tests)
│   ├─ test_distribution_validation.py  # Statistical distribution tests
│   ├─ test_advanced_scenarios.py # Advanced scenario integration tests
│   ├─ test_spc_analytics.py      # SPC analytics unit tests (23 tests)
│   └─ validate_opcua_server.py   # Server validation script
│
├─ docs/
│   ├─ USER_MANUAL.md             # Comprehensive user manual
│   ├─ phase11_spc_implementation_summary.md
│   └─ address_space.md           # OPC UA address space reference
│
├─ results/                       # CSV outputs from baseline scenarios
│
├─ requirements.txt               # Python dependencies
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

### Completed Phases

| Phase | Features |
|-------|----------|
| **Phase 5** | Enhanced State Logic - 6-state machine, BLOCKED/STARVED detection, time tracking |
| **Phase 6** | OEE Calculation - Per-station & line-level Availability x Performance x Quality |
| **Phase 7** | Multi-Buffer Lines - Config-driven N-machine topologies, YAML scenarios |
| **Phase 8** | Quality Modeling - Health-correlated defects, individual part tracking, First Pass Yield |
| **Phase 9** | OPC UA Alarms - Machine failure, maintenance, quality, buffer alerts with edge detection |
| **Phase 10** | Advanced Failures - Weibull/exponential distributions, competing risks, MTBF/MTTR |
| **Phase 11** | SPC Analytics - X-bar/R charts, Cp/Cpk capability, Western Electric rules, Six Sigma |
| **Phase 12** | Shift Tracking - 8-hour shift rotation, per-shift metrics reset, shift-based OEE |

See the [User Manual](docs/USER_MANUAL.md) for detailed documentation of each phase.

### Phase 12: Shift Tracking & Management ✅

**Status:** Complete (2026-02-08)

Production shift management with automatic rotation, per-shift metrics, and cumulative totals.

**Key Features:**

- **Automatic Shift Rotation**: Configurable shift schedules (2-shift, 3-shift, custom)
- **Per-Shift Metrics Reset**: Parts, defects, OEE reset at each shift boundary
- **Cumulative Totals**: Overall production totals preserved across all shifts
- **Previous Shift Summary**: Compare current vs. previous shift performance
- **Time Tracking**: Elapsed time and countdown to next shift change
- **Per-Machine Tracking**: Failure counts and state time per machine per shift
- **Backward Compatible**: Optional feature, only enabled when `shifts` block present in config

**Configuration:**

```yaml
# Add to any scenario in config/line_models.yaml
shifts:
  schedule:
    - name: "Day Shift"
      duration: 28800        # 8 hours in seconds
      start_offset: 0
    - name: "Evening Shift"
      duration: 28800
      start_offset: 28800
    - name: "Night Shift"
      duration: 28800
      start_offset: 57600
```

**Available Scenarios:**

- `shift_line`: 2-machine line with 3-shift rotation (beginner)
- `advanced_shift_line`: Full-featured line with shifts + advanced failures + SPC (expert)

**Run:**

```bash
python src/opcua_server.py --scenario shift_line
python src/opcua_server.py --scenario advanced_shift_line
```

**OPC UA Variables (Phase 12):**

```plaintext
Line1/Shift/
  CurrentShiftNumber     (Int32)   - Sequential counter (1, 2, 3...)
  CurrentShiftName       (String)  - "Day Shift", "Evening Shift", etc.
  ShiftElapsedTime       (Double)  - Time spent in current shift
  ShiftTimeRemaining     (Double)  - Countdown to next shift

  CurrentShift/                    - Resets at each shift boundary
    PartsProduced        (Int32)
    GoodParts            (Int32)
    DefectiveParts       (Int32)
    DefectRate           (Double)
    Availability         (Double)
    Performance          (Double)
    Quality              (Double)
    OEE                  (Double)

  PreviousShift/                   - Snapshot of last completed shift
    ShiftNumber          (Int32)
    ShiftName            (String)
    PartsProduced        (Int32)
    OEE                  (Double)

  Totals/                          - Cumulative, NEVER reset
    TotalPartsProduced   (Int32)
    TotalGoodParts       (Int32)
    TotalDefectiveParts  (Int32)
    TotalDefectRate      (Double)
    TotalShiftsCompleted (Int32)
```

---

### Future Phases

- **Phase 13:** Historical Data & Visualization - InfluxDB/TimescaleDB, Grafana dashboards, CSV export
- **Phase 14:** Scrap & Rework Routing - Non-serial topologies with quality gates
- **Phase 15:** Parallel Lines & Assembly - Multi-line coordination

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
