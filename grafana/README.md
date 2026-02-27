# Grafana Dashboards

9 dashboards for monitoring the Simantha manufacturing digital twin. All dashboards are auto-provisioned when running via Docker Compose and placed in the **Simantha Manufacturing** folder.

## Data Pipeline

Two InfluxDB measurements feed the dashboards:

| Measurement | Source | Content | Update Rate |
|-------------|--------|---------|-------------|
| `opcua` | Telegraf polling OPC UA server | All continuous KPIs: OEE, throughput, WIP, scrap, utilization, buffer levels, SPC, shifts, failure modes, MTTR/MTBF | Every 1s |
| `sim_events` | InfluxDB Historian (direct write) | State changes, alarms, shift changes, production summaries, SPC violations | Event-based (2-10/min) |

**Strategy**: Dashboards use `opcua` for continuous KPI trends and `sim_events` for event-based views (state timeline, alarm logs, shift history).

```
OPC UA Server (:4840)
  ├── Telegraf (1s poll) ──→ InfluxDB "opcua" measurement
  └── InfluxDB Historian ──→ InfluxDB "sim_events" measurement
                                    │
                              Grafana (:3000)
```

## Dashboards

### Manufacturing Overview (`manufacturing_overview.json`)

**UID:** `simantha-overview` | **Tags:** manufacturing, simantha, overview

High-level production status. Start here for a quick health check.

| Panel | Type | Source | Description |
|-------|------|--------|-------------|
| Line OEE | stat | `opcua` | Current OEE % with red/yellow/green thresholds |
| Throughput | stat | `opcua` | Total finished parts |
| Total WIP | stat | `opcua` | Work-in-progress across all buffers |
| Total Scrap | stat | `opcua` | Parts routed to scrap sinks |
| OEE Trend | timeseries | `opcua` | `LineOEE` over time |
| Throughput Over Time | timeseries | `opcua` | Cumulative production |
| Scrap Rate Trend | timeseries | `opcua` | `ScrapRate` over time |
| Events by Type | pie | `sim_events` | Counts per event type |
| Events by Source | pie | `sim_events` | Counts per equipment source |

### OEE Detail (`oee_detail.json`)

**UID:** `simantha-oee-detail` | **Tags:** manufacturing, simantha, oee

Deep OEE analysis with Availability/Performance/Quality breakdown at line and machine level.

| Panel | Type | Source | Description |
|-------|------|--------|-------------|
| Line OEE | gauge | `opcua` | OEE gauge (0-100%) |
| Availability | gauge | `opcua` | Availability component |
| Performance | gauge | `opcua` | Performance component |
| Quality | gauge | `opcua` | Quality component |
| Line OEE Components Over Time | timeseries | `opcua` | A, P, Q, OEE on one chart (color-coded) |
| OEE per Machine | bar gauge | `opcua` | `M{i}_OEE` comparison |
| Availability per Machine | bar gauge | `opcua` | `M{i}_Availability` comparison |
| Performance per Machine | bar gauge | `opcua` | `M{i}_Performance` comparison |
| Quality per Machine | bar gauge | `opcua` | `M{i}_Quality` comparison |
| OEE Trend per Machine | timeseries | `opcua` | Per-machine OEE over time |
| Availability Trend per Machine | timeseries | `opcua` | Identifies downtime-constrained stations |
| Good Parts per Machine | bar gauge | `opcua` | `M{i}_GoodParts` |
| Defective Parts per Machine | bar gauge | `opcua` | `M{i}_DefectParts` |
| Machine Performance Summary | table | `opcua` | TargetPPM, ActualPPM, PartCount, Utilisation |
| Performance Trend per Machine | timeseries | `opcua` | Speed loss patterns |
| Quality Trend per Machine | timeseries | `opcua` | Defect rate patterns |

### Machine KPIs (`machine_kpis.json`)

**UID:** `simantha-machine-kpis` | **Tags:** manufacturing, simantha, machine-kpis

Per-machine comparison view. All panels use regex matching (`M\d+_*`) so they auto-scale from 2-machine to 8-machine scenarios.

