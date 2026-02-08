"""
Statistical Validation Tests for Distributions (Phase 10d)

Tests that scipy distributions converge to expected statistical properties.
These tests use large sample sizes and are marked as slow.

Run with: pytest tests/test_distribution_validation.py -v -m slow
"""
import pytest
import numpy as np
import scipy.stats
from src.failure_modes import FailureMode, DistributionFactory


@pytest.mark.slow
class TestExponentialConvergence:
    """Test exponential distribution converges to theoretical MTTF."""

    def test_exponential_mttf_convergence_100(self):
        """Exponential with mean=100 converges to MTTF=100."""
        MTTF_TARGET = 100
        N_SAMPLES = 1000

        fm = FailureMode(
            name="test",
            type="random",
            mttf_config={"distribution": "exponential", "mean": MTTF_TARGET},
            mttr_config={"distribution": "constant", "value": 5}
        )

        # Sample time-to-failure
        samples = [fm.sample_time_to_failure() for _ in range(N_SAMPLES)]
        sample_mean = np.mean(samples)
        sample_std = np.std(samples)

        # Exponential: mean = MTTF, std = MTTF
        print(f"\n  Target MTTF: {MTTF_TARGET}")
        print(f"  Sample mean: {sample_mean:.2f}")
        print(f"  Sample std: {sample_std:.2f}")
        print(f"  Theoretical std: {MTTF_TARGET}")

        # Allow 10% tolerance for mean (1000 samples should be enough)
        assert 90 < sample_mean < 110, f"Mean {sample_mean} not within 10% of {MTTF_TARGET}"

        # Kolmogorov-Smirnov test (tests if samples match distribution)
        ks_stat, p_value = scipy.stats.kstest(samples, 'expon', args=(0, MTTF_TARGET))
        print(f"  KS test p-value: {p_value:.4f}")

        # p-value > 0.05 means we cannot reject the hypothesis that samples come from exponential
        assert p_value > 0.05, f"KS test failed: p={p_value} (samples don't match exponential)"

    def test_exponential_mttf_convergence_500(self):
        """Exponential with mean=500 converges to MTTF=500."""
        MTTF_TARGET = 500
        N_SAMPLES = 1000

        fm = FailureMode(
            name="test",
            type="random",
            mttf_config={"distribution": "exponential", "mean": MTTF_TARGET},
            mttr_config={"distribution": "constant", "value": 5}
        )

        samples = [fm.sample_time_to_failure() for _ in range(N_SAMPLES)]
        sample_mean = np.mean(samples)

        # Allow 10% tolerance
        assert 450 < sample_mean < 550, f"Mean {sample_mean} not within 10% of {MTTF_TARGET}"


@pytest.mark.slow
class TestWeibullBathtubCurve:
    """Test Weibull distribution shows increasing hazard rate (bathtub curve)."""

    def test_weibull_increasing_hazard_rate(self):
        """Weibull with shape > 1 shows increasing failure rate (wear-out)."""
        # Weibull with shape > 1 has increasing hazard rate
        # This means more failures occur later in life (wear-out)
        fm = FailureMode(
            name="test",
            type="wearout",
            mttf_config={"distribution": "weibull", "shape": 2.5, "scale": 500},
            mttr_config={"distribution": "constant", "value": 10}
        )

        N_SAMPLES = 2000
        samples = [fm.sample_time_to_failure() for _ in range(N_SAMPLES)]

        # Divide into time periods
        scale = 500
        early_period = (0, scale * 0.5)  # 0-250
        middle_period = (scale * 0.5, scale)  # 250-500
        late_period = (scale, scale * 1.5)  # 500-750

        early_count = sum(1 for s in samples if early_period[0] <= s < early_period[1])
        middle_count = sum(1 for s in samples if middle_period[0] <= s < middle_period[1])
        late_count = sum(1 for s in samples if late_period[0] <= s < late_period[1])

        print(f"\n  Failure distribution (shape=2.5, scale=500):")
        print(f"  Early period [0-250]: {early_count} failures")
        print(f"  Middle period [250-500]: {middle_count} failures")
        print(f"  Late period [500-750]: {late_count} failures")

        # For Weibull with shape > 1, we expect increasing hazard rate
        # So middle should have more than early (wear-out pattern)
        assert middle_count > early_count, "Weibull should show increasing failures (wear-out)"

        # Verify it's actually Weibull distribution
        ks_stat, p_value = scipy.stats.kstest(
            samples,
            lambda x: scipy.stats.weibull_min.cdf(x, c=2.5, scale=500)
        )
        print(f"  KS test p-value: {p_value:.4f}")
        assert p_value > 0.01, f"KS test failed: p={p_value}"

    def test_weibull_shape_less_than_1_decreasing_hazard(self):
        """Weibull with shape < 1 shows decreasing failure rate (infant mortality)."""
        # Weibull with shape < 1 has decreasing hazard rate (early failures)
        fm = FailureMode(
            name="test",
            type="wearout",
            mttf_config={"distribution": "weibull", "shape": 0.5, "scale": 500},
            mttr_config={"distribution": "constant", "value": 10}
        )

        N_SAMPLES = 2000
        samples = [fm.sample_time_to_failure() for _ in range(N_SAMPLES)]

        scale = 500
        early_period = (0, scale * 0.5)
        middle_period = (scale * 0.5, scale)

        early_count = sum(1 for s in samples if early_period[0] <= s < early_period[1])
        middle_count = sum(1 for s in samples if middle_period[0] <= s < middle_period[1])

        print(f"\n  Failure distribution (shape=0.5, scale=500):")
        print(f"  Early period [0-250]: {early_count} failures")
        print(f"  Middle period [250-500]: {middle_count} failures")

        # For shape < 1, more failures occur early (infant mortality)
        assert early_count > middle_count, "Weibull shape<1 should show early failures"


