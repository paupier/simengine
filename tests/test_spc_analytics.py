"""
Unit Tests for SPC Analytics Module (Phase 11)

Tests control charts, capability indices, and Western Electric rules.
"""
import pytest
import numpy as np
from spc_analytics import (
    SPCConfiguration,
    ControlLimits,
    SPCMetrics,
    ControlChart,
    CapabilityAnalysis,
    ProcessMonitor,
    CONTROL_CHART_CONSTANTS
)


class TestSPCConfiguration:
    """Test SPCConfiguration dataclass."""

    def test_default_configuration(self):
        """Test default SPC configuration values."""
        config = SPCConfiguration()
        assert config.subgroup_size == 5
        assert config.num_subgroups == 25
        assert config.usl is None
        assert config.lsl is None
        assert config.target is None
        assert config.enable_western_electric is True
        assert config.characteristic == "cycle_time"

    def test_custom_configuration(self):
        """Test custom SPC configuration."""
        config = SPCConfiguration(
            subgroup_size=10,
            num_subgroups=30,
            usl=1.2,
            lsl=0.8,
            target=1.0,
            enable_western_electric=False,
            characteristic="diameter"
        )
        assert config.subgroup_size == 10
        assert config.num_subgroups == 30
        assert config.usl == 1.2
        assert config.lsl == 0.8
        assert config.target == 1.0
        assert config.enable_western_electric is False
        assert config.characteristic == "diameter"


class TestControlChart:
    """Test ControlChart class for X-bar and R charts."""

    def test_control_chart_initialization(self):
        """Test control chart initializes correctly."""
        config = SPCConfiguration(subgroup_size=5, num_subgroups=25)
        chart = ControlChart(config)

        assert len(chart.subgroups) == 0
        assert len(chart.x_bar_values) == 0
        assert len(chart.range_values) == 0
        assert chart.x_bar_limits is None
        assert chart.r_limits is None

    def test_add_samples_to_subgroup(self):
        """Test adding samples to create a subgroup."""
        config = SPCConfiguration(subgroup_size=5, num_subgroups=25)
        chart = ControlChart(config)

        # Add 5 samples (one complete subgroup)
        samples = [1.0, 1.1, 0.9, 1.2, 0.8]
        for sample in samples:
            chart.add_sample(sample)

        # Should have completed one subgroup
        assert len(chart.subgroups) == 1
        assert len(chart.x_bar_values) == 1
        assert len(chart.range_values) == 1

        # Check subgroup statistics
        assert chart.x_bar_values[0] == pytest.approx(1.0, abs=0.01)  # Mean
        assert chart.range_values[0] == pytest.approx(0.4, abs=0.01)  # Range = 1.2 - 0.8

    def test_control_limits_calculation(self):
        """Test control limits are calculated after enough subgroups."""
        config = SPCConfiguration(subgroup_size=5, num_subgroups=25)
        chart = ControlChart(config)

        # Add 25 subgroups (125 samples total)
        np.random.seed(42)
        for _ in range(25):
            for _ in range(5):
                chart.add_sample(np.random.normal(loc=1.0, scale=0.05))

        # Control limits should now be calculated
        assert chart.x_bar_limits is not None
        assert chart.r_limits is not None

        # X-bar limits should be around the mean (1.0)
        assert 0.8 < chart.x_bar_limits.cl < 1.2
        assert chart.x_bar_limits.ucl > chart.x_bar_limits.cl
        assert chart.x_bar_limits.lcl < chart.x_bar_limits.cl

        # R limits should be positive
        assert chart.r_limits.cl > 0
        assert chart.r_limits.ucl > chart.r_limits.cl
        assert chart.r_limits.lcl >= 0  # Can be 0 for small subgroup sizes

    def test_control_chart_constants(self):
        """Test control chart constants table exists and is correct."""
        # Constants should exist for subgroup sizes 2-10
        for n in range(2, 11):
            assert n in CONTROL_CHART_CONSTANTS

            A2, D3, D4, d2, c4 = CONTROL_CHART_CONSTANTS[n]

            # All constants should be positive
            assert A2 > 0
            assert D3 >= 0  # Can be 0 for small n
            assert D4 > 0
            assert d2 > 0
            assert c4 > 0

    def test_western_electric_rule1(self):
        """Test Rule 1: Point beyond 3-sigma control limits."""
        config = SPCConfiguration(subgroup_size=5, num_subgroups=25)
        chart = ControlChart(config)

        # Create stable process (25 subgroups)
        np.random.seed(42)
        for _ in range(25):
            for _ in range(5):
                chart.add_sample(np.random.normal(loc=1.0, scale=0.02))

        # Should be in control
        in_control, violations = chart.check_out_of_control()
        assert in_control is True
        assert len(violations) == 0

        # Add out-of-control point (way beyond UCL)
        for _ in range(5):
            chart.add_sample(5.0)  # Very high value

        in_control, violations = chart.check_out_of_control()
        assert in_control is False
        assert any("Rule1" in v for v in violations)

    def test_western_electric_rule4(self):
        """Test Rule 4: 8 consecutive points on same side of center line."""
        config = SPCConfiguration(subgroup_size=5, num_subgroups=25)
        chart = ControlChart(config)

        # Create stable process (25 subgroups)
        np.random.seed(42)
        for _ in range(25):
            for _ in range(5):
                chart.add_sample(np.random.normal(loc=1.0, scale=0.02))

        # Add 8 subgroups all above the center line
        for _ in range(8):
            for _ in range(5):
                # Slight offset to ensure above centerline but within limits
                chart.add_sample(chart.x_bar_limits.cl + 0.05)

        in_control, violations = chart.check_out_of_control()
        # Should detect Rule 4 violation (8 consecutive points on same side)
        assert in_control is False
        assert any("Rule4" in v for v in violations)


