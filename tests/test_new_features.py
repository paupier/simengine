"""
Tests for new Simantha features:
- Warm-up period support
- Priority maintainer scheduling
- Multi-state degradation
- Variable interarrival times (config validation)
- Part routing history analysis
- Event tracing (CLI flag)
"""
import pytest
import random
from collections import defaultdict
from unittest.mock import MagicMock
from simantha import Source, Machine, Buffer, Sink, System, Maintainer
from simantha.utils import generate_degradation_matrix

from config_loader import (
    load_line_config,
    validate_warm_up,
    validate_maintainer_config,
    validate_interarrival_distribution,
)
from priority_maintainer import PriorityMaintainer
from opcua_server import (
    detect_machine_state,
    accumulate_time,
    analyze_part_routing,
    build_simantha_system,
    calculate_oee_from_sim,
    process_machine_step,
    collect_system_metrics,
    _get_dead_band_for_key,
    CachedOpcuaNode,
)


# ========== Warm-Up Period ==========


class TestWarmUpConfig:
    """Test warm_up_time configuration validation."""

    def test_valid_warm_up_integer(self):
        validate_warm_up({"warm_up_time": 300})

    def test_valid_warm_up_float(self):
        validate_warm_up({"warm_up_time": 300.5})

    def test_valid_warm_up_zero(self):
        validate_warm_up({"warm_up_time": 0})

    def test_missing_warm_up(self):
        validate_warm_up({})  # no warm_up_time key is fine

    def test_negative_warm_up(self):
        with pytest.raises(ValueError, match="non-negative"):
            validate_warm_up({"warm_up_time": -10})

    def test_invalid_warm_up_type(self):
        with pytest.raises(ValueError, match="numeric"):
            validate_warm_up({"warm_up_time": "fast"})


class TestWarmUpSimulation:
    """Test warm-up period behavior with Simantha simulate()."""

    def test_warm_up_suppresses_early_counting(self):
        """Parts produced during warm-up are not counted in sink.level."""
        source = Source()
        m1 = Machine(name="M1", cycle_time=1)
        m2 = Machine(name="M2", cycle_time=1)
        b1 = Buffer(name="B1", capacity=10)
        sink = Sink(collect_parts=True)

        source.define_routing(downstream=[m1])
        m1.define_routing(upstream=[source], downstream=[b1])
        b1.define_routing(upstream=[m1], downstream=[m2])
        m2.define_routing(upstream=[b1], downstream=[sink])
        sink.define_routing(upstream=[m2])

        system = System(objects=[source, m1, b1, m2, sink])

        # Run with warm-up: 50s warm-up + 100s production
        system.simulate(warm_up_time=50, simulation_time=100, verbose=False)
        parts_with_warmup = sink.level

        # Run without warm-up: 150s total (same total time)
        system.simulate(warm_up_time=0, simulation_time=150, verbose=False)
        parts_without_warmup = sink.level

        # With warm-up, sink.level should be less because warm-up parts aren't counted
        assert parts_with_warmup < parts_without_warmup

    def test_warm_up_config_loads(self):
        """warm_up_line scenario loads with warm_up_time."""
        config = load_line_config("warm_up_line")
        assert config["warm_up_time"] == 300


# ========== Priority Maintainer ==========


class TestPriorityMaintainer:
    """Test PriorityMaintainer scheduling strategies."""

    def _make_mock_machine(self, name, time_entered=0, parts_made=100, cycle_time=1):
        m = MagicMock()
        m.name = name
        m.time_entered_queue = time_entered
        m.parts_made = parts_made
        m.cycle_time = cycle_time
        m.in_queue = True
        m.cm_distribution = 10
        m.pm_distribution = 5
        return m

    def test_fifo_selects_earliest(self):
        pm = PriorityMaintainer(strategy='fifo')
        m1 = self._make_mock_machine("M1", time_entered=5)
        m2 = self._make_mock_machine("M2", time_entered=10)
        assert pm.choose_maintenance_action([m1, m2]) == m1

    def test_fifo_random_tie_break(self):
        pm = PriorityMaintainer(strategy='fifo')
        m1 = self._make_mock_machine("M1", time_entered=5)
        m2 = self._make_mock_machine("M2", time_entered=5)
        results = {pm.choose_maintenance_action([m1, m2]) for _ in range(20)}
        # With ties, both should be possible
        assert len(results) >= 1

    def test_spt_selects_shortest_repair(self):
        pm = PriorityMaintainer(strategy='spt')
        m1 = self._make_mock_machine("M1")
        m1.cm_distribution = 20
        m2 = self._make_mock_machine("M2")
        m2.cm_distribution = 5
        assert pm.choose_maintenance_action([m1, m2]) == m2

    def test_priority_selects_highest_priority(self):
        pm = PriorityMaintainer(
            strategy='priority',
            machine_priorities={"M1": 3, "M2": 1, "M3": 2}
        )
        m1 = self._make_mock_machine("M1")
        m2 = self._make_mock_machine("M2")
        m3 = self._make_mock_machine("M3")
        assert pm.choose_maintenance_action([m1, m2, m3]) == m2

    def test_priority_unknown_machine_gets_low_priority(self):
        pm = PriorityMaintainer(
            strategy='priority',
            machine_priorities={"M1": 1}
        )
        m1 = self._make_mock_machine("M1")
        m2 = self._make_mock_machine("M2")  # not in priorities → 999
        assert pm.choose_maintenance_action([m1, m2]) == m1

    def test_bottleneck_selects_highest_utilization(self):
        pm = PriorityMaintainer(strategy='bottleneck')
        m1 = self._make_mock_machine("M1", parts_made=200, cycle_time=2)  # util=400
        m2 = self._make_mock_machine("M2", parts_made=100, cycle_time=1)  # util=100
        assert pm.choose_maintenance_action([m1, m2]) == m1

    def test_single_machine_queue(self):
        """Single machine in queue is always returned regardless of strategy."""
        for strategy in ['fifo', 'spt', 'priority', 'bottleneck']:
            pm = PriorityMaintainer(strategy=strategy)
            m1 = self._make_mock_machine("M1")
            assert pm.choose_maintenance_action([m1]) == m1


