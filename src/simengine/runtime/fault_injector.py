"""
Fault injection engine for anomaly detection experiments.

Applies parameterised degradation events at specific simulation times,
layered on top of the existing stochastic Markov-chain degradation.
Writes ground truth labels as a side effect, tracking injection times
and subsequent failure/repair events.

Three injection types:
  health_delta      — step jump in Markov health state
  noise_ramp        — linearly increases SPC measurement noise CV over N steps
  cycle_time_offset — shifts the nominal cycle time used for SPC measurements
"""
import csv
from dataclasses import dataclass, field
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# Injection dataclasses
# ---------------------------------------------------------------------------

@dataclass
class _HealthDelta:
    machine: str
    at_sim_time: float
    health_delta: int
    _fired: bool = field(default=False, repr=False)


@dataclass
class _NoiseRamp:
    machine: str
    at_sim_time: float
    duration: float
    target_multiplier: float
    _fired: bool = field(default=False, repr=False)
    _initial_noise: float = field(default=0.0, repr=False)


@dataclass
class _CycleTimeOffset:
    machine: str
    at_sim_time: float
    offset: float
    _fired: bool = field(default=False, repr=False)


# ---------------------------------------------------------------------------
# FaultInjector
# ---------------------------------------------------------------------------

class FaultInjector:
    """
    Checks and applies fault injections each simulation step.

    Call ``step()`` once per sim step immediately after system.simulate()
    returns and before process_machine_step() runs.  Mutations are applied
    directly to ``machine_health`` and ``machine_metrics`` dicts that the
    main loop already owns, so no additional wiring is needed.
    """

    def __init__(self, injections_config: list, spc_noise_scale: float = 0.0):
        """
        Args:
            injections_config: List of injection dicts from scenario YAML.
            spc_noise_scale: Scenario-level health-correlated noise multiplier.
                             Stored here for access by the main loop; actual
                             application happens in write_machine_opcua_vars().
        """
        self.spc_noise_scale = spc_noise_scale
        self._health_deltas: List[_HealthDelta] = []
        self._noise_ramps: List[_NoiseRamp] = []
        self._cycle_offsets: List[_CycleTimeOffset] = []

        for inj in injections_config:
            t = inj.get("type", "health_delta")
            if t == "health_delta":
                self._health_deltas.append(_HealthDelta(
                    machine=inj["machine"],
                    at_sim_time=float(inj["at_sim_time"]),
                    health_delta=int(inj["health_delta"]),
                ))
            elif t == "noise_ramp":
                self._noise_ramps.append(_NoiseRamp(
                    machine=inj["machine"],
                    at_sim_time=float(inj["at_sim_time"]),
                    duration=float(inj["duration"]),
                    target_multiplier=float(inj["target_multiplier"]),
                ))
            elif t == "cycle_time_offset":
                self._cycle_offsets.append(_CycleTimeOffset(
                    machine=inj["machine"],
                    at_sim_time=float(inj["at_sim_time"]),
                    offset=float(inj["offset"]),
                ))

    def step(
        self,
        sim_time: float,
        machine_health: Dict[str, int],
        machine_metrics: Dict[str, dict],
    ) -> List[dict]:
        """
        Apply all due injections and return records for newly fired ones.

        Returns:
            List of dicts, one per newly fired injection, for the ground
            truth writer.  Empty list if nothing fired this step.
        """
        fired = []

        # health_delta: one-shot at at_sim_time
        for inj in self._health_deltas:
            if not inj._fired and sim_time >= inj.at_sim_time:
                inj._fired = True
                prev = machine_health.get(inj.machine, 0)
                h_max = machine_metrics.get(inj.machine, {}).get("h_max", 1)
                new_health = min(prev + inj.health_delta, h_max)
                machine_health[inj.machine] = new_health
                fired.append({
                    "type": "health_delta",
                    "machine": inj.machine,
                    "injection_sim_time": sim_time,
                    "health_before": prev,
                    "health_after": new_health,
                    "h_max": h_max,
                    "failure_sim_time": None,
                    "repair_complete_sim_time": None,
                })

        # noise_ramp: fires once, then updates noise each step during ramp
        for inj in self._noise_ramps:
            if sim_time < inj.at_sim_time:
                continue
            metrics = machine_metrics.get(inj.machine)
            if metrics is None:
                continue
            if not inj._fired:
                inj._fired = True
                inj._initial_noise = metrics.get("spc_measurement_noise", 0.02)
                fired.append({
                    "type": "noise_ramp",
                    "machine": inj.machine,
                    "injection_sim_time": sim_time,
                    "duration": inj.duration,
                    "target_multiplier": inj.target_multiplier,
                    "initial_noise": inj._initial_noise,
                    "failure_sim_time": None,
                    "repair_complete_sim_time": None,
                })
            elapsed = sim_time - inj.at_sim_time
            if elapsed <= inj.duration:
                progress = elapsed / inj.duration
                # Linear interpolation: noise_cv × (1 + progress × (mult − 1))
                new_noise = inj._initial_noise * (1.0 + progress * (inj.target_multiplier - 1.0))
                metrics["spc_measurement_noise"] = new_noise

        # cycle_time_offset: one-shot, sets spc_target_cycle_time permanently
        for inj in self._cycle_offsets:
            if not inj._fired and sim_time >= inj.at_sim_time:
                inj._fired = True
                metrics = machine_metrics.get(inj.machine, {})
                original = metrics.get("cycle_time", 1.0)
                metrics["spc_target_cycle_time"] = original + inj.offset
                fired.append({
                    "type": "cycle_time_offset",
                    "machine": inj.machine,
                    "injection_sim_time": sim_time,
                    "original_cycle_time": original,
                    "offset": inj.offset,
                    "failure_sim_time": None,
                    "repair_complete_sim_time": None,
                })

        return fired


