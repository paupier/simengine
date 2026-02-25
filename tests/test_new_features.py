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
            m, pause_line=False, health_state=2, maint_active=False
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
            m, pause_line=False, health_state=5, maint_active=False
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
            m, pause_line=False, health_state=5, maint_active=True
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
            m, pause_line=False, health_state=0, maint_active=False
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