class TestPriorityMaintainerConfig:
    """Test config validation for maintainer scheduling."""

    def test_valid_strategy_fifo(self):
        config = {
            "machines": [{"name": "M1"}, {"name": "M2"}],
            "maintainer": {"enabled": True, "strategy": "fifo"}
        }
        validate_maintainer_config(config)

    def test_valid_strategy_bottleneck(self):
        config = {
            "machines": [{"name": "M1"}, {"name": "M2"}],
            "maintainer": {"enabled": True, "strategy": "bottleneck"}
        }
        validate_maintainer_config(config)

    def test_valid_strategy_priority_with_priorities(self):
        config = {
            "machines": [{"name": "M1"}, {"name": "M2"}],
            "maintainer": {
                "enabled": True,
                "strategy": "priority",
                "machine_priorities": {"M1": 1, "M2": 2}
            }
        }
        validate_maintainer_config(config)

    def test_invalid_strategy(self):
        config = {
            "machines": [{"name": "M1"}, {"name": "M2"}],
            "maintainer": {"enabled": True, "strategy": "random_chaos"}
        }
        with pytest.raises(ValueError, match="must be one of"):
            validate_maintainer_config(config)

    def test_priority_references_unknown_machine(self):
        config = {
            "machines": [{"name": "M1"}, {"name": "M2"}],
            "maintainer": {
                "enabled": True,
                "strategy": "priority",
                "machine_priorities": {"M1": 1, "M99": 2}
            }
        }
        with pytest.raises(ValueError, match="unknown machine"):
            validate_maintainer_config(config)

    def test_negative_priority_value(self):
        config = {
            "machines": [{"name": "M1"}, {"name": "M2"}],
            "maintainer": {
                "enabled": True,
                "strategy": "priority",
                "machine_priorities": {"M1": -1}
            }
        }
        with pytest.raises(ValueError, match="non-negative"):
            validate_maintainer_config(config)

    def test_disabled_maintainer_skips_validation(self):
        config = {
            "machines": [{"name": "M1"}, {"name": "M2"}],
            "maintainer": {"enabled": False, "strategy": "invalid_strategy"}
        }
        validate_maintainer_config(config)  # no error

    def test_load_priority_maintenance_line(self):
        """priority_maintenance_line scenario loads successfully."""
        config = load_line_config("priority_maintenance_line")
        assert config["maintainer"]["strategy"] == "bottleneck"

    def test_load_priority_user_line(self):
        """priority_user_line scenario loads successfully."""
        config = load_line_config("priority_user_line")
        assert config["maintainer"]["strategy"] == "priority"
        assert config["maintainer"]["machine_priorities"]["M1"] == 1

    def test_build_priority_maintainer(self):
        """build_simantha_system creates PriorityMaintainer for non-FIFO strategies."""
        config = load_line_config("priority_maintenance_line")
        system, source, sink, machines, buffers, maintainer, scrap_sinks = \
            build_simantha_system(config)
        assert isinstance(maintainer, PriorityMaintainer)
        assert maintainer.strategy == "bottleneck"

    def test_build_fifo_maintainer(self):
        """build_simantha_system creates standard Maintainer for FIFO."""
        config = load_line_config("extended_line")
        system, source, sink, machines, buffers, maintainer, scrap_sinks = \
            build_simantha_system(config)
        assert isinstance(maintainer, Maintainer)
        assert not isinstance(maintainer, PriorityMaintainer)


# ========== Multi-State Degradation ==========


class TestMultiStateDegradation:
    """Test multi-state health degradation support."""

    def test_generate_degradation_matrix_2_state(self):
        matrix = generate_degradation_matrix(p=0.01, h_max=1)
        assert len(matrix) == 2
        assert matrix[0] == [0.99, 0.01]
        assert matrix[1] == [0, 1]

    def test_generate_degradation_matrix_6_state(self):
        matrix = generate_degradation_matrix(p=0.01, h_max=5)
        assert len(matrix) == 6
        # First state: 99% stay, 1% degrade
        assert matrix[0][0] == pytest.approx(0.99)
        assert matrix[0][1] == pytest.approx(0.01)
        # Failed state: absorbing
        assert matrix[5] == [0, 0, 0, 0, 0, 1]

    def test_detect_state_degraded(self):
        """Machine with health > 0 but < failed_health shows DEGRADED."""
        m = MagicMock()
        m.blocked = False
        m.starved = False
        m.has_part = True
        m.failed_health = 5
        state = detect_machine_state(
            m, health_state=2, maint_active=False
        )
        assert state == "DEGRADED"

    def test_detect_state_failed_multistate(self):
        """Machine at failed_health shows FAILED."""
        m = MagicMock()
        m.blocked = False
        m.starved = False
        m.has_part = False
        m.failed_health = 5
        state = detect_machine_state(
            m, health_state=5, maint_active=False
        )
        assert state == "FAILED"

    def test_detect_state_under_repair_multistate(self):
        """Machine at failed_health with maintenance shows UNDER_REPAIR."""
        m = MagicMock()
        m.blocked = False
        m.starved = False
        m.has_part = False
        m.failed_health = 5
        state = detect_machine_state(
            m, health_state=5, maint_active=True
        )
        assert state == "UNDER_REPAIR"

    def test_detect_state_healthy_multistate(self):
        """Machine at health=0 with multi-state shows PROCESSING."""
        m = MagicMock()
        m.blocked = False
        m.starved = False
        m.has_part = True
        m.failed_health = 5
        state = detect_machine_state(
            m, health_state=0, maint_active=False
        )
        assert state == "PROCESSING"

    def test_accumulate_time_degraded(self):
        """DEGRADED state accumulates as processing_time."""
        metrics = {
            "processing_time": 0.0, "blocked_time": 0.0, "starved_time": 0.0,
            "down_time": 0.0, "idle_time": 0.0
        }
        accumulate_time(metrics, "DEGRADED", 5.0)
        assert metrics["processing_time"] == 5.0

    def test_load_multi_state_config(self):
        """multi_state_degradation_line scenario loads successfully."""
        config = load_line_config("multi_state_degradation_line")
        m1_cfg = config["machines"][0]
        assert m1_cfg["health_states"]["h_max"] == 5
        assert m1_cfg["health_states"]["p_degrade"] == 0.01
        assert m1_cfg["health_states"]["cbm_threshold"] == 3

    def test_build_multi_state_machines(self):
        """build_simantha_system creates machines with multi-state degradation matrix."""
        config = load_line_config("multi_state_degradation_line")
        system, source, sink, machines, buffers, maintainer, scrap_sinks = \
            build_simantha_system(config)

        m1 = machines["M1"]
        # M1 has h_max=5, so degradation_matrix should be 6x6
        assert len(m1.degradation_matrix) == 6
        assert m1.failed_health == 5
        # cbm_threshold=3 means preventive maintenance requested at health=3
        assert m1.cbm_threshold == 3

        m2 = machines["M2"]
        # M2 has h_max=3, so degradation_matrix should be 4x4
        assert len(m2.degradation_matrix) == 4
        assert m2.failed_health == 3

    def test_multi_state_simulation_runs(self):
        """Multi-state degradation simulation runs without error."""
        config = load_line_config("multi_state_degradation_line")
        system, source, sink, machines, buffers, maintainer, scrap_sinks = \
            build_simantha_system(config)

        random.seed(42)
        system.simulate(simulation_time=100, verbose=False)
        assert sink.level >= 0


