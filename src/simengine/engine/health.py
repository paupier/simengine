"""Health / degradation / repair model (build plan P4.1).

Discrete health states 0..h_max. Degradation is a per-step Bernoulli
(p_degrade); h_max is the failed state. Repair durations are sampled from the
MTTR distribution of the failure mode that "caused" the failure (competing
risks via the carried FailureModeManager) or, failing that, the station-level
health.mttr.

CBM (cbm_threshold < h_max): maintenance starts as soon as health reaches the
threshold; health is pinned for the repair duration and the station keeps
processing (parent-validated semantics — CBM never enters the FAILED path and
adds no downtime). The repair countdown is therefore keyed on
repair_remaining > 0, not on the reported UNDER_REPAIR state, which only
exists for health >= h_max.
"""
from typing import Optional

from simengine.config.distributions import (
    DistributionFactory,
    FailureMode,
    FailureModeManager,
    _rvs,
)


class HealthModel:
    """Per-station health state and repair countdown."""

    def __init__(self, health_cfg: Optional[dict], failure_modes_cfg: Optional[list]):
        health_cfg = health_cfg or {}
        self.h_max: int = health_cfg.get("h_max", 1)
        self.p_degrade: float = float(health_cfg.get("p_degrade", 0.0))
        self.cbm_threshold: int = health_cfg.get("cbm_threshold", self.h_max)
        self.mttr_dist = (
            DistributionFactory.create(health_cfg["mttr"]) if "mttr" in health_cfg else None
        )

        self.fmm: Optional[FailureModeManager] = None
        if failure_modes_cfg:
            modes = [
                FailureMode(
                    name=fm["name"],
                    type=fm["type"],
                    mttf_config=fm["mttf"],
                    mttr_config=fm["mttr"],
                )
                for fm in failure_modes_cfg
            ]
            self.fmm = FailureModeManager(modes)

        self.health: int = 0
        self.repair_remaining: float = 0.0
        self.active_failure_mode: Optional[str] = None
        self.pending_failure_mode: Optional[str] = None
        self._pending_fire_time: Optional[float] = None

    def start(self, np_rng) -> None:
        """Sample the initial competing-risks attribution (engine start)."""
        self.health = 0
        self.repair_remaining = 0.0
        self.active_failure_mode = None
        self._sample_attribution(np_rng)

    def _sample_attribution(self, np_rng) -> None:
        """Competing risks: earliest sampled MTTF names the next failure mode.

        MTTF scaling carried from the parent: divide the sample by h_max when
        h_max > 1 so total expected time-to-failure matches the configured MTTF.
        """
        if self.fmm is None:
            self.pending_failure_mode = None
            self._pending_fire_time = None
            return
        fire_time, mode_name = self.fmm.sample_next_failure(random_state=np_rng)
        if self.h_max > 1:
            fire_time /= self.h_max
        self.pending_failure_mode = mode_name
        self._pending_fire_time = fire_time

    def _sample_repair(self, np_rng, sim_step: float) -> float:
        if self.active_failure_mode and self.fmm is not None:
            sample = self.fmm.sample_repair_time(self.active_failure_mode, random_state=np_rng)
        elif self.mttr_dist is not None:
            sample = _rvs(self.mttr_dist, np_rng)
        else:
            sample = sim_step
        return max(sim_step, float(sample))

    def update(self, rng, np_rng, sim_step: float) -> None:
        """Advance the health model one step (P4.1 order)."""
        if self.repair_remaining > 0:
            self.repair_remaining -= sim_step
            if self.repair_remaining <= 0:
                self.health = 0
                self.repair_remaining = 0.0
                self.active_failure_mode = None
                self._sample_attribution(np_rng)
        elif self.health >= self.h_max:
            # Just failed: attribute and sample repair once
            self.active_failure_mode = self.pending_failure_mode
            self.repair_remaining = self._sample_repair(np_rng, sim_step)
        elif self.cbm_threshold < self.h_max and self.health >= self.cbm_threshold:
            # CBM: immediate maintenance, no failure path; health pinned for
            # the repair duration (no active_failure_mode -> station mttr).
            self.repair_remaining = self._sample_repair(np_rng, sim_step)
        else:
            if rng.random() < self.p_degrade:
                self.health += 1

    @property
    def failed(self) -> bool:
        return self.health >= self.h_max

    @property
    def under_repair(self) -> bool:
        return self.failed and self.repair_remaining > 0
