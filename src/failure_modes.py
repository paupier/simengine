"""
Failure Mode Management for Advanced Machine Failures (Phase 10)

This module provides realistic MTTF/MTTR distributions and multiple failure
types to replace the simple 2-state degradation matrix.

Key Features:
- Multiple failure modes per machine (mechanical, electrical, tooling, etc.)
- Statistical distributions (Weibull, Exponential, Lognormal, etc.)
- Competing risks model for multiple failure modes
- MTBF/MTTR calculation from historical data
"""
import numpy as np
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, field
import scipy.stats


@dataclass
class FailureMode:
    """
    Represents a single failure type with MTTF/MTTR distributions.

    Attributes:
        name: Unique identifier for this failure mode (e.g., "mechanical", "electrical")
        type: Failure type ("wearout", "random", "cycle_dependent")
        mttf_config: Configuration dict for MTTF distribution
        mttr_config: Configuration dict for MTTR distribution
        failure_count: Number of failures recorded
        total_downtime: Cumulative repair time (seconds)
        total_uptime: Cumulative operating time between failures (seconds)
        last_failure_time: Simulation time of last failure (for MTBF calculation)
    """
    name: str
    type: str
    mttf_config: dict
    mttr_config: dict
    failure_count: int = 0
    total_downtime: float = 0.0
    total_uptime: float = 0.0
    last_failure_time: float = 0.0

    def __post_init__(self):
        """Create scipy distribution objects from config."""
        self.mttf_dist = DistributionFactory.create(self.mttf_config)
        self.mttr_dist = DistributionFactory.create(self.mttr_config)

    def sample_time_to_failure(self) -> float:
        """
        Sample next time-to-failure from MTTF distribution.

        Returns:
            Time until next failure (positive float)
        """
        sample = self.mttf_dist.rvs()

        # Ensure positive value (critical for Simantha event scheduling)
        if sample <= 0:
            # If distribution produces non-positive value, use small positive fallback
            sample = 0.1

        return float(sample)

    def sample_repair_time(self) -> float:
        """
        Sample repair time from MTTR distribution.

        Returns:
            Repair duration (positive float)
        """
        sample = self.mttr_dist.rvs()

        # Ensure positive value
        if sample <= 0:
            sample = 0.1

        return float(sample)

    def record_failure(self, failure_time: float, downtime: float) -> None:
        """
        Record a failure event for MTBF/MTTR calculation.

        Args:
            failure_time: Simulation time when failure occurred
            downtime: Duration of repair (seconds)
        """
        self.failure_count += 1
        self.total_downtime += downtime

        # Calculate uptime since last failure
        if self.last_failure_time > 0:
            uptime = failure_time - self.last_failure_time
            self.total_uptime += uptime

        self.last_failure_time = failure_time

    def get_mtbf(self) -> float:
        """
        Calculate Mean Time Between Failures from recorded history.

        Returns:
            MTBF in simulation time units, or 0.0 if no failures recorded
        """
        if self.failure_count == 0:
            return 0.0

        return self.total_uptime / self.failure_count

    def get_mttr(self) -> float:
        """
        Calculate Mean Time To Repair from recorded history.

        Returns:
            MTTR in simulation time units, or 0.0 if no failures recorded
        """
        if self.failure_count == 0:
            return 0.0

        return self.total_downtime / self.failure_count

    def get_stats(self) -> Dict[str, float]:
        """
        Get comprehensive statistics for this failure mode.

        Returns:
            Dict with keys: failure_count, total_downtime, mtbf, mttr
        """
        return {
            "failure_count": self.failure_count,
            "total_downtime": self.total_downtime,
            "mtbf": self.get_mtbf(),
            "mttr": self.get_mttr(),
        }


class FailureModeManager:
    """
    Manages multiple failure modes with competing risks model.

    The competing risks model samples time-to-failure from all failure modes
    and selects the minimum (first to occur). This accurately models systems
    where multiple independent failure mechanisms compete.
    """

    def __init__(self, failure_modes: List[FailureMode]):
        """
        Initialize manager with list of failure modes.

        Args:
            failure_modes: List of FailureMode objects
        """
        self.failure_modes = failure_modes
        self.failure_modes_dict = {fm.name: fm for fm in failure_modes}

    def sample_next_failure(self) -> Tuple[float, str]:
        """
        Sample next failure using competing risks model.

        Samples time-to-failure from all failure modes and returns the
        minimum (earliest failure) along with the failure mode name.

        Returns:
            Tuple of (time_to_failure, failure_mode_name)

        Raises:
            ValueError: If no failure modes configured
        """
        if not self.failure_modes:
            raise ValueError("No failure modes configured")

        # Sample from all failure modes
        samples = []
        for fm in self.failure_modes:
            ttf = fm.sample_time_to_failure()
            samples.append((ttf, fm.name))

        # Return minimum (competing risks)
        min_sample = min(samples, key=lambda x: x[0])
        return min_sample

    def sample_repair_time(self, mode_name: str) -> float:
        """
        Sample repair time for a specific failure mode.

        Args:
            mode_name: Name of the failure mode

        Returns:
            Repair time (positive float)

        Raises:
            ValueError: If mode_name not found
        """
        if mode_name not in self.failure_modes_dict:
            raise ValueError(f"Failure mode '{mode_name}' not found")

        return self.failure_modes_dict[mode_name].sample_repair_time()

    def record_failure(self, mode_name: str, failure_time: float, downtime: float) -> None:
        """
        Record a failure event for a specific mode.

        Args:
            mode_name: Name of the failure mode that occurred
            failure_time: Simulation time when failure occurred
            downtime: Duration of repair (seconds)

        Raises:
            ValueError: If mode_name not found
        """
        if mode_name not in self.failure_modes_dict:
            raise ValueError(f"Failure mode '{mode_name}' not found")

        self.failure_modes_dict[mode_name].record_failure(failure_time, downtime)

    def get_active_mode_stats(self) -> Dict[str, Dict[str, float]]:
        """
        Get statistics for all failure modes.

        Returns:
            Dict mapping failure mode names to their stats dicts
        """
        return {
            fm.name: fm.get_stats()
            for fm in self.failure_modes
        }


