# OPC UA Address Space Reference (ISA-95)

**Namespace URI:** `http://simengine.local/`
**Namespace Index:** `ns=2`
**Source:** `src/simengine/publishers/opcua_server.py`, `opcua_nodes.py`

Hierarchy names are configurable per scenario via `enterprise`, `site`, `area`, `line_name` (all default to generic placeholders — see `config/scenarios.yaml`).

## BrowseNames vs NodeIds

The tree below shows **BrowseNames** — what you see when browsing, carrying the
full configured ISA-95 hierarchy.

**NodeIds are deliberately different**: they do *not* embed the ISA-95 path, so
renaming `enterprise`, `site`, `area` or `line_name` never invalidates a client
binding. Only one line is served per address space, so no line qualifier is
needed.

| Node | BrowseName path | NodeId |
|---|---|---|
| Line | `Acme > Plant1 > Area01 > Line1_Equipment` | `ns=2;s=Line` |
| Line state | `… > OperationsState > SimTime` | `ns=2;s=Line.OperationsState.SimTime` |
| Station | `… > Resources > Press01_Equipment` | `ns=2;s=Station.Press01` |
| Station tag | `… > OperationsState > State` | `ns=2;s=Station.Press01.OperationsState.State` |
| Process value | `… > ProcessValues > OilTemp` | `ns=2;s=Station.Press01.ProcessValues.OilTemp` |
| Station asset | `… > Resources > Press01_Asset` | `ns=2;s=StationAsset.Press01` |
| Buffer | `… > Resources > B1_StorageUnit` | `ns=2;s=Buffer.B1` |
| Line asset | `… > Line1_Asset` | `ns=2;s=LineAsset` |

The functional group segment (`OperationsState`, `OEE`, `ProcessValues`, …) is
kept rather than flattening to `Station.Press01.State`, because process value
names come from user config and could otherwise collide with a metric name — a
PV called `State` or `OEE` is legal.

Bind clients to NodeIds, not browse paths. `GET /api/v1/kg` publishes the exact
NodeId for every metric and process value.

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
     └─ {PVName}                (Double)  AnalogItemType + EngineeringUnits/EURange — see below
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

## ObjectTypes

The address space declares two ObjectTypes in `ns=2`, and every station and
buffer is an **instance** of one rather than a bare `BaseObjectType`:

| Type | NodeId | Instances |
|---|---|---|
| `StationType` | `ns=2;s=StationType` | `ns=2;s=Station.{name}` |
| `BufferStorageUnitType` | `ns=2;s=BufferStorageUnitType` | `ns=2;s=Buffer.{name}` |

This is what lets a SCADA client build **one** screen bound to `StationType`
and reuse it for every station, instead of a hand-built screen per station.
Both types are included in the NodeSet2 export, so an importing client resolves
the `HasTypeDefinition` references.

`StationType` declares `Identification`, `OperationsState`,
`OperationsPerformance`, `OEE` and `Alarms` as mandatory members.
`HealthState`/`HealthPercent` are **optional** members, instantiated only for
stations that configure a `health:` block. `ProcessValues/` is per-station and
added to the instance rather than declared on the type, since the PV set
differs per station.

Instance child NodeIds are derived by the standard instantiation rule
`"{parent}.{BrowseName}"`, which is why typed nodes and readable NodeIds are
not in tension here.

## Process values are AnalogItemType

Each configured process value is modelled as OPC UA `AnalogItemType` carrying
two standard properties, so clients render units and default trend scaling
without any per-tag configuration:

- **`EngineeringUnits`** (`EUInformation`) — the PV's configured `unit`.
- **`EURange`** (`Range`) — a *display* range derived from the PV's own config:
  the span of the profile's operating parameters, widened to include any
  configured `alarm_high`/`alarm_low` so a trend scaled to it always shows the
  alarm thresholds. It is not a calibrated instrument range.

A PV whose config yields no usable span (e.g. `constant_noise` with `mean: 0`
and no `noise`) stays a plain `BaseDataVariableType` rather than being given an
invented scale — `EURange` is mandatory on `AnalogItemType`, so it is all or
nothing per tag.

## Browsing (Python client)

```python
from asyncua.sync import Client
from asyncua import ua

client = Client("opc.tcp://localhost:4840/simengine/")
client.connect()

# Preferred: resolve the namespace by URI (never hard-code the index) and
# address nodes by their rename-invariant NodeId.
idx = client.get_namespace_array().index("http://simengine.local/")
state = client.get_node(ua.NodeId("Station.Press01.OperationsState.State", idx))
print(state.read_value())  # "PROCESSING"

oil_temp = client.get_node(ua.NodeId("Station.Press01.ProcessValues.OilTemp", idx))
print(oil_temp.read_value())

# Browsing by BrowseName still works, but the path shifts whenever the
# scenario's ISA-95 names are edited:
root = client.nodes.objects
line = root.get_child([f"{idx}:Acme", f"{idx}:Plant1",
                       f"{idx}:Area01", f"{idx}:Line1_Equipment"])
```

Or resolve NodeIds via the knowledge graph instead of walking browse paths — `GET /api/v1/kg?type=ProcessValue` returns the exact `ns=2;s=...` NodeId for every configured process value alongside its SparkplugB, MQTT, and REST addresses. See [`docs/ai_interface.md`](ai_interface.md).

## Offline export: NodeSet2 XML

`GET /api/v1/schema/nodeset2.xml?scenario=<name>` returns the scenario's
address space as an OPC UA **NodeSet2** (`UANodeSet`) document — the standard
information-model exchange format. The Comms tab exposes it as
*Download NodeSet2 XML*.

No run is required: the file is built from the saved scenario config through
the same `build_address_space()` the live publisher uses, so it cannot drift
from what a run actually serves. Import it into FactoryTalk Optix, Ignition or
UaExpert to build and bind screens before the engine is even started.

The export is deterministic — same config in, byte-identical XML out — so the
file can be committed and diffed alongside the scenario it describes.

**Bind by namespace URI, not index.** The exported file numbers the simengine
namespace `ns=1` (NodeSet2 files use a document-local index), while the live
server serves it at `ns=2`. Resolve `http://simengine.local/` in the client's
namespace array and use the index it maps to — every conformant client
(Optix included) does this by default. The NodeId *strings* are identical
either way, and stable across restarts.

**Types are included.** The export carries the `StationType` /
`BufferStorageUnitType` ObjectTypes as well as the instance tree, so an
importing client resolves every `HasTypeDefinition` reference and can template
one screen per type. The ns=0 standard `Server` subtree is excluded.

**NodeIds are rename-invariant** — see "BrowseNames vs NodeIds" above. Renaming
`enterprise`, `site`, `area` or `line_name` changes BrowseNames only, so an
already-imported NodeSet2 keeps working; re-export only if you want the browse
labels refreshed.