@pytest.mark.slow
class TestLognormalRepairTime:
    """Test lognormal distribution for repair times."""

    def test_lognormal_mttr_distribution(self):
        """Lognormal MTTR distribution has expected properties."""
        MTTR_MEAN = 15
        MTTR_STD = 5

        fm = FailureMode(
            name="test",
            type="random",
            mttf_config={"distribution": "constant", "value": 100},
            mttr_config={"distribution": "lognormal", "mean": MTTR_MEAN, "std": MTTR_STD}
        )

        N_SAMPLES = 1000
        samples = [fm.sample_repair_time() for _ in range(N_SAMPLES)]

        sample_mean = np.mean(samples)
        sample_median = np.median(samples)
        sample_std = np.std(samples)

        print(f"\n  Lognormal repair times (mean={MTTR_MEAN}, std={MTTR_STD}):")
        print(f"  Sample mean: {sample_mean:.2f}")
        print(f"  Sample median: {sample_median:.2f}")
        print(f"  Sample std: {sample_std:.2f}")

        # Lognormal is right-skewed: median < mean
        assert sample_median < sample_mean, "Lognormal should be right-skewed"

        # Mean should be in reasonable range (allow 30% tolerance due to skewness)
        assert 10 < sample_mean < 25, f"Mean {sample_mean} out of expected range"

        # All samples should be positive
        assert all(s > 0 for s in samples), "All repair times must be positive"

    def test_lognormal_positive_values_only(self):
        """Lognormal distribution never produces negative values."""
        fm = FailureMode(
            name="test",
            type="random",
            mttf_config={"distribution": "constant", "value": 100},
            mttr_config={"distribution": "lognormal", "mean": 10, "std": 3}
        )

        # Sample many times
        samples = [fm.sample_repair_time() for _ in range(1000)]

        # All must be positive
        assert all(s > 0 for s in samples)
        assert min(samples) > 0


@pytest.mark.slow
class TestNormalTruncation:
    """Test normal distribution is properly truncated at zero."""

    def test_normal_truncated_at_zero(self):
        """Normal distribution (truncated) never produces negative values."""
        fm = FailureMode(
            name="test",
            type="random",
            mttf_config={"distribution": "normal", "mean": 50, "std": 10},
            mttr_config={"distribution": "constant", "value": 5}
        )

        # Sample many times
        samples = [fm.sample_time_to_failure() for _ in range(1000)]

        # All must be non-negative (truncated at 0)
        assert all(s >= 0 for s in samples), "Truncated normal must be non-negative"
        assert min(samples) >= 0

        # Mean should be close to 50 (very few samples get truncated with this mean/std)
        sample_mean = np.mean(samples)
        print(f"\n  Truncated normal (mean=50, std=10):")
        print(f"  Sample mean: {sample_mean:.2f}")
        assert 45 < sample_mean < 55


