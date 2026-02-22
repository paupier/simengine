"""
Unit Tests for Failure Modes Module

Tests the core failure mode logic in isolation before OPC UA integration.
"""
import pytest
import numpy as np
from src.failure_modes import FailureMode, FailureModeManager, DistributionFactory, ConstantDistribution


class TestDistributionFactory:
    """Test distribution creation from YAML-like configs."""

    def test_constant_distribution(self):
        """Constant distribution returns fixed value."""
        config = {"distribution": "constant", "value": 10.0}
        dist = DistributionFactory.create(config)

        assert isinstance(dist, ConstantDistribution)
        assert dist.rvs() == 10.0
        assert dist.rvs() == 10.0  # Always same value

    def test_exponential_distribution(self):
        """Exponential distribution created with correct mean."""
        config = {"distribution": "exponential", "mean": 100}
        dist = DistributionFactory.create(config)

        # Sample multiple times to verify it's stochastic
        samples = [dist.rvs() for _ in range(500)]
        assert len(set(samples)) > 1  # Not all the same (stochastic)
        assert all(s > 0 for s in samples)  # All positive

        # Mean should be approximately correct (statistical test)
        # Exponential has std=mean, so 500 samples need wider tolerance
        assert 75 < np.mean(samples) < 125  # Within 25% for 500 samples

    def test_weibull_distribution(self):
        """Weibull distribution created with shape and scale."""
        config = {"distribution": "weibull", "shape": 2.5, "scale": 500}
        dist = DistributionFactory.create(config)

        samples = [dist.rvs() for _ in range(100)]
        assert all(s > 0 for s in samples)
        assert len(set(samples)) > 1  # Stochastic

    def test_lognormal_distribution(self):
        """Lognormal distribution created with mean and std."""
        config = {"distribution": "lognormal", "mean": 15, "std": 5}
        dist = DistributionFactory.create(config)

        samples = [dist.rvs() for _ in range(100)]
        assert all(s > 0 for s in samples)
        assert len(set(samples)) > 1

    def test_normal_distribution(self):
        """Normal distribution (truncated at 0) created."""
        config = {"distribution": "normal", "mean": 50, "std": 10}
        dist = DistributionFactory.create(config)

        samples = [dist.rvs() for _ in range(100)]
        assert all(s >= 0 for s in samples)  # Truncated at 0
        assert len(set(samples)) > 1

    def test_uniform_distribution(self):
        """Uniform distribution created with min/max."""
        config = {"distribution": "uniform", "min": 10, "max": 20}
        dist = DistributionFactory.create(config)

        samples = [dist.rvs() for _ in range(100)]
        assert all(10 <= s <= 20 for s in samples)
        assert len(set(samples)) > 1

    def test_unknown_distribution_raises_error(self):
        """Unknown distribution type raises ValueError."""
        config = {"distribution": "unknown_type"}

        with pytest.raises(ValueError, match="Unknown distribution type"):
            DistributionFactory.create(config)

    def test_missing_distribution_key_raises_error(self):
        """Missing 'distribution' key raises ValueError."""
        config = {"mean": 100}  # Missing 'distribution' key

        with pytest.raises(ValueError, match="missing 'distribution' key"):
            DistributionFactory.create(config)

    def test_missing_exponential_mean_raises_error(self):
        """Exponential without 'mean' parameter raises ValueError."""
        config = {"distribution": "exponential"}  # Missing 'mean'

        with pytest.raises(ValueError, match="requires 'mean' parameter"):
            DistributionFactory.create(config)

    def test_missing_weibull_parameters_raises_error(self):
        """Weibull without shape/scale raises ValueError."""
        config = {"distribution": "weibull", "shape": 2.5}  # Missing 'scale'

        with pytest.raises(ValueError, match="requires 'shape' and 'scale' parameters"):
            DistributionFactory.create(config)


