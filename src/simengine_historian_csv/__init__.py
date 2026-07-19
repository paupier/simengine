"""CSV historian plugin (stdlib-only).

Carried from the parent event_historian.py; registered through
simengine.plugins. Config via env: SIMENGINE_HISTORIAN_DIR (default
results/historian relative to the working directory).
"""
import csv
import json
import os
import time as _time
from datetime import datetime
from typing import List

from simengine.events import CSV_COLUMNS, EventHistorian, SimEvent


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


def create(scenario_name: str, run_id: str) -> CSVHistorian:
    output_dir = os.environ.get("SIMENGINE_HISTORIAN_DIR", "results/historian")
    return CSVHistorian(output_dir, scenario_name, run_id=run_id)


def register(registry: dict) -> None:
    registry["csv"] = create
