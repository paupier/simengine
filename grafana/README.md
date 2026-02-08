# Grafana + InfluxDB Setup Guide

Step-by-step guide for visualizing Simantha manufacturing simulation events in Grafana.

## Prerequisites

- Docker installed (recommended) or local InfluxDB/Grafana installations
- Python environment with `influxdb-client` package

## 1. Start InfluxDB 2.x

### Docker (recommended)

```bash
docker run -d \
  --name influxdb \
  -p 8086:8086 \
  -e DOCKER_INFLUXDB_INIT_MODE=setup \
  -e DOCKER_INFLUXDB_INIT_USERNAME=admin \
  -e DOCKER_INFLUXDB_INIT_PASSWORD=simantha123 \
  -e DOCKER_INFLUXDB_INIT_ORG=simantha \
  -e DOCKER_INFLUXDB_INIT_BUCKET=manufacturing \
  -e DOCKER_INFLUXDB_INIT_ADMIN_TOKEN=simantha-dev-token \
  influxdb:2.7
```

### Verify

Open http://localhost:8086 and log in with `admin` / `simantha123`.

## 2. Install Python Client

```bash
pip install influxdb-client>=1.30.0
```

## 3. Configure Simantha

Set your InfluxDB token as an environment variable:

```bash
# Windows
set INFLUXDB_TOKEN=simantha-dev-token

# Linux/Mac
export INFLUXDB_TOKEN=simantha-dev-token
```

Enable InfluxDB in your scenario's YAML config (or use `historian_line`):

```yaml
historian:
  enabled: true
  csv:
    enabled: true
    output_dir: "results/historian"
  influxdb:
    enabled: true
    url: "http://localhost:8086"
    token: "${INFLUXDB_TOKEN}"
    org: "simantha"
    bucket: "manufacturing"
    batch_size: 100
```

## 4. Run Simulation

```bash
python src/opcua_server.py --scenario historian_line
```

Events will be written to both CSV and InfluxDB simultaneously.

## 5. Start Grafana

### Docker

```bash
docker run -d \
  --name grafana \
  -p 3000:3000 \
  grafana/grafana:latest
```

Open http://localhost:3000 (default login: `admin` / `admin`).

## 6. Add InfluxDB Data Source

1. Go to **Configuration > Data Sources > Add data source**
2. Select **InfluxDB**
3. Configure:
   - **Query Language:** Flux
   - **URL:** `http://host.docker.internal:8086` (Docker) or `http://localhost:8086`
   - **Organization:** `simantha`
   - **Token:** `simantha-dev-token`
   - **Default Bucket:** `manufacturing`
4. Click **Save & Test**

## 7. Import Dashboards

1. Go to **Dashboards > Import**
2. Click **Upload JSON file**
3. Import each dashboard from `grafana/dashboards/`:

| Dashboard | File | Description |
|-----------|------|-------------|
| Manufacturing Overview | `manufacturing_overview.json` | KPI stats, throughput/OEE trends, event distribution |
| Machine State Timeline | `machine_state_timeline.json` | Gantt-style state bars, utilization, buffer levels |
| Alarm Event Log | `alarm_event_log.json` | Alarm counts by severity, filterable event table |
| Shift Comparison | `shift_comparison.json` | Per-shift parts/OEE, production timeline |

4. Select **InfluxDB** as the data source for each dashboard

## Alternative: CSV with Infinity Plugin

If you don't want to run InfluxDB, you can visualize CSV files directly using the **Grafana Infinity** plugin:

1. Install plugin: `grafana-cli plugins install yesoreyeram-infinity-datasource`
2. Add Infinity data source pointing to your CSV file
3. Create panels using CSV as the data source

Note: The Infinity plugin has limited time-series capabilities compared to InfluxDB.

## InfluxDB Measurement Schema

All events are stored in the `sim_events` measurement:

### Tags (indexed, filterable)

| Tag | Description | Example Values |
|-----|-------------|----------------|
| `event_type` | Type of event | `STATE_CHANGE`, `ALARM`, `SHIFT_CHANGE`, `PRODUCTION_SUMMARY` |
| `source` | Equipment name | `M1`, `M2`, `B1`, `Line1` |
| `source_type` | Equipment category | `machine`, `buffer`, `line`, `shift` |
| `severity` | Event severity | `INFO`, `LOW`, `MEDIUM`, `HIGH`, `CRITICAL` |
| `scenario` | Scenario name | `historian_line` |
| `shift_name` | Current shift | `Day Shift`, `Night Shift` |

### Fields (values)

| Field | Type | Description |
|-------|------|-------------|
| `sim_time` | float | Simulation time |
| `message` | string | Human-readable event description |
| `old_state` | string | Previous state (for STATE_CHANGE) |
| `new_state` | string | New state (for STATE_CHANGE) |
| `partcount` | int | Total parts at event time |
| `good_parts` | int | Good parts at event time |
| `defective_parts` | int | Defective parts at event time |
| `buffer_level` | int | Buffer level (-1 if N/A) |
| `oee` | float | OEE at event time |
| `utilisation` | float | Utilization at event time |
| `extra_json` | string | Additional metadata as JSON |

## Example Flux Queries

### Count events by type
```flux
from(bucket: "manufacturing")
  |> range(start: -1h)
  |> filter(fn: (r) => r._measurement == "sim_events")
  |> filter(fn: (r) => r._field == "sim_time")
  |> group(columns: ["event_type"])
  |> count()
```

### Machine state changes over time
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

### Production throughput trend
```flux
from(bucket: "manufacturing")
  |> range(start: -1h)
  |> filter(fn: (r) => r._measurement == "sim_events")
  |> filter(fn: (r) => r.event_type == "PRODUCTION_SUMMARY")
  |> filter(fn: (r) => r._field == "partcount")
  |> aggregateWindow(every: 1m, fn: last, createEmpty: false)
```

## Troubleshooting

### No data in Grafana
- Verify InfluxDB is running: `curl http://localhost:8086/health`
- Check the simulation is writing events: look for log output like `Event historian enabled: CSVHistorian + InfluxDBHistorian`
- Verify the time range in Grafana matches your simulation run time
- Check the bucket name matches: `manufacturing`

### Connection refused
- If using Docker, use `host.docker.internal` instead of `localhost` for the InfluxDB URL in Grafana
- Ensure ports 8086 (InfluxDB) and 3000 (Grafana) are not blocked

### Missing influxdb-client package
```
pip install influxdb-client>=1.30.0
```
The InfluxDB backend will raise a clear error if the package is not installed.