| Panel | Type | Source | Description |
|-------|------|--------|-------------|
| Per-Machine OEE | bar gauge | `opcua` | Side-by-side OEE comparison |
| Per-Machine Utilization | bar gauge | `opcua` | Utilization comparison |
| Per-Machine Part Count | bar gauge | `opcua` | Production count comparison |
| Scrap per Machine | bar gauge | `opcua` | `M{i}_ScrapCount` comparison |
| OEE Trend per Machine | timeseries | `opcua` | All machines on one chart |
| Machine Health Status | table | `opcua` | State + HealthPercent per machine |
| Active Alarms | table | `opcua` | MachineFailureActive + QualityAlertActive |

### Machine State Timeline (`machine_state_timeline.json`)

**UID:** `simantha-state-timeline` | **Tags:** manufacturing, simantha, state-timeline

Gantt-style visualization of machine states with color coding.

| Panel | Type | Source | Description |
|-------|------|--------|-------------|
| Machine State Timeline | state-timeline | `sim_events` | Color-coded state bars per machine |
| State Transition Counts | bar chart | `sim_events` | Stacked transition counts by state |
| Machine Utilization Trend | timeseries | `opcua` | `M{i}_Utilisation` over time |
| Buffer Levels Over Time | timeseries | `opcua` | `B{i}_Level` step chart |

**State colors:** PROCESSING=green, FAILED=red, BLOCKED=yellow, STARVED=orange, IDLE=blue, UNDER_REPAIR=purple, DEGRADED=cyan, PAUSED=gray

### Downtime & Reliability (`downtime_reliability.json`)

**UID:** `simantha-downtime-reliability` | **Tags:** manufacturing, simantha, downtime, reliability, mttr

Downtime analysis, failure mode drill-down, and maintenance tracking. Uses `machine` template variable (M1-M8) for failure mode detail.

| Panel | Type | Source | Description |
|-------|------|--------|-------------|
| Total Repairs | stat | `opcua` | `Sys_TotalRepairs` |
| Repair Queue | stat | `opcua` | `Sys_QueueLength` |
| Maintenance Active | stat | `opcua` | Yes/No indicator |
| Downtime per Machine | bar gauge | `opcua` | `M{i}_DownTime` (seconds) |
| Time-in-State Summary | table | `opcua` | ProcessingTime, BlockedTime, StarvedTime, DownTime, IdleTime per machine |
| Cumulative Downtime | timeseries | `opcua` | `M{i}_DownTime` trend |
| Blocked & Starved Time | timeseries | `opcua` | Identifies line balance issues |
| MTBF per Failure Mode | bar gauge | `opcua` | `${machine}_*MTBF` (selected machine) |
| MTTR per Failure Mode | bar gauge | `opcua` | `${machine}_*MTTR` (selected machine) |
| Failure Count per Mode | bar gauge | `opcua` | `${machine}_*FailureCount` |
| Total Downtime per Mode | bar gauge | `opcua` | `${machine}_*TotalDowntime` |
| MTBF Trends (All Machines) | timeseries | `opcua` | All `M{i}_*MTBF` fields |
| MTTR Trends (All Machines) | timeseries | `opcua` | All `M{i}_*MTTR` fields |
| Maintenance Strategy Summary | table | `opcua` | CMCount, PMCount, StrategyType, ActiveFailureMode |
| Repair Queue & Total Repairs | timeseries | `opcua` | Queue length + cumulative repairs (dual axis) |
| Recent Failure & Repair Events | table | `sim_events` | FAILED/UNDER_REPAIR state change log |

### SPC Control Charts (`spc_control_charts.json`)

**UID:** `simantha-spc` | **Tags:** manufacturing, simantha, spc

SPC overview with control charts for a selected machine. Uses `machine` template variable (M1-M8).

| Panel | Type | Source | Description |
|-------|------|--------|-------------|
| Cpk | stat | `opcua` | Thresholds: red <1.0, yellow <1.33, green >=1.33 |
| Sigma Level | stat | `opcua` | Process sigma level |
| Control Status | stat | `opcua` | IN CONTROL / OUT OF CONTROL |
| Violations | stat | `opcua` | Active violation count |
| X-bar Chart | timeseries | `opcua` | X-bar + UCL/CL/LCL (dashed control limits) |
| R Chart | timeseries | `opcua` | Range + UCL/CL/LCL (dashed control limits) |
| Capability Indices Trend | timeseries | `opcua` | Cp, Cpk, Pp, Ppk over time |
| All Machines Cpk Comparison | bar gauge | `opcua` | `M{i}_SPC_Cpk` side-by-side |

