# Historian + Grafana dashboards for scenario sense-checking

## Problem

There's no way to eyeball whether a running scenario is behaving sensibly —
states, KPIs, process values, and stoppage causes trending the way a human
watching an Optix/Ignition screen would expect — without polling the REST
API by hand. The `historian-influx` plugin (`simengine_historian_influx`)
already exists and records discrete events (state transitions, alarm
raise/clear, run start/end) to InfluxDB, and `docker-compose.yml` already has
an `influx` profile that stands up InfluxDB — but neither has ever been
exercised end-to-end, and there's no dashboard on top of either. The parent
project this repo was cloned from had a full Telegraf + Grafana pipeline (9
dashboards); it was deliberately deferred during the clone (see
`docs/specs/clone_build_plan.md`, `CLAUDE.md`'s "Known deferred items"), not
rebuilt.

## Data source decision

The parent's approach had Telegraf poll the OPC UA server directly and write
into InfluxDB — a second OPC UA subscriber, a large auto-generated
`telegraf.conf` per scenario (150KB in the parent repo, flagged as a
build-artifact anti-pattern in `docs/specs/performance_and_deployment_spec.md`),
and real added load on `CachedOpcuaNode`'s per-write lock/notify path (every
subscriber costs a per-write callback — same doc, D-series findings).

This design skips Telegraf and any wire-protocol polling entirely. The
engine's own `LineSnapshot` (what `SnapshotEventCollector` already reads
every step) is richer than either wire encoding: `publishers/metrics.py`
(the shared MQTT/SparkplugB schema) only carries `State, Health, PartsMade,
Good, Scrap, OEE, Availability, Performance, Quality, ActiveReasonCode` +
process values, but `StationSnapshot` additionally has the full `alarms`
list and `time_in_state` (seconds accumulated per state) — exactly the
downtime-attribution data a root-cause dashboard needs, and neither wire
encoding carries it. Historizing `LineSnapshot` directly, in-process, needs
no new service and no per-scenario config generation.

This means the dashboards answer "is this scenario's simulated behavior
sane" (engine ground truth), not "does the wire encoding exactly match the
engine" (wire fidelity) — the latter stays covered by the existing
single-source-of-truth architecture (`publishers/metrics.py`) and its tests,
not by this dashboard.

## Historian API change

`EventHistorian` (`src/simengine/events/__init__.py`) gains one new method
with a no-op default:

```python
def record_metrics(self, snapshot) -> None:
    """Record a periodic continuous-metrics sample. Default: no-op —
    only backends that support time-series metrics override this."""
```

Non-abstract (unlike `record_event`/`flush`/`close`/`get_event_count`), so
`simengine_historian_csv` and `simengine_historian_neo4j` need no changes.
`CompositeHistorian.record_metrics()` fans out to every backend, same
pattern as `record_events()`.

`InfluxDBHistorian` (`src/simengine_historian_influx/__init__.py`) overrides
it. It self-throttles on `snapshot.sim_time` (mirrors
`OPCUAMqttPublisher.publish`'s own throttle in
`src/simengine/publishers/opcua_mqtt.py`): tracks `_last_recorded_sim_time`,
no-ops until `sim_time - _last_recorded_sim_time >= sample_interval`.
`sample_interval` defaults to `5.0` seconds, configurable via a new
`INFLUXDB_SAMPLE_INTERVAL` env var — following the plugin's existing
convention of per-backend settings via env vars (`INFLUXDB_URL/TOKEN/ORG/BUCKET`),
not a new scenario-schema key (`CLAUDE.md`: "historians (plugin name list;
backends configured via env vars)").

`runtime/run_manager.py`'s `run_segment` gains one call alongside the
existing `collector.collect(snap)` / `historian.record_events(events)` pair
(around line 149-152):

```python
if historian is not None:
    historian.record_metrics(snap)
```

Called every step; the backend (not the caller) owns throttling — same
division of responsibility as the MQTT publisher.

## Data model

**`station_metrics`** measurement — tags `scenario`, `run_id`, `station`;
one point per station per sample, fields sourced from `StationSnapshot`:
`state` (string), `health`, `h_max`, `cycle_phase`, `parts_made`, `good`,
`scrap`, `rework`, `defective`, `availability`, `performance`, `quality`,
`oee`, `active_alarm_count` (`len(st.alarms)`), `active_reason_code` (reuse
`publishers/metrics.py`'s `top_reason_code()` helper — do not re-implement
the severity-ordering logic), one `time_in_state_<state>` field per one of the 7 canonical station states
(`engine/station.py`'s state constants lowercased —
`time_in_state_under_repair`, `time_in_state_failed`, `time_in_state_blocked`,
`time_in_state_starved`, `time_in_state_degraded`, `time_in_state_processing`,
`time_in_state_idle` — always all 7 present, `0.0` for unvisited states,
sourced from `st.time_in_state`), and one `pv_<name>` field per entry in
`st.process_values` (value only; `alarm_state`/`unit` are not carried since
Grafana panels don't need them per-sample and this keeps the schema stable
across PVs with different units).

