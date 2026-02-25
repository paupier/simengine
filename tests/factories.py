"""
Shared test factory functions for the simantha-opcua test suite.

This module provides reusable helpers for creating test objects:
  - make_event() — SimEvent with sensible defaults
  - make_part() — Mock Part with quality routing attributes
  - make_machine_metrics() — Machine metrics dict matching opcua_server structure
  - make_quality_machine() — QualityAwareMachine with mocked internals
"""
from unittest.mock import MagicMock
from event_historian import SimEvent


def make_event(timestamp=1.0, event_type="STATE_CHANGE", source="M1",
               message="test event", **kwargs):
    """Create a SimEvent with sensible defaults for testing."""
    return SimEvent(
        timestamp=timestamp,
        wall_clock=kwargs.pop("wall_clock", "2026-02-08T10:00:00"),
        event_type=event_type,
        source=source,
        source_type=kwargs.pop("source_type", "machine"),
        severity=kwargs.pop("severity", "INFO"),
        message=message,
        **kwargs,
    )


def make_part(is_defective=False, rework_count=0):
    """Create a mock Part with quality routing attributes."""
    part = MagicMock()
    part.is_defective = is_defective
    part.rework_count = rework_count
    part.routing_history = []
    part.scrapped = False
    part.scrapped_at_machine = None
    part.failed_at_machine = None
    part.defect_type = None
    return part


def make_machine_metrics(state="IDLE", partcount=0, **kwargs):
    """Create a machine_metrics dict matching the structure in opcua_server.py."""
    return {
        "partcount": partcount,
        "blocked_time": 0.0,
        "starved_time": 0.0,
        "down_time": 0.0,
        "processing_time": kwargs.get("processing_time", 0.0),
        "idle_time": kwargs.get("idle_time", 0.0),
        "prev_state": state,
        "cycle_time": 1.0,
        "good_parts": kwargs.get("good_parts", partcount),
        "defective_parts": kwargs.get("defective_parts", 0),
        "base_defect_rate": 0.0,
        "health_multiplier": 3.0,
        "prev_health_state": 0,
        "prev_maint_active": False,
        "prev_defect_rate": 0.0,
        "alarm_machine_failed_active": False,
        "alarm_maintenance_active": False,
        "alarm_quality_alert_active": False,
        "oee": kwargs.get("oee", 0.0),
        "oee_cached": kwargs.get("oee_cached", None),
        "oee_last_update_time": kwargs.get("oee_last_update_time", 0.0),
    }


def make_quality_machine(defect_rate=0.05, scrap_sink=None, rework_enabled=False,
                         rework_success_rate=0.8, max_rework=3,
                         enable_health_correlation=False, health_multiplier=3.0):
    """Create a QualityAwareMachine with mocked internals (bypasses __init__)."""
    from quality_machine import QualityAwareMachine, _init_quality_attrs

    m = object.__new__(QualityAwareMachine)
    _init_quality_attrs(
        m, defect_rate, health_multiplier, enable_health_correlation,
        rework_enabled, rework_success_rate, max_rework
    )
    m._scrap_sink = scrap_sink
    m.name = "M1"
    m.target_receiver = MagicMock()  # Original target (a buffer)
    m.target_receiver.reserved_vacancy = 1
    return m
