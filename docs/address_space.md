# OPC UA Address Space Structure

**Namespace URI:** `http://simantha.nist.gov/`  
**Version:** 1.0.0

---

## Hierarchy Overview

\`\`\`
Objects/
└─ SimanthaLine/
   ├─ System/
   │  ├─ Throughput
   │  ├─ TotalWIP
   │  ├─ SimTime
   │  ├─ SimulationSpeed (write)
   │  ├─ ResetCommand (write)
   │  ├─ ExportAlarmLog (write)
   │  ├─ OEE/
   │  │  ├─ OEE
   │  │  ├─ Availability
   │  │  ├─ Performance
   │  │  └─ Quality
   │  └─ KPIs/
   │     ├─ CycleTime
   │     ├─ Throughput
   │     ├─ MTBF
   │     └─ MTTR
   ├─ M1/
   │  ├─ State
   │  ├─ PartCount
   │  ├─ UpTime
   │  ├─ DownTime
   │  ├─ BlockedTime
   │  ├─ StarvedTime
   │  ├─ Utilization
   │  ├─ AlarmActive
   │  ├─ CycleTime (write)
   │  ├─ FailureRate (write)
   │  ├─ RepairTime (write)
   │  ├─ Alarms/
   │  │  ├─ ActiveAlarms
   │  │  ├─ TotalAlarms
   │  │  └─ LastAlarm/
   │  │     ├─ Code
   │  │     ├─ Message
   │  │     ├─ Timestamp
   │  │     └─ Severity
   │  └─ Quality/
   │     ├─ YieldRate (write)
   │     ├─ GoodParts
   │     ├─ DefectParts
   │     └─ Cpk
   ├─ M2/
   │  └─ (same structure as M1)
   └─ B1/
      ├─ CurrentLevel
      ├─ Capacity (write)
      └─ Analytics/
         ├─ AverageLevel
         ├─ MinLevel
         ├─ MaxLevel
         └─ EmptyEvents
\`\`\`

---

## Variable Reference Table

### System Variables

| Variable | NodeId | DataType | Access | Units | Description |
|----------|--------|----------|--------|-------|-------------|
| Throughput | ns=1;i=1001 | Int32 | Read | parts | Total parts delivered to sink |
| TotalWIP | ns=1;i=1002 | Int32 | Read | parts | Sum of all buffer levels |
| SimTime | ns=1;i=1003 | Float | Read | seconds | Current simulation time |
| SimulationSpeed | ns=1;i=1004 | Float | Write | multiplier | Real-time speed (1.0 = real-time) |
| ResetCommand | ns=1;i=1005 | Boolean | Write | - | Trigger simulation reset |

### Machine Variables (M1, M2)

| Variable | DataType | Access | Units | Description |
|----------|----------|--------|-------|-------------|
| State | String | Read | - | IDLE, RUNNING, BLOCKED, STARVED, FAULTED |
| PartCount | Int32 | Read | parts | Cumulative parts processed |
| UpTime | Float | Read | seconds | Time in RUNNING state |
| DownTime | Float | Read | seconds | Time in FAULTED state |
| BlockedTime | Float | Read | seconds | Time waiting (downstream full) |
| StarvedTime | Float | Read | seconds | Time waiting (upstream empty) |
| Utilization | Float | Read | % | UpTime / TotalTime × 100 |
| AlarmActive | Boolean | Read | - | True if machine faulted |
| CycleTime | Float | Write | seconds | Processing time per part |
| FailureRate | Float | Write | per hour | Random failure frequency |
| RepairTime | Float | Write | seconds | Mean repair duration |

### Buffer Variables

| Variable | DataType | Access | Units | Description |
|----------|----------|--------|-------|-------------|
| CurrentLevel | Int32 | Read | parts | Current WIP in buffer |
| Capacity | Int32 | Write | parts | Maximum buffer capacity |
| AverageLevel | Float | Read | parts | Time-weighted mean level |
| MinLevel | Int32 | Read | parts | Minimum level observed |
| MaxLevel | Int32 | Read | parts | Maximum level observed |
| EmptyEvents | Int32 | Read | count | Times buffer hit zero |

### OEE Variables

| Variable | DataType | Access | Units | Description |
|----------|----------|--------|-------|-------------|
| OEE | Float | Read | % | Overall Equipment Effectiveness |
| Availability | Float | Read | % | Uptime / Planned time |
| Performance | Float | Read | % | Actual vs. ideal cycle time |
| Quality | Float | Read | % | Good parts / Total parts |

---

## Data Types and Ranges

### Valid Ranges (Write Variables)

| Variable | Min | Max | Default | Notes |
|----------|-----|-----|---------|-------|
| CycleTime | 0.1 | 60.0 | 1.0 | Seconds per part |
| FailureRate | 0.0 | 10.0 | 0.0 | Per hour (0 = no failures) |
| RepairTime | 1.0 | 600.0 | 10.0 | Seconds |
| Capacity | 1 | 100 | 10 | Parts |
| SimulationSpeed | 0.1 | 100.0 | 1.0 | Real-time multiplier |
| YieldRate | 0.0 | 1.0 | 1.0 | Fraction (0-1) |

Writes outside these ranges return OPC UA `Bad` status code.

---

## State Machine

Machine `State` transitions:

\`\`\`
IDLE ──┬──> RUNNING ──┬──> BLOCKED
       │              │
       │              └──> STARVED
       │              │
       │              └──> FAULTED ──> (repair) ──> IDLE
       │
       └──────────────────────────────────────────> IDLE
\`\`\`

- **IDLE**: Waiting for simulation start or after repair
- **RUNNING**: Actively processing parts
- **BLOCKED**: Downstream buffer full, cannot output part
- **STARVED**: Upstream buffer empty, cannot retrieve part
- **FAULTED**: Random failure occurred, requires repair

---

## Alarm Codes

| Code | Severity | Description |
|------|----------|-------------|
| FAIL_MECH | 3 (Critical) | Mechanical failure (random) |
| FAIL_ELEC | 3 (Critical) | Electrical failure |
| STARVE | 1 (Warning) | Machine starved (upstream empty) |
| BLOCK | 1 (Warning) | Machine blocked (downstream full) |
| MAINT_START | 2 (Alarm) | Maintenance begun |
| MAINT_END | 1 (Warning) | Maintenance completed |

Severity levels: 1=Warning, 2=Alarm, 3=Critical

---

## Engineering Units (EU Information)

Variables include OPC UA `EUInformation`:

| Unit | Unit ID | Display | Variables |
|------|---------|---------|-----------|
| Second | 5457219 | s | CycleTime, RepairTime, SimTime, UpTime, DownTime |
| Percent | 20529 | % | Utilization, OEE, Availability, Performance, Quality |
| Count | Custom | parts | Throughput, PartCount, CurrentLevel, Capacity |
| Parts/Hour | Custom | PPH | System/KPIs/Throughput |

---

## NodeSet Export (Phase 6)

The complete address space is exportable to XML:

\`\`\`bash
python src/export_nodeset.py --output SimanthaLine_v1.0.xml
\`\`\`

Import into:
- UA Expert: Tools → Add Custom Types → Import XML
- UaModeler: Project → Import → NodeSet
- Ignition: Config → OPC UA → Import Types
