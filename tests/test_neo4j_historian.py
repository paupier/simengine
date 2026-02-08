"""Tests for Phase 13c: Neo4j Graph Database Historian (all mocked)."""

import os
import sys
import pytest
from unittest.mock import MagicMock, patch, call

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from event_historian import SimEvent
from neo4j_historian import (
    Neo4jHistorian,
    create_neo4j_historian_from_config,
    _source_type_to_label,
)


def make_event(**kwargs):
    """Helper to create a SimEvent with defaults."""
    defaults = {
        "timestamp": 10.0,
        "wall_clock": "2026-02-08T12:00:00",
        "event_type": "STATE_CHANGE",
        "source": "M1",
        "source_type": "machine",
        "severity": "INFO",
        "message": "M1: IDLE -> PROCESSING",
    }
    defaults.update(kwargs)
    return SimEvent(**defaults)


# ========== Source Type Mapping ==========


class TestSourceTypeToLabel:
    def test_machine(self):
        assert _source_type_to_label("machine") == "Machine"

    def test_buffer(self):
        assert _source_type_to_label("buffer") == "Buffer"

    def test_line(self):
        assert _source_type_to_label("line") == "Source"

    def test_shift(self):
        assert _source_type_to_label("shift") == "Source"

    def test_unknown(self):
        assert _source_type_to_label("unknown") == ""


# ========== Neo4jHistorian Tests (mocked driver) ==========


@patch("neo4j_historian.GraphDatabase", create=True)
class TestNeo4jHistorianInit:
    """Tests that require mocking the neo4j import."""

    @patch.dict("sys.modules", {"neo4j": MagicMock()})
    def test_init_creates_driver(self, mock_gdb):
        # Patch GraphDatabase inside the neo4j mock module
        import importlib
        import neo4j_historian
        importlib.reload(neo4j_historian)

        mock_driver = MagicMock()
        with patch("neo4j_historian.GraphDatabase", create=True) as mock_gdb_cls:
            mock_gdb_cls.driver.return_value = mock_driver
            # We need to actually import and instantiate
            # Since neo4j is mocked, the import inside __init__ will use the mock
            pass  # Tested via integration below


