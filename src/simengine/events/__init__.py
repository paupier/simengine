"""
Event-based historical data logging.

Provides event capture and storage backends for the Simantha OPC UA server.
Events are only recorded on meaningful changes (state transitions, alarms,
shift boundaries) - not every simulation step.

Backends:
  - CSVHistorian: Default, zero external dependencies
  - InfluxDBHistorian: Time-series DB for Grafana (optional, lazy import)
  - CompositeHistorian: Delegates to multiple backends simultaneously
"""

import csv
import json
import os
import time as _time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import List, Optional, Dict, Any


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


# ========== CSV BACKEND ==========


CSV_COLUMNS = [
    "run_id", "timestamp", "wall_clock", "event_type", "source", "source_type",
    "severity", "message", "old_state", "new_state", "partcount",
    "good_parts", "defective_parts", "buffer_level", "oee",
    "utilisation", "shift_number", "shift_name", "extra_json"
]


class CSVHistorian(EventHistorian):
    """CSV file storage backend (default).

    Writes events to CSV files with buffered I/O and optional file rotation.
    """

    def __init__(self, output_dir: str, scenario_name: str,
                 max_file_size_mb: float = 50.0,
                 rotate_on_shift: bool = True,
                 buffer_size: int = 100,
                 run_id: str = ""):
        self.output_dir = output_dir
        self.scenario_name = scenario_name
        self._run_id = run_id
        self.max_file_size_mb = max_file_size_mb
        self.rotate_on_shift = rotate_on_shift
        self.buffer_size = buffer_size

        self._event_count = 0
        self._file_index = 0
        self._buffer: List[SimEvent] = []
        self._last_flush_time = _time.time()

        # Ensure output directory exists
        os.makedirs(output_dir, exist_ok=True)

        # Generate base filename — use run_id directly if provided so that the
        # CSV filename matches the run_id Flask tracks via SIMANTHA_RUN_ID.
        if run_id:
            self._base_name = f"{run_id}_events"
        else:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            self._base_name = f"{scenario_name}_{ts}_events"

        # Open initial file
        self._file_handle = None
        self._writer = None
        self._current_path = None
        self._open_file()

    def _open_file(self):
        """Open a new CSV file with header."""
        if self._file_handle:
            self._file_handle.close()

        suffix = f"_{self._file_index:03d}" if self._file_index > 0 else ""
        filename = f"{self._base_name}{suffix}.csv"
        self._current_path = os.path.join(self.output_dir, filename)

        self._file_handle = open(self._current_path, "w", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._file_handle, fieldnames=CSV_COLUMNS)
        self._writer.writeheader()
        self._file_handle.flush()

    def _check_rotation(self):
        """Rotate file if size limit exceeded."""
        if self._current_path and os.path.exists(self._current_path):
            size_mb = os.path.getsize(self._current_path) / (1024 * 1024)
            if size_mb >= self.max_file_size_mb:
                self._file_index += 1
                self._open_file()

    def _event_to_row(self, event: SimEvent) -> dict:
        """Convert SimEvent to CSV row dict."""
        return {
            "run_id": self._run_id,
            "timestamp": event.timestamp,
            "wall_clock": event.wall_clock,
            "event_type": event.event_type,
            "source": event.source,
            "source_type": event.source_type,
            "severity": event.severity,
            "message": event.message,
            "old_state": event.old_state,
            "new_state": event.new_state,
            "partcount": event.partcount,
            "good_parts": event.good_parts,
            "defective_parts": event.defective_parts,
            "buffer_level": event.buffer_level,
            "oee": round(event.oee, 4),
            "utilisation": round(event.utilisation, 4),
            "shift_number": event.shift_number,
            "shift_name": event.shift_name,
            "extra_json": json.dumps(event.extra) if event.extra else "",
        }

    def record_event(self, event: SimEvent) -> None:
        self._buffer.append(event)
        self._event_count += 1
        if len(self._buffer) >= self.buffer_size:
            self.flush()

    def record_events(self, events: List[SimEvent]) -> None:
        self._buffer.extend(events)
        self._event_count += len(events)
        if len(self._buffer) >= self.buffer_size:
            self.flush()

    def flush(self) -> None:
        if not self._buffer:
            return
        for event in self._buffer:
            self._writer.writerow(self._event_to_row(event))
        self._file_handle.flush()
        self._buffer.clear()
        self._last_flush_time = _time.time()
        self._check_rotation()

    def rotate_for_shift(self):
        """Force file rotation at shift boundary."""
        if self.rotate_on_shift:
            self.flush()
            self._file_index += 1
            self._open_file()

    def close(self) -> None:
        self.flush()
        if self._file_handle:
            self._file_handle.close()
            self._file_handle = None

    def get_event_count(self) -> int:
        return self._event_count

    def get_current_path(self) -> str:
        return self._current_path

    def describe(self) -> str:
        return f"CSVHistorian -> {self.output_dir}/"


