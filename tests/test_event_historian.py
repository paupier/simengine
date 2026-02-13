"""Tests for Phase 13: Event Historian module."""

import csv
import json
import os
import sys
import pytest
from unittest.mock import MagicMock, patch

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from event_historian import (
    SimEvent,
    EventHistorian,
    CSVHistorian,
    InfluxDBHistorian,
    CompositeHistorian,
    CSV_COLUMNS,
    create_historian_from_config,
    collect_step_events,
    collect_production_summary,
    _resolve_env_vars,
)


# ========== SimEvent Tests ==========


class TestSimEvent:
    def test_creation_with_required_fields(self):
        event = SimEvent(
            timestamp=100.0,
            wall_clock="2026-02-08T10:00:00",
            event_type="STATE_CHANGE",
            source="M1",
            source_type="machine",
            severity="INFO",
            message="M1: IDLE -> PROCESSING",
        )
        assert event.timestamp == 100.0
        assert event.event_type == "STATE_CHANGE"
        assert event.source == "M1"
        assert event.message == "M1: IDLE -> PROCESSING"

    def test_default_values(self):
        event = SimEvent(
            timestamp=0.0, wall_clock="", event_type="",
            source="", source_type="", severity="", message="",
        )
        assert event.old_state == ""
        assert event.new_state == ""
        assert event.partcount == 0
        assert event.good_parts == 0
        assert event.defective_parts == 0
        assert event.buffer_level == -1
        assert event.oee == 0.0
        assert event.utilisation == 0.0
        assert event.shift_number == 0
        assert event.shift_name == ""
        assert event.extra == {}

    def test_extra_dict(self):
        event = SimEvent(
            timestamp=50.0, wall_clock="", event_type="ALARM",
            source="M1", source_type="machine", severity="CRITICAL",
            message="M1 failed",
            extra={"alarm_type": "MachineFailure", "is_active": True},
        )
        assert event.extra["alarm_type"] == "MachineFailure"
        assert event.extra["is_active"] is True


# ========== CSVHistorian Tests ==========


from factories import make_event as _make_event, make_machine_metrics as _make_machine_metrics


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

    @patch("event_historian.InfluxDBHistorian.__init__", return_value=None)
    def test_describe(self, mock_init):
        hist = InfluxDBHistorian.__new__(InfluxDBHistorian)
        hist._bucket = "manufacturing"
        assert "InfluxDBHistorian" in hist.describe()
        assert "manufacturing" in hist.describe()


# ========== CompositeHistorian Tests ==========


class TestCompositeHistorian:
    def test_delegates_record(self):
        h1 = MagicMock(spec=EventHistorian)
        h2 = MagicMock(spec=EventHistorian)
        composite = CompositeHistorian([h1, h2])

        event = _make_event()
        composite.record_event(event)
        h1.record_event.assert_called_once_with(event)
        h2.record_event.assert_called_once_with(event)

    def test_delegates_record_events(self):
        h1 = MagicMock(spec=EventHistorian)
        h2 = MagicMock(spec=EventHistorian)
        composite = CompositeHistorian([h1, h2])

        events = [_make_event(), _make_event()]
        composite.record_events(events)
        h1.record_events.assert_called_once_with(events)
        h2.record_events.assert_called_once_with(events)

    def test_delegates_flush_and_close(self):
        h1 = MagicMock(spec=EventHistorian)
        h2 = MagicMock(spec=EventHistorian)
        composite = CompositeHistorian([h1, h2])

        composite.flush()
        h1.flush.assert_called_once()
        h2.flush.assert_called_once()

        composite.close()
        h1.close.assert_called_once()
        h2.close.assert_called_once()

    def test_event_count_from_first(self):
        h1 = MagicMock(spec=EventHistorian)
        h1.get_event_count.return_value = 42
        h2 = MagicMock(spec=EventHistorian)
        composite = CompositeHistorian([h1, h2])
        assert composite.get_event_count() == 42

    def test_describe(self):
        h1 = MagicMock(spec=EventHistorian)
        h1.describe.return_value = "CSVHistorian"
        h2 = MagicMock(spec=EventHistorian)
        h2.describe.return_value = "InfluxDBHistorian"
        composite = CompositeHistorian([h1, h2])
        desc = composite.describe()
        assert "Composite" in desc
        assert "CSVHistorian" in desc
        assert "InfluxDBHistorian" in desc


