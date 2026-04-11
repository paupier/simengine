"""
LineState — per-line accounting that survives simulate() reinitialisations.

system.simulate(sim_step) is called once per real-time loop iteration.
Each call creates a fresh Simantha environment, so Simantha's own counters
(parts_made, _good_count, etc.) reset to 0.  LineState accumulates the
per-step delta and holds the running totals that the rest of the codebase
reads.

Compute cost is O(1) per step regardless of how long the simulation has
been running, so the sim clock stays locked to wall clock indefinitely.
A fixed --seed gives a deterministic sequence of per-step seeds
(base_seed + step_count) producing a reproducible trajectory.

Design note — converge/diverge topologies (future):
    MachineTotals is topology-agnostic: counters are keyed by machine name
    regardless of whether machines form a serial chain, a fork, or a merge.
    Adding fork-merge support requires changes to Simantha object construction
    and OPC UA node registration only — not LineState or any downstream KPI
    code that reads from self.machines[name].
"""

from dataclasses import dataclass, field


@dataclass
class MachineTotals:
    """Accumulated counters for one machine."""
    parts_made: int = 0
    good_count: int = 0
    scrap_count: int = 0
    defective_count: int = 0
    rework_count: int = 0
    rework_success_count: int = 0


@dataclass
class LineState:
    """Per-line accounting state that survives simulate() reinitialisations.

    The main loop writes to LineState via sync_sink() and sync_machine() after
    each simulate() call.  All downstream code (OEE, shift snapshots, OPC UA
    writes) reads from LineState rather than Simantha objects directly.

    Attributes:
        total_parts_produced:  Monotonically increasing part count.
        step_count:            Number of simulate() calls completed.
                               Used as warm-up boundary: counting is active
                               when step_count >= warm_up_time.
        machines:              Per-machine MachineTotals, keyed by machine name.
    """
    total_parts_produced: int = 0
    step_count: int = 0
    machines: dict = field(default_factory=dict)   # str -> MachineTotals

    def init_machine(self, name: str) -> None:
        """Ensure a MachineTotals entry exists for the given machine name."""
        if name not in self.machines:
            self.machines[name] = MachineTotals()

    def sync_sink(self, sink_level: int) -> int:
        """Update throughput counter from current sink.level.

        Each simulate(sim_step) runs a fresh environment, which calls
        Sink.initialize() and resets sink.level to 0.  Parts that arrive
        during the step increment sink.level from 0.  So sink.level IS
        the per-step count — accumulate it directly rather than computing
        a delta from a previous value (which would miss parts on consecutive
        same-level steps).

        Returns:
            delta_parts: parts produced this step (0 when none arrived).
        """
        delta = max(0, sink_level)
        self.total_parts_produced += delta
        return delta

    def sync_machine(self, name: str, machine_obj) -> None:
        """Accumulate per-step deltas from a Simantha machine object.

        Must be called immediately after system.simulate() returns, before any
        code reads from self.machines[name].
        """
        self.init_machine(name)
        mt = self.machines[name]

        mt.parts_made += machine_obj.parts_made
        if hasattr(machine_obj, '_good_count'):
            mt.good_count += machine_obj._good_count
            mt.scrap_count += machine_obj._scrap_count
            mt.defective_count += getattr(machine_obj, '_defective_count', 0)
            mt.rework_count += getattr(machine_obj, '_rework_count', 0)
            mt.rework_success_count += getattr(machine_obj, '_rework_success_count', 0)