@pytest.mark.slow
class TestUniformDistribution:
    """Test uniform distribution properties."""

    def test_uniform_range(self):
        """Uniform distribution samples within specified range."""
        MIN_VAL = 10
        MAX_VAL = 20

        fm = FailureMode(
            name="test",
            type="random",
            mttf_config={"distribution": "uniform", "min": MIN_VAL, "max": MAX_VAL},
            mttr_config={"distribution": "constant", "value": 5}
        )

        samples = [fm.sample_time_to_failure() for _ in range(1000)]

        # All samples must be in range
        assert all(MIN_VAL <= s <= MAX_VAL for s in samples)

        # Mean should be approximately (min + max) / 2
        sample_mean = np.mean(samples)
        expected_mean = (MIN_VAL + MAX_VAL) / 2
        print(f"\n  Uniform distribution [{MIN_VAL}, {MAX_VAL}]:")
        print(f"  Sample mean: {sample_mean:.2f}")
        print(f"  Expected mean: {expected_mean}")
        assert 14 < sample_mean < 16  # Allow 1.0 tolerance

    def test_uniform_distribution_flat(self):
        """Uniform distribution has approximately flat histogram."""
        fm = FailureMode(
            name="test",
            type="random",
            mttf_config={"distribution": "uniform", "min": 0, "max": 100},
            mttr_config={"distribution": "constant", "value": 5}
        )

        samples = [fm.sample_time_to_failure() for _ in range(1000)]

        # Divide into 10 bins
        bins = [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
        counts = [sum(1 for s in samples if bins[i] <= s < bins[i+1]) for i in range(len(bins)-1)]

        print(f"\n  Uniform histogram (10 bins):")
        for i, count in enumerate(counts):
            print(f"  Bin [{bins[i]}-{bins[i+1]}): {count}")

        # Each bin should have approximately 100 samples (1000 / 10)
        # Allow significant variation due to randomness
        for count in counts:
            assert 60 < count < 140, f"Bin count {count} not approximately uniform"


@pytest.mark.slow
class TestMTBFMTTRCalculation:
    """Test MTBF/MTTR calculation from simulation data."""

    def test_mtbf_calculation_from_multiple_failures(self):
        """MTBF calculated correctly from multiple failure events."""
        # Create failure mode with known MTTF
        KNOWN_MTTF = 100
        fm = FailureMode(
            name="test",
            type="random",
            mttf_config={"distribution": "constant", "value": KNOWN_MTTF},
            mttr_config={"distribution": "constant", "value": 10}
        )

        # Simulate failures
        current_time = 0
        for i in range(10):
            # Fail at regular intervals
            failure_time = current_time + KNOWN_MTTF
            downtime = 10
            fm.record_failure(failure_time, downtime)
            current_time = failure_time + downtime

        # MTBF should equal MTTF for this deterministic case
        calculated_mtbf = fm.get_mtbf()
        print(f"\n  Known MTTF: {KNOWN_MTTF}")
        print(f"  Calculated MTBF: {calculated_mtbf:.2f}")

        # Should be very close (small numerical errors ok)
        assert abs(calculated_mtbf - KNOWN_MTTF) <= 1.0

    def test_mttr_calculation_from_variable_repairs(self):
        """MTTR calculated correctly from variable repair times."""
        fm = FailureMode(
            name="test",
            type="random",
            mttf_config={"distribution": "constant", "value": 100},
            mttr_config={"distribution": "constant", "value": 15}  # Not used for this test
        )

        # Record failures with known downtimes
        repair_times = [10, 15, 20, 25, 30]  # Mean = 20
        for i, downtime in enumerate(repair_times):
            fm.record_failure(failure_time=i*100, downtime=downtime)

        calculated_mttr = fm.get_mttr()
        expected_mttr = np.mean(repair_times)

        print(f"\n  Repair times: {repair_times}")
        print(f"  Expected MTTR: {expected_mttr}")
        print(f"  Calculated MTTR: {calculated_mttr}")

        assert calculated_mttr == expected_mttr


@pytest.mark.slow
class TestCompetingRisksStatistics:
    """Test competing risks model produces correct failure mode proportions."""

    def test_competing_risks_proportions(self):
        """Competing risks produces expected failure mode proportions."""
        from src.failure_modes import FailureModeManager

        # Create two failure modes with 2:1 MTTF ratio
        fm1 = FailureMode(
            name="fast",
            type="random",
            mttf_config={"distribution": "exponential", "mean": 100},
            mttr_config={"distribution": "constant", "value": 5}
        )

        fm2 = FailureMode(
            name="slow",
            type="random",
            mttf_config={"distribution": "exponential", "mean": 200},  # 2x slower
            mttr_config={"distribution": "constant", "value": 5}
        )

        manager = FailureModeManager([fm1, fm2])

        # Sample many failures
        N_SAMPLES = 1000
        fast_count = 0
        slow_count = 0

        for _ in range(N_SAMPLES):
            time, mode = manager.sample_next_failure()
            if mode == "fast":
                fast_count += 1
            else:
                slow_count += 1

        fast_proportion = fast_count / N_SAMPLES
        slow_proportion = slow_count / N_SAMPLES

        print(f"\n  Competing risks (MTTF ratio 1:2):")
        print(f"  Fast failures: {fast_count} ({fast_proportion:.1%})")
        print(f"  Slow failures: {slow_count} ({slow_proportion:.1%})")

        # For exponential distributions with rates λ1 and λ2:
        # P(mode1 wins) = λ1 / (λ1 + λ2) = (1/100) / (1/100 + 1/200) = 0.667
        expected_fast_proportion = 0.667

        # Allow 10% tolerance
        assert 0.6 < fast_proportion < 0.75, f"Fast proportion {fast_proportion} not near {expected_fast_proportion}"
        assert 0.25 < slow_proportion < 0.4
