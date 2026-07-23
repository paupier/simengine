"""Historian plugin tests (build plan P6).

CSV/Influx backend tests carried from the parent test_event_historian.py,
re-pointed at the plugin packages; plus registry and snapshot-collector tests.
"""
import csv
import json
import os
import pytest
from unittest.mock import MagicMock, patch

from simengine.events import CSV_COLUMNS, SimEvent
from simengine.events.collect import SnapshotEventCollector
from simengine.plugins import HISTORIAN_BACKENDS, build_historians, load_configured_plugins
from simengine_historian_csv import CSVHistorian
from simengine_historian_influx import InfluxDBHistorian

from factories import make_event as _make_event


class TestCSVHistorian:
    def test_creates_file(self, tmp_path):
        hist = CSVHistorian(str(tmp_path), "test_scenario")
        assert os.path.exists(hist.get_current_path())
        hist.close()

    def test_writes_header(self, tmp_path):
        hist = CSVHistorian(str(tmp_path), "test_scenario")
        hist.close()
        with open(hist.get_current_path(), "r") as f:
            reader = csv.reader(f)
            header = next(reader)
        assert header == CSV_COLUMNS

    def test_records_single_event(self, tmp_path):
        hist = CSVHistorian(str(tmp_path), "test_scenario", buffer_size=1)
        event = _make_event(timestamp=42.0, message="M1: IDLE -> PROCESSING")
        hist.record_event(event)
        hist.close()

        with open(hist.get_current_path(), "r") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) == 1
        assert rows[0]["timestamp"] == "42.0"
        assert rows[0]["event_type"] == "STATE_CHANGE"
        assert rows[0]["source"] == "M1"
        assert rows[0]["message"] == "M1: IDLE -> PROCESSING"

    def test_records_multiple_events(self, tmp_path):
        hist = CSVHistorian(str(tmp_path), "test_scenario", buffer_size=100)
        for i in range(10):
            hist.record_event(_make_event(timestamp=float(i)))
        hist.close()

        with open(hist.get_current_path(), "r") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) == 10
        assert hist.get_event_count() == 10

    def test_record_events_batch(self, tmp_path):
        hist = CSVHistorian(str(tmp_path), "test_scenario", buffer_size=100)
        events = [_make_event(timestamp=float(i)) for i in range(5)]
        hist.record_events(events)
        hist.close()

        with open(hist.get_current_path(), "r") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) == 5
        assert hist.get_event_count() == 5

    def test_flush_writes_buffered(self, tmp_path):
        hist = CSVHistorian(str(tmp_path), "test_scenario", buffer_size=100)
        hist.record_event(_make_event())
        # Before flush, file only has header
        with open(hist.get_current_path(), "r") as f:
            lines = f.readlines()
        assert len(lines) == 1  # header only

        hist.flush()
        with open(hist.get_current_path(), "r") as f:
            lines = f.readlines()
        assert len(lines) == 2  # header + 1 event
        hist.close()

    def test_auto_flush_on_buffer_full(self, tmp_path):
        hist = CSVHistorian(str(tmp_path), "test_scenario", buffer_size=3)
        hist.record_event(_make_event(timestamp=1.0))
        hist.record_event(_make_event(timestamp=2.0))
        # Not flushed yet (buffer_size=3)
        with open(hist.get_current_path(), "r") as f:
            lines = f.readlines()
        assert len(lines) == 1

        hist.record_event(_make_event(timestamp=3.0))
        # Now flushed (3 >= buffer_size)
        with open(hist.get_current_path(), "r") as f:
            lines = f.readlines()
        assert len(lines) == 4  # header + 3
        hist.close()

    def test_extra_json_serialization(self, tmp_path):
        hist = CSVHistorian(str(tmp_path), "test_scenario", buffer_size=1)
        event = _make_event(extra={"alarm_type": "MachineFailure", "count": 5})
        hist.record_event(event)
        hist.close()

        with open(hist.get_current_path(), "r") as f:
            reader = csv.DictReader(f)
            row = next(reader)
        extra = json.loads(row["extra_json"])
        assert extra["alarm_type"] == "MachineFailure"
        assert extra["count"] == 5

    def test_empty_extra_is_empty_string(self, tmp_path):
        hist = CSVHistorian(str(tmp_path), "test_scenario", buffer_size=1)
        event = _make_event()
        hist.record_event(event)
        hist.close()

        with open(hist.get_current_path(), "r") as f:
            reader = csv.DictReader(f)
            row = next(reader)
        assert row["extra_json"] == ""

    def test_rotation_on_size(self, tmp_path):
        # Use tiny max size to trigger rotation
        hist = CSVHistorian(str(tmp_path), "test_scenario",
                           max_file_size_mb=0.0001, buffer_size=1)
        first_path = hist.get_current_path()

        # Write enough events to exceed 0.0001 MB (~100 bytes)
        for i in range(20):
            hist.record_event(_make_event(
                timestamp=float(i),
                message="A" * 50,
            ))

        hist.close()
        # Should have rotated to a new file
        csv_files = [f for f in os.listdir(tmp_path) if f.endswith(".csv")]
        assert len(csv_files) >= 2

    def test_rotate_for_shift(self, tmp_path):
        hist = CSVHistorian(str(tmp_path), "test_scenario", rotate_on_shift=True)
        first_path = hist.get_current_path()
        hist.record_event(_make_event())
        hist.rotate_for_shift()
        second_path = hist.get_current_path()
        assert first_path != second_path
        hist.close()

    def test_describe(self, tmp_path):
        hist = CSVHistorian(str(tmp_path), "test_scenario")
        assert "CSVHistorian" in hist.describe()
        hist.close()