### SPC Machine Detail (`spc_machine_detail.json`)

**UID:** `simantha-spc-machine-detail` | **Tags:** manufacturing, simantha, spc, quality

Comprehensive SPC analysis with all-machine overview + per-machine drill-down. Uses `machine` template variable (M1-M8).

| Panel | Type | Source | Description |
|-------|------|--------|-------------|
| Cpk per Machine | bar gauge | `opcua` | All machines Cpk comparison |
| Cp per Machine | bar gauge | `opcua` | All machines Cp comparison |
| All Machines SPC Summary | table | `opcua` | Cpk, Cp, Pp, Ppk, Sigma, InControl, Samples, Subgroups, Violations |
| Cpk / Cp / Ppk / Sigma / Status / Samples | 6x stat | `opcua` | Selected machine detail stats row |
| X-bar Chart | timeseries | `opcua` | Large chart with UCL/CL/LCL, data points shown |
| R Chart | timeseries | `opcua` | Large chart with UCL/CL/LCL, data points shown |
| Capability Indices Trend | timeseries | `opcua` | Cp vs Cpk gap (centering offset), Pp vs Ppk |
| Sigma Level Trend | timeseries | `opcua` | Sigma level over time with thresholds |
| Cpk Trend — All Machines | timeseries | `opcua` | Cross-machine Cpk comparison over time |
| Sigma Level Trend — All Machines | timeseries | `opcua` | Cross-machine sigma comparison |
| SPC Violation History | table | `sim_events` | SPC_VIOLATION event log |

### Shift Comparison (`shift_comparison.json`)

**UID:** `simantha-shift-comparison` | **Tags:** manufacturing, simantha, shifts

Shift performance monitoring. Requires `shifts` config in the scenario.

| Panel | Type | Source | Description |
|-------|------|--------|-------------|
| Total Shift Changes | stat | `sim_events` | Count of SHIFT_CHANGE events |
| Current Shift | stat | `opcua` | `Shift_Name` |
| Total Parts (All Shifts) | stat | `opcua` | `ShiftTotal_Parts` |
| Current Shift OEE | stat | `opcua` | `CurrShift_OEE` |
| Current Shift Parts Over Time | timeseries | `opcua` | `CurrShift_Parts` trend |
| Cumulative Production | timeseries | `opcua` | Total throughput across shifts |
| Shift Change History | table | `sim_events` | SHIFT_CHANGE event details |

### Alarm Event Log (`alarm_event_log.json`)

**UID:** `simantha-alarm-log` | **Tags:** manufacturing, simantha, alarms

Alarm monitoring and event log. All data from `sim_events`.

| Panel | Type | Source | Description |
|-------|------|--------|-------------|
| Critical / Medium / Low / Total Alarms | 4x stat | `sim_events` | Counts by severity |
| Alarms by Severity | bar chart | `sim_events` | Color-coded severity distribution |
| Alarms by Equipment | bar chart | `sim_events` | Which machines generate most alarms |
| Recent Alarm Events | table | `sim_events` | Filterable log (last 100 events) |

## Template Variables

All dashboards include a `run_id` dropdown to filter by simulation run:

| Variable | Type | Used In | Description |
|----------|------|---------|-------------|
| `run_id` | query | All 9 dashboards | Lists `run_id` tag values from InfluxDB; defaults to "All" |
| `machine` | custom (M1-M8) | Downtime & Reliability, SPC Control Charts, SPC Machine Detail | Selects which machine to drill into |

The `run_id` is auto-generated as `{scenario}_{YYYYMMDD_HHMMSS}` at simulation startup and propagated through Telegraf's `[global_tags]` and the InfluxDB historian's tag fields.

## OPC UA Field Names (`opcua` measurement)

Fields are created by Telegraf polling the OPC UA address space. The set of fields depends on the scenario's enabled features.

### Always Present