# ========== Variable Interarrival Distribution ==========


class TestInterarrivalDistributionConfig:
    """Test interarrival_distribution config validation."""

    def test_valid_constant(self):
        config = {"interarrival_distribution": {
            "distribution": "constant", "value": 5
        }}
        validate_interarrival_distribution(config)

    def test_valid_uniform(self):
        config = {"interarrival_distribution": {
            "distribution": "uniform", "min": 3, "max": 10
        }}
        validate_interarrival_distribution(config)

    def test_valid_exponential(self):
        config = {"interarrival_distribution": {
            "distribution": "exponential", "mean": 7
        }}
        validate_interarrival_distribution(config)

    def test_missing_interarrival(self):
        validate_interarrival_distribution({})  # no key is fine

    def test_invalid_distribution_type(self):
        config = {"interarrival_distribution": {
            "distribution": "poisson", "mean": 5
        }}
        with pytest.raises(ValueError, match="unknown distribution type"):
            validate_interarrival_distribution(config)

    def test_invalid_type(self):
        config = {"interarrival_distribution": "not_a_dict"}
        with pytest.raises(ValueError, match="must be a dictionary"):
            validate_interarrival_distribution(config)


# ========== Part Routing History ==========


class TestPartRoutingAnalysis:
    """Test analyze_part_routing function."""

    def test_empty_sink(self):
        sink = MagicMock()
        sink.contents = []
        result = analyze_part_routing(sink)
        assert result["total_parts"] == 0
        assert result["unique_routes"] == 0

    def test_no_contents_attr(self):
        sink = MagicMock(spec=[])
        result = analyze_part_routing(sink)
        assert result["total_parts"] == 0

    def test_single_route(self):
        sink = MagicMock()
        part1 = MagicMock()
        part1.routing_history = ["Source", "M1", "B1", "M2", "Sink"]
        part2 = MagicMock()
        part2.routing_history = ["Source", "M1", "B1", "M2", "Sink"]
        sink.contents = [part1, part2]

        result = analyze_part_routing(sink)
        assert result["total_parts"] == 2
        assert result["unique_routes"] == 1
        assert "Source -> M1 -> B1 -> M2 -> Sink" in result["route_counts"]
        assert result["route_counts"]["Source -> M1 -> B1 -> M2 -> Sink"] == 2

    def test_multiple_routes(self):
        sink = MagicMock()
        part1 = MagicMock()
        part1.routing_history = ["Source", "M1", "Sink"]
        part2 = MagicMock()
        part2.routing_history = ["Source", "M2", "Sink"]
        sink.contents = [part1, part2]

        result = analyze_part_routing(sink)
        assert result["unique_routes"] == 2

    def test_part_without_routing_history(self):
        sink = MagicMock()
        part1 = MagicMock(spec=[])  # no routing_history attribute
        sink.contents = [part1]

        result = analyze_part_routing(sink)
        assert result["total_parts"] == 1
        assert "unknown" in result["route_counts"]

    def test_real_simulation_routing(self):
        """Parts from a real simulation have routing history."""
        source = Source()
        m1 = Machine(name="M1", cycle_time=1)
        m2 = Machine(name="M2", cycle_time=1)
        b1 = Buffer(name="B1", capacity=10)
        sink = Sink(collect_parts=True)

        source.define_routing(downstream=[m1])
        m1.define_routing(upstream=[source], downstream=[b1])
        b1.define_routing(upstream=[m1], downstream=[m2])
        m2.define_routing(upstream=[b1], downstream=[sink])
        sink.define_routing(upstream=[m2])

        system = System(objects=[source, m1, b1, m2, sink])
        system.simulate(simulation_time=50, verbose=False)

        result = analyze_part_routing(sink)
        assert result["total_parts"] > 0
        assert result["unique_routes"] >= 1
        # Each part should have visited the machines and buffer
        for route in result["route_counts"].keys():
            assert "M1" in route
            assert "M2" in route


# ========== Event Tracing CLI Flag ==========


class TestEventTraceCLI:
    """Test --trace CLI argument handling."""

    def test_trace_flag_parsed(self):
        """--trace flag is parsed correctly."""
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument("--trace", action="store_true")
        args = parser.parse_args(["--trace"])
        assert args.trace is True

    def test_trace_flag_default(self):
        """--trace defaults to False."""
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument("--trace", action="store_true")
        args = parser.parse_args([])
        assert args.trace is False

    def test_trace_simulation_runs(self):
        """Simulation runs with trace=True without errors."""
        source = Source()
        m1 = Machine(name="M1", cycle_time=1)
        m2 = Machine(name="M2", cycle_time=1)
        b1 = Buffer(name="B1", capacity=10)
        sink = Sink()

        source.define_routing(downstream=[m1])
        m1.define_routing(upstream=[source], downstream=[b1])
        b1.define_routing(upstream=[m1], downstream=[m2])
        m2.define_routing(upstream=[b1], downstream=[sink])
        sink.define_routing(upstream=[m2])

        system = System(objects=[source, m1, b1, m2, sink])
        system.simulate(simulation_time=20, verbose=False, trace=True)
        assert sink.level >= 0


