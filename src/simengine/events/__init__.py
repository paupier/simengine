"""
Event contract for historical data logging (core).

Events are only recorded on meaningful changes (state transitions, alarm
raise/clear, run start/end) — not every simulation step. The concrete storage
backends live in optional plugin packages (simengine_historian_csv,
simengine_historian_influx, simengine_historian_neo4j) discovered through
simengine.plugins; this module holds the shared contract they implement:
SimEvent, EventHistorian, CompositeHistorian, and the CSV column order.
"""

import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List


# ========== EVENT SCHEMA ==========


@dataclass
class SimEvent:
    """Single historical event record.

    All storage backends receive the same SimEvent objects.
    """
    timestamp: float          # sim_time when event occurred
    wall_clock: str           # ISO 8601 real-time string
    event_type: str           # STATE_CHANGE, ALARM, SHIFT_CHANGE, MAINTENANCE,
                              # SPC_VIOLATION, PRODUCTION_SUMMARY, SCRAP, REWORK
    source: str               # Equipment name: "M1", "B1", "Line1"
    source_type: str          # "machine", "buffer", "line", "shift"
    severity: str             # INFO, LOW, MEDIUM, HIGH, CRITICAL
    message: str              # Human-readable description

    # State context
    old_state: str = ""
    new_state: str = ""

    # Numeric snapshot at event time
    partcount: int = 0
    good_parts: int = 0
    defective_parts: int = 0
    buffer_level: int = -1    # -1 = N/A
    oee: float = 0.0
    utilisation: float = 0.0

    # Shift context
    shift_number: int = 0
    shift_name: str = ""

    # Extensible metadata (JSON-serializable dict)
    extra: dict = field(default_factory=dict)


# ========== ABSTRACT HISTORIAN ==========


class EventHistorian(ABC):
    """Abstract base class for event storage backends."""

    @abstractmethod
    def record_event(self, event: SimEvent) -> None:
        """Record a single event."""

    def record_events(self, events: List[SimEvent]) -> None:
        """Record multiple events. Default delegates to record_event."""
        for event in events:
            self.record_event(event)

    @abstractmethod
    def flush(self) -> None:
        """Flush any buffered data to storage."""

    @abstractmethod
    def close(self) -> None:
        """Close the historian and release resources."""

    @abstractmethod
    def get_event_count(self) -> int:
        """Return total number of events recorded."""

    def describe(self) -> str:
        """Human-readable description of this historian."""
        return self.__class__.__name__


# ========== CSV CONTRACT ==========


CSV_COLUMNS = [
    "run_id", "timestamp", "wall_clock", "event_type", "source", "source_type",
    "severity", "message", "old_state", "new_state", "partcount",
    "good_parts", "defective_parts", "buffer_level", "oee",
    "utilisation", "shift_number", "shift_name", "extra_json"
]


# ========== COMPOSITE HISTORIAN ==========


class CompositeHistorian(EventHistorian):
    """Delegates to multiple backends simultaneously."""

    def __init__(self, historians: List[EventHistorian]):
        self._historians = historians

    def record_event(self, event: SimEvent) -> None:
        for h in self._historians:
            h.record_event(event)

    def record_events(self, events: List[SimEvent]) -> None:
        for h in self._historians:
            h.record_events(events)

    def flush(self) -> None:
        for h in self._historians:
            h.flush()

    def close(self) -> None:
        for h in self._historians:
            h.close()

    def get_event_count(self) -> int:
        if self._historians:
            return self._historians[0].get_event_count()
        return 0

    def describe(self) -> str:
        names = [h.describe() for h in self._historians]
        return f"CompositeHistorian[{', '.join(names)}]"


# ========== ENVIRONMENT VARIABLE SUBSTITUTION ==========


def _resolve_env_vars(value: str) -> str:
    """Resolve ${VAR} patterns in a string via os.environ."""
    if not isinstance(value, str) or "${" not in value:
        return value
    import re
    def _replace(match):
        var_name = match.group(1)
        env_val = os.environ.get(var_name)
        if env_val is None:
            raise ValueError(
                f"Environment variable '{var_name}' not set. "
                f"Required for historian configuration."
            )
        return env_val
    return re.sub(r'\$\{(\w+)\}', _replace, value)