| Field Pattern | Example | Description |
|---------------|---------|-------------|
| `SimTime` | — | Current simulation time |
| `LineState` | RUNNING | ISA-95 line state |
| `Throughput` | 142 | Total finished parts |
| `TotalWIP` | 8 | Sum of all buffer levels |
| `LineOEE` | 0.82 | Line-level OEE (0-1) |
| `LineAvailability` | 0.95 | Line availability component |
| `LinePerformance` | 0.91 | Line performance component |
| `LineQuality` | 0.95 | Line quality component |
| `LineGoodParts` | 135 | Good parts (line aggregate) |
| `LineDefectiveParts` | 7 | Defective parts (line aggregate) |
| `M{i}_State` | PROCESSING | Machine state (8 possible values) |
| `M{i}_PartCount` | 48 | Parts produced by machine |
| `M{i}_Utilisation` | 0.78 | Utilization ratio (0-1) |
| `M{i}_TargetPPM` | 6.0 | Target parts per minute |
| `M{i}_ActualPPM` | 5.2 | Actual parts per minute |
| `M{i}_ProcessingTime` | 480 | Cumulative processing time (s) |
| `M{i}_BlockedTime` | 30 | Cumulative blocked time (s) |
| `M{i}_StarvedTime` | 15 | Cumulative starved time (s) |
| `M{i}_DownTime` | 45 | Cumulative downtime (s) |
| `M{i}_IdleTime` | 30 | Cumulative idle time (s) |
| `M{i}_OEE` | 0.80 | Machine OEE (0-1) |
| `M{i}_Availability` | 0.92 | Machine availability (0-1) |
| `M{i}_Performance` | 0.90 | Machine performance (0-1) |
| `M{i}_Quality` | 0.97 | Machine quality (0-1) |
| `M{i}_GoodParts` | 46 | Good parts by machine |
| `M{i}_DefectParts` | 2 | Defective parts by machine |
| `M{i}_MachineFailureActive` | 0/1 | Failure alarm active |
| `M{i}_MaintenanceActive` | 0/1 | Maintenance in progress |
| `M{i}_QualityAlertActive` | 0/1 | Quality alert active |
| `B{i}_Level` | 3 | Current buffer inventory |
| `B{i}_Capacity` | 10 | Buffer maximum capacity |
| `Sys_MaintenanceActive` | 0/1 | Any maintenance in progress |
| `Sys_QueueLength` | 1 | Machines waiting for repair |
| `Sys_TotalRepairs` | 5 | Cumulative repair count |

### Conditional — Degradation/Advanced Failures

| Field Pattern | Description |
|---------------|-------------|
| `M{i}_HealthState` | Degradation level (0=healthy, N=failed) |
| `M{i}_HealthPercent` | Health as percentage (100% to 0%) |
| `M{i}_{Mode}FailureCount` | Failures per mode (e.g., `M1_MechanicalFailureCount`) |
| `M{i}_{Mode}TotalDowntime` | Downtime per failure mode |
| `M{i}_{Mode}MTBF` | Mean time between failures per mode |
| `M{i}_{Mode}MTTR` | Mean time to repair per mode |
| `M{i}_ActiveFailureMode` | Currently active failure mode name |
| `M{i}_StrategyType` | Maintenance strategy (fifo/spt/priority/bottleneck) |
| `M{i}_CMCount` | Corrective maintenance count |
| `M{i}_PMCount` | Preventive maintenance count |

### Conditional — SPC

| Field Pattern | Description |
|---------------|-------------|
| `M{i}_SPC_XBar` | Current X-bar (subgroup average) |
| `M{i}_SPC_XBar_UCL` | X-bar upper control limit |
| `M{i}_SPC_XBar_CL` | X-bar center line |
| `M{i}_SPC_XBar_LCL` | X-bar lower control limit |
| `M{i}_SPC_Range` | Current range value |
| `M{i}_SPC_R_UCL` | Range upper control limit |
| `M{i}_SPC_R_CL` | Range center line |
| `M{i}_SPC_R_LCL` | Range lower control limit |
| `M{i}_SPC_Cp` | Process capability index |
| `M{i}_SPC_Cpk` | Adjusted capability index |
| `M{i}_SPC_Pp` | Process performance index |
| `M{i}_SPC_Ppk` | Adjusted performance index |
| `M{i}_SPC_SigmaLevel` | Process sigma level |
| `M{i}_SPC_InControl` | In-control status (0/1) |
| `M{i}_SPC_Violations` | Active Western Electric rule violations |
| `M{i}_SPC_TotalSamples` | Total measurements collected |
| `M{i}_SPC_NumSubgroups` | Number of subgroups |