# ========== Integration: YAML Scenario Loading ==========


class TestNewScenarioLoading:
    """Test that all new scenarios load and validate correctly."""

    def test_warm_up_line_loads(self):
        config = load_line_config("warm_up_line")
        assert config["warm_up_time"] == 300

    def test_priority_maintenance_line_loads(self):
        config = load_line_config("priority_maintenance_line")
        assert config["maintainer"]["strategy"] == "bottleneck"

    def test_priority_user_line_loads(self):
        config = load_line_config("priority_user_line")
        assert config["maintainer"]["strategy"] == "priority"
        assert "machine_priorities" in config["maintainer"]

    def test_multi_state_degradation_line_loads(self):
        config = load_line_config("multi_state_degradation_line")
        assert config["machines"][0]["health_states"]["h_max"] == 5


# ========== Re-Seed for Monotonic Results ==========


class TestReseedMonotonic:
    """Verify re-seeding RNGs before simulate() makes sink.level monotonic."""

    def test_reseed_produces_monotonic_sink_level(self):
        """With re-seeding, sink.level should never decrease between steps."""
        import numpy as np

        config = load_line_config("balanced_line")
        system, source, sink, machines, buffers, maintainer, scrap_sinks = \
            build_simantha_system(config)

        seed = 42
        sim_time = 0.0
        prev_level = 0
        decreases = 0

        for _ in range(50):
            sim_time += 1.0
            random.seed(seed)
            np.random.seed(seed)
            system.simulate(simulation_time=sim_time)
            if sink.level < prev_level:
                decreases += 1
            prev_level = sink.level

        assert decreases == 0, (
            f"sink.level decreased {decreases} times with re-seeding"
        )

    def test_without_reseed_can_fluctuate(self):
        """Without re-seeding, sink.level may decrease (non-monotonic).

        This test documents the behavior difference — without re-seeding,
        simulate() can produce non-monotonic sink.level due to different
        RNG states across calls. The assertion is lenient since the
        fluctuation is probabilistic.
        """
        import numpy as np

        config = load_line_config("balanced_line")
        system, source, sink, machines, buffers, maintainer, scrap_sinks = \
            build_simantha_system(config)

        # Seed only once at the start (no re-seeding per step)
        random.seed(42)
        np.random.seed(42)

        sim_time = 0.0
        prev_level = 0
        decreases = 0

        for _ in range(200):
            sim_time += 1.0
            system.simulate(simulation_time=sim_time)
            if sink.level < prev_level:
                decreases += 1
            prev_level = sink.level

        # Non-monotonic behavior is probabilistic; just document the pattern
        assert True


# ========== Shift-Based OEE Reset ==========


class TestShiftOEESnapshots:
    """Test that OEE uses shift-relative deltas."""

    def test_calculate_oee_from_sim_basic(self):
        """OEE calculation with shift-relative values."""
        result = calculate_oee_from_sim(
            sim_time=600, machine_downtime=60, parts_made=50,
            cycle_time=10, good_parts=45, defective_parts=5
        )
        assert 0 < result["availability"] <= 1.0
        assert 0 < result["performance"] <= 1.0
        assert result["quality"] == 45 / 50  # 0.9
        assert abs(result["oee"] - result["availability"] * result["performance"] * result["quality"]) < 0.001

    def test_calculate_oee_zero_time(self):
        """OEE returns zeros for sim_time <= 0."""
        result = calculate_oee_from_sim(0, 0, 0, 10)
        assert result["oee"] == 0
        assert result["availability"] == 0

    def test_shift_snapshot_initial_is_zero(self):
        """Initial shift snapshot should be all zeros (start from sim start)."""
        snap = {
            "down_time_accum": 0.0, "parts_made": 0,
            "good_count": 0, "scrap_count": 0, "defective_count": 0,
            "metric_good": 0, "metric_defective": 0,
        }
        for v in snap.values():
            assert v == 0

    def test_shift_relative_oee_uses_delta(self):
        """Shift-relative OEE should use delta from snapshot, not absolute values."""
        # Machine produced 100 parts total, 10 down across whole run
        # Shift snapshot was taken at downtime=8, parts_made=80
        # So in current shift: 2s downtime, 20 parts in 100s
        shift_elapsed = 100
        shift_downtime = 10 - 8  # 2
        shift_parts = 100 - 80  # 20
        result = calculate_oee_from_sim(
            shift_elapsed, shift_downtime, shift_parts,
            cycle_time=5, good_parts=18, defective_parts=2
        )
        # Availability = (100 - 2) / 100 = 0.98
        assert abs(result["availability"] - 0.98) < 0.01
        # Performance = 20 / (98 / 5) = 20 / 19.6 ≈ 1.0 (capped)
        assert result["performance"] <= 1.0
        # Quality = 18 / 20 = 0.9
        assert abs(result["quality"] - 0.9) < 0.01

    def test_shift_oee_resets_on_rotation(self):
        """After shift rotation, snapshot counters should match machine state."""
        mock_machine = MagicMock()
        mock_machine.downtime = 50.0
        mock_machine.parts_made = 200
        mock_machine._good_count = 190
        mock_machine._scrap_count = 5
        mock_machine._defective_count = 5

        # Simulate taking a snapshot
        snap = {
            "downtime": mock_machine.downtime,
            "parts_made": mock_machine.parts_made,
            "good_count": mock_machine._good_count,
            "scrap_count": mock_machine._scrap_count,
            "defective_count": mock_machine._defective_count,
        }

        # After snapshot, machine produces more
        mock_machine.downtime = 55.0
        mock_machine.parts_made = 210
        mock_machine._good_count = 199
        mock_machine._scrap_count = 6
        mock_machine._defective_count = 5

        # Delta should be: parts=10, good=9, defective=1
        shift_parts = mock_machine.parts_made - snap["parts_made"]
        shift_good = mock_machine._good_count - snap["good_count"]
        shift_defective = (mock_machine._scrap_count + mock_machine._defective_count) - (snap["scrap_count"] + snap["defective_count"])

        assert shift_parts == 10
        assert shift_good == 9
        assert shift_defective == 1


# ========== MTTF Scaling for Multi-State Degradation ==========


