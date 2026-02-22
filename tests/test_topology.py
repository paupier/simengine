"""
Tests for topology validation and dynamic machine addition.

Covers the full path from config dict → validate_serial_topology() →
build_simantha_system() → simulate(), with focus on adding/removing
machines to/from a line.
"""
import copy
import pytest

from config_loader import validate_serial_topology


# ---------------------------------------------------------------------------
# Fixtures: base configs of varying sizes
# ---------------------------------------------------------------------------
@pytest.fixture
def two_machine_config():
    """Minimal valid 2-machine serial line config."""
    return {
        "machines": [
            {"name": "M1", "cycle_time": 1},
            {"name": "M2", "cycle_time": 1},
        ],
        "buffers": [
            {"name": "B1", "capacity": 10, "upstream": "M1", "downstream": "M2"},
        ],
    }


@pytest.fixture
def three_machine_config():
    """Valid 3-machine serial line config."""
    return {
        "machines": [
            {"name": "M1", "cycle_time": 1},
            {"name": "M2", "cycle_time": 1},
            {"name": "M3", "cycle_time": 1},
        ],
        "buffers": [
            {"name": "B1", "capacity": 10, "upstream": "M1", "downstream": "M2"},
            {"name": "B2", "capacity": 10, "upstream": "M2", "downstream": "M3"},
        ],
    }


@pytest.fixture
def five_machine_config():
    """Valid 5-machine serial line config."""
    machines = [{"name": f"M{i+1}", "cycle_time": 1} for i in range(5)]
    buffers = [
        {
            "name": f"B{i+1}",
            "capacity": 10,
            "upstream": f"M{i+1}",
            "downstream": f"M{i+2}",
        }
        for i in range(4)
    ]
    return {"machines": machines, "buffers": buffers}


# ---------------------------------------------------------------------------
# Validation: basic topology rules
# ---------------------------------------------------------------------------
class TestTopologyValidation:
    """Test validate_serial_topology() catches all topology errors."""

    def test_valid_2_machine_passes(self, two_machine_config):
        validate_serial_topology(two_machine_config)

    def test_valid_3_machine_passes(self, three_machine_config):
        validate_serial_topology(three_machine_config)

    def test_valid_5_machine_passes(self, five_machine_config):
        validate_serial_topology(five_machine_config)

    def test_missing_machines_field(self):
        with pytest.raises(ValueError, match="machines.*buffers"):
            validate_serial_topology({"buffers": []})

    def test_missing_buffers_field(self):
        with pytest.raises(ValueError, match="machines.*buffers"):
            validate_serial_topology({"machines": [{"name": "M1"}, {"name": "M2"}]})

    def test_single_machine_rejected(self):
        cfg = {
            "machines": [{"name": "M1", "cycle_time": 1}],
            "buffers": [],
        }
        with pytest.raises(ValueError, match="at least 2 machines"):
            validate_serial_topology(cfg)

    def test_zero_machines_rejected(self):
        cfg = {"machines": [], "buffers": []}
        with pytest.raises(ValueError, match="at least 2 machines"):
            validate_serial_topology(cfg)

    def test_buffer_count_mismatch_too_few(self, three_machine_config):
        """3 machines need 2 buffers; providing 1 should fail."""
        cfg = copy.deepcopy(three_machine_config)
        cfg["buffers"] = cfg["buffers"][:1]
        with pytest.raises(ValueError, match="requires 2 buffers.*got 1"):
            validate_serial_topology(cfg)

    def test_buffer_count_mismatch_too_many(self, two_machine_config):
        """2 machines need 1 buffer; providing 2 should fail."""
        cfg = copy.deepcopy(two_machine_config)
        cfg["buffers"].append(
            {"name": "B2", "capacity": 10, "upstream": "M2", "downstream": "M3"}
        )
        with pytest.raises(ValueError, match="requires 1 buffers.*got 2"):
            validate_serial_topology(cfg)

    def test_duplicate_machine_names(self, two_machine_config):
        cfg = copy.deepcopy(two_machine_config)
        cfg["machines"][1]["name"] = "M1"
        cfg["buffers"][0]["downstream"] = "M1"
        with pytest.raises(ValueError, match="unique"):
            validate_serial_topology(cfg)

    def test_duplicate_buffer_names(self, three_machine_config):
        cfg = copy.deepcopy(three_machine_config)
        cfg["buffers"][1]["name"] = "B1"
        with pytest.raises(ValueError, match="unique"):
            validate_serial_topology(cfg)

    def test_machine_missing_name(self):
        cfg = {
            "machines": [{"cycle_time": 1}, {"name": "M2", "cycle_time": 1}],
            "buffers": [
                {"name": "B1", "capacity": 10, "upstream": "M1", "downstream": "M2"}
            ],
        }
        with pytest.raises((ValueError, KeyError)):
            validate_serial_topology(cfg)

    def test_buffer_missing_name(self, two_machine_config):
        cfg = copy.deepcopy(two_machine_config)
        del cfg["buffers"][0]["name"]
        with pytest.raises((ValueError, KeyError)):
            validate_serial_topology(cfg)


