"""Tests for Phase 14: Quality-Aware Machine Routing (Scrap & Rework)."""

import os
import sys
import random
import pytest
from unittest.mock import MagicMock, patch

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from quality_machine import (
    QualityAwareMachine,
    QualityAdvancedMachine,
    _quality_route,
    _redirect_to,
)
from simantha import Sink, Buffer, Machine
from factories import make_part, make_quality_machine


# ========== _quality_route Tests ==========


class TestQualityRouteGoodParts:
    def test_good_part_increments_good_count(self):
        """Good parts increment _good_count and don't redirect."""
        m = make_quality_machine(defect_rate=0.0)
        part = make_part()
        original_target = m.target_receiver

        _quality_route(m, part)

        assert m._good_count == 1
        assert m._scrap_count == 0
        assert m.target_receiver is original_target

    def test_zero_defect_rate_always_good(self):
        """With defect_rate=0, all parts are good."""
        m = make_quality_machine(defect_rate=0.0)
        for _ in range(100):
            part = make_part()
            m.target_receiver = MagicMock()
            _quality_route(m, part)

        assert m._good_count == 100
        assert m._scrap_count == 0


class TestQualityRouteScrap:
    def test_defective_part_routed_to_scrap(self):
        """Defective part goes to scrap sink."""
        scrap = MagicMock(spec=Sink)
        scrap.reserve_vacancy = MagicMock()
        m = make_quality_machine(defect_rate=1.0, scrap_sink=scrap)

        part = MagicMock()
        part.is_defective = False
        part.rework_count = 0

        random.seed(42)
        _quality_route(m, part)

        assert m._scrap_count == 1
        assert m.target_receiver is scrap
        assert part.scrapped is True
        assert part.scrapped_at_machine == "M1"

    def test_scrap_count_increments_per_part(self):
        """Each scrapped part increments scrap_count."""
        scrap = MagicMock(spec=Sink)
        scrap.reserve_vacancy = MagicMock()
        m = make_quality_machine(defect_rate=1.0, scrap_sink=scrap)

        for _ in range(5):
            part = MagicMock()
            part.is_defective = False
            part.rework_count = 0
            m.target_receiver = MagicMock()
            m.target_receiver.reserved_vacancy = 1
            _quality_route(m, part)

        assert m._scrap_count == 5

    def test_no_scrap_sink_defective_flows_normally(self):
        """Without scrap sink, defective parts flow normally."""
        m = make_quality_machine(defect_rate=1.0, scrap_sink=None)
        original = m.target_receiver
        part = MagicMock()
        part.is_defective = False
        part.rework_count = 0

        _quality_route(m, part)

        assert m._defective_count == 1
        assert m._scrap_count == 0
        assert m.target_receiver is original  # Not redirected

    def test_defective_part_marked_correctly(self):
        """Defective part has is_defective, failed_at_machine, defect_type set."""
        scrap = MagicMock(spec=Sink)
        scrap.reserve_vacancy = MagicMock()
        m = make_quality_machine(defect_rate=1.0, scrap_sink=scrap)

        part = MagicMock()
        part.is_defective = False
        part.rework_count = 0

        _quality_route(m, part)

        assert part.is_defective is True
        assert part.failed_at_machine == "M1"
        assert part.defect_type == "quality"


