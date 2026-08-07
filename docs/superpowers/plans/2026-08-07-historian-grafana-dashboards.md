# Historian + Grafana Dashboards Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give simengine a scenario sense-check tool: periodic continuous metrics + the existing discrete event log flow into InfluxDB, visualized in 3 Grafana dashboards, both gated behind the existing `--profile influx` docker-compose profile.

**Architecture:** `EventHistorian` gains a `record_metrics(snapshot)` method (no-op default); `InfluxDBHistorian` overrides it to write two new time-series measurements (`station_metrics`, `line_metrics`) straight from the engine's `LineSnapshot`, self-throttled by sim-time. `run_manager.run_segment` calls it every step alongside the existing discrete-event path. `docker-compose.yml` adds a `grafana` service to the `influx` profile, provisioned (datasource + 3 dashboard JSONs) via file-based provisioning — no UI setup, no Telegraf, no wire-protocol polling.

**Tech Stack:** Python (`influxdb-client`), Grafana 11.3 (Flux query language against InfluxDB 2.x), Docker Compose.

## Global Constraints

- No Telegraf, no OPC UA/MQTT polling — data comes from `LineSnapshot` directly, in-process (spec's "Data source decision").
- `EventHistorian.record_metrics()` is a **non-abstract** method with a no-op default. `simengine_historian_csv`'s `CSVHistorian(EventHistorian)` inherits it for free. `simengine_historian_neo4j`'s `Neo4jHistorian` does **not** inherit `EventHistorian` at all (it's a duck-typed standalone class — confirmed via `grep -n "^class Neo4jHistorian" src/simengine_historian_neo4j/historian.py`, no base class), so it needs its own explicit no-op `record_metrics` method (Task 1) or `CompositeHistorian.record_metrics()` raises `AttributeError` on any run configured with `historians: ["neo4j"]`, crashing the run loop the moment Task 3 wires the call into `run_segment`.
- `sample_interval` is configured via a new `INFLUXDB_SAMPLE_INTERVAL` env var (default `5.0` seconds) — **not** a new scenario-schema key (`CLAUDE.md`: "historians (plugin name list; backends configured via env vars)").
- `station_metrics` tags: `scenario`, `run_id`, `station`. Fields: `state`, `health`, `h_max`, `cycle_phase`, `parts_made`, `good`, `scrap`, `rework`, `defective`, `availability`, `performance`, `quality`, `oee`, `active_alarm_count`, `active_reason_code`, `time_in_state_under_repair`, `time_in_state_failed`, `time_in_state_blocked`, `time_in_state_starved`, `time_in_state_degraded`, `time_in_state_processing`, `time_in_state_idle`, `pv_<name>` per process value.
- `line_metrics` tags: `scenario`, `run_id`. Fields: `sim_time`, `line_state`, `speed_ratio`, `throughput`, `total_wip`, `total_good`, `total_scrap`, `oee`, `buffer_<name>_level` per buffer.
- `active_reason_code` must reuse `publishers/metrics.py`'s `top_reason_code()` helper — do not re-implement the severity-ordering logic.
- Grafana rides the **existing** `influx` profile — no new compose profile.
- Grafana access is anonymous/no-login (`GF_AUTH_ANONYMOUS_ENABLED=true`, Viewer role) — matches this repo's single-operator, no-auth posture.
- CSV and Neo4j historians are out of scope for new functionality — Neo4j's one-line `record_metrics` no-op (Task 1) is a required correctness fix to keep `historians: ["neo4j"]` runs from crashing once Task 3 wires the call in, not new functionality.

---

### Task 1: `EventHistorian.record_metrics()` no-op default + `CompositeHistorian` fan-out + Neo4j no-op

**Files:**
- Modify: `src/simengine/events/__init__.py` (the `EventHistorian` ABC, ~line 62-88; `CompositeHistorian`, ~line 100-131)
- Modify: `src/simengine_historian_neo4j/historian.py` (`Neo4jHistorian`, add after `record_events`, ~line 247-251)
- Test: `tests/test_event_historian.py`, `tests/test_historian_plugins.py`

**Interfaces:**
- Produces: `EventHistorian.record_metrics(self, snapshot) -> None` (no-op default, overridable). `CompositeHistorian.record_metrics(self, snapshot) -> None` fans out to every backend. `Neo4jHistorian.record_metrics(self, snapshot) -> None` (no-op — Neo4j is a graph/causal-analysis backend, not a time-series one; it does not inherit `EventHistorian` so needs this explicitly).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_event_historian.py`, inside `class TestCompositeHistorian` (after the existing `test_delegates_record_events` method — read the file first to place it correctly):

```python
    def test_record_metrics_fans_out(self):
        h1 = MagicMock(spec=EventHistorian)
        h2 = MagicMock(spec=EventHistorian)
        composite = CompositeHistorian([h1, h2])

        snapshot = object()
        composite.record_metrics(snapshot)
        h1.record_metrics.assert_called_once_with(snapshot)
        h2.record_metrics.assert_called_once_with(snapshot)
```

Add a new top-level test class in the same file:

```python
class TestRecordMetricsDefault:
    def test_default_is_noop(self):
        class DummyHistorian(EventHistorian):
            def record_event(self, event): pass
            def flush(self): pass
            def close(self): pass
            def get_event_count(self): return 0

        hist = DummyHistorian()
        hist.record_metrics(object())  # must not raise
```

Add to `tests/test_historian_plugins.py`, inside `class TestCSVHistorian` (after `test_describe`):

```python
    def test_record_metrics_is_noop(self, tmp_path):
        hist = CSVHistorian(str(tmp_path), "test_scenario")
        hist.record_metrics(object())  # inherited no-op, must not raise
        hist.close()
```

Add a new test class to `tests/test_historian_plugins.py` (after `class TestInfluxDBHistorian:`'s block, before `class TestRunID:`):

```python
class TestNeo4jHistorian:
    def test_record_metrics_is_noop(self):
        from simengine_historian_neo4j.historian import Neo4jHistorian
        hist = Neo4jHistorian.__new__(Neo4jHistorian)  # bypass __init__, no real driver needed
        hist.record_metrics(object())  # must not raise
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_event_historian.py tests/test_historian_plugins.py -v -k "record_metrics"`
Expected: FAIL on all four new tests — `CompositeHistorian`/`DummyHistorian`/`CSVHistorian`/`Neo4jHistorian` have no `record_metrics` attribute yet.

- [ ] **Step 3: Implement**

In `src/simengine/events/__init__.py`, inside `class EventHistorian(ABC):`, add a new **non-abstract** method (no `@abstractmethod` decorator) right after the `record_events` method:

```python
    def record_metrics(self, snapshot) -> None:
        """Record a periodic continuous-metrics sample. Default: no-op —
        only backends that support time-series metrics override this."""
```

In `class CompositeHistorian(EventHistorian):`, add a method right after `record_events`:

```python
    def record_metrics(self, snapshot) -> None:
        for h in self._historians:
            h.record_metrics(snapshot)
```

In `src/simengine_historian_neo4j/historian.py`, inside `class Neo4jHistorian:`, add a method right after `record_events` (before `flush`):

```python
    def record_metrics(self, snapshot) -> None:
        """No-op — Neo4j is a graph/causal-analysis backend, not time-series."""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_event_historian.py tests/test_historian_plugins.py -v -k "record_metrics"`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add src/simengine/events/__init__.py src/simengine_historian_neo4j/historian.py tests/test_event_historian.py tests/test_historian_plugins.py
git commit -m "feat: add EventHistorian.record_metrics() no-op default + CompositeHistorian fan-out + Neo4j no-op"
```

---

### Task 2: `InfluxDBHistorian.record_metrics()` — station_metrics/line_metrics writer

**Files:**
- Modify: `src/simengine_historian_influx/__init__.py`
- Test: `tests/test_historian_plugins.py`

**Interfaces:**
- Consumes: `EventHistorian.record_metrics(self, snapshot)` signature from Task 1. `publishers.metrics.top_reason_code(station_snapshot) -> str` (existing, `src/simengine/publishers/metrics.py:49`).
- Produces: `InfluxDBHistorian.record_metrics(self, snapshot)` — writes one `station_metrics` point per station + one `line_metrics` point, throttled by `self._sample_interval` against `snapshot.sim_time`. `InfluxDBHistorian.__init__` gains a `sample_interval: float = 5.0` parameter. `create(scenario_name, run_id)` factory reads `INFLUXDB_SAMPLE_INTERVAL` env var (default `"5"`).

The `snapshot` argument is duck-typed (a `LineSnapshot`-shaped object: `.sim_time`, `.line_state`, `.speed_ratio`, `.throughput`, `.total_wip`, `.total_good`, `.total_scrap`, `.oee`, `.stations` dict of name -> station-snapshot-shaped object with `.state, .health, .h_max, .cycle_phase, .parts_made, .good, .scrap, .rework, .defective, .availability, .performance, .quality, .oee, .time_in_state (dict), .alarms (list), .process_values (list of objects with .name, .value)`, `.buffers` dict of name -> object with `.level`). Do not import `simengine.engine.*` in this plugin file — historian plugins only depend on `simengine.events` and (for this task) `simengine.publishers.metrics`, keeping them decoupled from engine internals, matching the existing `SimEvent`-based decoupling.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_historian_plugins.py`, inside `class TestInfluxDBHistorian` (after the existing `test_describe` method):

```python
    def _make_snapshot(self):
        from types import SimpleNamespace
        pv = SimpleNamespace(name="RamForce", value=850.5)
        alarm = SimpleNamespace(code="CS_JAM", severity="WARNING",
                                source="Press01", text="Press01: cycle stop - CS_JAM",
                                activated_at=10.0)
        station = SimpleNamespace(
            state="PROCESSING", health=2, h_max=5, cycle_phase=0.5,
            parts_made=10, good=9, scrap=1, rework=0, defective=1,
            availability=0.95, performance=0.9, quality=0.9, oee=0.77,
            time_in_state={"PROCESSING": 100.0, "IDLE": 20.0},
            alarms=[alarm], process_values=[pv],
        )
        buffer = SimpleNamespace(level=3)
        return SimpleNamespace(
            sim_time=120.0, line_state="RUNNING", speed_ratio=1.0,
            throughput=0.5, total_wip=3, total_good=9, total_scrap=1,
            oee=0.77, stations={"Press01": station}, buffers={"B1": buffer},
        )

    def test_record_metrics_writes_station_and_line_points(self):
        hist = InfluxDBHistorian.__new__(InfluxDBHistorian)
        hist._scenario = "demo_line"
        hist._run_id = "run1"
        hist._bucket = "manufacturing"
        hist._org = "simengine"
        hist._sample_interval = 5.0
        hist._last_recorded_sim_time = None

        mock_chain = MagicMock()
        mock_point_cls = MagicMock(return_value=mock_chain)
        mock_chain.tag.return_value = mock_chain
        mock_chain.field.return_value = mock_chain
        mock_write_api = MagicMock()
        hist._write_api = mock_write_api

        mock_influx = MagicMock()
        mock_influx.Point = mock_point_cls
        with patch.dict("sys.modules", {"influxdb_client": mock_influx}):
            hist.record_metrics(self._make_snapshot())

        assert hist._last_recorded_sim_time == 120.0
        mock_write_api.write.assert_called_once()
        _, kwargs = mock_write_api.write.call_args
        assert kwargs["bucket"] == "manufacturing"
        assert kwargs["org"] == "simengine"
        points = kwargs["record"]
        assert len(points) == 2  # 1 station + 1 line

        # Point("station_metrics") called once, Point("line_metrics") once
        measurement_calls = [c[0][0] for c in mock_point_cls.call_args_list]
        assert measurement_calls == ["station_metrics", "line_metrics"]

        # tags (both points chain off the same mock, so calls accumulate across both)
        tag_calls = [c[0] for c in mock_chain.tag.call_args_list]
        assert ("scenario", "demo_line") in tag_calls
        assert ("station", "Press01") in tag_calls

        # station fields include the flattened time_in_state and pv_ fields
        field_names = [c[0][0] for c in mock_chain.field.call_args_list]
        assert "time_in_state_processing" in field_names
        assert "time_in_state_idle" in field_names
        assert "time_in_state_under_repair" in field_names  # zero-filled, unvisited state
        assert "pv_RamForce" in field_names
        assert "active_reason_code" in field_names
        assert "active_alarm_count" in field_names

        # line fields
        assert "buffer_B1_level" in field_names
        assert "total_wip" in field_names

    def test_record_metrics_throttled(self):
        hist = InfluxDBHistorian.__new__(InfluxDBHistorian)
        hist._scenario = "demo_line"
        hist._run_id = "run1"
        hist._bucket = "manufacturing"
        hist._org = "simengine"
        hist._sample_interval = 5.0
        hist._last_recorded_sim_time = 118.0  # < 2s since last sample at sim_time=120.0

        mock_write_api = MagicMock()
        hist._write_api = mock_write_api
        mock_influx = MagicMock()
        with patch.dict("sys.modules", {"influxdb_client": mock_influx}):
            hist.record_metrics(self._make_snapshot())

        mock_write_api.write.assert_not_called()
        assert hist._last_recorded_sim_time == 118.0  # unchanged
```

Also add, inside `class TestInfluxDBHistorian`:

```python
    def test_create_reads_sample_interval_env(self, monkeypatch):
        from simengine_historian_influx import create
        monkeypatch.setenv("INFLUXDB_SAMPLE_INTERVAL", "10")
        monkeypatch.setenv("INFLUXDB_TOKEN", "t")
        # create() constructs a real InfluxDBHistorian; patch __init__ to capture kwargs
        # instead of touching a real client.
        captured = {}
        original_init = InfluxDBHistorian.__init__

        def fake_init(self, **kwargs):
            captured.update(kwargs)

        monkeypatch.setattr(InfluxDBHistorian, "__init__", fake_init)
        try:
            create("demo_line", "run1")
        finally:
            monkeypatch.setattr(InfluxDBHistorian, "__init__", original_init)
        assert captured["sample_interval"] == 10.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_historian_plugins.py -v -k "record_metrics or sample_interval"`
Expected: FAIL — `AttributeError: 'InfluxDBHistorian' object has no attribute 'record_metrics'` (and the env-var test fails since `create()` doesn't pass `sample_interval` yet).

- [ ] **Step 3: Implement**

In `src/simengine_historian_influx/__init__.py`:

Add near the top, after the existing imports, a module-level tuple of the 7 canonical station states:

```python
_STATION_STATES = ("UNDER_REPAIR", "FAILED", "BLOCKED", "STARVED", "DEGRADED",
                    "PROCESSING", "IDLE")
```

Change the import line `from simengine.events import EventHistorian, SimEvent, _resolve_env_vars` to also import the reused helper:

```python
from simengine.events import EventHistorian, SimEvent, _resolve_env_vars
from simengine.publishers.metrics import top_reason_code
```

In `InfluxDBHistorian.__init__`, add a `sample_interval: float = 5.0` parameter and two new instance attributes. The signature becomes:

```python
    def __init__(self, url: str, token: str, org: str, bucket: str,
                 scenario_name: str, batch_size: int = 100,
                 run_id: str = "", sample_interval: float = 5.0):
```

and inside the body, after `self._event_count = 0`, add:

```python
        self._sample_interval = sample_interval
        self._last_recorded_sim_time = None
```

Add three new methods after `_event_to_point` (before `record_event`):

```python
    def _station_metrics_point(self, name: str, st):
        from influxdb_client import Point

        point = (
            Point("station_metrics")
            .tag("scenario", self._scenario)
            .tag("run_id", self._run_id)
            .tag("station", name)
            .field("state", st.state)
            .field("health", int(st.health))
            .field("h_max", int(st.h_max))
            .field("cycle_phase", float(st.cycle_phase))
            .field("parts_made", int(st.parts_made))
            .field("good", int(st.good))
            .field("scrap", int(st.scrap))
            .field("rework", int(st.rework))
            .field("defective", int(st.defective))
            .field("availability", float(st.availability))
            .field("performance", float(st.performance))
            .field("quality", float(st.quality))
            .field("oee", float(st.oee))
            .field("active_alarm_count", len(st.alarms))
            .field("active_reason_code", top_reason_code(st))
        )
        for state in _STATION_STATES:
            point = point.field(f"time_in_state_{state.lower()}",
                                float(st.time_in_state.get(state, 0.0)))
        for pv in st.process_values:
            point = point.field(f"pv_{pv.name}", float(pv.value))
        return point

    def _line_metrics_point(self, snapshot):
        from influxdb_client import Point

        point = (
            Point("line_metrics")
            .tag("scenario", self._scenario)
            .tag("run_id", self._run_id)
            .field("sim_time", float(snapshot.sim_time))
            .field("line_state", snapshot.line_state)
            .field("speed_ratio", float(snapshot.speed_ratio))
            .field("throughput", float(snapshot.throughput))
            .field("total_wip", int(snapshot.total_wip))
            .field("total_good", int(snapshot.total_good))
            .field("total_scrap", int(snapshot.total_scrap))
            .field("oee", float(snapshot.oee))
        )
        for bname, buf in snapshot.buffers.items():
            point = point.field(f"buffer_{bname}_level", int(buf.level))
        return point

    def record_metrics(self, snapshot) -> None:
        if (self._last_recorded_sim_time is not None
                and snapshot.sim_time - self._last_recorded_sim_time < self._sample_interval):
            return
        self._last_recorded_sim_time = snapshot.sim_time
        points = [self._station_metrics_point(name, st)
                  for name, st in snapshot.stations.items()]
        points.append(self._line_metrics_point(snapshot))
        self._write_api.write(bucket=self._bucket, org=self._org, record=points)
```

In the `create()` factory function, add the new kwarg:

```python
def create(scenario_name: str, run_id: str) -> InfluxDBHistorian:
    return InfluxDBHistorian(
        url=os.environ.get("INFLUXDB_URL", "http://localhost:8086"),
        token=_resolve_env_vars(os.environ.get("INFLUXDB_TOKEN", "")),
        org=os.environ.get("INFLUXDB_ORG", "simengine"),
        bucket=os.environ.get("INFLUXDB_BUCKET", "manufacturing"),
        scenario_name=scenario_name,
        run_id=run_id,
        sample_interval=float(os.environ.get("INFLUXDB_SAMPLE_INTERVAL", "5")),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_historian_plugins.py -v -k "record_metrics or sample_interval"`
Expected: PASS (3 passed)

Then run the full plugin test file to make sure nothing existing broke:

Run: `.venv/bin/pytest tests/test_historian_plugins.py -v`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add src/simengine_historian_influx/__init__.py tests/test_historian_plugins.py
git commit -m "feat: InfluxDBHistorian.record_metrics() writes station_metrics/line_metrics"
```

---

### Task 3: Wire `record_metrics` into `run_manager.run_segment`

**Files:**
- Modify: `src/simengine/runtime/run_manager.py:149-152`
- Test: `tests/test_run_manager.py` (existing file — covers `run_segment` glue behavior; add a new test class there following its established pattern)

**Interfaces:**
- Consumes: `EventHistorian.record_metrics(snapshot)` (Task 1), `historian`/`collector` locals already present in `run_segment` (existing code, `src/simengine/runtime/run_manager.py:114-152`). `two_station_config()` and the `NO_COMMS` constant already defined at the top of `tests/test_run_manager.py` (lines 15-25) — reuse them, don't redefine.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_run_manager.py`, after the existing `class TestConfigExposure:` block (read the file first — this plan assumes the two-station helpers at the top of the file, confirmed present: `NO_COMMS = {"opcua": {"enabled": False}}` and `def two_station_config(shifts_schedule=None)`):

```python
class TestRecordMetricsWiring:
    def test_record_metrics_called_each_step(self):
        from unittest.mock import MagicMock
        from simengine.events import EventHistorian
        from simengine.events.collect import SnapshotEventCollector

        config = two_station_config()
        engine = LineEngine(config, "wiring_test", seed=1, run_id="run_w")
        publishers = build_publishers(config)
        historian = MagicMock(spec=EventHistorian)
        collector = SnapshotEventCollector()

        rm = RunManager()
        rm.engine = engine
        rm.run_segment(engine, publishers, speed_ratio=1e9,
                        max_sim_time=3.0, historian=historian, collector=collector)

        assert historian.record_metrics.call_count > 0
        # called with the LineSnapshot, not the collected events
        called_arg = historian.record_metrics.call_args_list[0][0][0]
        assert hasattr(called_arg, "sim_time")

    def test_record_metrics_not_called_without_historian(self):
        config = two_station_config()
        engine = LineEngine(config, "wiring_test2", seed=1, run_id="run_w2")
        publishers = build_publishers(config)

        rm = RunManager()
        rm.engine = engine
        # Must not raise even though historian/collector default to None.
        rm.run_segment(engine, publishers, speed_ratio=1e9, max_sim_time=3.0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_run_manager.py -v -k TestRecordMetricsWiring`
Expected: FAIL — `test_record_metrics_called_each_step` fails because `historian.record_metrics.call_count == 0` (the method exists as a no-op mock but is never called by `run_segment` yet); `test_record_metrics_not_called_without_historian` should already pass (nothing calls `record_metrics` yet at all) — that's expected, it's a regression guard for the next step, not a red test.

- [ ] **Step 3: Implement**

In `src/simengine/runtime/run_manager.py`, replace the block at line 149-152:

```python
            if historian is not None and collector is not None:
                events = collector.collect(snap)
                if events:
                    historian.record_events(events)
```

with:

```python
            if historian is not None:
                historian.record_metrics(snap)
                if collector is not None:
                    events = collector.collect(snap)
                    if events:
                        historian.record_events(events)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_run_manager.py -v -k TestRecordMetricsWiring`
Expected: PASS (2 passed)

Then run the full suite to confirm nothing else regressed:

Run: `.venv/bin/pytest tests/ -q`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add src/simengine/runtime/run_manager.py tests/test_run_manager.py
git commit -m "feat: call historian.record_metrics() every step in run_segment"
```

---

### Task 4: Grafana service + provisioning (datasource + dashboard loader)

**Files:**
- Modify: `docker/docker-compose.yml`
- Create: `docker/grafana/provisioning/datasources/influxdb.yml`
- Create: `docker/grafana/provisioning/dashboards/dashboards.yml`
- Create: `docker/grafana/dashboards/` (directory — populated in Task 5)

**Interfaces:**
- Consumes: the `influxdb` service already defined in `docker/docker-compose.yml` (`profiles: ["influx"]`, port 8086, env vars `INFLUXDB_USER/PASSWORD/ORG=simengine (hardcoded)/BUCKET=manufacturing (hardcoded)/ADMIN_TOKEN`).
- Produces: a `grafana` service on the `influx` profile, reachable at `localhost:3000`, with datasource UID `influxdb-simengine` — Task 5's dashboard JSON references this UID.

- [ ] **Step 1: Add the `grafana` service to docker-compose.yml**

In `docker/docker-compose.yml`, add a new service after the `influxdb` service block (before `neo4j:`):

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
      INFLUXDB_TOKEN: ${INFLUXDB_TOKEN:-simengine-dev-token}
      INFLUXDB_ORG: simengine
      INFLUXDB_BUCKET: manufacturing
    volumes:
      - ./grafana/provisioning:/etc/grafana/provisioning:ro
      - ./grafana/dashboards:/var/lib/grafana/dashboards:ro
    depends_on:
      influxdb:
        condition: service_healthy
```

Also update the header comment block at the top of the file (currently lines 1-11) to mention Grafana under the `influx` profile bullet — change:

```
#   --profile influx  -> influxdb (event historian target; Grafana/Telegraf
#                        port from the parent stack is deferred)
```

to:

```
#   --profile influx  -> influxdb + grafana (event historian target + 3
#                        pre-provisioned dashboards at localhost:3000)
```

- [ ] **Step 2: Create the datasource provisioning file**

Create `docker/grafana/provisioning/datasources/influxdb.yml`:

```yaml
apiVersion: 1

datasources:
  - name: InfluxDB
    uid: influxdb-simengine
    type: influxdb
    access: proxy
    url: http://influxdb:8086
    isDefault: true
    jsonData:
      version: Flux
      organization: ${INFLUXDB_ORG}
      defaultBucket: ${INFLUXDB_BUCKET}
      tlsSkipVerify: true
    secureJsonData:
      token: ${INFLUXDB_TOKEN}
```

- [ ] **Step 3: Create the dashboard provider file**

Create `docker/grafana/provisioning/dashboards/dashboards.yml`:

```yaml
apiVersion: 1

providers:
  - name: simengine
    orgId: 1
    folder: ""
    type: file
    disableDeletion: false
    updateIntervalSeconds: 30
    options:
      path: /var/lib/grafana/dashboards
```

- [ ] **Step 4: Create the (empty for now) dashboards directory**

Run: `mkdir -p docker/grafana/dashboards && touch docker/grafana/dashboards/.gitkeep`

(Task 5 populates this directory with the 3 dashboard JSON files. The `.gitkeep` ensures the directory exists in git before Task 5 runs; delete it in Task 5 once real files are added, since an empty-directory marker alongside real dashboard files is unnecessary.)

- [ ] **Step 5: Validate the compose file parses**

Run: `docker compose -f docker/docker-compose.yml config --profile influx`
Expected: valid YAML output showing the `grafana` service with the volumes/environment above, no parse errors. (This does not require Docker to actually be running anything — `config` just validates and renders the merged config.)

- [ ] **Step 6: Commit**

```bash
git add docker/docker-compose.yml docker/grafana/
git commit -m "feat: add Grafana service + provisioning to the influx compose profile"
```

---

### Task 5: The 3 dashboard JSON files

**Files:**
- Create: `docker/grafana/dashboards/line_overview.json`
- Create: `docker/grafana/dashboards/station_kpis.json`
- Create: `docker/grafana/dashboards/root_cause.json`
- Delete: `docker/grafana/dashboards/.gitkeep` (from Task 4, now unnecessary)

**Interfaces:**
- Consumes: datasource UID `influxdb-simengine` (Task 4), measurements/fields from Task 2 (`station_metrics`, `line_metrics`) and the pre-existing `sim_events` measurement (`src/simengine_historian_influx/__init__.py`'s `_event_to_point`: tags `event_type, source, source_type, severity, scenario, run_id, shift_name`; fields `sim_time, message, old_state, new_state, partcount, good_parts, defective_parts, buffer_level, oee, utilisation, shift_number, extra_json`).

All three dashboards share two Flux template variables: `$scenario` (single-value) and `$station` (per-dashboard multi/single as noted below), both queried live from InfluxDB tag values so the dashboards work unmodified across every scenario.

- [ ] **Step 1: Remove the placeholder file**

Run: `rm docker/grafana/dashboards/.gitkeep`

- [ ] **Step 2: Create `line_overview.json`**

```json
{
  "title": "simengine — Line Overview",
  "uid": "simengine-line-overview",
  "schemaVersion": 39,
  "version": 1,
  "editable": true,
  "timezone": "browser",
  "time": {"from": "now-1h", "to": "now"},
  "refresh": "10s",
  "templating": {
    "list": [
      {
        "name": "scenario",
        "type": "query",
        "datasource": {"type": "influxdb", "uid": "influxdb-simengine"},
        "query": "import \"influxdata/influxdb/schema\"\nschema.tagValues(bucket: \"manufacturing\", tag: \"scenario\", predicate: (r) => r._measurement == \"line_metrics\")",
        "refresh": 2,
        "sort": 1,
        "includeAll": false,
        "multi": false,
        "current": {}
      },
      {
        "name": "station",
        "type": "query",
        "datasource": {"type": "influxdb", "uid": "influxdb-simengine"},
        "query": "import \"influxdata/influxdb/schema\"\nschema.tagValues(bucket: \"manufacturing\", tag: \"station\", predicate: (r) => r._measurement == \"station_metrics\" and r.scenario == \"${scenario}\")",
        "refresh": 2,
        "sort": 1,
        "includeAll": true,
        "multi": true,
        "current": {}
      }
    ]
  },
  "panels": [
    {
      "id": 1,
      "title": "Station States",
      "type": "state-timeline",
      "gridPos": {"h": 8, "w": 24, "x": 0, "y": 0},
      "datasource": {"type": "influxdb", "uid": "influxdb-simengine"},
      "targets": [
        {
          "refId": "A",
          "datasource": {"type": "influxdb", "uid": "influxdb-simengine"},
          "query": "from(bucket: \"manufacturing\")\n  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)\n  |> filter(fn: (r) => r._measurement == \"station_metrics\" and r.scenario == \"${scenario}\" and r._field == \"state\")\n  |> filter(fn: (r) => r.station =~ /${station:regex}/)"
        }
      ]
    },
    {
      "id": 2,
      "title": "Line OEE",
      "type": "timeseries",
      "gridPos": {"h": 8, "w": 8, "x": 0, "y": 8},
      "datasource": {"type": "influxdb", "uid": "influxdb-simengine"},
      "fieldConfig": {"defaults": {"unit": "percentunit", "max": 1, "min": 0}, "overrides": []},
      "targets": [
        {
          "refId": "A",
          "datasource": {"type": "influxdb", "uid": "influxdb-simengine"},
          "query": "from(bucket: \"manufacturing\")\n  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)\n  |> filter(fn: (r) => r._measurement == \"line_metrics\" and r.scenario == \"${scenario}\" and r._field == \"oee\")"
        }
      ]
    },
    {
      "id": 3,
      "title": "Throughput",
      "type": "timeseries",
      "gridPos": {"h": 8, "w": 8, "x": 8, "y": 8},
      "datasource": {"type": "influxdb", "uid": "influxdb-simengine"},
      "targets": [
        {
          "refId": "A",
          "datasource": {"type": "influxdb", "uid": "influxdb-simengine"},
          "query": "from(bucket: \"manufacturing\")\n  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)\n  |> filter(fn: (r) => r._measurement == \"line_metrics\" and r.scenario == \"${scenario}\" and r._field == \"throughput\")"
        }
      ]
    },
    {
      "id": 4,
      "title": "WIP / Good / Scrap",
      "type": "timeseries",
      "gridPos": {"h": 8, "w": 8, "x": 16, "y": 8},
      "datasource": {"type": "influxdb", "uid": "influxdb-simengine"},
      "targets": [
        {
          "refId": "A",
          "datasource": {"type": "influxdb", "uid": "influxdb-simengine"},
          "query": "from(bucket: \"manufacturing\")\n  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)\n  |> filter(fn: (r) => r._measurement == \"line_metrics\" and r.scenario == \"${scenario}\")\n  |> filter(fn: (r) => r._field == \"total_wip\" or r._field == \"total_good\" or r._field == \"total_scrap\")"
        }
      ]
    }
  ]
}
```

- [ ] **Step 3: Create `station_kpis.json`**

```json
{
  "title": "simengine — Station KPIs & PVs",
  "uid": "simengine-station-kpis",
  "schemaVersion": 39,
  "version": 1,
  "editable": true,
  "timezone": "browser",
  "time": {"from": "now-1h", "to": "now"},
  "refresh": "10s",
  "templating": {
    "list": [
      {
        "name": "scenario",
        "type": "query",
        "datasource": {"type": "influxdb", "uid": "influxdb-simengine"},
        "query": "import \"influxdata/influxdb/schema\"\nschema.tagValues(bucket: \"manufacturing\", tag: \"scenario\", predicate: (r) => r._measurement == \"line_metrics\")",
        "refresh": 2,
        "sort": 1,
        "includeAll": false,
        "multi": false,
        "current": {}
      },
      {
        "name": "station",
        "type": "query",
        "datasource": {"type": "influxdb", "uid": "influxdb-simengine"},
        "query": "import \"influxdata/influxdb/schema\"\nschema.tagValues(bucket: \"manufacturing\", tag: \"station\", predicate: (r) => r._measurement == \"station_metrics\" and r.scenario == \"${scenario}\")",
        "refresh": 2,
        "sort": 1,
        "includeAll": false,
        "multi": false,
        "current": {}
      }
    ]
  },
  "panels": [
    {
      "id": 1,
      "title": "OEE / Availability / Performance / Quality — $station",
      "type": "timeseries",
      "gridPos": {"h": 10, "w": 24, "x": 0, "y": 0},
      "datasource": {"type": "influxdb", "uid": "influxdb-simengine"},
      "fieldConfig": {"defaults": {"unit": "percentunit", "max": 1, "min": 0}, "overrides": []},
      "targets": [
        {
          "refId": "A",
          "datasource": {"type": "influxdb", "uid": "influxdb-simengine"},
          "query": "from(bucket: \"manufacturing\")\n  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)\n  |> filter(fn: (r) => r._measurement == \"station_metrics\" and r.scenario == \"${scenario}\" and r.station == \"${station}\")\n  |> filter(fn: (r) => r._field == \"oee\" or r._field == \"availability\" or r._field == \"performance\" or r._field == \"quality\")"
        }
      ]
    },
    {
      "id": 2,
      "title": "Process Values — $station",
      "type": "timeseries",
      "gridPos": {"h": 10, "w": 24, "x": 0, "y": 10},
      "datasource": {"type": "influxdb", "uid": "influxdb-simengine"},
      "targets": [
        {
          "refId": "A",
          "datasource": {"type": "influxdb", "uid": "influxdb-simengine"},
          "query": "from(bucket: \"manufacturing\")\n  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)\n  |> filter(fn: (r) => r._measurement == \"station_metrics\" and r.scenario == \"${scenario}\" and r.station == \"${station}\")\n  |> filter(fn: (r) => r._field =~ /^pv_/)"
        }
      ]
    }
  ]
}
```

- [ ] **Step 4: Create `root_cause.json`**

```json
{
  "title": "simengine — Root Cause / Downtime",
  "uid": "simengine-root-cause",
  "schemaVersion": 39,
  "version": 1,
  "editable": true,
  "timezone": "browser",
  "time": {"from": "now-1h", "to": "now"},
  "refresh": "10s",
  "templating": {
    "list": [
      {
        "name": "scenario",
        "type": "query",
        "datasource": {"type": "influxdb", "uid": "influxdb-simengine"},
        "query": "import \"influxdata/influxdb/schema\"\nschema.tagValues(bucket: \"manufacturing\", tag: \"scenario\", predicate: (r) => r._measurement == \"line_metrics\")",
        "refresh": 2,
        "sort": 1,
        "includeAll": false,
        "multi": false,
        "current": {}
      },
      {
        "name": "station",
        "type": "query",
        "datasource": {"type": "influxdb", "uid": "influxdb-simengine"},
        "query": "import \"influxdata/influxdb/schema\"\nschema.tagValues(bucket: \"manufacturing\", tag: \"station\", predicate: (r) => r._measurement == \"station_metrics\" and r.scenario == \"${scenario}\")",
        "refresh": 2,
        "sort": 1,
        "includeAll": true,
        "multi": true,
        "current": {}
      }
    ]
  },
  "panels": [
    {
      "id": 1,
      "title": "Alarm Events",
      "type": "table",
      "gridPos": {"h": 10, "w": 24, "x": 0, "y": 0},
      "datasource": {"type": "influxdb", "uid": "influxdb-simengine"},
      "targets": [
        {
          "refId": "A",
          "datasource": {"type": "influxdb", "uid": "influxdb-simengine"},
          "query": "from(bucket: \"manufacturing\")\n  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)\n  |> filter(fn: (r) => r._measurement == \"sim_events\" and r.event_type == \"ALARM\" and r.scenario == \"${scenario}\")\n  |> filter(fn: (r) => r.source =~ /${station:regex}/)\n  |> filter(fn: (r) => r._field == \"message\" or r._field == \"old_state\" or r._field == \"new_state\")\n  |> pivot(rowKey: [\"_time\"], columnKey: [\"_field\"], valueColumn: \"_value\")\n  |> keep(columns: [\"_time\", \"source\", \"severity\", \"message\", \"old_state\", \"new_state\"])\n  |> sort(columns: [\"_time\"], desc: true)"
        }
      ]
    },
    {
      "id": 2,
      "title": "Stoppage Reason Pareto",
      "type": "barchart",
      "gridPos": {"h": 10, "w": 12, "x": 0, "y": 10},
      "datasource": {"type": "influxdb", "uid": "influxdb-simengine"},
      "targets": [
        {
          "refId": "A",
          "datasource": {"type": "influxdb", "uid": "influxdb-simengine"},
          "query": "from(bucket: \"manufacturing\")\n  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)\n  |> filter(fn: (r) => r._measurement == \"sim_events\" and r.event_type == \"ALARM\" and r._field == \"message\" and r.scenario == \"${scenario}\")\n  |> filter(fn: (r) => r.source =~ /${station:regex}/)\n  |> map(fn: (r) => ({r with reason: r._value}))\n  |> group(columns: [\"reason\"])\n  |> count(column: \"_value\")\n  |> group()\n  |> sort(columns: [\"_value\"], desc: true)"
        }
      ]
    },
    {
      "id": 3,
      "title": "Time in State (latest, per station)",
      "type": "barchart",
      "gridPos": {"h": 10, "w": 12, "x": 12, "y": 10},
      "datasource": {"type": "influxdb", "uid": "influxdb-simengine"},
      "targets": [
        {
          "refId": "A",
          "datasource": {"type": "influxdb", "uid": "influxdb-simengine"},
          "query": "from(bucket: \"manufacturing\")\n  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)\n  |> filter(fn: (r) => r._measurement == \"station_metrics\" and r.scenario == \"${scenario}\")\n  |> filter(fn: (r) => r.station =~ /${station:regex}/)\n  |> filter(fn: (r) => r._field =~ /^time_in_state_/)\n  |> last()\n  |> keep(columns: [\"station\", \"_field\", \"_value\"])"
        }
      ]
    }
  ]
}
```

- [ ] **Step 5: Validate all 3 files are syntactically valid JSON**

Run: `python3 -c "import json; [json.load(open(f)) for f in ['docker/grafana/dashboards/line_overview.json', 'docker/grafana/dashboards/station_kpis.json', 'docker/grafana/dashboards/root_cause.json']]; print('all valid JSON')"`
Expected: `all valid JSON`

- [ ] **Step 6: Commit**

```bash
git add docker/grafana/dashboards/
git commit -m "feat: add Line Overview, Station KPIs, and Root Cause Grafana dashboards"
```

---

### Task 6: End-to-end manual validation

**Files:** none (validation only — fixes to earlier tasks' files if this surfaces a real bug, per finding below)

**Interfaces:** none new — this task exercises everything Tasks 1-5 built together, against a real Docker stack.

This task has no unit tests — it's the spec's "Testing" section's end-to-end validation pass, and it's the step that actually proves the Flux queries in Task 5 are correct (they were hand-written against documented Flux syntax but never executed against a live InfluxDB/Grafana — this task is where that gets checked for real).

- [ ] **Step 1: Bring up the stack**

Pre-existing gotcha to know about before starting: `docker/docker-compose.yml`'s `influxdb` service inits with `INFLUXDB_INIT_ADMIN_TOKEN: ${INFLUXDB_TOKEN:-simengine-dev-token}` (defaults to `simengine-dev-token` if unset), but the `simengine` service passes `INFLUXDB_TOKEN: ${INFLUXDB_TOKEN:-}` (defaults to **empty string** if unset) — so if `INFLUXDB_TOKEN` isn't exported in your shell, `simengine` and `influxdb` end up with mismatched tokens and every historian write will 401. Export it explicitly first so both services agree:

```bash
export INFLUXDB_TOKEN=simengine-dev-token
```

Run: `docker compose -f docker/docker-compose.yml --profile influx up --build -d`

Wait for `influxdb` to report healthy and `grafana` to start (check with `docker compose -f docker/docker-compose.yml ps`).

- [ ] **Step 2: Configure a scenario with the influx historian and start a run**

Edit (or use the REST API to PATCH) `config/scenarios.yaml`'s `demo_line` entry to add `historians: ["influx"]` — or, simpler, start a run via the REST API and pass historian config however `build_historians` expects it (check `src/simengine/plugins.py`'s `build_historians` signature — it reads `config["historians"]`, a list of names already present as an empty list on `demo_line`, so setting it to `["influx"]` for this test run is the one edit needed). Then start a run:

```bash
curl -X POST http://localhost:8080/api/v1/run/start -H "Content-Type: application/json" \
  -d '{"scenario": "demo_line", "seed": 42, "speed_ratio": 20}'
```

Let it run for at least 60 real seconds (≈ 20 minutes of sim time at `speed_ratio: 20`, comfortably past several `INFLUXDB_SAMPLE_INTERVAL` cycles and multiple station state changes).

- [ ] **Step 3: Confirm data landed in InfluxDB**

Use the InfluxDB UI (`http://localhost:8086`, login `admin` / `simengine-dev` unless overridden) or the CLI:

```bash
docker compose -f docker/docker-compose.yml exec influxdb influx query \
  'from(bucket:"manufacturing") |> range(start: -10m) |> filter(fn: (r) => r._measurement == "station_metrics") |> limit(n:5)' \
  --org simengine --token simengine-dev-token
```

Expected: rows returned with `station`, `scenario`, `run_id` tags and the fields listed in this plan's Global Constraints. Repeat for `line_metrics` and confirm `sim_events` (from the pre-existing event historian path) also has rows with `event_type = "ALARM"` or `"STATE_CHANGE"`.

If no rows appear: check `docker compose -f docker/docker-compose.yml logs simengine` for historian errors, verify `INFLUXDB_TOKEN`/`INFLUXDB_URL` env vars reached the `simengine` container (`docker/docker-compose.yml`'s `simengine` service already declares these — confirm they're not empty), and re-check Task 2's `record_metrics` implementation against the actual error.

- [ ] **Step 4: Confirm all 3 dashboards render**

Open `http://localhost:3000` (no login required — anonymous Viewer). For each of the 3 dashboards (Line Overview, Station KPIs & PVs, Root Cause / Downtime):

1. Confirm the `$scenario` variable dropdown populates with `demo_line`.
2. Confirm the `$station` variable dropdown populates with the demo_line station names (`Press01`, `Weld02`, `Pack03`).
3. Confirm every panel renders without a query error banner and shows non-empty data (a flat/empty panel with no error is acceptable only if the underlying data genuinely has no matching rows yet — e.g. no alarms fired during the test window; a red "query error" banner is not acceptable and must be fixed).

If any panel shows a query error: read the exact Grafana error message (usually a Flux compile/type error), fix the corresponding `query` string in the dashboard JSON from Task 5, redeploy (`docker compose -f docker/docker-compose.yml restart grafana` picks up the file-provisioned dashboard on its `updateIntervalSeconds: 30` poll, or restart the container for an immediate pickup), and re-verify. Common likely fixes if needed: Flux `regex` variable format requires the variable to be multi-value for `:regex` to produce a valid `(a|b|c)` pattern — if `$station` is empty (no selection) some Flux versions render `${station:regex}` as `(?:)` which matches everything (acceptable) or as an empty invalid regex (needs a guard) — if this happens, change the affected panel's variable reference from `${station:regex}` to `${station:pipe}` with a corresponding `=~ /^(${station:pipe})$/` pattern, or set `includeAll: true` with a non-empty `current` default in the dashboard JSON so a selection always exists.

- [ ] **Step 5: Tear down**

Run: `docker compose -f docker/docker-compose.yml --profile influx down`

- [ ] **Step 6: Commit any fixes made during validation**

If Step 4 required fixes to any dashboard JSON or the historian code:

```bash
git add docker/grafana/dashboards/ src/simengine_historian_influx/
git commit -m "fix: correct Flux queries / historian output found during e2e Grafana validation"
```

If no fixes were needed, skip this step (nothing to commit).
