"""
LineState — per-line accounting that survives simulate() reinitialisations.

Two simulation modes are supported:

REPRODUCIBLE (default)
    system.simulate(cumulative_N) is called every step, re-seeded to the same
    value each time.  Simantha object counters (parts_made, _good_count, etc.)
    are authoritative totals for the window [0, N] — LineState copies them
    directly.  The re-seed guarantee ensures the trajectory in [0, N] is
    identical each call, so counters increase monotonically.
    Cost: O(N) per step → O(N²) total.  Practical limit: a few hours of sim time.

REALTIME
    system.simulate(sim_step) is called once per real-time loop iteration.
    Each call creates a fresh Simantha environment, so counters reset to 0.
    LineState accumulates the per-step delta instead of copying the total.
    Cost: O(1) per step → O(N) total.  Sim clock stays locked to wall clock
    indefinitely — suitable for continuous, multi-shift deployments.

The rest of the codebase reads exclusively from LineState.  The only code that
differs between modes is inside sync_sink() and sync_machine().

Design note — converge/diverge topologies (future):
    MachineTotals is topology-agnostic: it holds per-machine counters keyed by
    name regardless of whether machines are in a serial chain, a fork, or a
    merge.  Adding fork-merge support requires changes to:
      1. Simantha object construction (multiple upstreams/downstreams per buffer)
      2. OPC UA node registration (new node paths for fork/merge machines)
      3. run_segment() — calling sync_machine() for each machine in the graph
    It does NOT require changes to LineState, MachineTotals, or any downstream
    KPI code that reads from self.machines[name].  The abstraction is the
    enablement foundation for that future work.
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
                               Used as warm-up boundary in REALTIME mode.
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