class TestQualityRouteRework:
    def test_rework_success_clears_defective(self):
        """Successful rework clears is_defective and increments good_count."""
        scrap = MagicMock(spec=Sink)
        scrap.reserve_vacancy = MagicMock()
        m = make_quality_machine(
            defect_rate=1.0, scrap_sink=scrap,
            rework_enabled=True, rework_success_rate=1.0, max_rework=3
        )
        original = m.target_receiver
        part = MagicMock()
        part.is_defective = False
        part.rework_count = 0

        _quality_route(m, part)

        assert m._rework_count == 1
        assert m._rework_success_count == 1
        assert m._good_count == 1
        assert m._scrap_count == 0
        assert part.is_defective is False
        assert m.target_receiver is original  # Not redirected to scrap

    def test_rework_failure_routes_to_scrap(self):
        """Failed rework sends part to scrap."""
        scrap = MagicMock(spec=Sink)
        scrap.reserve_vacancy = MagicMock()
        m = make_quality_machine(
            defect_rate=1.0, scrap_sink=scrap,
            rework_enabled=True, rework_success_rate=0.0, max_rework=3
        )
        part = MagicMock()
        part.is_defective = False
        part.rework_count = 0

        _quality_route(m, part)

        assert m._rework_count == 1
        assert m._rework_success_count == 0
        assert m._scrap_count == 1
        assert m.target_receiver is scrap

    def test_max_rework_exceeded_routes_to_scrap(self):
        """Part exceeding max_rework goes to scrap."""
        scrap = MagicMock(spec=Sink)
        scrap.reserve_vacancy = MagicMock()
        m = make_quality_machine(
            defect_rate=1.0, scrap_sink=scrap,
            rework_enabled=True, rework_success_rate=1.0, max_rework=2
        )
        # Part already at max rework count
        part = MagicMock()
        part.is_defective = False
        part.rework_count = 2  # Already at max

        _quality_route(m, part)

        assert m._scrap_count == 1
        assert m._rework_count == 0  # No rework attempted (at limit)
        assert m.target_receiver is scrap

    def test_rework_increments_part_rework_count(self):
        """Rework attempt increments rework_count on part."""
        scrap = MagicMock(spec=Sink)
        scrap.reserve_vacancy = MagicMock()
        m = make_quality_machine(
            defect_rate=1.0, scrap_sink=scrap,
            rework_enabled=True, rework_success_rate=1.0, max_rework=3
        )
        part = MagicMock()
        part.is_defective = False
        part.rework_count = 0

        _quality_route(m, part)

        assert part.rework_count == 1


class TestQualityRouteHealthCorrelation:
    def test_health_increases_effective_rate(self):
        """Health state 1 with multiplier increases effective defect rate."""
        scrap = MagicMock(spec=Sink)
        scrap.reserve_vacancy = MagicMock()
        m = make_quality_machine(
            defect_rate=0.02, scrap_sink=scrap,
            enable_health_correlation=True, health_multiplier=3.0
        )
        # Set health to failed state
        m.health = 1  # Failed

        # With health_state=1: effective_rate = 0.02 * (1 + 3.0 * 1) = 0.08
        # Run many trials
        random.seed(42)
        total_scrapped = 0
        for _ in range(1000):
            part = MagicMock()
            part.is_defective = False
            part.rework_count = 0
            m.target_receiver = MagicMock()
            m.target_receiver.reserved_vacancy = 1
            _quality_route(m, part)
            if m.target_receiver is scrap:
                total_scrapped += 1

        # Expected ~8% defect rate, allow tolerance
        assert total_scrapped > 50, f"Expected ~80 defects, got {total_scrapped}"
        assert total_scrapped < 120, f"Expected ~80 defects, got {total_scrapped}"

    def test_healthy_machine_lower_defect_rate(self):
        """Health state 0 gives base defect rate."""
        scrap = MagicMock(spec=Sink)
        scrap.reserve_vacancy = MagicMock()
        m = make_quality_machine(
            defect_rate=0.02, scrap_sink=scrap,
            enable_health_correlation=True, health_multiplier=3.0
        )
        m.health = 0  # Healthy

        random.seed(42)
        for _ in range(1000):
            part = MagicMock()
            part.is_defective = False
            part.rework_count = 0
            m.target_receiver = MagicMock()
            m.target_receiver.reserved_vacancy = 1
            _quality_route(m, part)

        # Expected ~2% defect rate
        assert m._scrap_count > 5
        assert m._scrap_count < 45


# ========== _redirect_to Tests ==========