# ---------------------------------------------------------------------------
# GroundTruthWriter
# ---------------------------------------------------------------------------

_GT_COLUMNS = [
    "run_id", "type", "machine",
    "injection_sim_time", "health_before", "health_after", "h_max",
    "initial_noise", "target_multiplier", "duration",
    "original_cycle_time", "offset",
    "failure_sim_time", "repair_complete_sim_time",
    "anomaly_window_start", "anomaly_window_end",
]


class GroundTruthWriter:
    """
    Writes ground truth injection records to a CSV file.

    Records are written immediately when an injection fires.  Subsequent
    calls to notify_failure() and notify_repair_complete() fill in the
    failure and repair timestamps for the most recent health_delta injection
    on that machine (which defines the anomaly window end).

    The anomaly window is defined as:
      - health_delta:      [injection_sim_time, repair_complete_sim_time]
      - noise_ramp:        [injection_sim_time, injection_sim_time + duration]
      - cycle_time_offset: [injection_sim_time, end_of_run (left blank)]
    """

    def __init__(self, path: str, run_id: str):
        self._path = path
        self._run_id = run_id
        self._records: List[dict] = []   # in-memory; flushed on close()
        # Track pending health_delta records per machine (for failure updates)
        self._pending_health: Dict[str, dict] = {}

    def record_injection(self, record: dict) -> None:
        """Add a fired injection record. Called by FaultInjector.step() results."""
        row = {col: "" for col in _GT_COLUMNS}
        row["run_id"] = self._run_id
        row.update({k: v for k, v in record.items() if k in row})
        # Compute known anomaly window bounds
        t = record.get("type")
        start = record.get("injection_sim_time", "")
        row["anomaly_window_start"] = start
        if t == "noise_ramp":
            row["anomaly_window_end"] = float(start) + float(record.get("duration", 0))
        # health_delta and cycle_time_offset: end filled later or left blank
        self._records.append(row)
        if t == "health_delta":
            self._pending_health[record["machine"]] = row

    def notify_failure(self, machine: str, sim_time: float) -> None:
        """Fill failure_sim_time for the pending health_delta on this machine."""
        row = self._pending_health.get(machine)
        if row and not row.get("failure_sim_time"):
            row["failure_sim_time"] = sim_time

    def notify_repair_complete(self, machine: str, sim_time: float) -> None:
        """Fill repair_complete_sim_time and close the anomaly window."""
        row = self._pending_health.get(machine)
        if row and not row.get("repair_complete_sim_time"):
            row["repair_complete_sim_time"] = sim_time
            row["anomaly_window_end"] = sim_time
            # Clear pending — next failure starts a new record
            del self._pending_health[machine]

    def close(self) -> None:
        """Write all records to CSV. Safe to call even if no injections fired."""
        with open(self._path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=_GT_COLUMNS)
            writer.writeheader()
            writer.writerows(self._records)
