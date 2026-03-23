"""Tests for Neo4j Graph Database Historian (rewritten for batch + causal engine)."""

import os
import sys
import pytest
from collections import deque
from unittest.mock import MagicMock, patch, call

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from event_historian import SimEvent
from neo4j_historian import Neo4jHistorian, create_neo4j_historian_from_config
from factories import make_event


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_historian(scenario="test_scenario", run_id="run_001"):
    """Create historian with mocked neo4j driver, bypassing __init__."""
    mock_driver = MagicMock()
    mock_session = MagicMock()
    mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)
    # session.run returns a result; for elementId queries return a list
    mock_session.run.return_value = iter([])

    h = object.__new__(Neo4jHistorian)
    h._driver = mock_driver
    h._scenario = scenario
    h._run_id = run_id
    h._buffer = []
    h._run_created = True
    h._current_shift_number = 0
    h._last_event_eid = {}
    h._recent_events = {}
    h._upstream = {"M2": "M1", "M3": "M2"}
    h._downstream = {"M1": "M2", "M2": "M3"}
    return h, mock_driver, mock_session


# ---------------------------------------------------------------------------
# describe()
# ---------------------------------------------------------------------------

class TestDescribe:
    def test_describe_format(self):
        h, _, _ = _make_historian()
        assert "Neo4jHistorian" in h.describe()
        assert "batch=50" in h.describe()


# ---------------------------------------------------------------------------
# record_events — buffering
# ---------------------------------------------------------------------------

class TestRecordEventsBuffering:
    def test_events_accumulate_in_buffer_below_batch_size(self):
        h, _, mock_session = _make_historian()
        events = [make_event(source="M1") for _ in range(10)]
        h.record_events(events)
        assert len(h._buffer) == 10
        mock_session.run.assert_not_called()  # no flush yet

    def test_flush_triggered_at_batch_size(self):
        h, _, mock_session = _make_historian()
        h._buffer = [make_event(source="M1") for _ in range(49)]
        h.record_events([make_event(source="M1")])  # 50th event
        assert len(h._buffer) == 0  # flushed

    def test_flush_triggered_when_buffer_exceeds_batch_size(self):
        h, _, mock_session = _make_historian()
        events = [make_event(source="M1") for _ in range(55)]
        h.record_events(events)
        assert len(h._buffer) == 0  # flushed (55 >= 50)

    def test_record_events_empty_list(self):
        h, _, mock_session = _make_historian()
        h.record_events([])
        assert len(h._buffer) == 0
        mock_session.run.assert_not_called()


# ---------------------------------------------------------------------------
# flush()
# ---------------------------------------------------------------------------

class TestFlush:
    def test_flush_writes_buffer_to_neo4j(self):
        h, mock_driver, mock_session = _make_historian()
        h._buffer = [make_event(source="M1", event_type="STATE_CHANGE")]
        h.flush()
        assert len(h._buffer) == 0
        assert mock_driver.session.called

    def test_flush_empty_buffer_is_noop(self):
        h, mock_driver, _ = _make_historian()
        h.flush()
        mock_driver.session.assert_not_called()


# ---------------------------------------------------------------------------
# close()
# ---------------------------------------------------------------------------

class TestClose:
    def test_close_flushes_remaining_events(self):
        h, mock_driver, mock_session = _make_historian()
        h._buffer = [make_event(source="M1")]
        h.close()
        assert len(h._buffer) == 0

    def test_close_sets_run_end_time(self):
        h, mock_driver, mock_session = _make_historian()
        h.close()
        # session.run should have been called to set end_time on Run node
        assert mock_session.run.called
        calls = [str(c) for c in mock_session.run.call_args_list]
        assert any("end_time" in c for c in calls)

    def test_close_calls_driver_close(self):
        h, mock_driver, _ = _make_historian()
        h.close()
        mock_driver.close.assert_called_once()

    def test_close_tolerates_neo4j_error(self):
        h, mock_driver, mock_session = _make_historian()
        mock_session.run.side_effect = Exception("connection lost")
        h.close()  # must not raise
        mock_driver.close.assert_called_once()


