"""
Event contract tests (core): SimEvent, EventHistorian ABC, CompositeHistorian,
env-var resolution. Backend tests live in test_historian_plugins.py.
"""
import pytest
from unittest.mock import MagicMock

from simengine.events import (
    SimEvent,
    EventHistorian,
    CompositeHistorian,
    CSV_COLUMNS,
    _resolve_env_vars,
)

from factories import make_event as _make_event


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
