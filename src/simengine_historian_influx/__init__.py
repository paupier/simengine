"""InfluxDB historian plugin.

Carried from the parent event_historian.py; registered through
simengine.plugins. Requires the historian-influx extra (influxdb-client).
Config via env: INFLUXDB_URL, INFLUXDB_TOKEN, INFLUXDB_ORG, INFLUXDB_BUCKET.

Note: the parent's Telegraf generator and Grafana assets are deliberately not
carried yet — they target the parent address space. Events land in InfluxDB
via this backend directly; dashboards are a later, separate port.
"""
import json
import os
from typing import List

from simengine.events import EventHistorian, SimEvent, _resolve_env_vars


class InfluxDBHistorian(EventHistorian):
    """InfluxDB 2.x storage backend (optional).

    Requires: pip install influxdb-client
    """

    def __init__(self, url: str, token: str, org: str, bucket: str,
                 scenario_name: str, batch_size: int = 100,
                 run_id: str = ""):
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
    )


def register(registry: dict) -> None:
    registry["influx"] = create