# ---------------------------------------------------------------------------
# Causal inference engine
# ---------------------------------------------------------------------------

class TestCausalEngine:
    def _add_event_to_recent(self, h, source, new_state, event_type="STATE_CHANGE", sim_time=100.0, old_state="PROCESSING"):
        """Store (event, eid) tuple — matches new _recent_events structure."""
        e = make_event(source=source, event_type=event_type,
                       new_state=new_state, old_state=old_state, timestamp=sim_time)
        eid = f"eid_{source}_{sim_time}"  # deterministic test eid
        if source not in h._recent_events:
            h._recent_events[source] = deque(maxlen=100)
        h._recent_events[source].append((e, eid))
        return e, eid

    def test_starvation_cascade_within_window(self):
        """M1 FAILED → M2 STARVED within 5s → CAUSED edge created."""
        h, mock_driver, mock_session = _make_historian()
        self._add_event_to_recent(h, "M1", "FAILED", sim_time=100.0)
        target = make_event(source="M2", event_type="STATE_CHANGE",
                            new_state="STARVED", old_state="PROCESSING", timestamp=103.0)

        h._check_causal_rules(mock_session, target, "eid_M2_103.0")

        calls = [str(c) for c in mock_session.run.call_args_list]
        assert any("CAUSED" in c and "starvation_cascade" in c for c in calls)

    def test_starvation_cascade_outside_window_no_edge(self):
        """M1 FAILED 6s before M2 STARVED → no edge (window=5s)."""
        h, mock_driver, mock_session = _make_historian()
        self._add_event_to_recent(h, "M1", "FAILED", sim_time=100.0)
        target = make_event(source="M2", event_type="STATE_CHANGE",
                            new_state="STARVED", old_state="PROCESSING", timestamp=106.0)

        h._check_causal_rules(mock_session, target, "eid_M2_106.0")

        calls = [str(c) for c in mock_session.run.call_args_list]
        assert not any("starvation_cascade" in c for c in calls)

    def test_starvation_cascade_zero_lag_no_edge(self):
        """Same sim_time as trigger → lag_s=0 → no edge (must be strictly positive)."""
        h, mock_driver, mock_session = _make_historian()
        self._add_event_to_recent(h, "M1", "FAILED", sim_time=100.0)
        target = make_event(source="M2", event_type="STATE_CHANGE",
                            new_state="STARVED", old_state="PROCESSING", timestamp=100.0)

        h._check_causal_rules(mock_session, target, "eid_M2_100.0")

        calls = [str(c) for c in mock_session.run.call_args_list]
        assert not any("starvation_cascade" in c for c in calls)

    def test_starvation_cascade_under_repair_trigger(self):
        """UNDER_REPAIR (not just FAILED) also triggers starvation_cascade."""
        h, mock_driver, mock_session = _make_historian()
        self._add_event_to_recent(h, "M1", "UNDER_REPAIR", sim_time=100.0)
        target = make_event(source="M2", event_type="STATE_CHANGE",
                            new_state="STARVED", old_state="PROCESSING", timestamp=102.0)

        h._check_causal_rules(mock_session, target, "eid_M2_102.0")

        calls = [str(c) for c in mock_session.run.call_args_list]
        assert any("starvation_cascade" in c for c in calls)

    def test_blocking_cascade_within_window(self):
        """M2 BLOCKED → M1 BLOCKED within 5s → blocking_cascade edge."""
        h, mock_driver, mock_session = _make_historian()
        self._add_event_to_recent(h, "M2", "BLOCKED", sim_time=100.0)
        target = make_event(source="M1", event_type="STATE_CHANGE",
                            new_state="BLOCKED", old_state="PROCESSING", timestamp=103.0)

        h._check_causal_rules(mock_session, target, "eid_M1_103.0")

        calls = [str(c) for c in mock_session.run.call_args_list]
        assert any("blocking_cascade" in c for c in calls)

    def test_spc_quality_impact_within_window(self):
        """SPC_VIOLATION on M1 → SCRAP on M1 within 30s → spc_quality_impact edge."""
        h, mock_driver, mock_session = _make_historian()
        self._add_event_to_recent(h, "M1", "SPC_VIOLATION", event_type="SPC_VIOLATION", sim_time=100.0)
        target = make_event(source="M1", event_type="SCRAP",
                            new_state="", old_state="PROCESSING", timestamp=120.0)

        h._check_causal_rules(mock_session, target, "eid_M1_120.0")

        calls = [str(c) for c in mock_session.run.call_args_list]
        assert any("spc_quality_impact" in c for c in calls)

    def test_repair_recovery_within_window(self):
        """M1 exits UNDER_REPAIR → M2 exits STARVED within 10s → repair_recovery edge."""
        h, mock_driver, mock_session = _make_historian()
        self._add_event_to_recent(h, "M1", "PROCESSING",
                                  event_type="STATE_CHANGE", old_state="UNDER_REPAIR", sim_time=100.0)
        target = make_event(source="M2", event_type="STATE_CHANGE",
                            new_state="PROCESSING", old_state="STARVED", timestamp=107.0)

        h._check_causal_rules(mock_session, target, "eid_M2_107.0")

        calls = [str(c) for c in mock_session.run.call_args_list]
        assert any("repair_recovery" in c for c in calls)

    def test_most_recent_trigger_wins(self):
        """When multiple triggers qualify, only the most recent creates the CAUSED edge."""
        h, mock_driver, mock_session = _make_historian()
        # Two FAILED events from M1 — both within window of M2's STARVED
        self._add_event_to_recent(h, "M1", "FAILED", sim_time=97.0)   # older  → eid_M1_97.0
        self._add_event_to_recent(h, "M1", "FAILED", sim_time=99.0)   # most recent → eid_M1_99.0
        target = make_event(source="M2", event_type="STATE_CHANGE",
                            new_state="STARVED", old_state="PROCESSING", timestamp=102.0)

        h._check_causal_rules(mock_session, target, "eid_M2_102.0")

        calls = mock_session.run.call_args_list
        caused_calls = [c for c in calls if "CAUSED" in str(c)]
        assert len(caused_calls) == 1  # only one edge
        # The trigger eid used should be for the most recent trigger (99.0), not 97.0
        assert "eid_M1_99.0" in str(caused_calls[0])

    def test_no_causal_rule_fires_for_processing_target_without_starved_old_state(self):
        """PROCESSING target with old_state=PROCESSING → starvation/blocking rules skip."""
        h, mock_driver, mock_session = _make_historian()
        self._add_event_to_recent(h, "M1", "FAILED", sim_time=100.0)
        target = make_event(source="M2", event_type="STATE_CHANGE",
                            new_state="PROCESSING", old_state="PROCESSING", timestamp=102.0)

        h._check_causal_rules(mock_session, target, "eid_M2_102.0")

        calls = [str(c) for c in mock_session.run.call_args_list]
        assert not any("starvation_cascade" in c for c in calls)
        assert not any("blocking_cascade" in c for c in calls)

    def test_no_upstream_machine_skips_causal_check(self):
        """M1 has no upstream — starvation_cascade check skips gracefully."""
        h, mock_driver, mock_session = _make_historian()
        # M1 has no upstream in h._upstream
        target = make_event(source="M1", event_type="STATE_CHANGE",
                            new_state="STARVED", old_state="PROCESSING", timestamp=102.0)
        h._check_causal_rules(mock_session, target, "eid_M1_102.0")  # must not raise


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestErrorHandling:
    def test_mid_run_write_failure_is_silenced(self):
        """A Neo4j write failure during flush logs WARNING and discards batch — buffer is cleared first (intentional)."""
        h, mock_driver, mock_session = _make_historian()
        mock_driver.session.return_value.__enter__.side_effect = Exception("Neo4j down")
        h._buffer = [make_event(source="M1") for _ in range(50)]
        h._flush_batch()  # must not raise
        assert len(h._buffer) == 0  # buffer cleared before the try block (discard semantics)

    def test_causal_engine_failure_does_not_block_event_write(self):
        """Causal engine exception is caught; event write still completes."""
        h, mock_driver, mock_session = _make_historian()
        # Patch _check_causal_rules to raise
        h._check_causal_rules = MagicMock(side_effect=Exception("causal fail"))
        h._buffer = [make_event(source="M1", event_type="STATE_CHANGE", new_state="FAILED")]
        h._flush_batch()  # must not raise
        assert len(h._buffer) == 0