class TestFailureMode:
    """Test individual FailureMode behavior."""

    def test_failure_mode_creation(self):
        """FailureMode instantiated with correct attributes."""
        fm = FailureMode(
            name="mechanical",
            type="wearout",
            mttf_config={"distribution": "weibull", "shape": 2.5, "scale": 500},
            mttr_config={"distribution": "constant", "value": 10}
        )

        assert fm.name == "mechanical"
        assert fm.type == "wearout"
        assert fm.failure_count == 0
        assert fm.total_downtime == 0.0
        assert fm.total_uptime == 0.0

    def test_sample_time_to_failure_positive(self):
        """sample_time_to_failure returns positive values."""
        fm = FailureMode(
            name="test",
            type="random",
            mttf_config={"distribution": "exponential", "mean": 100},
            mttr_config={"distribution": "constant", "value": 5}
        )

        for _ in range(100):
            ttf = fm.sample_time_to_failure()
            assert ttf > 0, "Time to failure must be positive"

    def test_sample_repair_time_positive(self):
        """sample_repair_time returns positive values."""
        fm = FailureMode(
            name="test",
            type="random",
            mttf_config={"distribution": "constant", "value": 100},
            mttr_config={"distribution": "lognormal", "mean": 10, "std": 3}
        )

        for _ in range(100):
            ttr = fm.sample_repair_time()
            assert ttr > 0, "Repair time must be positive"

    def test_constant_distribution_deterministic(self):
        """Constant MTTF/MTTR returns same value every time."""
        fm = FailureMode(
            name="test",
            type="random",
            mttf_config={"distribution": "constant", "value": 100},
            mttr_config={"distribution": "constant", "value": 10}
        )

        ttf_samples = [fm.sample_time_to_failure() for _ in range(10)]
        assert all(ttf == 100 for ttf in ttf_samples)

        ttr_samples = [fm.sample_repair_time() for _ in range(10)]
        assert all(ttr == 10 for ttr in ttr_samples)

    def test_record_failure_increments_count(self):
        """record_failure increments failure_count."""
        fm = FailureMode(
            name="test",
            type="random",
            mttf_config={"distribution": "constant", "value": 100},
            mttr_config={"distribution": "constant", "value": 10}
        )

        assert fm.failure_count == 0

        fm.record_failure(failure_time=100, downtime=10)
        assert fm.failure_count == 1

        fm.record_failure(failure_time=210, downtime=10)
        assert fm.failure_count == 2

    def test_record_failure_accumulates_downtime(self):
        """record_failure accumulates total_downtime."""
        fm = FailureMode(
            name="test",
            type="random",
            mttf_config={"distribution": "constant", "value": 100},
            mttr_config={"distribution": "constant", "value": 10}
        )

        fm.record_failure(failure_time=100, downtime=10)
        assert fm.total_downtime == 10

        fm.record_failure(failure_time=210, downtime=15)
        assert fm.total_downtime == 25

    def test_record_failure_tracks_uptime(self):
        """record_failure calculates uptime between failures."""
        fm = FailureMode(
            name="test",
            type="random",
            mttf_config={"distribution": "constant", "value": 100},
            mttr_config={"distribution": "constant", "value": 10}
        )

        # First failure at t=100 (no uptime calculated yet)
        fm.record_failure(failure_time=100, downtime=10)
        assert fm.total_uptime == 0  # No previous failure to measure from

        # Second failure at t=210 (uptime = 210 - 100 = 110)
        fm.record_failure(failure_time=210, downtime=10)
        assert fm.total_uptime == 110

        # Third failure at t=330 (uptime += 330 - 210 = 120)
        fm.record_failure(failure_time=330, downtime=10)
        assert fm.total_uptime == 110 + 120

    def test_mtbf_calculation(self):
        """get_mtbf calculates correctly from history."""
        fm = FailureMode(
            name="test",
            type="random",
            mttf_config={"distribution": "constant", "value": 100},
            mttr_config={"distribution": "constant", "value": 10}
        )

        # No failures yet
        assert fm.get_mtbf() == 0.0

        # Simulate failures with known uptimes
        fm.record_failure(failure_time=100, downtime=10)
        fm.record_failure(failure_time=210, downtime=10)  # uptime = 110
        fm.record_failure(failure_time=330, downtime=10)  # uptime = 120

        # MTBF = total_uptime / failure_count = (110 + 120) / 3 = 76.67
        mtbf = fm.get_mtbf()
        assert abs(mtbf - 76.67) < 0.1

    def test_mttr_calculation(self):
        """get_mttr calculates correctly from history."""
        fm = FailureMode(
            name="test",
            type="random",
            mttf_config={"distribution": "constant", "value": 100},
            mttr_config={"distribution": "constant", "value": 10}
        )

        # No failures yet
        assert fm.get_mttr() == 0.0

        # Simulate failures with varying repair times
        fm.record_failure(failure_time=100, downtime=10)
        fm.record_failure(failure_time=210, downtime=15)
        fm.record_failure(failure_time=330, downtime=20)

        # MTTR = total_downtime / failure_count = (10 + 15 + 20) / 3 = 15
        mttr = fm.get_mttr()
        assert mttr == 15.0

    def test_get_stats(self):
        """get_stats returns complete statistics dict."""
        fm = FailureMode(
            name="test",
            type="random",
            mttf_config={"distribution": "constant", "value": 100},
            mttr_config={"distribution": "constant", "value": 10}
        )

        fm.record_failure(failure_time=100, downtime=10)
        fm.record_failure(failure_time=210, downtime=15)

        stats = fm.get_stats()
        assert stats["failure_count"] == 2
        assert stats["total_downtime"] == 25
        # MTBF = total_uptime / failure_count = 110 / 2 = 55
        assert stats["mtbf"] == 55.0
        assert stats["mttr"] == 12.5  # average downtime


