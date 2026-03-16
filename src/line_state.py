"""
LineState — per-line accounting that survives simulate() reinitialisations.

Two simulation modes are supported:

REPRODUCIBLE (current behaviour)
    system.simulate(cumulative_N) is called every step, re-seeded to the same
    value each time.  Simantha object counters (parts_made, _good_count, etc.)
    are authoritative totals for the window [0, N] — LineState copies them
    directly.  The re-seed guarantee ensures the trajectory in [0, N] is
    identical each call, so counters increase monotonically.

REALTIME (Phase B — stepping logic not yet active)
    system.simulate(sim_step) is called once per real-time loop iteration.
    Simantha counters reset to 0 on each call, so LineState accumulates the
    per-step delta instead of copying the total.

The rest of the codebase reads exclusively from LineState.  The only code that
differs between modes is inside sync_sink() and sync_machine().
"""

from dataclasses import dataclass, field
from enum import Enum


class SimMode(Enum):
    REPRODUCIBLE = "reproducible"
    REALTIME = "realtime"


@dataclass
class MachineTotals:
    """Accumulated counters for one machine, mode-agnostic to callers."""
    parts_made: int = 0
    good_count: int = 0
    scrap_count: int = 0
    defective_count: int = 0


@dataclass
class LineState:
    """Per-line accounting state that survives simulate() reinitialisations.

    The main loop writes to LineState via sync_sink() and sync_machine() after
    each simulate() call.  All downstream code (OEE, shift snapshots, OPC UA
    writes) reads from LineState rather than Simantha objects directly.

    Attributes:
        mode:                  SimMode controlling sync behaviour.
        total_parts_produced:  Monotonically increasing part count.
        step_count:            Number of simulate() calls completed.
                               Used as warm-up boundary in REALTIME mode (Phase B).
        machines:              Per-machine MachineTotals, keyed by machine name.
    """
    mode: SimMode = SimMode.REPRODUCIBLE
    total_parts_produced: int = 0
    step_count: int = 0
    _prev_sink_level: int = field(default=0, repr=False)
    machines: dict = field(default_factory=dict)   # str -> MachineTotals

    def init_machine(self, name: str) -> None:
        """Ensure a MachineTotals entry exists for the given machine name."""
        if name not in self.machines:
            self.machines[name] = MachineTotals()

    def sync_sink(self, sink_level: int) -> int:
        """Update throughput counter from current sink.level.

        In REPRODUCIBLE mode sink.level is a monotonically increasing total
        for [0, N].  In REALTIME mode each simulate(sim_step) runs a fresh
        environment so sink.level is the per-step count (0 or a small integer).
        max(0, ...) handles the reset from the previous step's non-zero value.

        Returns:
            delta_parts: parts produced this step (0 when paused or no change).
        """
        delta = max(0, sink_level - self._prev_sink_level)
        self._prev_sink_level = sink_level
        if self.mode == SimMode.REPRODUCIBLE:
            # Assign directly — sink.level is the authoritative running total.
            self.total_parts_produced = sink_level
        else:
            # Accumulate — sink.level is just this step's count.
            self.total_parts_produced += delta
        return delta

    def sync_machine(self, name: str, machine_obj) -> None:
        """Update per-machine totals from a Simantha machine object.

        Must be called immediately after system.simulate() returns, before any
        code reads from self.machines[name].
        """
        self.init_machine(name)
        mt = self.machines[name]

        if self.mode == SimMode.REPRODUCIBLE:
            # Simantha counters are authoritative totals for [0, N].
            mt.parts_made = machine_obj.parts_made
            if hasattr(machine_obj, '_good_count'):
                mt.good_count = machine_obj._good_count
                mt.scrap_count = machine_obj._scrap_count
                mt.defective_count = getattr(machine_obj, '_defective_count', 0)
        else:
            # REALTIME (Phase B): accumulate per-step deltas.
            mt.parts_made += machine_obj.parts_made
            if hasattr(machine_obj, '_good_count'):
                mt.good_count += machine_obj._good_count
                mt.scrap_count += machine_obj._scrap_count
                mt.defective_count += getattr(machine_obj, '_defective_count', 0)
