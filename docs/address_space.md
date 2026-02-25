# OPC UA Address Space Reference (ISA-95/ISO 23247)

**Namespace URI:** `http://simantha.nist.gov/`
**Namespace Index:** `ns=2`
**Last Updated:** 2026-02-25

> **Authoritative reference:** See the [User Manual, Section 9](user_manual.md#9-opc-ua-address-space-reference) for full tables with descriptions.

---

## ISA-95 Hierarchy

The address space follows the ISA-95 (IEC 62264) equipment hierarchy with ISO 23247 digital twin identification. Hierarchy names are configurable in scenario YAML via `enterprise`, `site`, `area`, and `line_name` keys.

```
Objects/
└─ {Enterprise}/                                  # default: WeylandIndustries
   └─ {Site}/                                     # default: LV426_Colony
      └─ {Area}/                                  # default: AtmosphereProcessor01
         ├─ {Line}_Equipment/                     # Live process data (Equipment model)
         │  ├─ Identification/
         │  │  ├─ EquipmentID                     (String, READ)
         │  │  ├─ EquipmentClass                  (String, READ)
         │  │  └─ Description                     (String, READ)
         │  │
         │  ├─ OperationsState/
         │  │  ├─ SimTime                         (Double, READ)
         │  │  ├─ LineState                       (String, READ)
         │  │  ├─ LineMode                        (String, READ)
         │  │  └─ Controls/
         │  │     ├─ CmdPauseLine                 (Boolean, WRITE)
         │  │     └─ SetInterarrivalTime          (Double, WRITE)
         │  │
         │  ├─ OperationsPerformance/
         │  │  ├─ Throughput                      (Int32, READ)
         │  │  ├─ TotalWIP                        (Int32, READ)
         │  │  ├─ TotalScrap                      (Int32, READ)
         │  │  └─ ScrapRate                       (Double, READ)
         │  │
         │  ├─ OEE/                               (Line-level OEE, bottleneck model)
         │  │  ├─ Availability                    (Double, READ)
         │  │  ├─ Performance                     (Double, READ)
         │  │  ├─ Quality                         (Double, READ)
         │  │  ├─ OEE                             (Double, READ)
         │  │  ├─ GoodPartCount                   (Int32, READ)
         │  │  └─ DefectivePartCount              (Int32, READ)
         │  │
         │  ├─ Resources/
         │  │  ├─ Machine1/ ... MachineN/         (see Per-Machine below)
         │  │  ├─ Buffer1/ ... BufferN/           (see Per-Buffer below)
         │  │  └─ ScrapBin1/ ... ScrapBinN/       (if scrap_sinks configured)
         │  │     └─ Level                        (Int32, READ)
         │  │
         │  ├─ SupportFunctions/
         │  │  ├─ Maintenance/
         │  │  │  ├─ MaintenanceActive            (Boolean, READ)
         │  │  │  ├─ QueueLength                  (Int32, READ)
         │  │  │  └─ TotalRepairs                 (Int32, READ)
         │  │  └─ ShiftManagement/                (if shifts configured)
         │  │     ├─ CurrentShiftNumber           (Int32, READ)
         │  │     ├─ CurrentShiftName             (String, READ)
         │  │     ├─ ShiftStartTime               (Double, READ)
         │  │     ├─ ShiftEndTime                 (Double, READ)
         │  │     ├─ ShiftDuration                (Double, READ)
         │  │     ├─ ShiftElapsedTime             (Double, READ)
         │  │     ├─ ShiftTimeRemaining           (Double, READ)
         │  │     ├─ CurrentShift/                (resets each shift)
         │  │     │  ├─ PartsProduced, GoodParts, DefectiveParts, DefectRate
         │  │     │  └─ Availability, Performance, Quality, OEE
         │  │     ├─ PreviousShift/               (last completed shift)
         │  │     │  ├─ ShiftNumber, ShiftName, PartsProduced
         │  │     │  └─ GoodParts, DefectiveParts, DefectRate, OEE
         │  │     └─ Totals/                      (cumulative, never reset)
         │  │        ├─ TotalPartsProduced, TotalGoodParts, TotalDefectiveParts
         │  │        └─ TotalDefectRate, TotalShiftsCompleted
         │  │
         │  └─ EventLog/
         │     └─ TotalEventsGenerated            (Int32, READ)
         │
         └─ {Line}_Asset/                         # Physical asset model (static metadata)
            ├─ Identification/
            │  ├─ PhysicalAssetID                 (String, READ)
            │  ├─ AssetClass                      (String, READ)
            │  └─ Description                     (String, READ)
            ├─ M1_Asset/ ... MN_Asset/
            │  └─ Identification/
            │     ├─ PhysicalAssetID, AssetClass, Vendor, Model, SerialNumber
            │     └─ InstallDate, NominalCycleTime
            └─ MaintenanceLog/
               └─ TotalRepairs                    (Int32, READ)
```

---

## Per-Machine Node Structure

Each `MachineN/` under `Resources/` contains ISA-95 sub-groups:

```
MachineN/
  ├─ Identification/
  │  ├─ EquipmentID                               (String, READ)
  │  ├─ EquipmentClass                            (String, READ)
  │  ├─ CycleTime                                 (Double, READ)
  │  └─ TargetPPM                                 (Double, READ)
  │
  ├─ OperationsState/
  │  ├─ State                                     (String, READ)
  │  ├─ HealthState                               (Int32, READ)   0=healthy, N=failed
  │  ├─ HealthPercent                             (Double, READ)  100=healthy, 0=failed
  │  ├─ BlockedTime                               (Double, READ)  accumulated when BLOCKED
  │  ├─ StarvedTime                               (Double, READ)  accumulated when STARVED
  │  ├─ DownTime                                  (Double, READ)  accumulated when FAILED/UNDER_REPAIR
  │  ├─ ProcessingTime                            (Double, READ)  accumulated when PROCESSING/DEGRADED
  │  └─ IdleTime                                  (Double, READ)  accumulated when IDLE/PAUSED
  │
  ├─ OperationsPerformance/
  │  ├─ PartCount                                 (Int32, READ)
  │  ├─ Utilisation                               (Double, READ)  0.0-1.0
  │  └─ ActualPPM                                 (Double, READ)
  │
  ├─ OEE/                                        (recalculated every step, shift-relative)
  │  ├─ Availability, Performance, Quality, OEE   (Double, READ)
  │  ├─ GoodPartCount, DefectivePartCount         (Int32, READ)
  │  └─ TheoreticalOutput                         (Double, READ)
  │
  ├─ Alarms/
  │  ├─ ActiveAlarmCount                          (Int32, READ)
  │  ├─ MachineFailedActive                       (Boolean, READ)
  │  ├─ MaintenanceActive                         (Boolean, READ)
  │  └─ QualityAlertActive                        (Boolean, READ)
  │
  ├─ FailureModes/                                (if enable_advanced_failures)
  │  ├─ ActiveFailureMode                         (String, READ)
  │  ├─ {Mode}FailureCount                        (Int32, READ)
  │  ├─ {Mode}TotalDowntime                       (Double, READ)
  │  ├─ {Mode}MTBF                                (Double, READ)
  │  └─ {Mode}MTTR                                (Double, READ)
  │
  ├─ MaintenanceStrategy/                         (if enable_advanced_failures)
  │  ├─ StrategyType                              (String, READ)
  │  ├─ NextPMScheduled                           (Double, READ)
  │  ├─ PMCount                                   (Int32, READ)
  │  └─ CMCount                                   (Int32, READ)
  │
  ├─ QualityRouting/                              (if quality_routing enabled)
  │  ├─ ScrapCount                                (Int32, READ)
  │  ├─ ReworkCount                               (Int32, READ)
  │  ├─ ReworkSuccessCount                        (Int32, READ)
  │  ├─ ReworkSuccessRate                         (Double, READ)
  │  └─ GoodCount                                 (Int32, READ)
  │
  └─ SPC/                                        (if enable_spc)
     ├─ XBarChart/ {XBar, UCL, CL, LCL}
     ├─ RChart/ {Range, UCL, CL, LCL}
     ├─ Capability/ {Cp, Cpk, Pp, Ppk, SigmaLevel}
     └─ Status/ {InControl, Violations, TotalSamples, NumSubgroups}
```

---

## Per-Buffer Node Structure

```
BufferN/                                          (StorageUnit under Resources/)
  ├─ Level                                        (Int32, READ)
  ├─ Capacity                                     (Int32, READ)
  └─ Alarms/
     ├─ ActiveAlarmCount                          (Int32, READ)
     ├─ HighLevelWarningActive                    (Boolean, READ)
     └─ LowLevelWarningActive                     (Boolean, READ)
```

---

## Access Rights

**Writable (control inputs under `OperationsState/Controls/`):**

| Variable | Type | Description |
|----------|------|-------------|
| `CmdPauseLine` | Boolean | Pause/resume entire line |
| `SetInterarrivalTime` | Double | Part arrival delay (0 = fast as possible) |

All other variables are **read-only**.

---

## State Machine

Machine `State` values (checked in priority order):

```
PAUSED ─────────────────────────────── (CmdPauseLine = true)
FAILED ─────────────────────────────── (health >= failed_health, no maintainer)
UNDER_REPAIR ───────────────────────── (health >= failed_health, maintainer active)
BLOCKED ────────────────────────────── (downstream buffer full)
STARVED ────────────────────────────── (upstream buffer empty)
DEGRADED ───────────────────────────── (health > 0 but < failed_health)
PROCESSING ─────────────────────────── (has_part = true)
IDLE ───────────────────────────────── (default)
```

With multi-state degradation, `failed_health = h_max` (the highest health state index). The DEGRADED state indicates the machine is operational but has begun degrading.

---

## Alarm Severity Levels

| Severity | Value | Triggers |
|----------|-------|----------|
| CRITICAL | 1000 | Machine failure |
| MEDIUM | 500 | Quality alert (defect rate > 5%) |
| LOW | 300 | Buffer high/low warnings |
| INFO | 100 | Maintenance start/end |

---

## Derivation Notes

**Time accumulators** (`BlockedTime`, `StarvedTime`, `DownTime`, `ProcessingTime`, `IdleTime`) are maintained by the main loop, not Simantha internals. Each step, 1 second is added to the bucket matching the machine's previous state. They naturally exclude warm-up time.

**OEE** recalculates every step using shift-relative deltas. Availability uses the main loop's `DownTime` accumulator (excludes warm-up), not Simantha's `machine.downtime`. Quality uses quality routing counters that only increment after warm-up, matching `parts_made`.

**HealthState** comes directly from Simantha's Markov chain (`machine.health`). With multi-state degradation, MTTF per degradation step = configured MTTF / `failed_health`.

---

## Browsing Nodes (Python Client)

Navigate the ISA-95 hierarchy using browse paths:

```python
from opcua import Client

client = Client("opc.tcp://localhost:4840/simantha/")
client.connect()

root = client.get_objects_node()
enterprise = root.get_child(["2:WeylandIndustries"])
site = enterprise.get_child(["2:LV426_Colony"])
area = site.get_child(["2:AtmosphereProcessor01"])
equip = area.get_child(["2:Nostromo_BioProductPakaging_Equipment"])

# Machine state
resources = equip.get_child(["2:Resources"])
machine1 = resources.get_child(["2:Machine1"])
ops_state = machine1.get_child(["2:OperationsState"])
state = ops_state.get_child(["2:State"])
print(state.get_value())  # "PROCESSING"
```

---

## Optional Node Groups

These nodes only appear when enabled in the scenario config (`config/line_models.yaml`):

| Node Group | Config Flag |
|------------|------------|
| `FailureModes/` | `enable_advanced_failures: true` |
| `MaintenanceStrategy/` | `enable_advanced_failures: true` |
| `SPC/` | `enable_spc: true` |
| `QualityRouting/` | `quality_routing.enabled: true` |
| `ShiftManagement/` | `shifts: schedule: [...]` |
| `ScrapBinN/` | `scrap_sinks: [...]` |

---

## ISA-95 Hierarchy Configuration

Override the default hierarchy names in your scenario YAML:

```yaml
my_scenario:
  enterprise: "AcmeCorp"
  site: "PlantA"
  area: "Assembly"
  line_name: "Line1"
  machines:
    - name: M1
      cycle_time: 1
    # ...
```

This creates the OPC UA path:
`Objects / AcmeCorp / PlantA / Assembly / Line1_Equipment / ...`