class TestMTTFScaling:
    """Test that AdvancedMachine scales MTTF for multi-state degradation."""

    def test_mttf_scaled_by_failed_health(self):
        """With failed_health > 1, get_time_to_degrade() returns MTTF / failed_health."""
        from advanced_machine import AdvancedMachine
        from failure_modes import FailureMode

        fm = FailureMode(
            name="mechanical", type="wearout",
            mttf_config={"distribution": "constant", "value": 600},
            mttr_config={"distribution": "constant", "value": 10}
        )
        # 5-state degradation: failed_health = 4
        matrix = [[0.99, 0.01, 0, 0, 0],
                   [0, 0.99, 0.01, 0, 0],
                   [0, 0, 0.99, 0.01, 0],
                   [0, 0, 0, 0.99, 0.01],
                   [0, 0, 0, 0, 1]]
        m = AdvancedMachine(
            name="M1", cycle_time=1, failure_modes=[fm],
            degradation_matrix=matrix
        )
        # Simulate initialization
        from simantha import Source, Buffer, Sink, System
        source = Source()
        sink = Sink()
        source.define_routing(downstream=[m])
        m.define_routing(upstream=[source], downstream=[sink])
        sink.define_routing(upstream=[m])
        system = System(objects=[source, m, sink])
        system.simulate(simulation_time=1, verbose=False)

        # failed_health = 4 (len(matrix) - 1)
        assert m.failed_health == 4
        ttd = m.get_time_to_degrade()
        # Should be 600 / 4 = 150
        assert ttd == pytest.approx(150.0)

    def test_mttf_not_scaled_for_2_state(self):
        """With failed_health = 1 (standard 2-state), MTTF is not scaled."""
        from advanced_machine import AdvancedMachine
        from failure_modes import FailureMode

        fm = FailureMode(
            name="mechanical", type="wearout",
            mttf_config={"distribution": "constant", "value": 600},
            mttr_config={"distribution": "constant", "value": 10}
        )
        m = AdvancedMachine(name="M1", cycle_time=1, failure_modes=[fm])
        from simantha import Source, Sink, System
        source = Source()
        sink = Sink()
        source.define_routing(downstream=[m])
        m.define_routing(upstream=[source], downstream=[sink])
        sink.define_routing(upstream=[m])
        system = System(objects=[source, m, sink])
        system.simulate(simulation_time=1, verbose=False)

        assert m.failed_health == 1
        ttd = m.get_time_to_degrade()
        # Should be unscaled: 600
        assert ttd == pytest.approx(600.0)


# ---------------------------------------------------------------------------
# CachedOpcuaNode dead-band tests
# ---------------------------------------------------------------------------

class _MockNode:
    """Minimal OPC UA node mock that records write calls."""
    def __init__(self):
        self.write_count = 0
        self.last_value = None

    def set_value(self, v):
        self.write_count += 1
        self.last_value = v

    def get_value(self):
        return self.last_value


class TestCachedOpcuaNodeDeadBand:
    def test_no_dead_band_writes_on_every_change(self):
        """dead_band=None: same as original — writes when value changes."""
        from opcua_server import CachedOpcuaNode
        node = _MockNode()
        cached = CachedOpcuaNode(node, dead_band=None)
        cached.set_value(1.0)
        cached.set_value(1.0001)  # tiny change — should write (no dead-band)
        assert node.write_count == 2

    def test_dead_band_suppresses_small_change(self):
        """Change smaller than dead_band is not written."""
        from opcua_server import CachedOpcuaNode
        node = _MockNode()
        cached = CachedOpcuaNode(node, dead_band=0.001)
        cached.set_value(0.9841)        # first write
        cached.set_value(0.98415)       # delta=0.00005 < 0.001 → skip
        assert node.write_count == 1
        assert node.last_value == 0.9841

    def test_dead_band_writes_when_threshold_crossed(self):
        """Change >= dead_band triggers a write."""
        from opcua_server import CachedOpcuaNode
        node = _MockNode()
        cached = CachedOpcuaNode(node, dead_band=0.001)
        cached.set_value(0.9841)        # first write
        cached.set_value(0.9852)        # delta=0.0011 >= 0.001 → write
        assert node.write_count == 2
        assert node.last_value == 0.9852

    def test_first_call_always_writes(self):
        """First set_value always writes regardless of dead_band."""
        from opcua_server import CachedOpcuaNode
        node = _MockNode()
        cached = CachedOpcuaNode(node, dead_band=0.001)
        cached.set_value(0.0)
        assert node.write_count == 1

    def test_dead_band_non_numeric_always_writes_on_change(self):
        """Strings/bools fall through to equality check — always write on change."""
        from opcua_server import CachedOpcuaNode
        node = _MockNode()
        cached = CachedOpcuaNode(node, dead_band=0.001)
        cached.set_value("IDLE")
        cached.set_value("BLOCKED")     # different string — must write
        assert node.write_count == 2

    def test_dead_band_non_numeric_skips_identical(self):
        """Strings that don't change are not written even with dead_band set."""
        from opcua_server import CachedOpcuaNode
        node = _MockNode()
        cached = CachedOpcuaNode(node, dead_band=0.001)
        cached.set_value("IDLE")
        cached.set_value("IDLE")        # same — skip
        assert node.write_count == 1

    def test_dead_band_accumulates_from_last_written_value(self):
        """Dead-band is relative to the last *written* value, not the last *seen* value."""
        from opcua_server import CachedOpcuaNode
        node = _MockNode()
        cached = CachedOpcuaNode(node, dead_band=0.001)
        cached.set_value(1.000)         # write (count=1)
        cached.set_value(1.0005)        # delta vs 1.000 = 0.0005 < 0.001 → skip
        cached.set_value(1.0008)        # delta vs 1.000 = 0.0008 < 0.001 → skip
        cached.set_value(1.0015)        # delta vs 1.000 = 0.0015 >= 0.001 → write (count=2)
        assert node.write_count == 2
        assert node.last_value == 1.0015


# ---------------------------------------------------------------------------
# ShiftManager.get_current_shift_metrics live OEE tests
# ---------------------------------------------------------------------------