# ========== InfluxDBHistorian Tests ==========


class TestInfluxDBHistorian:
    def test_init_without_package(self):
        """ImportError raised with clear message when influxdb-client not installed."""
        with patch.dict("sys.modules", {"influxdb_client": None}):
            with pytest.raises(ImportError, match="influxdb-client"):
                InfluxDBHistorian(
                    url="http://localhost:8086",
                    token="test-token",
                    org="test-org",
                    bucket="test-bucket",
                    scenario_name="test",
                )

    @patch("simengine_historian_influx.InfluxDBHistorian.__init__", return_value=None)
    def test_describe(self, mock_init):
        hist = InfluxDBHistorian.__new__(InfluxDBHistorian)
        hist._bucket = "manufacturing"
        assert "InfluxDBHistorian" in hist.describe()
        assert "manufacturing" in hist.describe()


# ========== CompositeHistorian Tests ==========


class TestRunID:
    """Tests for run_id propagation across historian backends."""

    def test_csv_columns_include_run_id(self):
        assert "run_id" in CSV_COLUMNS
        assert CSV_COLUMNS[0] == "run_id"

    def test_csv_historian_writes_run_id(self, tmp_path):
        hist = CSVHistorian(str(tmp_path), "test_scenario",
                            buffer_size=1, run_id="test_20260224_140000")
        event = _make_event(timestamp=10.0)
        hist.record_event(event)
        hist.close()

        with open(hist.get_current_path(), "r") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) == 1
        assert rows[0]["run_id"] == "test_20260224_140000"

    def test_csv_historian_default_empty_run_id(self, tmp_path):
        hist = CSVHistorian(str(tmp_path), "test_scenario", buffer_size=1)
        event = _make_event(timestamp=10.0)
        hist.record_event(event)
        hist.close()

        with open(hist.get_current_path(), "r") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert rows[0]["run_id"] == ""

    def test_influxdb_historian_run_id_tag(self):
        # Bypass __init__ like existing InfluxDB tests
        hist = InfluxDBHistorian.__new__(InfluxDBHistorian)
        hist._run_id = "myrun_20260224_150000"
        hist._bucket = "bkt"
        hist._scenario = "test"

        event = _make_event(timestamp=5.0)
        mock_chain = MagicMock()
        mock_point_cls = MagicMock(return_value=mock_chain)
        mock_chain.tag.return_value = mock_chain
        mock_chain.field.return_value = mock_chain

        mock_influx = MagicMock()
        mock_influx.Point = mock_point_cls
        with patch.dict("sys.modules", {"influxdb_client": mock_influx}):
            hist._event_to_point(event)

        # Verify run_id tag was set
        tag_calls = [c for c in mock_chain.tag.call_args_list
                     if c[0][0] == "run_id"]
        assert len(tag_calls) == 1
        assert tag_calls[0][0][1] == "myrun_20260224_150000"


