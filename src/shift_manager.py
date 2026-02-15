"""
Shift Management Module

Tracks manufacturing shifts with automatic rotation and per-shift metrics.
Production counts, defects, and other metrics reset at shift boundaries.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from datetime import datetime


@dataclass
class ShiftDefinition:
    """Definition of a single shift."""
    name: str                    # e.g., "Day Shift", "Night Shift"
    duration: float              # Shift duration in simulation time units
    start_offset: float = 0.0    # Offset from day start (for scheduling)


@dataclass
class ShiftMetrics:
    """Per-shift performance metrics."""
    shift_number: int
    shift_name: str
    start_time: float
    end_time: float

    # Production metrics
    parts_produced: int = 0
    good_parts: int = 0
    defective_parts: int = 0

    # Time metrics (per machine)
    processing_time: Dict[str, float] = field(default_factory=dict)
    down_time: Dict[str, float] = field(default_factory=dict)
    blocked_time: Dict[str, float] = field(default_factory=dict)
    starved_time: Dict[str, float] = field(default_factory=dict)
    idle_time: Dict[str, float] = field(default_factory=dict)

    # Failure tracking
    failure_count: Dict[str, int] = field(default_factory=dict)

    # Quality tracking
    defect_rate: float = 0.0

    # OEE metrics
    availability: float = 0.0
    performance: float = 0.0
    quality: float = 1.0
    oee: float = 0.0


class ShiftManager:
    """
    Manages shift rotation and per-shift metrics tracking.

    Automatically rotates shifts based on simulation time and tracks
    separate metrics for each shift while maintaining overall totals.
    """

    def __init__(self, shift_definitions: List[ShiftDefinition],
                 machine_names: List[str]):
        """
        Initialize shift manager.

        Args:
            shift_definitions: List of shift configurations
            machine_names: Names of machines to track
        """
        self.shift_definitions = shift_definitions
        self.machine_names = machine_names

        # Current shift tracking
        self.current_shift_index = 0
        self.current_shift_number = 1  # Sequential counter (1, 2, 3, ...)
        self.shift_start_time = 0.0
        self.shift_start_wall_clock = datetime.now()

        # Shift history
        self.shift_history: List[ShiftMetrics] = []

        # Current shift metrics (reset at shift end)
        self.current_metrics = self._create_new_shift_metrics()

        # Overall cumulative metrics (never reset)
        self.total_parts_produced = 0
        self.total_good_parts = 0
        self.total_defective_parts = 0
        self.total_shifts_completed = 0

    def _create_new_shift_metrics(self) -> ShiftMetrics:
        """Create a new ShiftMetrics object for the current shift."""
        current_shift = self.shift_definitions[self.current_shift_index]

        metrics = ShiftMetrics(
            shift_number=self.current_shift_number,
            shift_name=current_shift.name,
            start_time=self.shift_start_time,
            end_time=self.shift_start_time + current_shift.duration
        )

        # Initialize machine-specific dictionaries
        for machine in self.machine_names:
            metrics.processing_time[machine] = 0.0
            metrics.down_time[machine] = 0.0
            metrics.blocked_time[machine] = 0.0
            metrics.starved_time[machine] = 0.0
            metrics.idle_time[machine] = 0.0
            metrics.failure_count[machine] = 0

        return metrics

    def check_shift_rotation(self, current_sim_time: float) -> bool:
        """
        Check if shift should rotate based on current simulation time.

        Args:
            current_sim_time: Current simulation time

        Returns:
            True if shift rotated, False otherwise
        """
        current_shift = self.shift_definitions[self.current_shift_index]
        shift_end_time = self.shift_start_time + current_shift.duration

        if current_sim_time >= shift_end_time:
            # Shift is ending - finalize metrics
            self._finalize_current_shift()

            # Rotate to next shift
            self.current_shift_index = (self.current_shift_index + 1) % len(self.shift_definitions)
            self.current_shift_number += 1
            self.shift_start_time = shift_end_time  # Next shift starts where this one ended
            self.shift_start_wall_clock = datetime.now()

            # Create new metrics for next shift
            self.current_metrics = self._create_new_shift_metrics()

            return True

        return False

    def _finalize_current_shift(self):
        """Finalize the current shift and add to history."""
        # Calculate final metrics
        if self.current_metrics.parts_produced > 0:
            self.current_metrics.defect_rate = (
                self.current_metrics.defective_parts / self.current_metrics.parts_produced
            )

        # Calculate shift OEE (simplified - based on line totals)
        total_time = sum(
            self.current_metrics.processing_time.get(m, 0) +
            self.current_metrics.down_time.get(m, 0) +
            self.current_metrics.blocked_time.get(m, 0) +
            self.current_metrics.starved_time.get(m, 0) +
            self.current_metrics.idle_time.get(m, 0)
            for m in self.machine_names
        )

        if total_time > 0:
            total_processing = sum(self.current_metrics.processing_time.values())
            self.current_metrics.availability = total_processing / total_time
            self.current_metrics.performance = 1.0  # Simplified
            self.current_metrics.quality = 1.0 - self.current_metrics.defect_rate
            self.current_metrics.oee = (
                self.current_metrics.availability *
                self.current_metrics.performance *
                self.current_metrics.quality
            )

        # Add to history
        self.shift_history.append(self.current_metrics)
        self.total_shifts_completed += 1

    def update_production(self, parts_delta: int, defects_delta: int):
        """
        Update production metrics for current shift.

        Args:
            parts_delta: Parts produced since last update
            defects_delta: Defects produced since last update
        """
        self.current_metrics.parts_produced += parts_delta
        self.current_metrics.defective_parts += defects_delta
        self.current_metrics.good_parts = (
            self.current_metrics.parts_produced -
            self.current_metrics.defective_parts
        )

        # Update totals
        self.total_parts_produced += parts_delta
        self.total_defective_parts += defects_delta
        self.total_good_parts = self.total_parts_produced - self.total_defective_parts

    def update_machine_time(self, machine_name: str, time_delta: float,
                           state: str):
        """
        Update time tracking for a machine in current shift.

        Args:
            machine_name: Machine identifier
            time_delta: Time increment
            state: Machine state (PROCESSING, BLOCKED, etc.)
        """
        if state == "PROCESSING":
            self.current_metrics.processing_time[machine_name] += time_delta
        elif state == "BLOCKED":
            self.current_metrics.blocked_time[machine_name] += time_delta
        elif state == "STARVED":
            self.current_metrics.starved_time[machine_name] += time_delta
        elif state in ("FAILED", "UNDER_REPAIR"):
            self.current_metrics.down_time[machine_name] += time_delta
        elif state == "IDLE":
            self.current_metrics.idle_time[machine_name] += time_delta

    def record_failure(self, machine_name: str):
        """
        Record a machine failure in current shift.

        Args:
            machine_name: Machine that failed
        """
        if machine_name in self.current_metrics.failure_count:
            self.current_metrics.failure_count[machine_name] += 1

    def get_current_shift_info(self) -> Dict:
        """
        Get information about the current shift.

        Returns:
            Dictionary with shift information
        """
        current_shift = self.shift_definitions[self.current_shift_index]

        return {
            "shift_number": self.current_shift_number,
            "shift_name": current_shift.name,
            "shift_index": self.current_shift_index,
            "shift_duration": current_shift.duration,
            "shift_start_time": self.shift_start_time,
            "shift_end_time": self.shift_start_time + current_shift.duration,
            "shift_start_wall_clock": self.shift_start_wall_clock,
        }

    def get_current_shift_metrics(self) -> Dict:
        """
        Get current shift metrics for OPC UA.

        Returns:
            Dictionary with current shift metrics
        """
        return {
            "parts_produced": self.current_metrics.parts_produced,
            "good_parts": self.current_metrics.good_parts,
            "defective_parts": self.current_metrics.defective_parts,
            "defect_rate": (
                self.current_metrics.defective_parts / self.current_metrics.parts_produced
                if self.current_metrics.parts_produced > 0 else 0.0
            ),
            "availability": self.current_metrics.availability,
            "performance": self.current_metrics.performance,
            "quality": self.current_metrics.quality,
            "oee": self.current_metrics.oee,
        }

    def get_shift_time_remaining(self, current_sim_time: float) -> float:
        """
        Calculate time remaining in current shift.

        Args:
            current_sim_time: Current simulation time

        Returns:
            Time remaining in seconds
        """
        current_shift = self.shift_definitions[self.current_shift_index]
        shift_end_time = self.shift_start_time + current_shift.duration
        return max(0.0, shift_end_time - current_sim_time)

    def get_shift_elapsed_time(self, current_sim_time: float) -> float:
        """
        Calculate time elapsed in current shift.

        Args:
            current_sim_time: Current simulation time

        Returns:
            Time elapsed in seconds
        """
        return current_sim_time - self.shift_start_time

    def get_previous_shift_summary(self) -> Optional[Dict]:
        """
        Get summary of the most recently completed shift.

        Returns:
            Dictionary with previous shift metrics, or None if no completed shifts
        """
        if not self.shift_history:
            return None

        prev_shift = self.shift_history[-1]
        return {
            "shift_number": prev_shift.shift_number,
            "shift_name": prev_shift.shift_name,
            "start_time": prev_shift.start_time,
            "end_time": prev_shift.end_time,
            "parts_produced": prev_shift.parts_produced,
            "good_parts": prev_shift.good_parts,
            "defective_parts": prev_shift.defective_parts,
            "defect_rate": prev_shift.defect_rate,
            "oee": prev_shift.oee,
            "availability": prev_shift.availability,
            "performance": prev_shift.performance,
            "quality": prev_shift.quality,
        }

    def get_total_metrics(self) -> Dict:
        """
        Get overall cumulative metrics across all shifts.

        Returns:
            Dictionary with total metrics
        """
        return {
            "total_parts_produced": self.total_parts_produced,
            "total_good_parts": self.total_good_parts,
            "total_defective_parts": self.total_defective_parts,
            "total_defect_rate": (
                self.total_defective_parts / self.total_parts_produced
                if self.total_parts_produced > 0 else 0.0
            ),
            "total_shifts_completed": self.total_shifts_completed,
        }


def create_shift_manager_from_config(config: Dict, machine_names: List[str]) -> Optional[ShiftManager]:
    """
    Create a ShiftManager from YAML configuration.

    Args:
        config: Configuration dictionary from YAML
        machine_names: List of machine names

    Returns:
        ShiftManager instance or None if shifts not configured
    """
    if "shifts" not in config:
        return None

    shifts_config = config["shifts"]

    # Parse shift definitions
    shift_definitions = []
    for shift_cfg in shifts_config.get("schedule", []):
        shift_def = ShiftDefinition(
            name=shift_cfg["name"],
            duration=shift_cfg["duration"],
            start_offset=shift_cfg.get("start_offset", 0.0)
        )
        shift_definitions.append(shift_def)

    if not shift_definitions:
        return None

    return ShiftManager(shift_definitions, machine_names)
