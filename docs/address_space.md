# OPC UA Address Space Reference (ISA-95)

**Namespace URI:** `http://simengine.local/`
**Namespace Index:** `ns=2`
**Source:** `src/simengine/publishers/opcua_server.py`, `opcua_nodes.py`

Hierarchy names are configurable per scenario via `enterprise`, `site`, `area`, `line_name` (all default to generic placeholders — see `config/scenarios.yaml`).

```
Objects/
└─ {Enterprise}/
   └─ {Site}/
      └─ {Area}/
         ├─ {Line}_Equipment/
         │  ├─ Identification/
         │  │  ├─ EquipmentID        (String)
         │  │  ├─ EquipmentClass     (String)  "ProductionLine"
         │  │  ├─ Description        (String)
         │  │  └─ RunID              (String)  {scenario}_{YYYYMMDD_HHMMSS}
         │  │
         │  ├─ OperationsState/
         │  │  ├─ SimTime            (Double)
         │  │  ├─ LineState          (String)  RUNNING | CHANGEOVER | STOPPED
         │  │  └─ Controls/
         │  │     └─ SimSpeedRatio   (Double)  fixed at run start; sim-seconds per wall-second
         │  │
         │  ├─ OperationsPerformance/
         │  │  ├─ Throughput         (Double)  parts/sim-second, cumulative
         │  │  ├─ TotalWIP           (Int32)
         │  │  └─ TotalScrap         (Int32)
         │  │
         │  ├─ OEE/                  (bottleneck line-level model)
         │  │  ├─ OEE                (Double)
         │  │  └─ GoodPartCount      (Int32)
         │  │
         │  ├─ Resources/
         │  │  ├─ {Station}_Equipment/    one per configured station — see below
         │  │  ├─ {Station}_Asset/        static identification (Vendor/Model/SerialNumber)
         │  │  └─ {Buffer}_StorageUnit/   one per configured buffer — see below
         │  │
         │  └─ SupportFunctions/          (only present if shifts are configured)
         │     └─ ShiftManagement/
         │        ├─ CurrentShiftNumber   (Int32)
         │        ├─ CurrentShiftName     (String)
         │        ├─ ShiftElapsedTime     (Double)
         │        ├─ ShiftTimeRemaining   (Double)
         │        ├─ CurrentShiftParts    (Int32)
         │        └─ CurrentShiftGoodParts (Int32)
         │
         └─ {Line}_Asset/
            └─ Identification/
               ├─ PhysicalAssetID  (String)
               └─ AssetClass       (String)  "ProductionLine"
```

## Per-station node structure (`{Station}_Equipment/`)

```
{Station}_Equipment/
  ├─ Identification/
  │  ├─ EquipmentID     (String)
  │  ├─ EquipmentClass  (String)  "WorkCell"
  │  └─ Description     (String)
  │
  ├─ OperationsState/
  │  ├─ State            (String)  IDLE | PROCESSING | BLOCKED | STARVED |
  │  │                              DEGRADED | FAILED | UNDER_REPAIR
  │  ├─ HealthState       (Int32)   only present if `health:` is configured
  │  ├─ HealthPercent     (Double)  100*(1 - health/h_max); only if health configured
  │  └─ CyclePhase        (Double)  0.0-1.0 progress through the current cycle
  │
  ├─ OperationsPerformance/
  │  ├─ PartCount         (Int32)
  │  ├─ ScrapCount        (Int32)
  │  ├─ ReworkCount       (Int32)
  │  ├─ BlockedTime, StarvedTime, DownTime,
  │  │  ProcessingTime, IdleTime, MinorStopTime  (Double, seconds accumulated)
  │
  ├─ OEE/
  │  ├─ Availability, Performance, Quality, OEE   (Double)
  │  └─ GoodPartCount, DefectivePartCount         (Int32)
  │
  ├─ Alarms/
  │  ├─ ActiveAlarmCount        (Int32)
  │  ├─ ActiveReasonCode        (String)  highest-severity active code, e.g. FM_BEARING_WEAR
  │  ├─ ActiveReasonText        (String)  human-readable
  │  ├─ LastAlarmMessage        (String)
  │  ├─ LastAlarmSeverity       (String)
  │  ├─ MachineFailureActive    (Boolean) any FM_* alarm active
  │  ├─ MaintenanceActive       (Boolean) any MT_* alarm active
  │  └─ QualityAlertActive      (Boolean) any PV_* alarm active
  │
  └─ ProcessValues/             (only present if `process_values:` is configured)
     └─ {PVName}                (Double)  one Float variable per configured process value
```

Reason codes follow the taxonomy `FM_*` (failure modes, CRITICAL), `PV_*` (process-value threshold, HIGH), `CS_*` (cycle stops, WARNING), `MT_*` (maintenance, INFO) — see `src/simengine/engine/alarms.py`.

## Per-buffer node structure (`{Buffer}_StorageUnit/`)

```
{Buffer}_StorageUnit/
  ├─ CurrentLevel   (Int32)
  ├─ Capacity       (Int32)
  └─ Alarms/
     ├─ ActiveAlarmCount           (Int32)
     ├─ HighLevelWarningActive     (Boolean)  level >= capacity
     └─ LowLevelWarningActive      (Boolean)  level == 0
```

## Writes

All variables are **read-only** during a run. `SimSpeedRatio` reflects the value the run was started with and cannot be changed via an OPC UA client at runtime; stop and restart the run (via REST, the UI, or an MCP tool) to change it.

## Optional node groups

| Node group | Present when |
|---|---|
| `HealthState`, `HealthPercent` | station has a `health:` block |
| `ProcessValues/` | station has a `process_values:` list |
| `SupportFunctions/ShiftManagement/` | scenario has `shifts.schedule` configured |

## Browsing (Python client)

```python
from opcua import Client

client = Client("opc.tcp://localhost:4840/simengine/")
client.connect()

root = client.get_objects_node()
line = root.get_child(["2:Acme", "2:Plant1", "2:Area01", "2:Line1_Equipment"])
press01 = line.get_child(["2:Resources", "2:Press01_Equipment"])
state = press01.get_child(["2:OperationsState", "2:State"])
print(state.get_value())  # "PROCESSING"

oil_temp = press01.get_child(["2:ProcessValues", "2:OilTemp"])
print(oil_temp.get_value())
```

Or resolve NodeIds via the knowledge graph instead of walking browse paths — `GET /api/v1/kg?type=ProcessValue` returns the exact `ns=2;s=...` NodeId for every configured process value alongside its SparkplugB, MQTT, and REST addresses. See [`docs/ai_interface.md`](ai_interface.md).
