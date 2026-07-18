"""Process-value models (build plan §5 / Phase 3).

Per-station continuous float signals evaluated each step from cycle phase and
health state. All randomness flows through DistributionFactory with the
per-step RNG. Four profiles, formulas exact per §5:

  cycle_peak       baseline + peak_i * sin(pi * phase) while cycling; the peak
                   is sampled once per cycle and health-drifted
  first_order_lag  value += (target - value) * (sim_step / tau) + noise;
                   target = setpoint * drift when working, else ambient
  cycle_ramp       range[0] + (range[1]-range[0]) * phase + noise while cycling
  constant_noise   mean * drift + noise, always

drift = 1 + health_drift * health.

Threshold alarms: value > alarm_high raises PV_{NAME}_HIGH, value < alarm_low
raises PV_{NAME}_LOW. Clearing requires re-crossing the limit by 1% of the
limit (hysteresis, prevents alarm chatter).
"""
import math

from simengine.config.distributions import DistributionFactory, _rvs
from simengine.engine import alarms as alarm_defs
from simengine.engine.alarms import AlarmRegistry

OK = "OK"
HIGH = "HIGH"
LOW = "LOW"


class ProcessValueModel:
    """One configured process value on one station."""

    def __init__(self, cfg: dict):
        self.name = cfg["name"]
        self.unit = cfg["unit"]
        self.profile = cfg["profile"]
        self.health_drift = float(cfg.get("health_drift", 0.0))
        self.alarm_high = cfg.get("alarm_high")
        self.alarm_low = cfg.get("alarm_low")

        self.noise_dist = (
            DistributionFactory.create(cfg["noise"]) if "noise" in cfg else None
        )

        if self.profile == "cycle_peak":
            self.baseline = float(cfg["baseline"])
            self.peak_dist = DistributionFactory.create(cfg["peak"])
            self.value = self.baseline
            self._peak_i = 0.0
            self._peak_cycle = -1
        elif self.profile == "first_order_lag":
            self.setpoint = float(cfg["setpoint"])
            self.tau = float(cfg["tau"])
            self.initial = float(cfg["initial"])
            self.ambient = float(cfg.get("ambient", self.initial))
            self.value = self.initial
        elif self.profile == "cycle_ramp":
            self.range = [float(v) for v in cfg["range"]]
            self.value = self.range[0]
        elif self.profile == "constant_noise":
            self.mean = float(cfg["mean"])
            self.value = self.mean
        else:  # pragma: no cover - config validation rejects this earlier
            raise ValueError(f"Unknown process value profile: {self.profile}")

        self.alarm_state = OK

    def _noise(self, np_rng) -> float:
        return float(_rvs(self.noise_dist, np_rng)) if self.noise_dist else 0.0

    def update(self, station, np_rng, sim_step: float,
               alarms: AlarmRegistry, sim_time: float) -> None:
        drift = 1.0 + self.health_drift * station.health
        cycling = station.is_working
        phase = station.cycle_phase

        if self.profile == "cycle_peak":
            if not cycling:
                self.value = self.baseline
            else:
                if station.cycle_serial != self._peak_cycle:
                    self._peak_i = float(_rvs(self.peak_dist, np_rng)) * drift
                    self._peak_cycle = station.cycle_serial
                self.value = self.baseline + self._peak_i * math.sin(math.pi * phase)

        elif self.profile == "first_order_lag":
            working = cycling or station.state == "DEGRADED"
            target = self.setpoint * drift if working else self.ambient
            self.value += (target - self.value) * (sim_step / self.tau)
            self.value += self._noise(np_rng)

        elif self.profile == "cycle_ramp":
            if not cycling:
                self.value = self.range[0]
            else:
                lo, hi = self.range
                self.value = lo + (hi - lo) * phase + self._noise(np_rng)

        elif self.profile == "constant_noise":
            self.value = self.mean * drift + self._noise(np_rng)

        self._check_alarms(station.name, alarms, sim_time)

    def _check_alarms(self, station_name: str, alarms: AlarmRegistry,
                      sim_time: float) -> None:
        high_code = alarm_defs.pv_code(self.name, "HIGH")
        low_code = alarm_defs.pv_code(self.name, "LOW")

        if self.alarm_high is not None:
            if self.value > self.alarm_high:
                alarms.raise_(
                    high_code, station_name, "HIGH",
                    alarm_defs.pv_text(station_name, self.name, self.value,
                                       self.unit, self.alarm_high, "HIGH"),
                    sim_time,
                )
                self.alarm_state = HIGH
            elif (self.alarm_state == HIGH
                  and self.value < self.alarm_high - 0.01 * abs(self.alarm_high)):
                alarms.clear(high_code, station_name)
                self.alarm_state = OK

        if self.alarm_low is not None:
            if self.value < self.alarm_low:
                alarms.raise_(
                    low_code, station_name, "HIGH",
                    alarm_defs.pv_text(station_name, self.name, self.value,
                                       self.unit, self.alarm_low, "LOW"),
                    sim_time,
                )
                self.alarm_state = LOW
            elif (self.alarm_state == LOW
                  and self.value > self.alarm_low + 0.01 * abs(self.alarm_low)):
                alarms.clear(low_code, station_name)
                self.alarm_state = OK