class TestFailureModeManager:
    """Test FailureModeManager competing risks logic."""

    def test_manager_creation(self):
        """FailureModeManager instantiated with failure modes."""
        fm1 = FailureMode(
            name="mechanical",
            type="wearout",
            mttf_config={"distribution": "constant", "value": 100},
            mttr_config={"distribution": "constant", "value": 10}
        )
        fm2 = FailureMode(
            name="electrical",
            type="random",
            mttf_config={"distribution": "constant", "value": 200},
            mttr_config={"distribution": "constant", "value": 5}
        )

        manager = FailureModeManager([fm1, fm2])

        assert len(manager.failure_modes) == 2
        assert "mechanical" in manager.failure_modes_dict
        assert "electrical" in manager.failure_modes_dict

    def test_competing_risks_returns_minimum(self):
        """Competing risks model selects minimum time-to-failure."""
        # Create two failure modes with constant (deterministic) MTTF
        fm_fast = FailureMode(
            name="fast",
            type="random",
            mttf_config={"distribution": "constant", "value": 10},
            mttr_config={"distribution": "constant", "value": 5}
        )
        fm_slow = FailureMode(
            name="slow",
            type="random",
            mttf_config={"distribution": "constant", "value": 100},
            mttr_config={"distribution": "constant", "value": 5}
        )

        manager = FailureModeManager([fm_fast, fm_slow])

        # Sample next failure (should always be "fast" with ttf=10)
        for _ in range(10):
            time, mode = manager.sample_next_failure()
            assert time == 10, "Should select minimum time"
            assert mode == "fast", "Should select fast failure mode"

    def test_competing_risks_stochastic(self):
        """Competing risks with stochastic distributions varies results."""
        fm1 = FailureMode(
            name="mode1",
            type="random",
            mttf_config={"distribution": "exponential", "mean": 100},
            mttr_config={"distribution": "constant", "value": 5}
        )
        fm2 = FailureMode(
            name="mode2",
            type="random",
            mttf_config={"distribution": "exponential", "mean": 100},
            mttr_config={"distribution": "constant", "value": 5}
        )

        manager = FailureModeManager([fm1, fm2])

        # Sample multiple times
        results = [manager.sample_next_failure() for _ in range(100)]

        # Should have variation in times
        times = [r[0] for r in results]
        assert len(set(times)) > 1, "Times should vary (stochastic)"

        # Should have variation in which mode wins
        modes = [r[1] for r in results]
        assert "mode1" in modes and "mode2" in modes, "Both modes should occur"

    def test_sample_repair_time(self):
        """sample_repair_time returns correct mode's MTTR."""
        fm1 = FailureMode(
            name="mode1",
            type="random",
            mttf_config={"distribution": "constant", "value": 100},
            mttr_config={"distribution": "constant", "value": 10}
        )
        fm2 = FailureMode(
            name="mode2",
            type="random",
            mttf_config={"distribution": "constant", "value": 100},
            mttr_config={"distribution": "constant", "value": 20}
        )

        manager = FailureModeManager([fm1, fm2])

        assert manager.sample_repair_time("mode1") == 10
        assert manager.sample_repair_time("mode2") == 20

    def test_sample_repair_time_invalid_mode_raises_error(self):
        """sample_repair_time with unknown mode raises ValueError."""
        fm = FailureMode(
            name="mode1",
            type="random",
            mttf_config={"distribution": "constant", "value": 100},
            mttr_config={"distribution": "constant", "value": 10}
        )

        manager = FailureModeManager([fm])

        with pytest.raises(ValueError, match="not found"):
            manager.sample_repair_time("unknown_mode")

    def test_record_failure(self):
        """record_failure updates correct failure mode."""
        fm1 = FailureMode(
            name="mode1",
            type="random",
            mttf_config={"distribution": "constant", "value": 100},
            mttr_config={"distribution": "constant", "value": 10}
        )
        fm2 = FailureMode(
            name="mode2",
            type="random",
            mttf_config={"distribution": "constant", "value": 100},
            mttr_config={"distribution": "constant", "value": 10}
        )

        manager = FailureModeManager([fm1, fm2])

        manager.record_failure("mode1", failure_time=100, downtime=10)

        assert fm1.failure_count == 1
        assert fm2.failure_count == 0

    def test_record_failure_invalid_mode_raises_error(self):
        """record_failure with unknown mode raises ValueError."""
        fm = FailureMode(
            name="mode1",
            type="random",
            mttf_config={"distribution": "constant", "value": 100},
            mttr_config={"distribution": "constant", "value": 10}
        )

        manager = FailureModeManager([fm])

        with pytest.raises(ValueError, match="not found"):
            manager.record_failure("unknown_mode", failure_time=100, downtime=10)

    def test_get_active_mode_stats(self):
        """get_active_mode_stats returns stats for all modes."""
        fm1 = FailureMode(
            name="mode1",
            type="random",
            mttf_config={"distribution": "constant", "value": 100},
            mttr_config={"distribution": "constant", "value": 10}
        )
        fm2 = FailureMode(
            name="mode2",
            type="random",
            mttf_config={"distribution": "constant", "value": 100},
            mttr_config={"distribution": "constant", "value": 10}
        )

        manager = FailureModeManager([fm1, fm2])

        # Record some failures
        manager.record_failure("mode1", failure_time=100, downtime=10)
        manager.record_failure("mode1", failure_time=210, downtime=15)
        manager.record_failure("mode2", failure_time=150, downtime=5)

        stats = manager.get_active_mode_stats()

        assert "mode1" in stats
        assert "mode2" in stats
        assert stats["mode1"]["failure_count"] == 2
        assert stats["mode2"]["failure_count"] == 1

    def test_empty_failure_modes_raises_error(self):
        """sample_next_failure with no modes raises ValueError."""
        manager = FailureModeManager([])

        with pytest.raises(ValueError, match="No failure modes configured"):
            manager.sample_next_failure()
