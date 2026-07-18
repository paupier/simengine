"""Station model: 7-state machine, cycle mechanics, cycle stops, quality roll.

Build plan P4.2 (state machine, normative detection precedence), P4.3
(cycle stops), P4.7 (quality roll salvaged from the parent's quality mixin).

A station holds at most one part. Parts are pulled from the upstream buffer
(infinite source for the first station), processed for cycle_time seconds,
quality-rolled on completion, and pushed to the downstream buffer (infinite
sink for the last station). Scrapped parts are discarded at the station.
"""
from typing import Optional

from simengine.config.distributions import DistributionFactory, _rvs
from simengine.config.loader import resolve_cycle_time
from simengine.engine import alarms as alarm_defs
from simengine.engine.alarms import AlarmRegistry
from simengine.engine.health import HealthModel

# The 7 states (P4.2)
UNDER_REPAIR = "UNDER_REPAIR"
FAILED = "FAILED"
BLOCKED = "BLOCKED"
STARVED = "STARVED"
DEGRADED = "DEGRADED"
PROCESSING = "PROCESSING"
IDLE = "IDLE"

# Time bucket for active cycle stops (feeds OEE Performance, not Availability)
MINOR_STOP = "MINOR_STOP"


class Buffer:
    """Bounded integer buffer between two stations."""

    def __init__(self, name: str, capacity: int):
        self.name = name
        self.capacity = capacity
        self.level = 0

    @property
    def has_space(self) -> bool:
        return self.level < self.capacity

    @property
    def is_empty(self) -> bool:
        return self.level == 0

    def put(self) -> None:
        if not self.has_space:
            raise RuntimeError(f"Buffer {self.name} overflow")
        self.level += 1

    def take(self) -> None:
        if self.is_empty:
            raise RuntimeError(f"Buffer {self.name} underflow")
        self.level -= 1


class CycleStopModel:
    """One configured short-stop reason (P4.3)."""

    def __init__(self, cfg: dict):
        self.reason = cfg["reason"]
        self.code = alarm_defs.cs_code(self.reason)
        self.mtbe_dist = DistributionFactory.create(cfg["mtbe"])
        self.duration_dist = DistributionFactory.create(cfg["duration"])
        self.next_fire: float = 0.0
        self.stop_remaining: float = 0.0

    def start(self, np_rng) -> None:
        self.next_fire = float(_rvs(self.mtbe_dist, np_rng))
        self.stop_remaining = 0.0

    @property
    def active(self) -> bool:
        return self.stop_remaining > 0