# ========== INFLUXDB BACKEND ==========


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


# ========== FACTORY ==========


def create_historian_from_config(config: dict, scenario_name: str,
                                 run_id: str = "") -> Optional[EventHistorian]:
    """Create historian from YAML config. Returns None if not configured."""
    historian_cfg = config.get("historian")
    if not historian_cfg or not historian_cfg.get("enabled", False):
        return None

    historians = []

    # CSV backend
    csv_cfg = historian_cfg.get("csv", {})
    if csv_cfg.get("enabled", False):
        # Resolve output_dir relative to script location
        output_dir = csv_cfg.get("output_dir", "results/historian")
        if not os.path.isabs(output_dir):
            script_dir = os.path.dirname(os.path.abspath(__file__))
            project_root = os.path.dirname(script_dir)
            output_dir = os.path.join(project_root, output_dir)

        historians.append(CSVHistorian(
            output_dir=output_dir,
            scenario_name=scenario_name,
            max_file_size_mb=csv_cfg.get("max_file_size_mb", 50.0),
            rotate_on_shift=csv_cfg.get("rotate_on_shift", True),
            run_id=run_id,
        ))

    # InfluxDB backend
    influx_cfg = historian_cfg.get("influxdb", {})
    if influx_cfg.get("enabled", False):
        historians.append(InfluxDBHistorian(
            url=_resolve_env_vars(influx_cfg["url"]),
            token=_resolve_env_vars(influx_cfg["token"]),
            org=_resolve_env_vars(influx_cfg["org"]),
            bucket=_resolve_env_vars(influx_cfg["bucket"]),
            scenario_name=scenario_name,
            batch_size=influx_cfg.get("batch_size", 100),
            run_id=run_id,
        ))

    if not historians:
        return None
    if len(historians) == 1:
        return historians[0]
    return CompositeHistorian(historians)


# ========== EVENT COLLECTION HELPERS ==========


def _get_shift_info(shift_manager) -> tuple:
    """Extract shift number and name from shift_manager (if active)."""
    if shift_manager is None:
        return 0, ""
    return (
        shift_manager.current_shift_number,
        shift_manager.shift_definitions[shift_manager.current_shift_index].name
    )


