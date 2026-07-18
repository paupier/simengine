"""Gate P1 — snapshot contract: construction, asdict round-trip, JSON-serializable."""
import json
from dataclasses import asdict

from simengine.engine.snapshot import (
    ProcessValueSnapshot,
    ActiveAlarm,
    StationSnapshot,
    BufferSnapshot,
    LineSnapshot,
)


def make_line_snapshot():
    pv = ProcessValueSnapshot(name="OilTemp", unit="degC", value=54.7, alarm_state="OK")
    alarm = ActiveAlarm(
        code="PV_OILTEMP_HIGH", severity="HIGH", source="Press01",
        text="Press01: OilTemp 68.3degC above 68", activated_at=123.0,
    )
    station = StationSnapshot(
        name="Press01", state="PROCESSING", health=1, h_max=5, cycle_phase=0.5,
        parts_made=10, good=9, scrap=1, rework=0, defective=1,
        availability=0.98, performance=0.95, quality=0.9, oee=0.8379,
        time_in_state={"PROCESSING": 100.0, "IDLE": 20.0},
        process_values=[pv], alarms=[alarm],
    )
    buf = BufferSnapshot(name="B1", level=3, capacity=10)
    return LineSnapshot(
        run_id="demo_line_20260718_120000", scenario="demo_line",
        sim_time=120.0, step_count=120, line_state="RUNNING", speed_ratio=1.0,
        throughput=0.083, total_wip=4, total_good=9, total_scrap=1, oee=0.8379,
        stations={"Press01": station}, buffers={"B1": buf},
        shift=None, recipe=None,
    )


def test_nested_construction():
    snap = make_line_snapshot()
    assert snap.stations["Press01"].process_values[0].name == "OilTemp"
    assert snap.stations["Press01"].alarms[0].code == "PV_OILTEMP_HIGH"
    assert snap.buffers["B1"].capacity == 10


def test_asdict_round_trip():
    snap = make_line_snapshot()
    d = asdict(snap)
    assert d["run_id"] == "demo_line_20260718_120000"
    assert d["stations"]["Press01"]["state"] == "PROCESSING"
    assert d["stations"]["Press01"]["process_values"][0]["value"] == 54.7
    assert d["stations"]["Press01"]["alarms"][0]["severity"] == "HIGH"
    assert d["buffers"]["B1"]["level"] == 3
    assert d["shift"] is None and d["recipe"] is None


def test_json_serializable():
    snap = make_line_snapshot()
    text = json.dumps(asdict(snap))
    back = json.loads(text)
    assert back["stations"]["Press01"]["time_in_state"]["PROCESSING"] == 100.0
    assert back["oee"] == 0.8379


def test_defaults():
    s = StationSnapshot(
        name="S", state="IDLE", health=0, h_max=1, cycle_phase=0.0,
        parts_made=0, good=0, scrap=0, rework=0, defective=0,
        availability=1.0, performance=0.0, quality=1.0, oee=0.0,
    )
    assert s.time_in_state == {} and s.process_values == [] and s.alarms == []