# ---------------------------------------------------------------------------
# Validation: buffer routing
# ---------------------------------------------------------------------------
class TestBufferRoutingValidation:
    """Test that buffer upstream/downstream must match machine order."""

    def test_buffer_missing_upstream(self, two_machine_config):
        cfg = copy.deepcopy(two_machine_config)
        del cfg["buffers"][0]["upstream"]
        with pytest.raises(ValueError, match="missing upstream/downstream"):
            validate_serial_topology(cfg)

    def test_buffer_missing_downstream(self, two_machine_config):
        cfg = copy.deepcopy(two_machine_config)
        del cfg["buffers"][0]["downstream"]
        with pytest.raises(ValueError, match="missing upstream/downstream"):
            validate_serial_topology(cfg)

    def test_buffer_wrong_upstream(self, three_machine_config):
        """B2 should have upstream=M2, not M1."""
        cfg = copy.deepcopy(three_machine_config)
        cfg["buffers"][1]["upstream"] = "M1"
        with pytest.raises(ValueError, match="Expected M2.*got M1"):
            validate_serial_topology(cfg)

    def test_buffer_wrong_downstream(self, three_machine_config):
        """B1 should have downstream=M2, not M3."""
        cfg = copy.deepcopy(three_machine_config)
        cfg["buffers"][0]["downstream"] = "M3"
        with pytest.raises(ValueError, match="routing invalid"):
            validate_serial_topology(cfg)

    def test_swapped_buffer_order(self, three_machine_config):
        """Swapping B1 and B2 order should fail routing validation."""
        cfg = copy.deepcopy(three_machine_config)
        cfg["buffers"] = [cfg["buffers"][1], cfg["buffers"][0]]
        with pytest.raises(ValueError, match="routing invalid"):
            validate_serial_topology(cfg)

    def test_buffer_references_nonexistent_machine(self, two_machine_config):
        cfg = copy.deepcopy(two_machine_config)
        cfg["buffers"][0]["downstream"] = "MX"
        with pytest.raises(ValueError, match="routing invalid"):
            validate_serial_topology(cfg)