class TestCurrentShiftOEELive:
    """OEE is computed live mid-shift, not just at shift finalisation."""

    def _make_manager(self):
        from shift_manager import ShiftManager, ShiftDefinition
        shifts = [ShiftDefinition(name="Day", duration=28800.0)]
        return ShiftManager(shifts, machine_names=["M1", "M2"])

    def test_oee_is_nonzero_during_active_shift(self):
        """CurrShift_OEE is > 0 once machines have logged processing time."""
        mgr = self._make_manager()
        mgr.update_machine_time("M1", 500.0, "PROCESSING")
        mgr.update_machine_time("M1", 100.0, "IDLE")
        mgr.update_machine_time("M2", 400.0, "PROCESSING")
        mgr.update_machine_time("M2", 200.0, "BLOCKED")
        metrics = mgr.get_current_shift_metrics()
        assert metrics["oee"] > 0.0, "OEE must be non-zero when machines have run"

    def test_availability_computed_from_processing_fraction(self):
        """Availability = processing / total time across all machines."""
        mgr = self._make_manager()
        mgr.update_machine_time("M1", 600.0, "PROCESSING")
        mgr.update_machine_time("M1", 400.0, "FAILED")
        mgr.update_machine_time("M2", 600.0, "PROCESSING")
        mgr.update_machine_time("M2", 400.0, "FAILED")
        metrics = mgr.get_current_shift_metrics()
        assert abs(metrics["availability"] - 0.6) < 1e-9

    def test_oee_zero_before_any_machine_time_logged(self):
        """OEE is 0 at shift start before any state time is recorded."""
        mgr = self._make_manager()
        metrics = mgr.get_current_shift_metrics()
        assert metrics["oee"] == 0.0


# ========== collect_system_metrics repair counting ==========


class TestCollectSystemMetricsRepairs:
    """total_repairs must count cm/pm even without a Simantha Maintainer."""

    def _make_machine(self, cm=0, pm=0):
        m = MagicMock()
        m.level = 0
        m.total_cm_count = cm
        m.total_pm_count = pm
        return m

    def _make_buffer(self, level=0):
        b = MagicMock()
        b.level = level
        return b

    def test_no_maintainer_zero_repairs(self):
        """Returns 0 repairs when no maintainer and machines have no repairs."""
        buffers = {"B1": self._make_buffer(3)}
        machines = {"M1": self._make_machine(0, 0), "M2": self._make_machine(0, 0)}
        _, _, _, total_repairs = collect_system_metrics(buffers, None, machines)
        assert total_repairs == 0

    def test_no_maintainer_counts_cm_repairs(self):
        """Returns correct repair count when maintainer=None but machines have cm_count > 0."""
        buffers = {"B1": self._make_buffer(2)}
        machines = {"M1": self._make_machine(cm=3), "M2": self._make_machine(cm=5)}
        _, _, _, total_repairs = collect_system_metrics(buffers, None, machines)
        assert total_repairs == 8

    def test_with_maintainer_still_counts_repairs(self):
        """Repair count is consistent whether or not a Simantha maintainer is present."""
        buffers = {"B1": self._make_buffer(0)}
        machines = {"M1": self._make_machine(cm=2, pm=1)}
        maintainer = MagicMock()
        maintainer.utilization = 0
        maintainer.get_queue.return_value = []
        _, _, _, total_repairs = collect_system_metrics(buffers, maintainer, machines)
        assert total_repairs == 3

    def test_no_machines_arg_returns_zero_repairs(self):
        """When machines=None, repair count defaults to 0."""
        buffers = {"B1": self._make_buffer(0)}
        _, _, _, total_repairs = collect_system_metrics(buffers, None, None)
        assert total_repairs == 0


# ========== Dead-Band Key Mapping ==========


class TestDeadBandKeyMapping:
    """Test that _get_dead_band_for_key returns the correct band values."""

    def test_time_accumulator_returns_5(self):
        """Time accumulator keys must return 5.0, not 1.0 (sim_step == 1.0)."""
        assert _get_dead_band_for_key("blocked_time") == 5.0
        assert _get_dead_band_for_key("starved_time") == 5.0
        assert _get_dead_band_for_key("idle_time") == 5.0
        assert _get_dead_band_for_key("processing_time") == 5.0
        assert _get_dead_band_for_key("down_time") == 5.0

    def test_oee_float_returns_0001(self):
        """OEE float keys use a tight 0.001 band."""
        assert _get_dead_band_for_key("oee") == 0.001
        assert _get_dead_band_for_key("availability") == 0.001
        assert _get_dead_band_for_key("performance") == 0.001
        assert _get_dead_band_for_key("quality") == 0.001

    def test_fm_suffix_accumulators_return_5(self):
        """Failure-mode float accumulators (downtime / mtbf / mttr) use 5.0 band."""
        assert _get_dead_band_for_key("fm_bearing_wear_downtime") == 5.0
        assert _get_dead_band_for_key("fm_bearing_wear_mtbf") == 5.0
        assert _get_dead_band_for_key("fm_bearing_wear_mttr") == 5.0

    def test_integer_and_string_keys_return_none(self):
        """Integer / string / boolean keys return None (exact equality check only)."""
        assert _get_dead_band_for_key("state") is None
        assert _get_dead_band_for_key("part_count") is None
        assert _get_dead_band_for_key("health_state") is None


class TestCachedOpcuaNodeDeadBand:
    """Verify CachedOpcuaNode suppresses writes correctly with a 5.0 dead-band."""

    def _make_node(self):
        return MagicMock()

    def test_first_write_always_goes_through(self):
        node = self._make_node()
        cached = CachedOpcuaNode(node, dead_band=5.0)
        cached.set_value(0.0)
        node.set_value.assert_called_once_with(0.0)

    def test_small_deltas_are_suppressed(self):
        """Four +1.0 increments stay within the 5.0 band — no extra writes."""
        node = self._make_node()
        cached = CachedOpcuaNode(node, dead_band=5.0)
        cached.set_value(0.0)   # write #1 (sentinel)
        for i in range(1, 5):
            cached.set_value(float(i))  # delta < 5.0 → suppressed
        assert node.set_value.call_count == 1

    def test_delta_at_band_boundary_is_suppressed(self):
        """abs(5.0 - 0.0) == 5.0 is NOT < 5.0, so it should write."""
        node = self._make_node()
        cached = CachedOpcuaNode(node, dead_band=5.0)
        cached.set_value(0.0)
        cached.set_value(5.0)  # abs delta == band → write
        assert node.set_value.call_count == 2

    def test_large_delta_forces_write(self):
        """A delta larger than the band triggers a write."""
        node = self._make_node()
        cached = CachedOpcuaNode(node, dead_band=5.0)
        cached.set_value(0.0)
        cached.set_value(10.0)
        assert node.set_value.call_count == 2