# ========== Factory Tests ==========


class TestCreateHistorianFromConfig:
    def test_no_historian_config_returns_none(self):
        config = {"machines": [], "buffers": []}
        assert create_historian_from_config(config, "test") is None

    def test_disabled_historian_returns_none(self):
        config = {"historian": {"enabled": False}}
        assert create_historian_from_config(config, "test") is None

    def test_csv_only_creates_csv_historian(self, tmp_path):
        config = {
            "historian": {
                "enabled": True,
                "csv": {"enabled": True, "output_dir": str(tmp_path)},
            }
        }
        hist = create_historian_from_config(config, "test")
        assert isinstance(hist, CSVHistorian)
        hist.close()

    def test_no_backends_enabled_returns_none(self):
        config = {
            "historian": {
                "enabled": True,
                "csv": {"enabled": False},
                "influxdb": {"enabled": False},
            }
        }
        assert create_historian_from_config(config, "test") is None


# ========== Environment Variable Resolution ==========


class TestEnvVarResolution:
    def test_no_vars(self):
        assert _resolve_env_vars("plain string") == "plain string"

    def test_resolve_env_var(self, monkeypatch):
        monkeypatch.setenv("MY_TOKEN", "secret123")
        assert _resolve_env_vars("${MY_TOKEN}") == "secret123"

    def test_resolve_embedded_env_var(self, monkeypatch):
        monkeypatch.setenv("DB_HOST", "myhost")
        assert _resolve_env_vars("http://${DB_HOST}:8086") == "http://myhost:8086"

    def test_missing_env_var_raises(self):
        with pytest.raises(ValueError, match="not set"):
            _resolve_env_vars("${NONEXISTENT_VAR_12345}")

    def test_non_string_passthrough(self):
        assert _resolve_env_vars(42) == 42
        assert _resolve_env_vars(None) is None


# ========== Event Collection Tests ==========