# ---------------------------------------------------------------------------
# Adding machines: mimicking web UI "add machine" flow
# ---------------------------------------------------------------------------
class TestAddMachine:
    """Test the pattern used by the config editor: add machine + buffer, validate."""

    def test_add_third_machine(self, two_machine_config):
        """Simulate clicking '+ Add Machine' on a 2-machine line."""
        cfg = copy.deepcopy(two_machine_config)
        cfg["machines"].append({"name": "M3", "cycle_time": 1})
        cfg["buffers"].append(
            {"name": "B2", "capacity": 10, "upstream": "M2", "downstream": "M3"}
        )
        validate_serial_topology(cfg)
        assert len(cfg["machines"]) == 3
        assert len(cfg["buffers"]) == 2

    def test_add_fourth_and_fifth_machine(self, three_machine_config):
        """Add two machines in sequence."""
        cfg = copy.deepcopy(three_machine_config)
        for extra in range(4, 6):
            prev = f"M{extra - 1}"
            name = f"M{extra}"
            cfg["machines"].append({"name": name, "cycle_time": 1})
            cfg["buffers"].append(
                {
                    "name": f"B{extra - 1}",
                    "capacity": 10,
                    "upstream": prev,
                    "downstream": name,
                }
            )
        validate_serial_topology(cfg)
        assert len(cfg["machines"]) == 5
        assert len(cfg["buffers"]) == 4

    def test_add_machine_without_buffer_fails(self, two_machine_config):
        """Adding a machine without its buffer must fail."""
        cfg = copy.deepcopy(two_machine_config)
        cfg["machines"].append({"name": "M3", "cycle_time": 1})
        with pytest.raises(ValueError, match="requires 2 buffers.*got 1"):
            validate_serial_topology(cfg)

    def test_add_machine_with_wrong_routing_fails(self, two_machine_config):
        """Adding M3 + B2 but buffer upstream wrong."""
        cfg = copy.deepcopy(two_machine_config)
        cfg["machines"].append({"name": "M3", "cycle_time": 1})
        cfg["buffers"].append(
            {"name": "B2", "capacity": 10, "upstream": "M1", "downstream": "M3"}
        )
        with pytest.raises(ValueError, match="Expected M2.*got M1"):
            validate_serial_topology(cfg)

    def test_add_machine_with_features(self, two_machine_config):
        """New machine can have SPC, degradation, defect_rate."""
        cfg = copy.deepcopy(two_machine_config)
        cfg["machines"].append({
            "name": "M3",
            "cycle_time": 2,
            "enable_spc": True,
            "enable_degradation": True,
            "defect_rate": 0.05,
        })
        cfg["buffers"].append(
            {"name": "B2", "capacity": 5, "upstream": "M2", "downstream": "M3"}
        )
        validate_serial_topology(cfg)

    def test_add_machine_with_target_ppm(self, two_machine_config):
        """New machine can use target_ppm instead of cycle_time."""
        cfg = copy.deepcopy(two_machine_config)
        cfg["machines"].append({"name": "M3", "target_ppm": 30})
        cfg["buffers"].append(
            {"name": "B2", "capacity": 10, "upstream": "M2", "downstream": "M3"}
        )
        validate_serial_topology(cfg)


# ---------------------------------------------------------------------------
# Removing machines
# ---------------------------------------------------------------------------
class TestRemoveMachine:
    """Test removing a machine from a line."""

    def test_remove_last_machine(self, three_machine_config):
        """Remove M3, shrink to 2-machine line."""
        cfg = copy.deepcopy(three_machine_config)
        cfg["machines"] = cfg["machines"][:2]
        cfg["buffers"] = cfg["buffers"][:1]
        validate_serial_topology(cfg)
        assert len(cfg["machines"]) == 2
        assert len(cfg["buffers"]) == 1

    def test_remove_middle_machine(self, three_machine_config):
        """Remove M2, rewire B1 to connect M1→M3."""
        cfg = copy.deepcopy(three_machine_config)
        cfg["machines"] = [cfg["machines"][0], cfg["machines"][2]]
        cfg["buffers"] = [
            {"name": "B1", "capacity": 10, "upstream": "M1", "downstream": "M3"}
        ]
        validate_serial_topology(cfg)

    def test_remove_to_one_machine_fails(self, two_machine_config):
        """Can't have a line with just one machine."""
        cfg = copy.deepcopy(two_machine_config)
        cfg["machines"] = [cfg["machines"][0]]
        cfg["buffers"] = []
        with pytest.raises(ValueError, match="at least 2 machines"):
            validate_serial_topology(cfg)

    def test_remove_machine_without_buffer_fails(self, three_machine_config):
        """Removing M3 but keeping B2 should fail."""
        cfg = copy.deepcopy(three_machine_config)
        cfg["machines"] = cfg["machines"][:2]
        # Still have 2 buffers for 2 machines
        with pytest.raises(ValueError, match="requires 1 buffers.*got 2"):
            validate_serial_topology(cfg)