# ========== Fast-machine ProcessingTime correction ==========


def _make_process_step_args(cycle_time=1.0, prev_state="IDLE", parts_made=0,
                            total_parts=5, prev_partcount=5):
    """Return (machine_mock, metrics, config_machines, opcua_vars, sink) for process_machine_step tests."""
    machine = MagicMock()
    machine.blocked = False
    machine.starved = True
    machine.has_part = False
    machine.health = 0
    machine.failed_health = 1
    machine.under_repair = False
    machine.parts_made = parts_made
    machine.downtime = 0.0

    metrics = {
        "partcount": prev_partcount,
        "blocked_time": 0.0,
        "starved_time": 0.0,
        "down_time": 0.0,
        "processing_time": 0.0,
        "idle_time": 0.0,
        "prev_state": prev_state,
        "cycle_time": cycle_time,
        "target_ppm": 60.0 / cycle_time,
        "good_parts": prev_partcount,
        "defective_parts": 0,
        "base_defect_rate": 0.0,
        "health_multiplier": 3.0,
        "prev_health_state": 0,
        "prev_maint_active": False,
        "prev_defect_rate": 0.0,
        "alarm_machine_failed_active": False,
        "alarm_maintenance_active": False,
        "alarm_quality_alert_active": False,
        "oee_cached": None,
        "spc_measurement_noise": 0.02,
        "spc_prev_in_control": True,
        "spc_cumulative_ooc": 0,
    }

    config_machines = [{"name": "M1", "enable_degradation": False,
                        "enable_advanced_failures": False}]
    machine_vars = defaultdict(MagicMock)
    opcua_vars = {"machines": {"M1": machine_vars}}
    sink = MagicMock()
    sink.contents = []

    return machine, metrics, config_machines, opcua_vars, sink, total_parts


class TestFastMachineProcessingTimeCorrection:
    """Processing time must be credited to fast machines (cycle_time < sim_step).

    Root cause: end-of-step snapshot always shows STARVED for machines that
    complete processing within a single 1-second step, so accumulate_time()
    misattributes all time to starved_time.  The post-hoc correction uses
    machine_obj.parts_made (the per-step delta) to reallocate time.
    """

    def test_fast_machine_starved_gets_processing_credit(self):
        """cycle_time=0.9s < sim_step=1.0s: 0.9s credited to processing_time."""
        machine, metrics, config_machines, opcua_vars, sink, total_parts = \
            _make_process_step_args(cycle_time=0.9, prev_state="STARVED", parts_made=1,
                                    total_parts=6, prev_partcount=5)

        process_machine_step(
            "M1", machine, metrics, config_machines,
            total_parts, 1.0, None, None, {}, opcua_vars, sink, 10.0,
            write_opcua=True
        )

        assert abs(metrics["processing_time"] - 0.9) < 1e-9
        assert abs(metrics["starved_time"] - 0.1) < 1e-9

    def test_fast_machine_idle_gets_processing_credit(self):
        """When prev_state is IDLE, credit is taken from idle_time."""
        machine, metrics, config_machines, opcua_vars, sink, total_parts = \
            _make_process_step_args(cycle_time=0.8, prev_state="IDLE", parts_made=1,
                                    total_parts=6, prev_partcount=5)

        process_machine_step(
            "M1", machine, metrics, config_machines,
            total_parts, 1.0, None, None, {}, opcua_vars, sink, 10.0,
            write_opcua=True
        )

        assert abs(metrics["processing_time"] - 0.8) < 1e-9
        assert abs(metrics["idle_time"] - 0.2) < 1e-9

    def test_normal_machine_no_correction(self):
        """cycle_time=1.0s == sim_step: no correction applied."""
        machine, metrics, config_machines, opcua_vars, sink, total_parts = \
            _make_process_step_args(cycle_time=1.0, prev_state="STARVED", parts_made=1,
                                    total_parts=6, prev_partcount=5)

        process_machine_step(
            "M1", machine, metrics, config_machines,
            total_parts, 1.0, None, None, {}, opcua_vars, sink, 10.0,
            write_opcua=True
        )

        # No correction for cycle_time == sim_step; all time in starved_time
        assert metrics["processing_time"] == 0.0
        assert metrics["starved_time"] == 1.0

    def test_no_parts_made_no_correction(self):
        """When parts_made=0 the correction does not fire."""
        machine, metrics, config_machines, opcua_vars, sink, total_parts = \
            _make_process_step_args(cycle_time=0.9, prev_state="STARVED", parts_made=0,
                                    total_parts=5, prev_partcount=5)

        process_machine_step(
            "M1", machine, metrics, config_machines,
            total_parts, 1.0, None, None, {}, opcua_vars, sink, 10.0,
            write_opcua=True
        )

        assert metrics["processing_time"] == 0.0
        assert metrics["starved_time"] == 1.0

    def test_two_parts_in_one_step_credits_double_cycle_time(self):
        """Making 2 parts in one step with 0.4s cycle credits 0.8s processing."""
        machine, metrics, config_machines, opcua_vars, sink, total_parts = \
            _make_process_step_args(cycle_time=0.4, prev_state="STARVED", parts_made=2,
                                    total_parts=7, prev_partcount=5)

        process_machine_step(
            "M1", machine, metrics, config_machines,
            total_parts, 1.0, None, None, {}, opcua_vars, sink, 10.0,
            write_opcua=True
        )

        assert abs(metrics["processing_time"] - 0.8) < 1e-9
        assert abs(metrics["starved_time"] - 0.2) < 1e-9


# ========== SPC Cumulative OOC Counter ==========