class DistributionFactory:
    """
    Creates scipy.stats distribution objects from YAML configuration.

    Supported distributions:
    - constant: Fixed value (not stochastic)
    - exponential: Constant hazard rate (random failures)
    - weibull: Weibull distribution (wear-out failures when shape > 1)
    - lognormal: Log-normal distribution (typical for repair times)
    - normal: Normal distribution (truncated at 0 for positive values)
    - uniform: Uniform distribution over [min, max]
    """

    @staticmethod
    def create(config: dict) -> scipy.stats.rv_continuous:
        """
        Create scipy distribution from configuration.

        Args:
            config: Dict with 'distribution' key and distribution-specific parameters

        Returns:
            scipy.stats distribution object (frozen)

        Raises:
            ValueError: If distribution type unknown or required parameters missing

        Examples:
            >>> config = {"distribution": "exponential", "mean": 100}
            >>> dist = DistributionFactory.create(config)
            >>> sample = dist.rvs()  # Sample from exponential(mean=100)

            >>> config = {"distribution": "weibull", "shape": 2.5, "scale": 500}
            >>> dist = DistributionFactory.create(config)
            >>> sample = dist.rvs()  # Sample from Weibull(2.5, 500)
        """
        dist_type = config.get("distribution")

        if dist_type is None:
            raise ValueError("Configuration missing 'distribution' key")

        # Constant distribution (deterministic)
        if dist_type == "constant":
            value = config.get("value")
            if value is None:
                raise ValueError("Constant distribution requires 'value' parameter")

            return ConstantDistribution(value)

        # Exponential distribution (constant hazard rate)
        elif dist_type == "exponential":
            mean = config.get("mean")
            if mean is None:
                raise ValueError("Exponential distribution requires 'mean' parameter")

            # scipy.stats.expon uses scale parameter (mean = scale)
            return scipy.stats.expon(scale=mean)

        # Weibull distribution (wear-out failures)
        elif dist_type == "weibull":
            shape = config.get("shape")
            scale = config.get("scale")

            if shape is None or scale is None:
                raise ValueError("Weibull distribution requires 'shape' and 'scale' parameters")

            # scipy.stats.weibull_min: shape = beta, scale = eta
            return scipy.stats.weibull_min(c=shape, scale=scale)

        # Log-normal distribution (typical for repair times)
        elif dist_type == "lognormal":
            mean = config.get("mean")
            std = config.get("std")

            if mean is None or std is None:
                raise ValueError("Lognormal distribution requires 'mean' and 'std' parameters")

            # scipy.stats.lognorm: s = sigma, scale = exp(mu)
            # For lognormal, median = exp(mu), so scale = median
            # Using mean as approximation to median for simplicity
            return scipy.stats.lognorm(s=std/mean, scale=mean)

        # Normal distribution (truncated at 0)
        elif dist_type == "normal":
            mean = config.get("mean")
            std = config.get("std")

            if mean is None or std is None:
                raise ValueError("Normal distribution requires 'mean' and 'std' parameters")

            # Use truncated normal to ensure positive values
            a = -mean / std  # Truncate at 0 (in standard deviations)
            return scipy.stats.truncnorm(a=a, b=np.inf, loc=mean, scale=std)

        # Uniform distribution
        elif dist_type == "uniform":
            min_val = config.get("min")
            max_val = config.get("max")

            if min_val is None or max_val is None:
                raise ValueError("Uniform distribution requires 'min' and 'max' parameters")

            # scipy.stats.uniform: loc = min, scale = (max - min)
            return scipy.stats.uniform(loc=min_val, scale=max_val - min_val)

        else:
            raise ValueError(
                f"Unknown distribution type '{dist_type}'. "
                f"Supported: constant, exponential, weibull, lognormal, normal, uniform"
            )


class ConstantDistribution:
    """
    Mock distribution that always returns a constant value.

    This is not a true scipy.stats distribution, but implements the
    same interface (rvs() method) for compatibility.
    """

    def __init__(self, value: float):
        """
        Initialize with constant value.

        Args:
            value: The constant value to return
        """
        self.value = value

    def rvs(self, size=None):
        """
        Sample from distribution (always returns constant value).

        Args:
            size: Ignored (for compatibility with scipy.stats interface)

        Returns:
            The constant value
        """
        return self.value