class TestPluginRegistry:
    def test_unknown_historian_install_hint(self):
        with pytest.raises(RuntimeError, match=r"pip install simengine\[historian-nope\]"):
            load_configured_plugins({"historians": ["nope"]})

    def test_csv_registers_and_builds(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SIMENGINE_HISTORIAN_DIR", str(tmp_path))
        composite = build_historians({"historians": ["csv"]}, "demo", "run_reg")
        assert composite is not None
        composite.record_event(_make_event(timestamp=1.0))
        composite.close()
        files = os.listdir(tmp_path)
        assert any(f.startswith("run_reg") for f in files)

    def test_empty_historians_returns_none(self):
        assert build_historians({"historians": []}, "demo", "r") is None
        assert build_historians({}, "demo", "r") is None


class TestSnapshotEventCollector:
    def make_engine(self):
        from simengine.engine.line import LineEngine
        return LineEngine({
            "stations": [
                {"name": "S1", "cycle_time": 2.0,
                 "health": {"h_max": 2, "p_degrade": 1.0,
                            "mttr": {"distribution": "constant", "value": 3}}},
                {"name": "S2", "cycle_time": 2.0},
            ],
            "buffers": [{"name": "B1", "capacity": 5}],
        }, "collector_test", seed=1, run_id="run_c")

    def test_run_start_emitted_once(self):
        eng = self.make_engine()
        col = SnapshotEventCollector()
        events1 = col.collect(eng.snapshot())
        assert [e.event_type for e in events1] == ["RUN_START"]
        events2 = col.collect(eng.snapshot())
        assert not [e for e in events2 if e.event_type == "RUN_START"]

    def test_state_transitions_edge_detected(self):
        eng = self.make_engine()
        col = SnapshotEventCollector()
        col.collect(eng.snapshot())
        all_events = []
        for _ in range(12):
            eng.step()
            all_events += col.collect(eng.snapshot())
        changes = [e for e in all_events if e.event_type == "STATE_CHANGE"]
        assert changes, "expected state changes (S1 degrades/fails/repairs)"
        # edge-detection: consecutive identical states emit nothing
        for e in changes:
            assert e.old_state != e.new_state

    def test_alarm_raise_and_clear_events(self):
        eng = self.make_engine()
        col = SnapshotEventCollector()
        col.collect(eng.snapshot())
        all_events = []
        for _ in range(12):
            eng.step()
            all_events += col.collect(eng.snapshot())
        alarms = [e for e in all_events if e.event_type == "ALARM"]
        raised = [e for e in alarms if e.new_state == "ACTIVE"]
        cleared = [e for e in alarms if e.new_state == "CLEARED"]
        assert raised and cleared
        assert any(e.extra.get("code", "").startswith("FM_") for e in raised)

    def test_run_end_event(self):
        eng = self.make_engine()
        col = SnapshotEventCollector()
        col.collect(eng.snapshot())
        end = col.run_end_event(eng.snapshot())
        assert end is not None and end.event_type == "RUN_END"

    def test_run_end_before_start_is_none(self):
        col = SnapshotEventCollector()
        assert col.run_end_event(None) is None