class TestRedirectTo:
    def test_buffer_reservation_fixed(self):
        """Redirecting from Buffer decrements reserved_vacancy."""
        m = MagicMock()
        original_buffer = MagicMock()
        original_buffer.reserved_vacancy = 3
        m.target_receiver = original_buffer

        scrap = MagicMock(spec=Sink)
        scrap.reserve_vacancy = MagicMock()

        _redirect_to(m, scrap)

        assert original_buffer.reserved_vacancy == 2
        assert m.target_receiver is scrap
        scrap.reserve_vacancy.assert_called_once_with(1)

    def test_sink_original_no_reserved_vacancy(self):
        """Redirecting from Sink (no reserved_vacancy attr) works."""
        m = MagicMock()
        original_sink = MagicMock(spec=Sink)
        del original_sink.reserved_vacancy  # Sinks don't have this
        m.target_receiver = original_sink

        new_scrap = MagicMock(spec=Sink)
        new_scrap.reserve_vacancy = MagicMock()

        _redirect_to(m, new_scrap)

        assert m.target_receiver is new_scrap

    def test_reserved_vacancy_never_negative(self):
        """reserved_vacancy doesn't go below 0."""
        m = MagicMock()
        original_buffer = MagicMock()
        original_buffer.reserved_vacancy = 0
        m.target_receiver = original_buffer

        scrap = MagicMock(spec=Sink)
        scrap.reserve_vacancy = MagicMock()

        _redirect_to(m, scrap)

        assert original_buffer.reserved_vacancy == 0  # max(0, 0-1)


# ========== QualityAwareMachine Class Tests ==========


class TestQualityAwareMachineClass:
    def test_init_defaults(self):
        """QualityAwareMachine initializes with correct defaults."""
        m = QualityAwareMachine(name="M1", cycle_time=1)
        assert m._defect_rate == 0.0
        assert m._scrap_sink is None
        assert m._scrap_count == 0
        assert m._good_count == 0
        assert m._rework_enabled is False

    def test_init_with_params(self):
        """QualityAwareMachine accepts all quality params."""
        m = QualityAwareMachine(
            name="M1", cycle_time=2,
            defect_rate=0.1, health_multiplier=5.0,
            enable_health_correlation=True,
            rework_enabled=True, rework_success_rate=0.9, max_rework=5
        )
        assert m._defect_rate == 0.1
        assert m._health_multiplier == 5.0
        assert m._enable_health_correlation is True
        assert m._rework_enabled is True
        assert m._rework_success_rate == 0.9
        assert m._max_rework == 5

    def test_set_scrap_sink(self):
        """set_scrap_sink stores the sink reference."""
        m = QualityAwareMachine(name="M1", cycle_time=1)
        scrap = MagicMock(spec=Sink)
        m.set_scrap_sink(scrap)
        assert m._scrap_sink is scrap

    def test_is_subclass_of_machine(self):
        """QualityAwareMachine is a Machine."""
        assert issubclass(QualityAwareMachine, Machine)

    def test_with_degradation_matrix(self):
        """QualityAwareMachine works with degradation_matrix."""
        m = QualityAwareMachine(
            name="M1", cycle_time=1, defect_rate=0.05,
            degradation_matrix=[[0.99, 0.01], [0.0, 1.0]],
            cbm_threshold=1
        )
        assert m._defect_rate == 0.05
        assert m.name == "M1"


# ========== QualityAdvancedMachine Tests ==========


