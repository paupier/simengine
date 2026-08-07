"""InfluxDB historian plugin.

Carried from the parent event_historian.py; registered through
simengine.plugins. Requires the historian-influx extra (influxdb-client).
Config via env: INFLUXDB_URL, INFLUXDB_TOKEN, INFLUXDB_ORG, INFLUXDB_BUCKET,
INFLUXDB_SAMPLE_INTERVAL.

Besides event recording, this plugin also writes periodic `station_metrics`/
`line_metrics` samples (via `record_metrics`, throttled by
INFLUXDB_SAMPLE_INTERVAL) for continuous trending. Pre-provisioned Grafana
dashboards that read this data live under `docker/grafana/`.
"""
import json
import os
from typing import List

from simengine.events import EventHistorian, SimEvent, _resolve_env_vars
from simengine.publishers.metrics import top_reason_code


_STATION_STATES = ("UNDER_REPAIR", "FAILED", "BLOCKED", "STARVED", "DEGRADED",
                    "PROCESSING", "IDLE", "MINOR_STOP")


class InfluxDBHistorian(EventHistorian):
    """InfluxDB 2.x storage backend (optional).

    Requires: pip install influxdb-client
    """

    def __init__(self, url: str, token: str, org: str, bucket: str,
                 scenario_name: str, batch_size: int = 100,
                 run_id: str = "", sample_interval: float = 5.0):
        try:
            from influxdb_client import InfluxDBClient, WriteOptions
        except ImportError:
            raise ImportError(
                "influxdb-client package required for InfluxDB historian. "
                "Install with: pip install influxdb-client"
            )

        self._client = InfluxDBClient(url=url, token=token, org=org,
                                      timeout=30_000)
        self._write_api = self._client.write_api(
            write_options=WriteOptions(batch_size=batch_size, flush_interval=10_000)
        )
        self._bucket = bucket
        self._org = org
        self._scenario = scenario_name
        self._run_id = run_id
        self._event_count = 0
        self._sample_interval = sample_interval
        self._last_recorded_sim_time = None

    def _event_to_point(self, event: SimEvent):
        from influxdb_client import Point

        point = (
            Point("sim_events")
            .tag("event_type", event.event_type)
            .tag("source", event.source)
            .tag("source_type", event.source_type)
            .tag("severity", event.severity)
            .tag("scenario", self._scenario)
            .tag("run_id", self._run_id)
            .tag("shift_name", event.shift_name)
            .field("sim_time", event.timestamp)
            .field("message", event.message)
            .field("old_state", event.old_state)
            .field("new_state", event.new_state)
            .field("partcount", event.partcount)
            .field("good_parts", event.good_parts)
            .field("defective_parts", event.defective_parts)
            .field("buffer_level", event.buffer_level)
            .field("oee", float(event.oee))
            .field("utilisation", float(event.utilisation))
            .field("shift_number", event.shift_number)
            .field("extra_json", json.dumps(event.extra) if event.extra else "")
        )
        return point

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

    def record_event(self, event: SimEvent) -> None:
        point = self._event_to_point(event)
        self._write_api.write(bucket=self._bucket, org=self._org, record=point)
        self._event_count += 1

    def record_events(self, events: List[SimEvent]) -> None:
        points = [self._event_to_point(e) for e in events]
        self._write_api.write(bucket=self._bucket, org=self._org, record=points)
        self._event_count += len(events)

    def flush(self) -> None:
        self._write_api.flush()

    def close(self) -> None:
        self.flush()
        self._write_api.close()
        self._client.close()

    def get_event_count(self) -> int:
        return self._event_count

    def describe(self) -> str:
        return f"InfluxDBHistorian -> {self._bucket}"


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


def register(registry: dict) -> None:
    registry["influx"] = create