### Conditional — Quality Routing

| Field Pattern | Description |
|---------------|-------------|
| `M{i}_ScrapCount` | Parts routed to scrap |
| `M{i}_ReworkCount` | Parts sent for rework |
| `M{i}_ReworkSuccessCount` | Successfully reworked parts |
| `M{i}_ReworkSuccessRate` | Rework success ratio |
| `M{i}_GoodCount` | Parts passing quality check |
| `TotalScrap` | Total scrap across all machines |
| `ScrapRate` | Line scrap rate |
| `Scrap{i}_Level` | Scrap bin accumulation |

### Conditional — Shifts

| Field Pattern | Description |
|---------------|-------------|
| `Shift_Number` | Current shift ordinal |
| `Shift_Name` | Current shift name |
| `Shift_Elapsed` | Time elapsed in current shift |
| `Shift_Remaining` | Time remaining in current shift |
| `CurrShift_Parts` | Parts produced this shift |
| `CurrShift_OEE` | OEE this shift |
| `CurrShift_Avail` | Availability this shift |
| `CurrShift_Perf` | Performance this shift |
| `CurrShift_Qual` | Quality this shift |
| `PrevShift_Parts` | Parts produced previous shift |
| `PrevShift_OEE` | OEE previous shift |
| `ShiftTotal_Parts` | Cumulative parts all shifts |
| `ShiftTotal_Completed` | Number of completed shifts |

## Setup

### Docker Compose (recommended)

Dashboards are auto-provisioned — no manual import needed.

```bash
docker compose -f docker/docker-compose.yml up --build -d
```

- **Grafana:** http://localhost:3000 (login: `admin` / `simantha`)
- **InfluxDB:** http://localhost:8086 (login: `admin` / `simantha123`)
- **Web UI:** http://localhost:8080

Start a simulation via the Web UI, then open Grafana. Dashboards appear in the **Simantha Manufacturing** folder.

### Manual Import

If running Grafana standalone:

1. Configure InfluxDB data source:
   - **Query Language:** Flux
   - **URL:** `http://localhost:8086` (or `http://host.docker.internal:8086` from Docker)
   - **Organization:** `simantha`
   - **Token:** `simantha-dev-token`
   - **Default Bucket:** `manufacturing`
   - **Data source name:** `InfluxDB` (dashboards reference this name)

2. Import each `.json` file from `grafana/dashboards/` via **Dashboards > Import > Upload JSON file**.

### Telegraf Configuration

Telegraf polls the OPC UA server every 1s. The config is auto-generated per scenario:

```bash
python docker/telegraf/generate_telegraf_conf.py \
  --config config/line_models.yaml \
  --scenario full_feature_8_machine_line \
  --run-id "my_run_20260227" \
  --output docker/telegraf/telegraf.conf
```

The `run_id` is injected as a `[global_tags]` entry so all `opcua` data points are tagged and filterable per run.

## Example Flux Queries

### Line OEE (from `opcua`)
```flux
from(bucket: "manufacturing")
  |> range(start: -1h)
  |> filter(fn: (r) => r._measurement == "opcua")
  |> filter(fn: (r) => r._field == "LineOEE")
  |> aggregateWindow(every: 10s, fn: last, createEmpty: false)
  |> map(fn: (r) => ({r with _value: r._value * 100.0}))
```

### Per-machine OEE comparison
```flux
from(bucket: "manufacturing")
  |> range(start: -1h)
  |> filter(fn: (r) => r._measurement == "opcua")
  |> filter(fn: (r) => r._field =~ /^M\d+_OEE$/)
  |> last()
  |> map(fn: (r) => ({r with _value: r._value * 100.0}))
```