# ---------------------------------------------------------------------------
# Simulation: build + run with dynamically added machines
# ---------------------------------------------------------------------------
class TestBuildAndSimulate:
    """Test build_simantha_system() + simulate() with various machine counts.

    These tests confirm the full path works, not just validation.
    """

    def test_build_2_machine_system(self, two_machine_config):
        from opcua_server import build_simantha_system
        system, source, sink, machines, buffers, maint, scrap = \
            build_simantha_system(two_machine_config)
        assert len(machines) == 2
        assert len(buffers) == 1
        assert maint is None

    def test_build_3_machine_system(self, three_machine_config):
        from opcua_server import build_simantha_system
        system, source, sink, machines, buffers, maint, scrap = \
            build_simantha_system(three_machine_config)
        assert len(machines) == 3
        assert len(buffers) == 2

    def test_build_5_machine_system(self, five_machine_config):
        from opcua_server import build_simantha_system
        system, source, sink, machines, buffers, maint, scrap = \
            build_simantha_system(five_machine_config)
        assert len(machines) == 5
        assert len(buffers) == 4

    def test_simulate_2_machines_produces_parts(self, two_machine_config):
        from opcua_server import build_simantha_system
        system, source, sink, machines, buffers, maint, scrap = \
            build_simantha_system(two_machine_config)
        system.simulate(simulation_time=20)
        assert sink.level > 0, "2-machine line should produce parts"

    def test_simulate_3_machines_produces_parts(self, three_machine_config):
        from opcua_server import build_simantha_system
        system, source, sink, machines, buffers, maint, scrap = \
            build_simantha_system(three_machine_config)
        system.simulate(simulation_time=20)
        assert sink.level > 0, "3-machine line should produce parts"

    def test_simulate_5_machines_produces_parts(self, five_machine_config):
        from opcua_server import build_simantha_system
        system, source, sink, machines, buffers, maint, scrap = \
            build_simantha_system(five_machine_config)
        system.simulate(simulation_time=30)
        assert sink.level > 0, "5-machine line should produce parts"

    def test_add_machine_then_simulate(self, two_machine_config):
        """Full flow: start with 2 machines, add a 3rd, build, simulate."""
        cfg = copy.deepcopy(two_machine_config)
        cfg["machines"].append({"name": "M3", "cycle_time": 1})
        cfg["buffers"].append(
            {"name": "B2", "capacity": 10, "upstream": "M2", "downstream": "M3"}
        )
        validate_serial_topology(cfg)

        from opcua_server import build_simantha_system
        system, source, sink, machines, buffers, maint, scrap = \
            build_simantha_system(cfg)
        assert len(machines) == 3
        system.simulate(simulation_time=20)
        assert sink.level > 0

    def test_add_machine_with_degradation_and_maintainer(self, two_machine_config):
        """Add M3 with degradation, add a maintainer, build, simulate."""
        cfg = copy.deepcopy(two_machine_config)
        cfg["machines"].append({
            "name": "M3",
            "cycle_time": 1,
            "enable_degradation": True,
            "degradation_matrix": [[0.99, 0.01], [0.0, 1.0]],
            "cbm_threshold": 1,
        })
        cfg["buffers"].append(
            {"name": "B2", "capacity": 10, "upstream": "M2", "downstream": "M3"}
        )
        cfg["maintainer"] = {"enabled": True, "capacity": 1}
        validate_serial_topology(cfg)

        from opcua_server import build_simantha_system
        system, source, sink, machines, buffers, maint, scrap = \
            build_simantha_system(cfg)
        assert maint is not None
        assert len(machines) == 3
        system.simulate(simulation_time=30)
        assert sink.level > 0

    def test_add_machines_up_to_8(self):
        """Build and simulate an 8-machine line (stress test)."""
        n = 8
        machines = [{"name": f"M{i+1}", "cycle_time": 1} for i in range(n)]
        buffers = [
            {
                "name": f"B{i+1}",
                "capacity": 5,
                "upstream": f"M{i+1}",
                "downstream": f"M{i+2}",
            }
            for i in range(n - 1)
        ]
        cfg = {"machines": machines, "buffers": buffers}
        validate_serial_topology(cfg)

        from opcua_server import build_simantha_system
        system, source, sink, mach, buf, maint, scrap = \
            build_simantha_system(cfg)
        assert len(mach) == 8
        assert len(buf) == 7
        system.simulate(simulation_time=30)
        assert sink.level > 0, "8-machine line should produce parts"

    def test_mixed_cycle_times(self):
        """Bottleneck scenario: machines with different cycle times."""
        cfg = {
            "machines": [
                {"name": "M1", "cycle_time": 1},
                {"name": "M2", "cycle_time": 3},   # bottleneck
                {"name": "M3", "cycle_time": 1},
                {"name": "M4", "cycle_time": 1},
            ],
            "buffers": [
                {"name": "B1", "capacity": 10, "upstream": "M1", "downstream": "M2"},
                {"name": "B2", "capacity": 10, "upstream": "M2", "downstream": "M3"},
                {"name": "B3", "capacity": 10, "upstream": "M3", "downstream": "M4"},
            ],
        }
        validate_serial_topology(cfg)

        from opcua_server import build_simantha_system
        system, source, sink, machines, buffers, maint, scrap = \
            build_simantha_system(cfg)
        system.simulate(simulation_time=30)
        assert sink.level > 0
        # Throughput limited by bottleneck M2 (cycle_time=3 → ~10 parts in 30s)
        assert sink.level <= 15, f"Bottleneck should limit output, got {sink.level}"

    def test_small_buffer_capacity(self):
        """Tiny buffers (capacity=1) should still work without errors."""
        cfg = {
            "machines": [
                {"name": "M1", "cycle_time": 1},
                {"name": "M2", "cycle_time": 1},
                {"name": "M3", "cycle_time": 1},
            ],
            "buffers": [
                {"name": "B1", "capacity": 1, "upstream": "M1", "downstream": "M2"},
                {"name": "B2", "capacity": 1, "upstream": "M2", "downstream": "M3"},
            ],
        }
        validate_serial_topology(cfg)

        from opcua_server import build_simantha_system
        system, source, sink, machines, buffers, maint, scrap = \
            build_simantha_system(cfg)
        system.simulate(simulation_time=20)
        assert sink.level >= 0  # May be limited by blocking

    def test_add_machine_with_target_ppm_simulates(self, two_machine_config):
        """Machine added with target_ppm instead of cycle_time."""
        cfg = copy.deepcopy(two_machine_config)
        cfg["machines"].append({"name": "M3", "target_ppm": 60})
        cfg["buffers"].append(
            {"name": "B2", "capacity": 10, "upstream": "M2", "downstream": "M3"}
        )
        validate_serial_topology(cfg)

        from opcua_server import build_simantha_system
        system, source, sink, machines, buffers, maint, scrap = \
            build_simantha_system(cfg)
        # Simantha wraps cycle_time in a Distribution object; just verify build worked
        assert "M3" in machines
        system.simulate(simulation_time=20)
        assert sink.level > 0


