"""
Statistical Process Control (SPC) Analytics Module

Implements control charts (X-bar, R), capability indices (Cp/Cpk/Pp/Ppk),
and Western Electric rules for out-of-control detection.

"""
import math

import numpy as np
from collections import deque
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass, field


# Control chart constants for subgroup sizes 2-10
# Source: Montgomery, "Introduction to Statistical Quality Control", 7th ed.
# Format: n: (A2, D3, D4, d2, c4)
CONTROL_CHART_CONSTANTS = {
    2: (1.880, 0.000, 3.267, 1.128, 0.7979),
    3: (1.023, 0.000, 2.574, 1.693, 0.8862),
    4: (0.729, 0.000, 2.282, 2.059, 0.9213),
    5: (0.577, 0.000, 2.114, 2.326, 0.9400),
    6: (0.483, 0.000, 2.004, 2.534, 0.9515),
    7: (0.419, 0.076, 1.924, 2.704, 0.9594),
    8: (0.373, 0.136, 1.864, 2.847, 0.9650),
    9: (0.337, 0.184, 1.816, 2.970, 0.9693),
    10: (0.308, 0.223, 1.777, 3.078, 0.9727),
}


@dataclass
class SPCConfiguration:
    """Configuration for SPC monitoring."""
    subgroup_size: int = 5              # Samples per subgroup
    num_subgroups: int = 25             # Subgroups for control limit calculation
    usl: Optional[float] = None         # Upper specification limit
    lsl: Optional[float] = None         # Lower specification limit
    target: Optional[float] = None      # Target value (nominal)
    enable_western_electric: bool = True  # Enable out-of-control rules
    characteristic: str = "cycle_time"  # Measurement characteristic


@dataclass
class ControlLimits:
    """Control chart limits."""
    ucl: float  # Upper control limit (μ + 3σ)
    cl: float   # Center line (μ)
    lcl: float  # Lower control limit (μ - 3σ)


@dataclass
class SPCMetrics:
    """Complete SPC analysis results."""
    # Current subgroup statistics
    x_bar: float                    # Current subgroup mean
    range: float                    # Current subgroup range

    # X-bar chart limits
    x_bar_ucl: float
    x_bar_cl: float
    x_bar_lcl: float

    # R chart limits
    r_ucl: float
    r_cl: float
    r_lcl: float

    # Process capability
    cp: float                       # Potential capability
    cpk: float                      # Actual capability
    pp: float                       # Process performance
    ppk: float                      # Performance index

    # Status
    in_control: bool                # Process in statistical control
    violations: List[str]           # Active rule violations
    sigma_level: float              # Estimated sigma quality level

    # Sample counts
    total_samples: int              # Total samples collected
    num_subgroups: int              # Number of complete subgroups