**`line_metrics`** measurement — tags `scenario`, `run_id`; one point per
sample, fields from `LineSnapshot`: `sim_time`, `line_state`, `speed_ratio`,
`throughput`, `total_wip`, `total_good`, `total_scrap`, `oee`, one
`buffer_<name>_level` field per entry in `snapshot.buffers`.

Both share the `scenario`/`run_id` tag pair already used by the existing
`sim_events` measurement, so one `$scenario` + `$run_id` Grafana template
variable pair filters all three measurements consistently.

## Dashboards

Three, JSON-provisioned (Grafana file-based provisioning, no UI-driven setup)
under `docker/grafana/provisioning/` + `docker/grafana/dashboards/`:

1. **Line Overview** (`line_overview.json`) — station-state timeline
   (Grafana State Timeline panel type, one series per `$station`, repeated),
   line-level OEE/throughput/WIP trend from `line_metrics`.
2. **Station KPIs & PVs** (`station_kpis.json`) — per-station
   OEE/Availability/Performance/Quality trend and `pv_*` trends from
   `station_metrics`, panels repeated by `$station` (PV panels further
   scoped to the fields that exist for the selected station, since PV sets
   differ per station/scenario).
3. **Root Cause / Downtime** (`root_cause.json`) — alarm event table from
   `sim_events` (`event_type = 'ALARM'`: code from the `extra_json` field,
   message, station, timestamp), a Pareto bar chart of alarm-code
   occurrence counts, and a `time_in_state_*` breakdown bar per station
   (latest sample within the selected dashboard time range).

Template variables: `$scenario` and `$station` sourced from InfluxDB tag
values (`SHOW TAG VALUES` / Flux `schema.tagValues()` depending on the
provisioned datasource's query language), so the same 3 dashboards work
unmodified across every scenario without hardcoding station/PV names.

## Docker Compose

`grafana` is added to `docker/docker-compose.yml` under the **existing**
`influx` profile (not a new profile) — `--profile influx` brings up
InfluxDB + Grafana together, since Grafana is meaningless without the influx
historian populating it. Stock `grafana/grafana` image (no custom
Dockerfile, unlike the parent's `docker/grafana/Dockerfile`), provisioning
and dashboard JSON mounted as read-only volumes:

```yaml
grafana:
  image: grafana/grafana:11.3.0
  container_name: simengine-grafana
  profiles: ["influx"]
  ports:
    - "3000:3000"
  environment:
    GF_AUTH_ANONYMOUS_ENABLED: "true"
    GF_AUTH_ANONYMOUS_ORG_ROLE: Viewer
  volumes:
    - ./grafana/provisioning:/etc/grafana/provisioning:ro
    - ./grafana/dashboards:/var/lib/grafana/dashboards:ro
  depends_on:
    influxdb:
      condition: service_healthy
```

Anonymous viewer access (no login) — this is a local dev sense-check tool,
consistent with the rest of this repo's single-operator, no-auth posture
(`CLAUDE.md`: i3X has no auth either, for the same reason).

## Out of scope

- CSV and Neo4j historians — not part of this ask; `record_metrics()`'s
  no-op default leaves them exactly as they are today.
- Wire-level (OPC UA/MQTT) verification — explicitly traded away above in
  favor of engine ground truth.
- The other 6 legacy parent dashboards (shift comparison, SPC control
  charts, SPC machine detail, downtime/reliability, line balance, alarm
  event log as a standalone dashboard — folded into Root Cause / Downtime
  here instead) and the infra dashboards (`docker_containers.json`,
  `host_metrics.json`) — not ported.
- Any change to the `historians` scenario-schema shape (still a bare list of
  plugin names) or to `comms`/publisher behavior.

## Testing

- Unit tests for `InfluxDBHistorian.record_metrics()`'s throttling logic and
  field-flattening (`time_in_state_*`, `pv_*`, `buffer_*_level`), following
  the existing `simengine_historian_influx` test patterns (mocked
  `influxdb_client`, no real server needed — see how the existing
  `record_event` path is tested today for the pattern to match).
- `CompositeHistorian.record_metrics()` fan-out test.
- Default no-op verified for CSV/Neo4j backends (call `record_metrics()`,
  assert no error and no behavior change).
- End-to-end manual validation: `docker compose --profile influx up`, run a
  scenario with `historians: [influx]` configured, confirm `station_metrics`,
  `line_metrics`, and `sim_events` all land in InfluxDB with expected tags/
  fields, confirm all 3 dashboards render with real data and the `$scenario`/
  `$station` variables populate and filter correctly.