# ---------------------------------------------------------------------------
# create_neo4j_historian_from_config
# ---------------------------------------------------------------------------

class TestFactoryFunction:
    def test_no_historian_key_returns_none(self):
        assert create_neo4j_historian_from_config({}, "test", "run_001") is None

    def test_historian_without_neo4j_key_returns_none(self):
        config = {"historian": {"csv": {"output_dir": "results/historian"}}}
        assert create_neo4j_historian_from_config(config, "test", "run_001") is None

    def test_neo4j_key_present_creates_historian(self):
        """Presence of the neo4j key (not an enabled flag) triggers creation."""
        os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
        os.environ.setdefault("NEO4J_USER", "neo4j")
        os.environ.setdefault("NEO4J_PASSWORD", "test")
        config = {
            "historian": {
                "neo4j": {
                    "uri": "${NEO4J_URI}",
                    "user": "${NEO4J_USER}",
                    "password": "${NEO4J_PASSWORD}",
                }
            }
        }
        with patch("neo4j_historian.GraphDatabase") as mock_gdb:
            mock_driver = MagicMock()
            mock_session = MagicMock()
            mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)
            mock_session.run.return_value = iter([])
            mock_gdb.driver.return_value = mock_driver
            result = create_neo4j_historian_from_config(config, "test", "run_001")
            assert result is not None

    def test_connection_failure_raises_connection_error(self):
        """Neo4j unavailable at init → ConnectionError with clear message."""
        os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
        os.environ.setdefault("NEO4J_USER", "neo4j")
        os.environ.setdefault("NEO4J_PASSWORD", "test")
        config = {
            "historian": {
                "neo4j": {
                    "uri": "${NEO4J_URI}",
                    "user": "${NEO4J_USER}",
                    "password": "${NEO4J_PASSWORD}",
                }
            }
        }
        with patch("neo4j_historian.GraphDatabase") as mock_gdb:
            mock_gdb.driver.side_effect = Exception("connection refused")
            with pytest.raises(ConnectionError, match="Neo4j"):
                create_neo4j_historian_from_config(config, "test", "run_001")