class TestCapabilityAnalysis:
    """Test process capability calculations."""

    def test_cp_calculation(self):
        """Test Cp (Process Capability) calculation."""
        # Create data with known statistics
        np.random.seed(42)
        data = np.random.normal(loc=1.0, scale=0.05, size=100)

        usl = 1.2
        lsl = 0.8

        cp = CapabilityAnalysis.calculate_cp(data, usl, lsl)

        # Cp = (USL - LSL) / (6 * sigma)
        # sigma ≈ 0.05, so Cp ≈ (1.2 - 0.8) / (6 * 0.05) = 0.4 / 0.3 = 1.33
        assert 1.0 < cp < 2.0  # Reasonable range

    def test_cpk_calculation(self):
        """Test Cpk (Process Capability Index) calculation."""
        # Perfectly centered process
        np.random.seed(42)
        data = np.random.normal(loc=1.0, scale=0.05, size=100)

        usl = 1.2
        lsl = 0.8

        cpk = CapabilityAnalysis.calculate_cpk(data, usl, lsl)

        # For centered process, Cpk ≈ Cp
        cp = CapabilityAnalysis.calculate_cp(data, usl, lsl)
        assert cpk == pytest.approx(cp, abs=0.2)

    def test_cpk_off_center_process(self):
        """Test Cpk with off-center process (Cpk < Cp)."""
        # Off-center process (mean = 1.1 instead of 1.0)
        np.random.seed(42)
        data = np.random.normal(loc=1.1, scale=0.05, size=100)

        usl = 1.2
        lsl = 0.8

        cp = CapabilityAnalysis.calculate_cp(data, usl, lsl)
        cpk = CapabilityAnalysis.calculate_cpk(data, usl, lsl)

        # Cpk should be less than Cp for off-center process
        assert cpk < cp

    def test_pp_ppk_calculation(self):
        """Test Pp and Ppk (Performance indices) calculation."""
        np.random.seed(42)
        data = np.random.normal(loc=1.0, scale=0.05, size=100)

        usl = 1.2
        lsl = 0.8

        pp = CapabilityAnalysis.calculate_pp(data, usl, lsl)
        ppk = CapabilityAnalysis.calculate_ppk(data, usl, lsl)

        # Pp/Ppk should be similar to Cp/Cpk for stable process
        cp = CapabilityAnalysis.calculate_cp(data, usl, lsl)
        cpk = CapabilityAnalysis.calculate_cpk(data, usl, lsl)

        assert pp == pytest.approx(cp, abs=0.01)
        assert ppk == pytest.approx(cpk, abs=0.01)

    def test_sigma_level_estimation(self):
        """Test Six Sigma quality level estimation from Cpk."""
        # Test known Cpk -> Sigma mappings
        assert CapabilityAnalysis.estimate_sigma_level(2.0) == 6.0  # 6-sigma
        assert CapabilityAnalysis.estimate_sigma_level(1.67) == 5.0  # 5-sigma
        assert CapabilityAnalysis.estimate_sigma_level(1.33) == 4.0  # 4-sigma
        assert CapabilityAnalysis.estimate_sigma_level(1.0) == 3.0  # 3-sigma

        # Test interpolation
        sigma = CapabilityAnalysis.estimate_sigma_level(1.5)
        assert 4.0 < sigma < 5.0

        # Test edge cases
        assert CapabilityAnalysis.estimate_sigma_level(0.0) == 0.0
        assert CapabilityAnalysis.estimate_sigma_level(-1.0) == 0.0

    def test_zero_sigma_edge_case(self):
        """Test Cp/Cpk with zero variance (perfect process)."""
        # All samples identical (zero variance)
        data = np.array([1.0, 1.0, 1.0, 1.0, 1.0])

        usl = 1.2
        lsl = 0.8

        cp = CapabilityAnalysis.calculate_cp(data, usl, lsl)
        cpk = CapabilityAnalysis.calculate_cpk(data, usl, lsl)

        # Should return infinity (perfectly capable)
        assert cp == float('inf')
        assert cpk == float('inf')