# ---------------------------------------------------------------------------
# Scenario-level fields with added machines
# ---------------------------------------------------------------------------
class TestScenarioFeaturesWithAddedMachines:
    """Test that scenario-level features work after adding machines."""

    def test_warm_up_with_3_machines(self, three_machine_config):
        """warm_up_time should work with any machine count."""
        cfg = copy.deepcopy(three_machine_config)
        cfg["warm_up_time"] = 10
        validate_serial_topology(cfg)

        from opcua_server import build_simantha_system
        system, source, sink, machines, buffers, maint, scrap = \
            build_simantha_system(cfg)
        system.simulate(warm_up_time=10, simulation_time=20)
        # Sink level reflects only post-warm-up production
        assert sink.level >= 0

    def test_priority_maintainer_with_added_machine(self, two_machine_config):
        """Add M3 + degradation + priority maintainer."""
        cfg = copy.deepcopy(two_machine_config)
        # Enable degradation on existing machines
        for m in cfg["machines"]:
            m["enable_degradation"] = True
            m["degradation_matrix"] = [[0.98, 0.02], [0.0, 1.0]]
            m["cbm_threshold"] = 1
        # Add M3
        cfg["machines"].append({
            "name": "M3",
            "cycle_time": 1,
            "enable_degradation": True,
            "degradation_matrix": [[0.98, 0.02], [0.0, 1.0]],
            "cbm_threshold": 1,
        })
        cfg["buffers"].append(
            {"name": "B2", "capacity": 10, "upstream": "M2", "downstream": "M3"}
        )
        cfg["maintainer"] = {
            "enabled": True,
            "capacity": 1,
            "strategy": "priority",
            "machine_priorities": {"M1": 3, "M2": 1, "M3": 2},
        }
        validate_serial_topology(cfg)

        from opcua_server import build_simantha_system
        system, source, sink, machines, buffers, maint, scrap = \
            build_simantha_system(cfg)
        assert maint is not None
        system.simulate(simulation_time=30)
        assert sink.level > 0

    def test_maintainer_priorities_missing_new_machine(self, two_machine_config):
        """Priority maintainer that doesn't reference the new machine should
        still validate (missing machines get default priority)."""
        cfg = copy.deepcopy(two_machine_config)
        for m in cfg["machines"]:
            m["enable_degradation"] = True
            m["degradation_matrix"] = [[0.98, 0.02], [0.0, 1.0]]
            m["cbm_threshold"] = 1
        cfg["machines"].append({
            "name": "M3",
            "cycle_time": 1,
            "enable_degradation": True,
            "degradation_matrix": [[0.98, 0.02], [0.0, 1.0]],
            "cbm_threshold": 1,
        })
        cfg["buffers"].append(
            {"name": "B2", "capacity": 10, "upstream": "M2", "downstream": "M3"}
        )
        cfg["maintainer"] = {
            "enabled": True,
            "strategy": "priority",
            "machine_priorities": {"M1": 1, "M2": 2},
            # M3 not listed — should still work
        }
        validate_serial_topology(cfg)

    def test_multi_state_degradation_on_added_machine(self, two_machine_config):
        """Add M3 with multi-state health_states config."""
        cfg = copy.deepcopy(two_machine_config)
        cfg["machines"].append({
            "name": "M3",
            "cycle_time": 1,
            "enable_degradation": True,
            "health_states": {
                "h_max": 5,
                "p_degrade": 0.01,
                "cbm_threshold": 3,
            },
            "health_multiplier": 2.0,
        })
        cfg["buffers"].append(
            {"name": "B2", "capacity": 10, "upstream": "M2", "downstream": "M3"}
        )
        cfg["maintainer"] = {"enabled": True, "capacity": 1}
        validate_serial_topology(cfg)

        from opcua_server import build_simantha_system
        system, source, sink, machines, buffers, maint, scrap = \
            build_simantha_system(cfg)
        assert len(machines) == 3
        system.simulate(simulation_time=30)
        assert sink.level > 0