### MTTR per failure mode for a specific machine
```flux
from(bucket: "manufacturing")
  |> range(start: -1h)
  |> filter(fn: (r) => r._measurement == "opcua")
  |> filter(fn: (r) => r._field =~ /^M1_\w+MTTR$/)
  |> last()
```

### Buffer levels over time
```flux
from(bucket: "manufacturing")
  |> range(start: -1h)
  |> filter(fn: (r) => r._measurement == "opcua")
  |> filter(fn: (r) => r._field =~ /^B\d+_Level$/)
  |> aggregateWindow(every: 10s, fn: last, createEmpty: false)
```

### Filter by run_id
```flux
from(bucket: "manufacturing")
  |> range(start: -1h)
  |> filter(fn: (r) => r._measurement == "opcua")
  |> filter(fn: (r) => r.run_id == "full_feature_line_20260227_143000")
  |> filter(fn: (r) => r._field == "LineOEE")
  |> last()
```

### Machine state timeline (from `sim_events`)
```flux
from(bucket: "manufacturing")
  |> range(start: -1h)
  |> filter(fn: (r) => r._measurement == "sim_events")
  |> filter(fn: (r) => r.event_type == "STATE_CHANGE")
  |> filter(fn: (r) => r.source_type == "machine")
  |> filter(fn: (r) => r._field == "new_state")
  |> group(columns: ["source"])
```

### Critical alarms
```flux
from(bucket: "manufacturing")
  |> range(start: -1h)
  |> filter(fn: (r) => r._measurement == "sim_events")
  |> filter(fn: (r) => r.event_type == "ALARM")
  |> filter(fn: (r) => r.severity == "CRITICAL")
  |> filter(fn: (r) => r._field == "message")
```

## `sim_events` Measurement Schema

Event-based data written directly by the InfluxDB historian.

### Tags

| Tag | Example Values |
|-----|----------------|
| `event_type` | `STATE_CHANGE`, `ALARM`, `SHIFT_CHANGE`, `PRODUCTION_SUMMARY`, `SPC_VIOLATION`, `SCRAP`, `REWORK` |
| `source` | `M1`, `M2`, `B1`, `Line1` |
| `source_type` | `machine`, `buffer`, `line`, `shift` |
| `severity` | `INFO`, `LOW`, `MEDIUM`, `HIGH`, `CRITICAL` |
| `shift_name` | `Day Shift`, `Night Shift` |
| `run_id` | `full_feature_line_20260227_143000` |

### Fields

| Field | Type | Description |
|-------|------|-------------|
| `sim_time` | float | Simulation time at event |
| `message` | string | Human-readable event description |
| `old_state` | string | Previous state (STATE_CHANGE) |
| `new_state` | string | New state (STATE_CHANGE) |
| `partcount` | int | Total parts at event time |
| `good_parts` | int | Good parts at event time |
| `defective_parts` | int | Defective parts at event time |
| `buffer_level` | int | Buffer/WIP level (-1 if N/A) |
| `oee` | float | OEE at event time (0-1) |
| `utilisation` | float | Utilization at event time (0-1) |
| `extra_json` | string | Additional metadata as JSON |

## Troubleshooting

### No data in Grafana
- Verify InfluxDB is running: `curl http://localhost:8086/health`
- Confirm the simulation is producing data — check Web UI at http://localhost:8080
- Match the Grafana time range to your simulation run (default: last 1h)
- Verify bucket name: `manufacturing`
- Check the `run_id` dropdown — select "All" or the specific run

### Dashboards show "No data" for SPC/Shift/Failure panels
- These fields only exist if the scenario has the corresponding feature enabled
- Use `full_feature_line` or `full_feature_8_machine_line` scenarios for all panels to populate

### Telegraf not collecting data
- Verify OPC UA server is running on port 4840
- Check Telegraf logs: `docker logs simantha-telegraf`
- Regenerate telegraf.conf if you changed scenarios: run `generate_telegraf_conf.py`

### Connection refused between containers
- Use Docker service names (`influxdb`, `simantha`) not `localhost` for inter-container connections
- From host machine, use `localhost` with mapped ports (8086, 3000, 4840, 8080)

### Missing influxdb-client package
```bash
pip install influxdb-client>=1.30.0
```
The InfluxDB historian raises a clear error at startup if the package is missing.