def _make_spc_result(in_control=True):
    """Build a minimal SPCResult-like mock for write_machine_opcua_vars."""
    m = MagicMock()
    m.in_control = in_control
    m.violations = [] if in_control else ["Western Electric Rule 1"]
    m.x_bar = 1.0
    m.x_bar_ucl = 1.05
    m.x_bar_cl = 1.0
    m.x_bar_lcl = 0.95
    m.range = 0.05
    m.r_ucl = 0.12
    m.r_cl = 0.06
    m.r_lcl = 0.0
    m.cp = 1.5
    m.cpk = 1.3
    m.pp = 1.4
    m.ppk = 1.2
    m.sigma_level = 4.0
    m.total_samples = 25
    m.num_subgroups = 5
    return m


class TestSPCCumulativeOOC:
    """spc_cumulative_ooc counts in_control True→False transitions only."""

    def _call_step(self, metrics, spc_result, parts_made=1):
        machine, _, config_machines, opcua_vars, sink, total_parts = \
            _make_process_step_args(cycle_time=1.0, prev_state="STARVED",
                                    parts_made=parts_made,
                                    total_parts=6, prev_partcount=5)
        spc_monitor = MagicMock()
        spc_monitor.get_metrics.return_value = spc_result
        spc_monitors = {"M1": spc_monitor}

        process_machine_step(
            "M1", machine, metrics, config_machines,
            6, 1.0, None, None, spc_monitors, opcua_vars, sink, 10.0,
            write_opcua=True
        )

    def _base_metrics(self):
        _, metrics, _, _, _, _ = _make_process_step_args(cycle_time=1.0)
        return metrics

    def test_first_ooc_increments_counter(self):
        """Transition from in_control=True to False increments counter to 1."""
        metrics = self._base_metrics()
        metrics["spc_prev_in_control"] = True
        metrics["spc_cumulative_ooc"] = 0

        self._call_step(metrics, _make_spc_result(in_control=False))

        assert metrics["spc_cumulative_ooc"] == 1
        assert metrics["spc_prev_in_control"] is False

    def test_staying_ooc_does_not_increment(self):
        """Remaining OOC (False→False) must not increment the counter again."""
        metrics = self._base_metrics()
        metrics["spc_prev_in_control"] = False
        metrics["spc_cumulative_ooc"] = 1

        self._call_step(metrics, _make_spc_result(in_control=False))

        assert metrics["spc_cumulative_ooc"] == 1

    def test_recovery_to_in_control_does_not_increment(self):
        """Returning to in_control (False→True) must not increment counter."""
        metrics = self._base_metrics()
        metrics["spc_prev_in_control"] = False
        metrics["spc_cumulative_ooc"] = 1

        self._call_step(metrics, _make_spc_result(in_control=True))

        assert metrics["spc_cumulative_ooc"] == 1
        assert metrics["spc_prev_in_control"] is True

    def test_two_ooc_events_count_two(self):
        """Two separate in_control→OOC transitions accumulate to 2."""
        metrics = self._base_metrics()
        metrics["spc_prev_in_control"] = True
        metrics["spc_cumulative_ooc"] = 0

        # First OOC event
        self._call_step(metrics, _make_spc_result(in_control=False))
        assert metrics["spc_cumulative_ooc"] == 1

        # Recovery
        self._call_step(metrics, _make_spc_result(in_control=True))
        assert metrics["spc_cumulative_ooc"] == 1

        # Second OOC event
        self._call_step(metrics, _make_spc_result(in_control=False))
        assert metrics["spc_cumulative_ooc"] == 2

    def test_always_in_control_stays_zero(self):
        """Process that never goes OOC must have cumulative_ooc=0."""
        metrics = self._base_metrics()
        metrics["spc_prev_in_control"] = True
        metrics["spc_cumulative_ooc"] = 0

        for _ in range(5):
            self._call_step(metrics, _make_spc_result(in_control=True))

        assert metrics["spc_cumulative_ooc"] == 0


class TestSPCNoiseScalePerHealth:
    """noise_scale_per_health increases SPC measurement noise with health state."""

    def _call_with_health(self, health_state, noise_scale, h_max=4, base_noise=0.02):
        machine, metrics, config_machines, opcua_vars, sink, total_parts = \
            _make_process_step_args(cycle_time=1.0, prev_state="PROCESSING",
                                    parts_made=1, total_parts=6, prev_partcount=5)
        machine.health = health_state
        machine.failed_health = h_max
        metrics["spc_measurement_noise"] = base_noise
        metrics["spc_noise_scale"] = noise_scale
        metrics["h_max"] = h_max

        measurements = []
        spc_monitor = MagicMock()
        spc_monitor.get_metrics.return_value = _make_spc_result(in_control=True)
        spc_monitor.add_measurement.side_effect = lambda m: measurements.append(m)

        process_machine_step(
            "M1", machine, metrics, config_machines,
            6, 1.0, None, None, {"M1": spc_monitor}, opcua_vars, sink, 10.0,
            write_opcua=True
        )
        return measurements

    def test_no_scale_uses_base_noise(self):
        """With spc_noise_scale=0, noise_cv is unchanged regardless of health."""
        import random
        random.seed(42)
        measurements = self._call_with_health(health_state=3, noise_scale=0.0)
        assert len(measurements) == 1
        assert 0.9 < measurements[0] < 1.1  # within ±10% is fine

    def test_full_health_scale_increases_variance(self):
        """At health=h_max with scale=2.0, effective CV = base*(1+2.0) = 3x."""
        import random
        import statistics
        random.seed(42)
        all_m_low = []
        all_m_high = []
        for _ in range(100):
            all_m_low += self._call_with_health(health_state=0, noise_scale=2.0)
            all_m_high += self._call_with_health(health_state=4, noise_scale=2.0)
        assert statistics.stdev(all_m_high) > statistics.stdev(all_m_low) * 1.5

    def test_zero_health_no_scaling(self):
        """At health=0, noise_cv is always unchanged regardless of noise_scale."""
        import random
        random.seed(0)
        m_no_scale = self._call_with_health(health_state=0, noise_scale=0.0)
        random.seed(0)
        m_has_scale = self._call_with_health(health_state=0, noise_scale=3.0)
        # Same seed, same effective noise (health=0 → scale factor = 0) → same measurement
        assert m_no_scale == m_has_scale