class TestQualityAdvancedMachine:
    def test_init(self):
        """QualityAdvancedMachine initializes with quality + failure params."""
        from failure_modes import FailureMode
        fm = FailureMode(
            name="mechanical", type="wearout",
            mttf_config={"distribution": "exponential", "mean": 100},
            mttr_config={"distribution": "exponential", "mean": 10}
        )
        m = QualityAdvancedMachine(
            name="M1", cycle_time=1,
            failure_modes=[fm],
            defect_rate=0.05
        )
        assert m._defect_rate == 0.05
        assert m._scrap_count == 0
        assert hasattr(m, 'failure_mode_manager')

    def test_set_scrap_sink(self):
        """QualityAdvancedMachine has set_scrap_sink."""
        from failure_modes import FailureMode
        fm = FailureMode(
            name="mechanical", type="wearout",
            mttf_config={"distribution": "exponential", "mean": 100},
            mttr_config={"distribution": "exponential", "mean": 10}
        )
        m = QualityAdvancedMachine(
            name="M1", cycle_time=1, failure_modes=[fm], defect_rate=0.05
        )
        scrap = MagicMock(spec=Sink)
        m.set_scrap_sink(scrap)
        assert m._scrap_sink is scrap


# ========== Config Loading Tests ==========


class TestScrapLineScenarioLoads:
    def test_scrap_line_loads(self):
        """scrap_line scenario loads and validates."""
        from config_loader import load_line_config
        config = load_line_config("scrap_line")
        assert len(config["machines"]) == 2
        assert "scrap_sinks" in config
        assert len(config["scrap_sinks"]) == 2

    def test_rework_line_loads(self):
        """rework_line scenario loads and validates."""
        from config_loader import load_line_config
        config = load_line_config("rework_line")
        assert len(config["machines"]) == 2
        assert config["machines"][0]["quality_routing"]["mode"] == "scrap_and_rework"

    def test_balanced_line_still_loads(self):
        """Existing balanced_line scenario still loads (backward compat)."""
        from config_loader import load_line_config
        config = load_line_config("balanced_line")
        assert len(config["machines"]) == 2
        assert "scrap_sinks" not in config


# ========== Build System Tests ==========


class TestBuildSystemWithScrap:
    def test_scrap_sinks_created(self):
        """build_simantha_system creates scrap sinks from config."""
        from config_loader import load_line_config
        from opcua_server import build_simantha_system
        config = load_line_config("scrap_line")
        _, _, _, machines, _, _, scrap_sinks = build_simantha_system(config)
        assert "ScrapBin1" in scrap_sinks
        assert "ScrapBin2" in scrap_sinks

    def test_machines_are_quality_aware(self):
        """Machines with quality_routing become QualityAwareMachine."""
        from config_loader import load_line_config
        from opcua_server import build_simantha_system
        config = load_line_config("scrap_line")
        _, _, _, machines, _, _, _ = build_simantha_system(config)
        assert isinstance(machines["M1"], QualityAwareMachine)
        assert isinstance(machines["M2"], QualityAwareMachine)

    def test_scrap_sink_wired_to_machine(self):
        """Scrap sinks are connected to machine._scrap_sink."""
        from config_loader import load_line_config
        from opcua_server import build_simantha_system
        config = load_line_config("scrap_line")
        _, _, _, machines, _, _, scrap_sinks = build_simantha_system(config)
        assert machines["M1"]._scrap_sink is scrap_sinks["ScrapBin1"]
        assert machines["M2"]._scrap_sink is scrap_sinks["ScrapBin2"]

    def test_scrap_sink_not_in_downstream(self):
        """Scrap sinks are NOT in machine.downstream list."""
        from config_loader import load_line_config
        from opcua_server import build_simantha_system
        config = load_line_config("scrap_line")
        _, _, _, machines, _, _, scrap_sinks = build_simantha_system(config)
        for scrap_sink in scrap_sinks.values():
            assert scrap_sink not in machines["M1"].downstream
            assert scrap_sink not in machines["M2"].downstream

    def test_backward_compat_no_scrap(self):
        """balanced_line returns empty scrap_sinks dict."""
        from config_loader import load_line_config
        from opcua_server import build_simantha_system
        config = load_line_config("balanced_line")
        _, _, _, _, _, _, scrap_sinks = build_simantha_system(config)
        assert scrap_sinks == {}