class StationModel:
    """One production station."""

    def __init__(self, cfg: dict, sim_step: float = 1.0,
                 rework_enabled: bool = False, rework_success_rate: float = 0.8,
                 health_multiplier: float = 1.0):
        self.name = cfg["name"]
        self.cycle_time = resolve_cycle_time(cfg)
        self.defect_rate = float(cfg.get("defect_rate", 0.0))
        self.sim_step = sim_step
        self.health_model = HealthModel(cfg.get("health"), cfg.get("failure_modes"))
        self.cycle_stops = [CycleStopModel(cs) for cs in cfg.get("cycle_stops", [])]

        # Engine-level quality options; not exposed in the v1 YAML schema.
        self.rework_enabled = rework_enabled
        self.rework_success_rate = rework_success_rate
        self.health_multiplier = float(cfg.get("health_multiplier", health_multiplier))

        # Cycle state
        self.has_part = False
        self.part_ready = False       # completed part waiting for downstream space
        self.cycle_elapsed = 0.0
        self.is_working = False       # advanced its cycle this step

        # Counters (post-warm-up only)
        self.parts_made = 0
        self.good = 0
        self.scrap = 0
        self.rework = 0
        self.defective = 0
        self.parts_out = 0            # parts successfully pushed downstream

        self.state = IDLE
        self.time_in_state: dict = {}

        self._was_failed = False
        self._kpi_baseline = self._kpi_totals()

    # ----- lifecycle -----

    def start(self, np_rng) -> None:
        self.health_model.start(np_rng)
        for cs in self.cycle_stops:
            cs.start(np_rng)

    # ----- helpers -----

    @property
    def health(self) -> int:
        return self.health_model.health

    @property
    def h_max(self) -> int:
        return self.health_model.h_max

    @property
    def cycle_stopped(self) -> bool:
        return any(cs.active for cs in self.cycle_stops)

    @property
    def cycle_phase(self) -> float:
        if self.is_working and self.cycle_time > 0:
            return min(1.0, self.cycle_elapsed / self.cycle_time)
        return 0.0

    # ----- per-step logic -----

    def step(self, rng, np_rng, sim_step: float,
             upstream: Optional[Buffer], downstream: Optional[Buffer],
             alarms: AlarmRegistry, sim_time: float, counting: bool) -> None:
        hm = self.health_model
        hm.update(rng, np_rng, sim_step)
        self._update_failure_alarms(alarms, sim_time)

        # Active cycle stops count down regardless of anything else
        for cs in self.cycle_stops:
            if cs.active:
                cs.stop_remaining -= sim_step
                if cs.stop_remaining <= 0:
                    cs.stop_remaining = 0.0
                    alarms.clear(cs.code, self.name)
                    cs.next_fire = float(_rvs(cs.mtbe_dist, np_rng))

        can_work = not hm.failed
        self.is_working = False

        if can_work and self.has_part and not self.part_ready:
            # Pending stops tick down only while the station is processing;
            # an activation halts this step's cycle progress (P4.3).
            for cs in self.cycle_stops:
                if not cs.active:
                    cs.next_fire -= sim_step
                    if cs.next_fire <= 0:
                        cs.stop_remaining = max(sim_step, float(_rvs(cs.duration_dist, np_rng)))
                        alarms.raise_(cs.code, self.name, "WARNING",
                                      alarm_defs.cs_text(self.name, cs.reason), sim_time)

            if not self.cycle_stopped:
                self.is_working = True
                self.cycle_elapsed += sim_step
                if self.cycle_elapsed >= self.cycle_time:
                    self._complete_cycle(rng, counting)

        # Push a completed part when downstream has space (sink is infinite)
        if self.part_ready and (downstream is None or downstream.has_space):
            if downstream is not None:
                downstream.put()
            self.part_ready = False
            self.has_part = False
            if counting:
                self.parts_out += 1

        # Pull the next part (source is infinite for the first station)
        if not self.has_part and can_work:
            if upstream is None or not upstream.is_empty:
                if upstream is not None:
                    upstream.take()
                self.has_part = True
                self.cycle_elapsed = 0.0

        self._detect_state(upstream, downstream)
        if counting:
            bucket = MINOR_STOP if self.cycle_stopped else self.state
            self.time_in_state[bucket] = self.time_in_state.get(bucket, 0.0) + sim_step

    def _complete_cycle(self, rng, counting: bool) -> None:
        """Quality roll on cycle completion (P4.7)."""
        self.cycle_elapsed = 0.0
        p_defect = min(1.0, self.defect_rate * (self.health_multiplier ** self.health))
        is_defective = rng.random() < p_defect

        scrapped = False
        if is_defective:
            if self.rework_enabled and rng.random() < self.rework_success_rate:
                outcome = "rework"
            else:
                outcome = "scrap"
                scrapped = True
        else:
            outcome = "good"

        if counting:
            self.parts_made += 1
            if is_defective:
                self.defective += 1
            if outcome == "good":
                self.good += 1
            elif outcome == "rework":
                self.rework += 1
                self.good += 1
            else:
                self.scrap += 1

        if scrapped:
            # Scrap is discarded at the station; nothing moves downstream.
            self.has_part = False
            self.part_ready = False
        else:
            self.part_ready = True

    def _update_failure_alarms(self, alarms: AlarmRegistry, sim_time: float) -> None:
        hm = self.health_model
        if hm.failed and not self._was_failed:
            mode = hm.pending_failure_mode or "failure"
            alarms.raise_(alarm_defs.fm_code(mode), self.name, "CRITICAL",
                          alarm_defs.fm_text(self.name, mode), sim_time)
        elif not hm.failed and self._was_failed:
            for alarm in list(alarms.active_for(self.name)):
                if alarm.code.startswith("FM_"):
                    alarms.clear(alarm.code, self.name)
            alarms.clear(alarm_defs.MT_REPAIR, self.name)
        self._was_failed = hm.failed

        if hm.under_repair:
            # idempotent raise doubles as a per-step countdown text refresh
            alarms.raise_(alarm_defs.MT_REPAIR, self.name, "INFO",
                          alarm_defs.mt_repair_text(self.name, hm.repair_remaining),
                          sim_time)
        elif not hm.failed:
            alarms.clear(alarm_defs.MT_REPAIR, self.name)

    def _detect_state(self, upstream: Optional[Buffer],
                      downstream: Optional[Buffer]) -> None:
        """Normative detection precedence (P4.2)."""
        hm = self.health_model
        if hm.failed and hm.repair_remaining > 0:
            self.state = UNDER_REPAIR
        elif hm.failed:
            self.state = FAILED
        elif self.cycle_stopped:
            self.state = IDLE
        elif self.part_ready and downstream is not None and not downstream.has_space:
            self.state = BLOCKED
        elif (not self.has_part and upstream is not None and upstream.is_empty):
            self.state = STARVED
        elif 0 < hm.health < hm.h_max:
            self.state = DEGRADED
        elif self.has_part and not self.part_ready:
            self.state = PROCESSING
        else:
            self.state = IDLE

    # ----- KPIs (P4.5, shift-relative deltas) -----

    def _kpi_totals(self) -> dict:
        return {
            "time_in_state": dict(self.time_in_state),
            "parts_made": self.parts_made,
            "good": self.good,
        }

    def reset_kpi_baseline(self) -> None:
        self._kpi_baseline = self._kpi_totals()

    def kpis(self) -> dict:
        base = self._kpi_baseline
        times = {
            k: self.time_in_state.get(k, 0.0) - base["time_in_state"].get(k, 0.0)
            for k in set(self.time_in_state) | set(base["time_in_state"])
        }
        total_time = sum(times.values())
        down_time = times.get(FAILED, 0.0) + times.get(UNDER_REPAIR, 0.0)
        parts = self.parts_made - base["parts_made"]
        good = self.good - base["good"]

        availability = 1.0 - (down_time / total_time) if total_time > 0 else 0.0
        run_time = total_time - down_time
        performance = (
            min(1.0, (parts * self.cycle_time) / run_time) if run_time > 0 else 0.0
        )
        quality = good / max(1, parts)
        return {
            "availability": availability,
            "performance": performance,
            "quality": quality,
            "oee": availability * performance * quality,
        }
