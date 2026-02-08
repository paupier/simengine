# OPC UA Address Space Reference

**Namespace URI:** `urn:simantha:opcua`
**Namespace Index:** `ns=2`
**Version:** Phase 12

> **Authoritative reference:** See the [User Manual, Section 9](USER_MANUAL.md#9-opc-ua-address-space-reference) for full tables with descriptions.

---

## Hierarchy Overview

```
Objects/
└─ Line1/
   ├─ System/
   │  ├─ SimTime                        (Double, READ)
   │  ├─ Throughput                     (Int32, READ)
   │  └─ Controls/
   │     ├─ cmdPauseLine                (Boolean, WRITE)
   │     └─ setInterarrivalTime         (Double, WRITE)
   │
   ├─ LineKPIs/
   │  ├─ TotalWIP                       (Int32, READ)
   │  └─ LineOEE/
   │     ├─ Availability                (Double, READ)
   │     ├─ Performance                 (Double, READ)
   │     ├─ Quality                     (Double, READ)
   │     └─ OEE                         (Double, READ)
   │
   ├─ Station1/ ... StationN/
   │  ├─ State                          (String, READ)
   │  ├─ PartCount                      (Int32, READ)
   │  ├─ Utilisation                    (Double, READ)
   │  ├─ BlockedTime                    (Double, READ)
   │  ├─ StarvedTime                    (Double, READ)
   │  ├─ DownTime                       (Double, READ)
   │  ├─ ProcessingTime                 (Double, READ)
   │  ├─ IdleTime                       (Double, READ)
   │  ├─ HealthState                    (Int32, READ)
   │  ├─ HealthPercent                  (Double, READ)
   │  ├─ OEE/
   │  │  ├─ Availability                (Double, READ)
   │  │  ├─ Performance                 (Double, READ)
   │  │  ├─ Quality                     (Double, READ)
   │  │  ├─ OEE                         (Double, READ)
   │  │  ├─ GoodPartCount               (Int32, READ)
   │  │  ├─ DefectivePartCount          (Int32, READ)
   │  │  └─ TheoreticalOutput           (Double, READ)
   │  ├─ Alarms/
   │  │  ├─ ActiveAlarmCount            (Int32, READ)
   │  │  ├─ LastAlarmTime               (DateTime, READ)
   │  │  ├─ LastAlarmMessage            (String, READ)
   │  │  ├─ LastAlarmSeverity           (String, READ)
   │  │  ├─ MachineFailureActive        (Boolean, READ)
   │  │  ├─ MaintenanceActive           (Boolean, READ)
   │  │  └─ QualityAlertActive          (Boolean, READ)
   │  ├─ FailureModes/                  (Phase 10, optional)
   │  │  ├─ ActiveFailureMode           (String, READ)
   │  │  ├─ {Mode}FailureCount          (Int32, READ)
   │  │  ├─ {Mode}TotalDowntime         (Double, READ)
   │  │  ├─ {Mode}MTBF                  (Double, READ)
   │  │  └─ {Mode}MTTR                  (Double, READ)
   │  ├─ MaintenanceStrategy/           (Phase 10, optional)
   │  │  ├─ StrategyType                (String, READ)
   │  │  ├─ NextPMScheduled             (Double, READ)
   │  │  ├─ PMCount                     (Int32, READ)
   │  │  └─ CMCount                     (Int32, READ)
   │  └─ SPC/                           (Phase 11, optional)
   │     ├─ XBarChart/ {XBar, UCL, CL, LCL}
   │     ├─ RChart/ {Range, UCL, CL, LCL}
   │     ├─ Capability/ {Cp, Cpk, Pp, Ppk, SigmaLevel}
   │     └─ Status/ {InControl, Violations, TotalSamples, NumSubgroups}
   │
   ├─ Buffer1/ ... BufferN/
   │  ├─ CurrentLevel                   (Int32, READ)
   │  ├─ Capacity                       (Int32, READ)
   │  └─ Alarms/
   │     ├─ ActiveAlarmCount            (Int32, READ)
   │     ├─ HighLevelWarningActive      (Boolean, READ)
   │     └─ LowLevelWarningActive       (Boolean, READ)
   │
   ├─ Maintenance/
   │  ├─ MaintenanceActive              (Boolean, READ)
   │  ├─ QueueLength                    (Int32, READ)
   │  └─ TotalRepairs                   (Int32, READ)
   │
   ├─ Shift/                            (Phase 12, optional)
   │  ├─ CurrentShiftNumber             (Int32, READ)
   │  ├─ CurrentShiftName               (String, READ)
   │  ├─ ShiftStartTime                 (Double, READ)
   │  ├─ ShiftEndTime                   (Double, READ)
   │  ├─ ShiftDuration                  (Double, READ)
   │  ├─ ShiftElapsedTime               (Double, READ)
   │  ├─ ShiftTimeRemaining             (Double, READ)
   │  ├─ CurrentShift/                  (resets each shift)
   │  │  ├─ PartsProduced               (Int32, READ)
   │  │  ├─ GoodParts                   (Int32, READ)
   │  │  ├─ DefectiveParts              (Int32, READ)
   │  │  ├─ DefectRate                  (Double, READ)
   │  │  ├─ Availability                (Double, READ)
   │  │  ├─ Performance                 (Double, READ)
   │  │  ├─ Quality                     (Double, READ)
   │  │  └─ OEE                         (Double, READ)
   │  ├─ PreviousShift/                 (last completed shift)
   │  │  ├─ ShiftNumber                 (Int32, READ)
   │  │  ├─ ShiftName                   (String, READ)
   │  │  ├─ PartsProduced               (Int32, READ)
   │  │  ├─ GoodParts                   (Int32, READ)
   │  │  ├─ DefectiveParts              (Int32, READ)
   │  │  ├─ DefectRate                  (Double, READ)
   │  │  └─ OEE                         (Double, READ)
   │  └─ Totals/                        (cumulative, never reset)
   │     ├─ TotalPartsProduced          (Int32, READ)
   │     ├─ TotalGoodParts              (Int32, READ)
   │     ├─ TotalDefectiveParts         (Int32, READ)
   │     ├─ TotalDefectRate             (Double, READ)
   │     └─ TotalShiftsCompleted        (Int32, READ)
   │
   └─ EventLog/
      └─ TotalEventsGenerated           (Int32, READ)
```

---

## Access Rights

**Writable (control inputs):**

| Variable | Type | Description |
|----------|------|-------------|
| `System/Controls/cmdPauseLine` | Boolean | Pause/resume entire line |
| `System/Controls/setInterarrivalTime` | Double | Part arrival delay (0 = fast as possible) |

All other variables are **read-only**.

---

## State Machine

Machine `State` values (checked in priority order):

```
PAUSED ─────────────────────────────── (cmdPauseLine = true)
FAILED ─────────────────────────────── (health = 1, no maintainer)
UNDER_REPAIR ───────────────────────── (health = 1, maintainer active)
BLOCKED ────────────────────────────── (downstream buffer full)
STARVED ────────────────────────────── (upstream buffer empty)
PROCESSING ─────────────────────────── (has_part = true)
IDLE ───────────────────────────────── (default)
```

---

## Alarm Severity Levels

| Severity | Value | Triggers |
|----------|-------|----------|
| CRITICAL | 1000 | Machine failure |
| MEDIUM | 500 | Quality alert (defect rate > 5%) |
| LOW | 300 | Buffer high/low warnings |
| INFO | 100 | Maintenance start/end |

---

## Browsing Nodes (Python Client)

Use browse paths, not string node IDs:

```python
from opcua import Client

client = Client("opc.tcp://localhost:4840/simantha/")
client.connect()

root = client.get_objects_node()
line1 = root.get_child(["2:Line1"])
station1 = line1.get_child(["2:Station1"])
state = station1.get_child(["2:State"])

print(state.get_value())  # "PROCESSING"
```

---

## Optional Node Groups

These nodes only appear when enabled in the scenario config (`config/line_models.yaml`):

| Node Group | Config Flag | Phase |
|------------|------------|-------|
| `FailureModes/` | `enable_advanced_failures: true` | 10 |
| `MaintenanceStrategy/` | `enable_advanced_failures: true` | 10 |
| `SPC/` | `enable_spc: true` | 11 |
| `Shift/` | `shifts: schedule: [...]` | 12 |