class TestCollectStepEvents:
    def test_state_change_detected(self):
        machines = {"M1": MagicMock()}
        metrics = {"M1": _make_machine_metrics(state="PROCESSING")}
        historian_state = {"M1_state": "IDLE"}
        config = {"historian": {"events": {"state_changes": True}}}

        events = collect_step_events(
            sim_time=10.0,
            machines=machines,
            machine_metrics=metrics,
            buffers={},
            machine_alarms_map={},
            buffer_alarms_map={},
            shift_manager=None,
            shift_rotated=False,
            spc_monitors={},
            historian_state=historian_state,
            config=config,
        )

        assert len(events) == 1
        assert events[0].event_type == "STATE_CHANGE"
        assert events[0].old_state == "IDLE"
        assert events[0].new_state == "PROCESSING"
        assert events[0].source == "M1"
        # Verify historian_state updated
        assert historian_state["M1_state"] == "PROCESSING"

    def test_no_event_when_state_unchanged(self):
        machines = {"M1": MagicMock()}
        metrics = {"M1": _make_machine_metrics(state="PROCESSING")}
        historian_state = {"M1_state": "PROCESSING"}
        config = {"historian": {"events": {"state_changes": True}}}

        events = collect_step_events(
            sim_time=10.0,
            machines=machines,
            machine_metrics=metrics,
            buffers={},
            machine_alarms_map={},
            buffer_alarms_map={},
            shift_manager=None,
            shift_rotated=False,
            spc_monitors={},
            historian_state=historian_state,
            config=config,
        )

        assert len(events) == 0

    def test_alarm_event_collected(self):
        machines = {"M1": MagicMock()}
        metrics = {"M1": _make_machine_metrics(state="FAILED")}
        historian_state = {"M1_state": "FAILED"}  # no state change
        config = {"historian": {"events": {"state_changes": True, "alarms": True}}}

        alarms = [("MachineFailure", "CRITICAL", "M1 failed", True, "alarm_failure")]
        events = collect_step_events(
            sim_time=10.0,
            machines=machines,
            machine_metrics=metrics,
            buffers={},
            machine_alarms_map={"M1": alarms},
            buffer_alarms_map={},
            shift_manager=None,
            shift_rotated=False,
            spc_monitors={},
            historian_state=historian_state,
            config=config,
        )

        assert len(events) == 1
        assert events[0].event_type == "ALARM"
        assert events[0].severity == "CRITICAL"
        assert events[0].extra["alarm_type"] == "MachineFailure"

    def test_buffer_level_change_detected(self):
        buffer_mock = MagicMock()
        buffer_mock.level = 5
        buffers = {"B1": buffer_mock}
        historian_state = {"B1_level": 3}
        config = {"historian": {"events": {"state_changes": False, "buffer_level_changes": True}}}

        events = collect_step_events(
            sim_time=10.0,
            machines={},
            machine_metrics={},
            buffers=buffers,
            machine_alarms_map={},
            buffer_alarms_map={},
            shift_manager=None,
            shift_rotated=False,
            spc_monitors={},
            historian_state=historian_state,
            config=config,
        )

        assert len(events) == 1
        assert events[0].source == "B1"
        assert events[0].source_type == "buffer"
        assert events[0].buffer_level == 5
        assert historian_state["B1_level"] == 5

    def test_shift_change_event(self):
        shift_manager = MagicMock()
        shift_manager.current_shift_number = 2
        shift_manager.current_shift_index = 1
        shift_def = MagicMock()
        shift_def.name = "Evening Shift"
        shift_manager.shift_definitions = [MagicMock(), shift_def]
        shift_manager.get_previous_shift_summary.return_value = {
            "shift_name": "Day Shift", "parts_produced": 100, "oee": 0.85,
        }

        config = {"historian": {"events": {"state_changes": False, "shift_changes": True}}}

        events = collect_step_events(
            sim_time=28800.0,
            machines={},
            machine_metrics={},
            buffers={},
            machine_alarms_map={},
            buffer_alarms_map={},
            shift_manager=shift_manager,
            shift_rotated=True,
            spc_monitors={},
            historian_state={},
            config=config,
        )

        assert len(events) == 1
        assert events[0].event_type == "SHIFT_CHANGE"
        assert events[0].shift_number == 2
        assert events[0].shift_name == "Evening Shift"
        assert events[0].extra["prev_shift_parts"] == 100

    def test_disabled_events_not_collected(self):
        machines = {"M1": MagicMock()}
        metrics = {"M1": _make_machine_metrics(state="PROCESSING")}
        historian_state = {"M1_state": "IDLE"}
        config = {"historian": {"events": {"state_changes": False}}}

        events = collect_step_events(
            sim_time=10.0,
            machines=machines,
            machine_metrics=metrics,
            buffers={},
            machine_alarms_map={},
            buffer_alarms_map={},
            shift_manager=None,
            shift_rotated=False,
            spc_monitors={},
            historian_state=historian_state,
            config=config,
        )

        assert len(events) == 0


class TestCollectProductionSummary:
    def test_creates_summary_event(self):
        event = collect_production_summary(
            sim_time=60.0,
            total_parts_produced=55,
            total_wip=7,
            line_oee=0.85,
            shift_manager=None,
        )
        assert event.event_type == "PRODUCTION_SUMMARY"
        assert event.source == "Line1"
        assert event.partcount == 55
        assert event.extra["total_wip"] == 7
        assert event.extra["line_oee"] == 0.85