# ---------------------------------------------------------------------------
# FOLLOWED_BY relationship
# ---------------------------------------------------------------------------

class TestFollowedBy:
    def test_followed_by_written_for_sequential_events_same_machine(self):
        """Two STATE_CHANGE events from M1 in one batch → FOLLOWED_BY edge written."""
        h, mock_driver, mock_session = _make_historian()
        # First event — sim_time=10.0
        e1 = make_event(source="M1", event_type="STATE_CHANGE",
                        new_state="DEGRADED", old_state="PROCESSING", timestamp=10.0)
        # Second event — sim_time=11.0
        e2 = make_event(source="M1", event_type="STATE_CHANGE",
                        new_state="FAILED", old_state="DEGRADED", timestamp=11.0)
        # Simulate elementId results: UNWIND returns two records
        eid_records = [
            {"eid": "eid_M1_10", "source": "M1", "sim_time": 10.0, "event_type": "STATE_CHANGE"},
            {"eid": "eid_M1_11", "source": "M1", "sim_time": 11.0, "event_type": "STATE_CHANGE"},
        ]
        mock_session.run.return_value = iter(eid_records)

        h._buffer = [e1, e2]
        h._flush_batch()

        calls = [str(c) for c in mock_session.run.call_args_list]
        assert any("FOLLOWED_BY" in c for c in calls)