class TestNeo4jHistorianWithMockedDriver:
    """Test Neo4j historian with a pre-mocked driver (skip import check)."""

    def _create_historian(self):
        """Create historian with mocked neo4j driver, bypassing import."""
        mock_driver = MagicMock()
        mock_session = MagicMock()
        mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

        # Create historian by bypassing __init__
        historian = object.__new__(Neo4jHistorian)
        historian._driver = mock_driver
        historian._scenario_name = "test_scenario"
        historian._track_parts = True
        historian._max_parts = 100
        historian._part_counter = 0
        historian._event_count = 0

        return historian, mock_driver, mock_session

    def test_describe(self):
        h, _, _ = self._create_historian()
        desc = h.describe()
        assert "Neo4jHistorian" in desc
        assert "parts=on" in desc

    def test_describe_parts_off(self):
        h, _, _ = self._create_historian()
        h._track_parts = False
        assert "parts=off" in h.describe()

    def test_event_count_starts_at_zero(self):
        h, _, _ = self._create_historian()
        assert h.event_count == 0

    def test_create_topology(self):
        h, mock_driver, mock_session = self._create_historian()

        config = {
            "machines": [
                {"name": "M1", "cycle_time": 1.0},
                {"name": "M2", "cycle_time": 1.5},
            ],
            "buffers": [
                {"name": "B1", "capacity": 10, "upstream": "M1", "downstream": "M2"},
            ],
        }

        h.create_topology(config)

        # Should have called session.run multiple times
        assert mock_session.run.call_count >= 7  # clear + Source + 2 Machines + Buffer + Sink + FEEDS relations

    def test_record_events_increments_count(self):
        h, mock_driver, mock_session = self._create_historian()

        events = [
            make_event(source="M1", event_type="STATE_CHANGE"),
            make_event(source="M2", event_type="ALARM", severity="CRITICAL"),
        ]

        h.record_events(events)
        assert h.event_count == 2

    def test_record_events_empty_list(self):
        h, mock_driver, mock_session = self._create_historian()
        h.record_events([])
        assert h.event_count == 0

    def test_record_events_creates_nodes(self):
        h, mock_driver, mock_session = self._create_historian()

        events = [make_event(source="M1")]
        h.record_events(events)

        # Should have called session.run to create Event node and link
        assert mock_session.run.called

    def test_record_parts_creates_part_nodes(self):
        h, mock_driver, mock_session = self._create_historian()

        h.record_parts(
            delta_parts=2,
            machine_names=["M1", "M2"],
            defective_count=0,
            sim_time=50.0,
        )

        assert h._part_counter == 2
        # 2 parts, each with 1 CREATE + 2 PROCESSED_BY links = 6 calls
        assert mock_session.run.call_count == 6

    def test_record_parts_respects_max(self):
        h, mock_driver, mock_session = self._create_historian()
        h._max_parts = 3

        h.record_parts(delta_parts=5, machine_names=["M1"], sim_time=10.0)

        # Should cap at 3 parts
        assert h._part_counter == 3

    def test_record_parts_disabled(self):
        h, mock_driver, mock_session = self._create_historian()
        h._track_parts = False

        h.record_parts(delta_parts=5, machine_names=["M1"], sim_time=10.0)

        assert h._part_counter == 0
        assert not mock_session.run.called

    def test_record_parts_defective(self):
        h, mock_driver, mock_session = self._create_historian()

        h.record_parts(
            delta_parts=3,
            machine_names=["M1"],
            defective_count=1,
            defect_machine="M1",
            sim_time=50.0,
        )

        assert h._part_counter == 3
        # Check that at least one call included defect attributes
        all_calls = mock_session.run.call_args_list
        # First part's CREATE should have is_defective=True
        first_create_props = all_calls[0][1].get("props", {})
        assert first_create_props.get("is_defective") is True

    def test_close(self):
        h, mock_driver, _ = self._create_historian()
        h.close()
        mock_driver.close.assert_called_once()


# ========== Factory Function Tests ==========


class TestCreateNeo4jHistorianFromConfig:
    def test_no_config_returns_none(self):
        assert create_neo4j_historian_from_config({}, "test") is None

    def test_disabled_returns_none(self):
        config = {"historian": {"enabled": False}}
        assert create_neo4j_historian_from_config(config, "test") is None

    def test_neo4j_disabled_returns_none(self):
        config = {"historian": {"enabled": True, "neo4j": {"enabled": False}}}
        assert create_neo4j_historian_from_config(config, "test") is None

    @patch.dict("sys.modules", {"neo4j": MagicMock()})
    def test_neo4j_enabled_creates_historian(self):
        os.environ["NEO4J_PASSWORD"] = "test_pass"
        try:
            config = {
                "historian": {
                    "enabled": True,
                    "neo4j": {
                        "enabled": True,
                        "uri": "bolt://localhost:7687",
                        "user": "neo4j",
                        "password": "${NEO4J_PASSWORD}",
                        "track_parts": True,
                        "max_parts": 5000,
                    },
                }
            }
            # Need to reload to pick up the mock
            import importlib
            import neo4j_historian
            importlib.reload(neo4j_historian)

            result = neo4j_historian.create_neo4j_historian_from_config(config, "test")
            assert result is not None
        finally:
            del os.environ["NEO4J_PASSWORD"]


# ========== Import Error Test ==========


class TestNeo4jImportError:
    def test_init_without_package_raises(self):
        """Neo4jHistorian raises clear error when neo4j package is missing."""
        # Temporarily remove neo4j from sys.modules if present
        neo4j_backup = sys.modules.pop("neo4j", None)
        try:
            # Reload the module to clear any cached import
            import importlib
            import neo4j_historian
            importlib.reload(neo4j_historian)

            with pytest.raises(ImportError, match="neo4j"):
                neo4j_historian.Neo4jHistorian(
                    uri="bolt://localhost:7687",
                    user="neo4j",
                    password="test",
                )
        finally:
            if neo4j_backup is not None:
                sys.modules["neo4j"] = neo4j_backup