class TestProcessMonitor:
    """Test ProcessMonitor integration class."""

    def test_process_monitor_initialization(self):
        """Test ProcessMonitor initializes correctly."""
        config = SPCConfiguration(
            subgroup_size=5,
            num_subgroups=25,
            usl=1.2,
            lsl=0.8
        )
        monitor = ProcessMonitor(config)

        assert monitor.config == config
        assert len(monitor.all_samples) == 0
        assert monitor.total_sample_count == 0

    def test_add_measurements(self):
        """Test adding measurements to ProcessMonitor."""
        config = SPCConfiguration(subgroup_size=5, num_subgroups=25)
        monitor = ProcessMonitor(config)

        # Add 10 measurements
        for i in range(10):
            monitor.add_measurement(1.0 + i * 0.01)

        assert monitor.total_sample_count == 10
        assert len(monitor.all_samples) == 10

    def test_get_metrics_insufficient_data(self):
        """Test getting metrics with insufficient data returns zeros."""
        config = SPCConfiguration(
            subgroup_size=5,
            num_subgroups=25,
            usl=1.2,
            lsl=0.8
        )
        monitor = ProcessMonitor(config)

        # Add only 3 samples (less than one subgroup)
        monitor.add_measurement(1.0)
        monitor.add_measurement(1.1)
        monitor.add_measurement(0.9)

        metrics = monitor.get_metrics()

        # Should return zeros/defaults for most metrics
        assert metrics.total_samples == 3
        assert metrics.num_subgroups == 0
        assert metrics.x_bar == 0.0  # No complete subgroup yet
        assert metrics.cp == 0.0  # Not enough data

    def test_get_metrics_with_sufficient_data(self):
        """Test getting complete SPC metrics with sufficient data."""
        config = SPCConfiguration(
            subgroup_size=5,
            num_subgroups=25,
            usl=1.2,
            lsl=0.8
        )
        monitor = ProcessMonitor(config)

        # Add 125 samples (25 subgroups)
        np.random.seed(42)
        for _ in range(125):
            monitor.add_measurement(np.random.normal(loc=1.0, scale=0.05))

        metrics = monitor.get_metrics()

        # Should have complete metrics
        assert metrics.total_samples == 125
        assert metrics.num_subgroups == 25

        # X-bar chart should have limits
        assert metrics.x_bar_ucl > 0
        assert metrics.x_bar_cl > 0
        assert metrics.x_bar_lcl >= 0

        # R chart should have limits
        assert metrics.r_ucl > 0
        assert metrics.r_cl > 0
        assert metrics.r_lcl >= 0

        # Capability indices should be calculated
        assert metrics.cp > 0
        assert metrics.cpk > 0
        assert metrics.pp > 0
        assert metrics.ppk > 0
        assert metrics.sigma_level > 0

        # Should be in control (stable process)
        assert metrics.in_control is True
        assert len(metrics.violations) == 0

    def test_process_monitor_out_of_control_detection(self):
        """Test ProcessMonitor detects out-of-control conditions."""
        config = SPCConfiguration(
            subgroup_size=5,
            num_subgroups=25,
            usl=1.2,
            lsl=0.8
        )
        monitor = ProcessMonitor(config)

        # Create stable process (25 subgroups)
        np.random.seed(42)
        for _ in range(125):
            monitor.add_measurement(np.random.normal(loc=1.0, scale=0.02))

        metrics_before = monitor.get_metrics()
        assert metrics_before.in_control is True

        # Add out-of-control points (way beyond limits)
        for _ in range(5):
            monitor.add_measurement(5.0)

        metrics_after = monitor.get_metrics()
        assert metrics_after.in_control is False
        assert len(metrics_after.violations) > 0

    def test_reset_functionality(self):
        """Test ProcessMonitor reset clears all data."""
        config = SPCConfiguration(subgroup_size=5, num_subgroups=25)
        monitor = ProcessMonitor(config)

        # Add some measurements
        for i in range(50):
            monitor.add_measurement(1.0 + i * 0.01)

        assert monitor.total_sample_count == 50

        # Reset
        monitor.reset()

        # Should be cleared
        assert monitor.total_sample_count == 0
        assert len(monitor.all_samples) == 0
        assert len(monitor.control_chart.subgroups) == 0

    def test_capability_with_no_spec_limits(self):
        """Test capability indices return 0 when no spec limits provided."""
        config = SPCConfiguration(
            subgroup_size=5,
            num_subgroups=25
            # No USL/LSL specified
        )
        monitor = ProcessMonitor(config)

        # Add sufficient data
        np.random.seed(42)
        for _ in range(125):
            monitor.add_measurement(np.random.normal(loc=1.0, scale=0.05))

        metrics = monitor.get_metrics()

        # Capability indices should be 0 (no spec limits)
        assert metrics.cp == 0.0
        assert metrics.cpk == 0.0
        assert metrics.pp == 0.0
        assert metrics.ppk == 0.0
        assert metrics.sigma_level == 0.0

        # But control chart should still work
        assert metrics.x_bar_ucl > 0
        assert metrics.in_control is True


class TestSPCMetrics:
    """Test SPCMetrics dataclass."""

    def test_spc_metrics_creation(self):
        """Test SPCMetrics dataclass can be created."""
        metrics = SPCMetrics(
            x_bar=1.0,
            range=0.2,
            x_bar_ucl=1.1,
            x_bar_cl=1.0,
            x_bar_lcl=0.9,
            r_ucl=0.4,
            r_cl=0.2,
            r_lcl=0.0,
            cp=1.5,
            cpk=1.3,
            pp=1.5,
            ppk=1.3,
            in_control=True,
            violations=[],
            sigma_level=4.5,
            total_samples=125,
            num_subgroups=25
        )

        assert metrics.x_bar == 1.0
        assert metrics.cp == 1.5
        assert metrics.in_control is True
        assert metrics.total_samples == 125


class TestControlLimits:
    """Test ControlLimits dataclass."""

    def test_control_limits_creation(self):
        """Test ControlLimits dataclass can be created."""
        limits = ControlLimits(ucl=1.1, cl=1.0, lcl=0.9)

        assert limits.ucl == 1.1
        assert limits.cl == 1.0
        assert limits.lcl == 0.9


# Run tests with: pytest tests/test_spc_analytics.py -v