class ControlChart:
    """
    X-bar and R (Range) control chart.

    Monitors process mean and variability using subgroups of samples.
    """

    def __init__(self, config: SPCConfiguration):
        self.config = config
        self.subgroups: deque = deque(maxlen=config.num_subgroups)
        self.x_bar_values: deque = deque(maxlen=config.num_subgroups)
        self.range_values: deque = deque(maxlen=config.num_subgroups)

        self._current_subgroup: List[float] = []

        self.x_bar_limits: Optional[ControlLimits] = None
        self.r_limits: Optional[ControlLimits] = None

        self.grand_mean: float = 0.0
        self.mean_range: float = 0.0

    def add_sample(self, value: float) -> None:
        """Add a sample measurement to the current subgroup."""
        self._current_subgroup.append(value)

        # Complete subgroup when we reach target size
        if len(self._current_subgroup) >= self.config.subgroup_size:
            self._complete_subgroup()

    def _complete_subgroup(self) -> None:
        """Calculate statistics for completed subgroup and update limits."""
        subgroup = np.array(self._current_subgroup)

        # Subgroup statistics
        x_bar = np.mean(subgroup)
        r = np.ptp(subgroup)  # Range: max - min

        # Store subgroup data
        self.subgroups.append(subgroup)
        self.x_bar_values.append(x_bar)
        self.range_values.append(r)

        # Clear for next subgroup
        self._current_subgroup = []

        # Recalculate control limits if we have enough data
        if len(self.subgroups) >= self.config.num_subgroups:
            self._calculate_control_limits()

    def _calculate_control_limits(self) -> None:
        """Calculate control limits from historical subgroups."""
        n = self.config.subgroup_size

        if n not in CONTROL_CHART_CONSTANTS:
            raise ValueError(f"Subgroup size {n} not supported (use 2-10)")

        A2, D3, D4, d2, c4 = CONTROL_CHART_CONSTANTS[n]

        # Calculate grand statistics
        self.grand_mean = float(np.mean(list(self.x_bar_values)))
        self.mean_range = float(np.mean(list(self.range_values)))

        # X-bar chart control limits
        # UCL = X̄̄ + A2 * R̄
        # LCL = X̄̄ - A2 * R̄
        self.x_bar_limits = ControlLimits(
            ucl=self.grand_mean + A2 * self.mean_range,
            cl=self.grand_mean,
            lcl=self.grand_mean - A2 * self.mean_range
        )

        # R chart control limits
        # UCL = D4 * R̄
        # LCL = D3 * R̄
        self.r_limits = ControlLimits(
            ucl=D4 * self.mean_range,
            cl=self.mean_range,
            lcl=D3 * self.mean_range
        )

    def check_out_of_control(self) -> Tuple[bool, List[str]]:
        """
        Check for out-of-control conditions using Western Electric rules.

        Returns:
            (in_control, violations) where violations is a list of rule descriptions
        """
        if not self.x_bar_limits or len(self.x_bar_values) < 8:
            # Not enough data yet
            return True, []

        violations = []
        x_bars = list(self.x_bar_values)

        ucl = self.x_bar_limits.ucl
        lcl = self.x_bar_limits.lcl
        cl = self.x_bar_limits.cl
        sigma = (ucl - cl) / 3.0  # Estimate sigma from control limits

        # Rule 1: One point beyond 3σ (outside control limits)
        if x_bars[-1] > ucl or x_bars[-1] < lcl:
            violations.append("Rule1: Point beyond 3σ control limits")

        # Rule 2: 2 out of 3 consecutive points beyond 2σ on same side
        if len(x_bars) >= 3:
            last_3 = x_bars[-3:]
            upper_2sigma = cl + 2 * sigma
            lower_2sigma = cl - 2 * sigma

            beyond_upper = sum(1 for x in last_3 if x > upper_2sigma)
            beyond_lower = sum(1 for x in last_3 if x < lower_2sigma)

            if beyond_upper >= 2:
                violations.append("Rule2: 2 of 3 points beyond +2σ")
            if beyond_lower >= 2:
                violations.append("Rule2: 2 of 3 points beyond -2σ")

        # Rule 3: 4 out of 5 consecutive points beyond 1σ on same side
        if len(x_bars) >= 5:
            last_5 = x_bars[-5:]
            upper_1sigma = cl + sigma
            lower_1sigma = cl - sigma

            beyond_upper = sum(1 for x in last_5 if x > upper_1sigma)
            beyond_lower = sum(1 for x in last_5 if x < lower_1sigma)

            if beyond_upper >= 4:
                violations.append("Rule3: 4 of 5 points beyond +1σ")
            if beyond_lower >= 4:
                violations.append("Rule3: 4 of 5 points beyond -1σ")

        # Rule 4: 8 consecutive points on same side of center line
        if len(x_bars) >= 8:
            last_8 = x_bars[-8:]
            all_above = all(x > cl for x in last_8)
            all_below = all(x < cl for x in last_8)

            if all_above:
                violations.append("Rule4: 8 consecutive points above centerline")
            if all_below:
                violations.append("Rule4: 8 consecutive points below centerline")

        in_control = len(violations) == 0
        return in_control, violations


class CapabilityAnalysis:
    """
    Process capability and performance indices.

    Measures how well process meets specifications (USL/LSL).
    """

    @staticmethod
    def calculate_cp(data: np.ndarray, usl: float, lsl: float) -> float:
        """
        Calculate Cp (Process Capability).

        Cp = (USL - LSL) / (6σ)

        Measures potential capability (assumes centered process).
        """
        sigma = np.std(data, ddof=1)  # Sample standard deviation

        if sigma == 0 or np.isnan(sigma):
            return float('inf') if usl > lsl else 0.0

        cp = (usl - lsl) / (6 * sigma)
        return float(cp)

    @staticmethod
    def calculate_cpk(data: np.ndarray, usl: float, lsl: float) -> float:
        """
        Calculate Cpk (Process Capability Index).

        Cpk = min((USL - μ) / 3σ, (μ - LSL) / 3σ)

        Measures actual capability accounting for process centering.
        """
        mu = np.mean(data)
        sigma = np.std(data, ddof=1)

        if sigma == 0 or np.isnan(sigma):
            return float('inf') if lsl < mu < usl else 0.0

        cpu = (usl - mu) / (3 * sigma)  # Upper capability
        cpl = (mu - lsl) / (3 * sigma)  # Lower capability
        cpk = min(cpu, cpl)

        return float(cpk)

    @staticmethod
    def calculate_pp(data: np.ndarray, usl: float, lsl: float) -> float:
        """
        Calculate Pp (Process Performance).

        Same formula as Cp but uses overall sigma instead of within-subgroup sigma.
        """
        return CapabilityAnalysis.calculate_cp(data, usl, lsl)

    @staticmethod
    def calculate_ppk(data: np.ndarray, usl: float, lsl: float) -> float:
        """
        Calculate Ppk (Process Performance Index).

        Same formula as Cpk but uses overall sigma.
        """
        return CapabilityAnalysis.calculate_cpk(data, usl, lsl)

    @staticmethod
    def estimate_sigma_level(cpk: float) -> float:
        """
        Estimate Six Sigma quality level from Cpk.

        Approximate mapping:
        - Cpk ≥ 2.0  → 6σ (3.4 DPMO)
        - Cpk ≥ 1.67 → 5σ (233 DPMO)
        - Cpk ≥ 1.33 → 4σ (6,210 DPMO)
        - Cpk ≥ 1.0  → 3σ (66,807 DPMO)
        """
        if cpk <= 0:
            return 0.0

        # Piecewise mapping
        if cpk >= 2.0:
            return 6.0
        elif cpk >= 1.67:
            return 5.0 + (cpk - 1.67) / (2.0 - 1.67)  # Interpolate
        elif cpk >= 1.33:
            return 4.0 + (cpk - 1.33) / (1.67 - 1.33)
        elif cpk >= 1.0:
            return 3.0 + (cpk - 1.0) / (1.33 - 1.0)
        else:
            return 2.0 + cpk  # Below 3σ


