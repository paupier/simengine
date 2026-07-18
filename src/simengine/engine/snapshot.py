"""The snapshot contract — the system-wide read-only state representation.

Every consumer (publishers, REST, historian event collection, MCP tools)
reads the same per-step ``LineSnapshot`` built by ``LineEngine.snapshot()``.
JSON serialization is ``dataclasses.asdict``; REST returns exactly that shape.
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ProcessValueSnapshot:
    name: str
    unit: str
    value: float
    alarm_state: str          # "OK" | "HIGH" | "LOW"


@dataclass
class ActiveAlarm:
    code: str                 # e.g. "FM_BEARING_WEAR", "PV_TEMP_HIGH", "CS_JAM"
    severity: str             # "INFO" | "WARNING" | "HIGH" | "CRITICAL"
    source: str               # station name
    text: str                 # human-readable
    activated_at: float       # sim_time seconds


@dataclass
class StationSnapshot:
    name: str
    state: str                # one of the 7 states (see engine/station.py)
    health: int
    h_max: int
    cycle_phase: float        # 0.0-1.0 progress through current cycle, 0.0 when not PROCESSING
    parts_made: int
    good: int
    scrap: int
    rework: int
    defective: int
    availability: float
    performance: float
    quality: float
    oee: float
    time_in_state: dict = field(default_factory=dict)   # state -> accumulated seconds
    process_values: list = field(default_factory=list)  # list[ProcessValueSnapshot]
    alarms: list = field(default_factory=list)          # list[ActiveAlarm]


@dataclass
class BufferSnapshot:
    name: str
    level: int
    capacity: int


@dataclass
class LineSnapshot:
    run_id: str
    scenario: str
    sim_time: float
    step_count: int
    line_state: str           # "RUNNING" | "CHANGEOVER" | "STOPPED"
    speed_ratio: float
    throughput: float         # parts per sim-second, cumulative
    total_wip: int
    total_good: int
    total_scrap: int
    oee: float                # bottleneck model
    stations: dict = field(default_factory=dict)   # name -> StationSnapshot
    buffers: dict = field(default_factory=dict)    # name -> BufferSnapshot
    shift: Optional[dict] = None                   # shift_manager passthrough or None
    recipe: Optional[dict] = None                  # recipe state passthrough or None