def collect_step_events(
    sim_time: float,
    machines: dict,
    machine_metrics: dict,
    buffers: dict,
    machine_alarms_map: Dict[str, list],
    buffer_alarms_map: Dict[str, list],
    shift_manager,
    shift_rotated: bool,
    spc_monitors: dict,
    historian_state: dict,
    config: dict,
    machine_totals: dict = None,
) -> List[SimEvent]:
    """Collect all historian events for one simulation step.

    Uses edge detection to only emit events when something changes.

    Args:
        sim_time: Current simulation time
        machines: dict of machine_name -> machine_obj
        machine_metrics: dict of machine_name -> metrics dict
        buffers: dict of buffer_name -> buffer_obj
        machine_alarms_map: dict of machine_name -> list of alarm tuples from this step
        buffer_alarms_map: dict of buffer_name -> list of alarm tuples from this step
        shift_manager: ShiftManager or None
        shift_rotated: True if a shift change happened this step
        spc_monitors: dict of machine_name -> ProcessMonitor
        historian_state: mutable dict for tracking previous states (edge detection)
        config: scenario config dict

    Returns:
        List of SimEvent objects generated this step.
    """
    events = []
    wall_clock = datetime.now().isoformat()
    shift_number, shift_name = _get_shift_info(shift_manager)
    event_cfg = config.get("historian", {}).get("events", {})

    # ---- Machine events ----
    for machine_name in machines:
        metrics = machine_metrics[machine_name]
        current_state = metrics["prev_state"]  # Already set to current state by main loop

        # Compute OEE/utilisation for snapshot
        total_time = sum(metrics[k] for k in [
            "processing_time", "blocked_time", "starved_time", "down_time", "idle_time"
        ])
        utilisation = metrics["processing_time"] / total_time if total_time > 0 else 0.0

        # STATE_CHANGE events
        if event_cfg.get("state_changes", True):
            prev = historian_state.get(f"{machine_name}_state", "IDLE")
            if prev != current_state:
                oee_cached = metrics.get("oee_cached") or {}
                events.append(SimEvent(
                    timestamp=sim_time,
                    wall_clock=wall_clock,
                    event_type="STATE_CHANGE",
                    source=machine_name,
                    source_type="machine",
                    severity="INFO",
                    message=f"{machine_name}: {prev} -> {current_state}",
                    old_state=prev,
                    new_state=current_state,
                    partcount=metrics["partcount"],
                    good_parts=metrics["good_parts"],
                    defective_parts=metrics["defective_parts"],
                    oee=metrics.get("oee", 0.0),
                    utilisation=utilisation,
                    shift_number=shift_number,
                    shift_name=shift_name,
                    extra={
                        "availability": round(oee_cached.get("availability", 0), 4),
                        "performance": round(oee_cached.get("performance", 0), 4),
                        "quality": round(oee_cached.get("quality", 0), 4),
                    },
                ))
                historian_state[f"{machine_name}_state"] = current_state

        # ALARM events (reuse alarm tuples from alarm detection)
        if event_cfg.get("alarms", True):
            alarms = machine_alarms_map.get(machine_name, [])
            for alarm in alarms:
                alarm_type, severity, message, is_active, var_key = alarm
                events.append(SimEvent(
                    timestamp=sim_time,
                    wall_clock=wall_clock,
                    event_type="ALARM",
                    source=machine_name,
                    source_type="machine",
                    severity=severity,
                    message=message,
                    partcount=metrics["partcount"],
                    good_parts=metrics["good_parts"],
                    defective_parts=metrics["defective_parts"],
                    utilisation=utilisation,
                    shift_number=shift_number,
                    shift_name=shift_name,
                    extra={"alarm_type": alarm_type, "is_active": is_active},
                ))

        # SPC_VIOLATION events
        if event_cfg.get("spc_violations", True) and machine_name in spc_monitors:
            spc_monitor = spc_monitors[machine_name]
            spc_metrics = spc_monitor.get_metrics()
            prev_in_control = historian_state.get(f"{machine_name}_spc_in_control", True)
            if spc_metrics.in_control != prev_in_control:
                status = "in control" if spc_metrics.in_control else "OUT OF CONTROL"
                violations_str = ", ".join(spc_metrics.violations) if spc_metrics.violations else ""
                events.append(SimEvent(
                    timestamp=sim_time,
                    wall_clock=wall_clock,
                    event_type="SPC_VIOLATION",
                    source=machine_name,
                    source_type="machine",
                    severity="MEDIUM" if not spc_metrics.in_control else "INFO",
                    message=f"{machine_name} SPC: {status}",
                    partcount=metrics["partcount"],
                    shift_number=shift_number,
                    shift_name=shift_name,
                    extra={
                        "in_control": spc_metrics.in_control,
                        "violations": violations_str,
                        "cpk": spc_metrics.cpk,
                        "x_bar": spc_metrics.x_bar,
                    },
                ))
                historian_state[f"{machine_name}_spc_in_control"] = spc_metrics.in_control

        # SCRAP events (quality routing)
        # Use machine_totals (LineState accumulated values) when available — _scrap_count
        # on the machine object resets to 0 every step via initialize_addon_process().
        if event_cfg.get("state_changes", True):
            mt = machine_totals.get(machine_name) if machine_totals else None
            scrap_count = mt.scrap_count if mt is not None else getattr(machines[machine_name], '_scrap_count', None)
            if isinstance(scrap_count, (int, float)):
                prev_scrap = historian_state.get(f"{machine_name}_scrap_count", 0)
                if scrap_count > prev_scrap:
                    events.append(SimEvent(
                        timestamp=sim_time,
                        wall_clock=wall_clock,
                        event_type="SCRAP",
                        source=machine_name,
                        source_type="machine",
                        severity="LOW",
                        message=f"{machine_name} scrapped a part (total: {scrap_count})",
                        partcount=metrics["partcount"],
                        good_parts=metrics["good_parts"],
                        defective_parts=metrics["defective_parts"],
                        oee=metrics.get("oee", 0.0),
                        utilisation=utilisation,
                        shift_number=shift_number,
                        shift_name=shift_name,
                        extra={"scrap_count": scrap_count},
                    ))
                    historian_state[f"{machine_name}_scrap_count"] = scrap_count

            # REWORK events
            rework_count = mt.rework_count if mt is not None else getattr(machines[machine_name], '_rework_count', None)
            if isinstance(rework_count, (int, float)):
                prev_rework = historian_state.get(f"{machine_name}_rework_count", 0)
                if rework_count > prev_rework:
                    success_count = getattr(machines[machine_name], '_rework_success_count', 0)
                    events.append(SimEvent(
                        timestamp=sim_time,
                        wall_clock=wall_clock,
                        event_type="REWORK",
                        source=machine_name,
                        source_type="machine",
                        severity="LOW",
                        message=f"{machine_name} rework attempt (total: {rework_count})",
                        partcount=metrics["partcount"],
                        good_parts=metrics["good_parts"],
                        defective_parts=metrics["defective_parts"],
                        oee=metrics.get("oee", 0.0),
                        utilisation=utilisation,
                        shift_number=shift_number,
                        shift_name=shift_name,
                        extra={"rework_count": rework_count, "rework_success_count": success_count},
                    ))
                    historian_state[f"{machine_name}_rework_count"] = rework_count

    # ---- Buffer events ----
    if event_cfg.get("buffer_level_changes", True):
        for buffer_name, buffer_obj in buffers.items():
            level = buffer_obj.level
            prev_level = historian_state.get(f"{buffer_name}_level", -1)
            if prev_level != level:
                events.append(SimEvent(
                    timestamp=sim_time,
                    wall_clock=wall_clock,
                    event_type="STATE_CHANGE",
                    source=buffer_name,
                    source_type="buffer",
                    severity="INFO",
                    message=f"{buffer_name}: level {prev_level} -> {level}",
                    old_state=str(prev_level),
                    new_state=str(level),
                    buffer_level=level,
                    shift_number=shift_number,
                    shift_name=shift_name,
                ))
                historian_state[f"{buffer_name}_level"] = level

    # Buffer alarm events
    if event_cfg.get("alarms", True):
        for buffer_name, alarms in buffer_alarms_map.items():
            buffer_obj = buffers[buffer_name]
            for alarm in alarms:
                alarm_type, severity, message, is_active, var_key = alarm
                events.append(SimEvent(
                    timestamp=sim_time,
                    wall_clock=wall_clock,
                    event_type="ALARM",
                    source=buffer_name,
                    source_type="buffer",
                    severity=severity,
                    message=message,
                    buffer_level=buffer_obj.level,
                    shift_number=shift_number,
                    shift_name=shift_name,
                    extra={"alarm_type": alarm_type, "is_active": is_active},
                ))

    # ---- Shift events ----
    if event_cfg.get("shift_changes", True) and shift_rotated and shift_manager:
        prev_shift = shift_manager.get_previous_shift_summary()
        extra = {}
        if prev_shift:
            extra = {
                "prev_shift_name": prev_shift.get("shift_name", ""),
                "prev_shift_parts": prev_shift.get("parts_produced", 0),
                "prev_shift_oee": prev_shift.get("oee", 0.0),
            }
        events.append(SimEvent(
            timestamp=sim_time,
            wall_clock=wall_clock,
            event_type="SHIFT_CHANGE",
            source="Line1",
            source_type="shift",
            severity="INFO",
            message=f"Shift {shift_number} started: {shift_name}",
            shift_number=shift_number,
            shift_name=shift_name,
            extra=extra,
        ))

    return events


def collect_production_summary(
    sim_time: float,
    total_parts_produced: int,
    total_wip: int,
    line_oee: float,
    shift_manager,
    line_availability: float = 0.0,
    line_performance: float = 0.0,
    line_quality: float = 0.0,
    machine_metrics: dict = None,
) -> SimEvent:
    """Create a periodic production summary event."""
    shift_number, shift_name = _get_shift_info(shift_manager)
    extra = {
        "total_wip": total_wip,
        "line_oee": round(line_oee, 4),
        "line_availability": round(line_availability, 4),
        "line_performance": round(line_performance, 4),
        "line_quality": round(line_quality, 4),
    }
    if machine_metrics:
        extra["machine_partcounts"] = {
            name: int(m["partcount"]) for name, m in machine_metrics.items()
        }
    return SimEvent(
        timestamp=sim_time,
        wall_clock=datetime.now().isoformat(),
        event_type="PRODUCTION_SUMMARY",
        source="Line1",
        source_type="line",
        severity="INFO",
        message=f"Production summary at t={sim_time:.0f}",
        partcount=total_parts_produced,
        buffer_level=total_wip,
        oee=round(line_oee, 4),
        shift_number=shift_number,
        shift_name=shift_name,
        extra=extra,
    )