class ProcessMonitor:
    """
    Main SPC monitoring class.

    Integrates control charts and capability analysis for process monitoring.
    """

    def __init__(self, config: SPCConfiguration):
        self.config = config
        self.control_chart = ControlChart(config)
        self.total_sample_count = 0
        # Welford running aggregates (perf spec P1): O(1) memory and update,
        # mathematically identical to batch mean/std over the full history.
        self._mean = 0.0
        self._m2 = 0.0

    def add_measurement(self, value: float) -> None:
        """
        Add a new measurement to SPC analysis.

        Args:
            value: Measured value (e.g., cycle time, dimension, etc.)
        """
        self.total_sample_count += 1
        delta = value - self._mean
        self._mean += delta / self.total_sample_count
        self._m2 += delta * (value - self._mean)
        self.control_chart.add_sample(value)

    @property
    def _overall_std(self) -> float:
        """Sample standard deviation (ddof=1) over the full history."""
        if self.total_sample_count < 2:
            return 0.0
        return math.sqrt(self._m2 / (self.total_sample_count - 1))

    def get_metrics(self) -> SPCMetrics:
        """
        Get current SPC metrics.

        Returns:
            SPCMetrics with control chart limits, capability indices, and status
        """
        # Control chart values (current subgroup)
        x_bar = float(self.control_chart.x_bar_values[-1]) if self.control_chart.x_bar_values else 0.0
        r = float(self.control_chart.range_values[-1]) if self.control_chart.range_values else 0.0

        # X-bar chart limits
        if self.control_chart.x_bar_limits:
            x_bar_ucl = self.control_chart.x_bar_limits.ucl
            x_bar_cl = self.control_chart.x_bar_limits.cl
            x_bar_lcl = self.control_chart.x_bar_limits.lcl
        else:
            x_bar_ucl = x_bar_cl = x_bar_lcl = 0.0

        # R chart limits
        if self.control_chart.r_limits:
            r_ucl = self.control_chart.r_limits.ucl
            r_cl = self.control_chart.r_limits.cl
            r_lcl = self.control_chart.r_limits.lcl
        else:
            r_ucl = r_cl = r_lcl = 0.0

        # Out-of-control detection
        in_control, violations = self.control_chart.check_out_of_control()

        # Capability indices (require spec limits and sufficient data).
        # Computed from the Welford running stats — same formulas as the
        # array-based CapabilityAnalysis statics, zero array construction.
        has_specs = (self.config.usl is not None and self.config.lsl is not None)
        has_data = self.total_sample_count > 10

        if has_specs and has_data:
            usl, lsl = self.config.usl, self.config.lsl
            mu, sigma = self._mean, self._overall_std
            if sigma == 0 or math.isnan(sigma):
                cp = float('inf') if usl > lsl else 0.0
                cpk = float('inf') if lsl < mu < usl else 0.0
            else:
                cp = (usl - lsl) / (6 * sigma)
                cpk = min((usl - mu) / (3 * sigma), (mu - lsl) / (3 * sigma))
            pp, ppk = cp, cpk  # overall-sigma variants share the formulas here
            sigma_level = CapabilityAnalysis.estimate_sigma_level(cpk)
        else:
            cp = cpk = pp = ppk = sigma_level = 0.0

        return SPCMetrics(
            x_bar=x_bar,
            range=r,
            x_bar_ucl=x_bar_ucl,
            x_bar_cl=x_bar_cl,
            x_bar_lcl=x_bar_lcl,
            r_ucl=r_ucl,
            r_cl=r_cl,
            r_lcl=r_lcl,
            cp=cp,
            cpk=cpk,
            pp=pp,
            ppk=ppk,
            in_control=in_control,
            violations=violations,
            sigma_level=sigma_level,
            total_samples=self.total_sample_count,
            num_subgroups=len(self.control_chart.subgroups)
        )

    def reset(self) -> None:
        """Reset SPC monitoring (clear all data)."""
        self.control_chart = ControlChart(self.config)
        self.total_sample_count = 0
        self._mean = 0.0
        self._m2 = 0.0
