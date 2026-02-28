"""Tests for the dynamic Telegraf config generator (ISA-95 aligned)."""
import os
import sys

# Add docker/telegraf to path so we can import the generator
_test_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_test_dir)
sys.path.insert(0, os.path.join(_project_root, "docker", "telegraf"))

from generate_telegraf_conf import generate_telegraf_conf, _equip_prefix  # noqa: E402
import pytest  # noqa: E402

# Default ISA-95 equipment prefix (matches build_opcua_server defaults)
EP = "WeylandIndustries.LV426_Colony.AtmosphereProcessor01.Nostromo_BioProductPakaging_Equipment"


# ---------------------------------------------------------------------------
# Fixtures: scenario configs
# ---------------------------------------------------------------------------
@pytest.fixture
def balanced_line_config():
    """Simple 3-machine line, no optional features."""
    return {
        "machines": [
            {"name": "M1", "cycle_time": 1.0},
            {"name": "M2", "cycle_time": 1.0},
            {"name": "M3", "cycle_time": 1.0},
        ],
        "buffers": [
            {"name": "B1", "capacity": 10, "upstream": "M1", "downstream": "M2"},
            {"name": "B2", "capacity": 10, "upstream": "M2", "downstream": "M3"},
        ],
    }


@pytest.fixture
def full_feature_2machine_config():
    """2-machine line with all features (mirrors full_feature_line)."""
    return {
        "machines": [
            {
                "name": "M1",
                "cycle_time": 1,
                "enable_spc": True,
                "spc": {"characteristic": "cycle_time", "subgroup_size": 5},
                "enable_degradation": True,
                "enable_advanced_failures": True,
                "failure_modes": [
                    {"name": "mechanical", "type": "wearout",
                     "mttf": {"distribution": "weibull", "shape": 2.5, "scale": 800},
                     "mttr": {"distribution": "lognormal", "mean": 15, "std": 5}},
                    {"name": "electrical", "type": "random",
                     "mttf": {"distribution": "exponential", "mean": 1200},
                     "mttr": {"distribution": "lognormal", "mean": 10, "std": 3}},
                ],
                "quality_routing": {
                    "enabled": True, "mode": "scrap_and_rework",
                    "defect_rate": 0.05, "scrap_sink": "ScrapBin1",
                },
            },
            {
                "name": "M2",
                "cycle_time": 1,
                "enable_spc": True,
                "spc": {"characteristic": "cycle_time", "subgroup_size": 5},
                "enable_advanced_failures": True,
                "failure_modes": [
                    {"name": "mechanical", "type": "wearout",
                     "mttf": {"distribution": "weibull", "shape": 2.5, "scale": 800},
                     "mttr": {"distribution": "lognormal", "mean": 15, "std": 5}},
                    {"name": "electrical", "type": "random",
                     "mttf": {"distribution": "exponential", "mean": 1200},
                     "mttr": {"distribution": "lognormal", "mean": 10, "std": 3}},
                ],
                "quality_routing": {
                    "enabled": True, "mode": "scrap",
                    "defect_rate": 0.02, "scrap_sink": "ScrapBin2",
                },
            },
        ],
        "buffers": [
            {"name": "B1", "capacity": 10, "upstream": "M1", "downstream": "M2"},
        ],
        "maintainer": {"enabled": True, "capacity": 1},
        "shifts": {
            "schedule": [
                {"name": "Day Shift", "duration": 28800, "start_offset": 0},
                {"name": "Evening Shift", "duration": 28800, "start_offset": 28800},
                {"name": "Night Shift", "duration": 28800, "start_offset": 57600},
            ]
        },
        "scrap_sinks": [
            {"name": "ScrapBin1"},
            {"name": "ScrapBin2"},
        ],
    }


@pytest.fixture
def eight_machine_config():
    """8-machine line with all features."""
    machines = []
    for i in range(1, 9):
        machines.append({
            "name": f"M{i}",
            "cycle_time": 1.0,
            "enable_spc": True,
            "spc": {"characteristic": "cycle_time", "subgroup_size": 5},
            "enable_degradation": True,
            "health_states": {"h_max": 4, "p_degrade": 0.01, "cbm_threshold": 2},
            "enable_advanced_failures": True,
            "failure_modes": [
                {"name": "mechanical", "type": "wearout",
                 "mttf": {"distribution": "weibull", "shape": 2.5, "scale": 800},
                 "mttr": {"distribution": "lognormal", "mean": 15, "std": 5}},
                {"name": "electrical", "type": "random",
                 "mttf": {"distribution": "exponential", "mean": 1200},
                 "mttr": {"distribution": "lognormal", "mean": 10, "std": 3}},
            ],
            "quality_routing": {
                "enabled": True, "mode": "scrap",
                "defect_rate": 0.03, "scrap_sink": f"ScrapBin{i}",
            },
        })

    buffers = []
    for i in range(1, 8):
        buffers.append({
            "name": f"B{i}", "capacity": 10,
            "upstream": f"M{i}", "downstream": f"M{i+1}",
        })

    return {
        "machines": machines,
        "buffers": buffers,
        "maintainer": {"enabled": True, "capacity": 2, "strategy": "bottleneck"},
        "shifts": {
            "schedule": [
                {"name": "Day Shift", "duration": 28800, "start_offset": 0},
                {"name": "Evening Shift", "duration": 28800, "start_offset": 28800},
                {"name": "Night Shift", "duration": 28800, "start_offset": 57600},
            ]
        },
        "scrap_sinks": [{"name": f"ScrapBin{i}"} for i in range(1, 9)],
        "warm_up_time": 600,
    }


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------
def _count_nodes(conf_text):
    """Count the number of node entries in a generated config."""
    return conf_text.count("{name=")


def _extract_identifiers(conf_text):
    """Extract all identifier values from node entries."""
    import re
    return re.findall(r'identifier="([^"]+)"', conf_text)


# ---------------------------------------------------------------------------
# Tests: basic generation
# ---------------------------------------------------------------------------
class TestBasicGeneration:
    def test_generates_valid_toml_structure(self, balanced_line_config):
        conf = generate_telegraf_conf(balanced_line_config)
        assert "[agent]" in conf
        assert "[[outputs.influxdb_v2]]" in conf
        assert "[[inputs.opcua]]" in conf
        assert "nodes = [" in conf

    def test_default_endpoints(self, balanced_line_config):
        conf = generate_telegraf_conf(balanced_line_config)
        assert 'opc.tcp://simantha:4840/simantha/' in conf
        assert 'http://influxdb:8086' in conf
        assert 'simantha-dev-token' in conf

    def test_custom_endpoints(self, balanced_line_config):
        conf = generate_telegraf_conf(
            balanced_line_config,
            opcua_endpoint="opc.tcp://localhost:4840/simantha/",
            influxdb_url="http://localhost:8086",
            influxdb_token="my-token",
            influxdb_org="my-org",
            influxdb_bucket="my-bucket",
        )
        assert 'opc.tcp://localhost:4840/simantha/' in conf
        assert 'http://localhost:8086' in conf
        assert 'my-token' in conf
        assert 'my-org' in conf
        assert 'my-bucket' in conf

    def test_header_comment_shows_counts(self, balanced_line_config):
        conf = generate_telegraf_conf(balanced_line_config)
        assert "3 machines" in conf
        assert "2 buffers" in conf
        assert "0 scrap sinks" in conf

    def test_isa95_comment_present(self, balanced_line_config):
        conf = generate_telegraf_conf(balanced_line_config)
        assert "ISA-95" in conf


# ---------------------------------------------------------------------------
# Tests: ISA-95 hierarchy
# ---------------------------------------------------------------------------
class TestISA95Hierarchy:
    def test_equip_prefix_default(self):
        config = {"machines": [], "buffers": []}
        assert _equip_prefix(config) == EP

    def test_equip_prefix_custom(self):
        config = {
            "enterprise": "AcmeCorp",
            "site": "PlantA",
            "area": "ShopFloor1",
            "line_name": "AssemblyLine",
            "machines": [], "buffers": [],
        }
        assert _equip_prefix(config) == "AcmeCorp.PlantA.ShopFloor1.AssemblyLine_Equipment"

    def test_all_identifiers_use_isa95_prefix(self, full_feature_2machine_config):
        conf = generate_telegraf_conf(full_feature_2machine_config)
        ids = _extract_identifiers(conf)
        for node_id in ids:
            assert node_id.startswith("WeylandIndustries."), f"Bad prefix: {node_id}"


# ---------------------------------------------------------------------------
# Tests: system-level nodes
# ---------------------------------------------------------------------------
class TestSystemNodes:
    def test_operations_state_nodes(self, balanced_line_config):
        conf = generate_telegraf_conf(balanced_line_config)
        ids = _extract_identifiers(conf)
        assert f"{EP}.OperationsState.SimTime" in ids
        assert f"{EP}.OperationsState.LineState" in ids
        assert f"{EP}.OperationsState.LineMode" in ids

    def test_operations_performance_nodes(self, balanced_line_config):
        conf = generate_telegraf_conf(balanced_line_config)
        ids = _extract_identifiers(conf)
        assert f"{EP}.OperationsPerformance.Throughput" in ids
        assert f"{EP}.OperationsPerformance.TotalWIP" in ids
        assert f"{EP}.OperationsPerformance.TotalScrap" in ids
        assert f"{EP}.OperationsPerformance.ScrapRate" in ids

    def test_line_oee_nodes(self, balanced_line_config):
        conf = generate_telegraf_conf(balanced_line_config)
        ids = _extract_identifiers(conf)
        assert f"{EP}.OEE.OEE" in ids
        assert f"{EP}.OEE.Availability" in ids
        assert f"{EP}.OEE.Performance" in ids
        assert f"{EP}.OEE.Quality" in ids
        assert f"{EP}.OEE.GoodPartCount" in ids
        assert f"{EP}.OEE.DefectivePartCount" in ids

    def test_event_log_node(self, balanced_line_config):
        conf = generate_telegraf_conf(balanced_line_config)
        ids = _extract_identifiers(conf)
        assert f"{EP}.EventLog.TotalEventsGenerated" in ids

    def test_maintenance_nodes(self, balanced_line_config):
        conf = generate_telegraf_conf(balanced_line_config)
        ids = _extract_identifiers(conf)
        sf = f"{EP}.SupportFunctions"
        assert f"{sf}.Maintenance.MaintenanceActive" in ids
        assert f"{sf}.Maintenance.QueueLength" in ids
        assert f"{sf}.Maintenance.TotalRepairs" in ids


# ---------------------------------------------------------------------------
# Tests: per-machine nodes
# ---------------------------------------------------------------------------
class TestMachineNodes:
    def test_basic_nodes_for_each_machine(self, balanced_line_config):
        """3-machine line should have ISA-95 grouped nodes for each."""
        conf = generate_telegraf_conf(balanced_line_config)
        ids = _extract_identifiers(conf)
        res = f"{EP}.Resources"
        for i in range(1, 4):
            mn = f"M{i}_Equipment"
            p = f"{res}.{mn}"
            assert f"{p}.OperationsState.State" in ids
            assert f"{p}.OperationsPerformance.PartCount" in ids
            assert f"{p}.OperationsPerformance.Utilisation" in ids
            assert f"{p}.OperationsPerformance.TargetPPM" in ids
            assert f"{p}.OperationsPerformance.ActualPPM" in ids
            assert f"{p}.OperationsPerformance.BlockedTime" in ids
            assert f"{p}.OEE.OEE" in ids
            assert f"{p}.Alarms.ActiveAlarmCount" in ids

    def test_no_health_without_degradation(self, balanced_line_config):
        conf = generate_telegraf_conf(balanced_line_config)
        ids = _extract_identifiers(conf)
        res = f"{EP}.Resources"
        assert f"{res}.M1_Equipment.OperationsState.HealthState" not in ids

    def test_health_with_degradation(self, full_feature_2machine_config):
        conf = generate_telegraf_conf(full_feature_2machine_config)
        ids = _extract_identifiers(conf)
        res = f"{EP}.Resources"
        assert f"{res}.M1_Equipment.OperationsState.HealthState" in ids
        assert f"{res}.M1_Equipment.OperationsState.HealthPercent" in ids

    def test_health_with_advanced_failures_only(self):
        config = {
            "machines": [{
                "name": "M1", "cycle_time": 1,
                "enable_advanced_failures": True,
                "failure_modes": [
                    {"name": "mechanical", "type": "wearout",
                     "mttf": {"distribution": "exponential", "mean": 500},
                     "mttr": {"distribution": "exponential", "mean": 10}},
                ],
            }],
            "buffers": [],
        }
        conf = generate_telegraf_conf(config)
        ids = _extract_identifiers(conf)
        res = f"{EP}.Resources"
        assert f"{res}.M1_Equipment.OperationsState.HealthState" in ids

    def test_no_failure_modes_without_advanced(self, balanced_line_config):
        conf = generate_telegraf_conf(balanced_line_config)
        ids = _extract_identifiers(conf)
        res = f"{EP}.Resources"
        assert f"{res}.M1_Equipment.FailureModes.ActiveFailureMode" not in ids
        assert f"{res}.M1_Equipment.MaintenanceStrategy.StrategyType" not in ids

    def test_failure_mode_nodes_with_advanced(self, full_feature_2machine_config):
        conf = generate_telegraf_conf(full_feature_2machine_config)
        ids = _extract_identifiers(conf)
        res = f"{EP}.Resources"
        p = f"{res}.M1_Equipment"
        assert f"{p}.FailureModes.ActiveFailureMode" in ids
        assert f"{p}.FailureModes.MechanicalFailureCount" in ids
        assert f"{p}.FailureModes.MechanicalTotalDowntime" in ids
        assert f"{p}.FailureModes.MechanicalMTBF" in ids
        assert f"{p}.FailureModes.MechanicalMTTR" in ids
        assert f"{p}.FailureModes.ElectricalFailureCount" in ids
        assert f"{p}.MaintenanceStrategy.StrategyType" in ids
        assert f"{p}.MaintenanceStrategy.PMCount" in ids

    def test_no_quality_routing_without_enabled(self, balanced_line_config):
        conf = generate_telegraf_conf(balanced_line_config)
        ids = _extract_identifiers(conf)
        res = f"{EP}.Resources"
        assert f"{res}.M1_Equipment.QualityRouting.ScrapCount" not in ids

    def test_quality_routing_when_enabled(self, full_feature_2machine_config):
        conf = generate_telegraf_conf(full_feature_2machine_config)
        ids = _extract_identifiers(conf)
        res = f"{EP}.Resources"
        p = f"{res}.M1_Equipment"
        assert f"{p}.QualityRouting.ScrapCount" in ids
        assert f"{p}.QualityRouting.ReworkCount" in ids
        assert f"{p}.QualityRouting.GoodCount" in ids

    def test_no_spc_without_enabled(self, balanced_line_config):
        conf = generate_telegraf_conf(balanced_line_config)
        ids = _extract_identifiers(conf)
        res = f"{EP}.Resources"
        assert f"{res}.M1_Equipment.SPC.XBarChart.XBar" not in ids

    def test_spc_when_enabled(self, full_feature_2machine_config):
        conf = generate_telegraf_conf(full_feature_2machine_config)
        ids = _extract_identifiers(conf)
        res = f"{EP}.Resources"
        p = f"{res}.M1_Equipment"
        assert f"{p}.SPC.XBarChart.XBar" in ids
        assert f"{p}.SPC.XBarChart.UCL" in ids
        assert f"{p}.SPC.XBarChart.CL" in ids
        assert f"{p}.SPC.XBarChart.LCL" in ids
        assert f"{p}.SPC.RChart.Range" in ids
        assert f"{p}.SPC.RChart.UCL" in ids
        assert f"{p}.SPC.Capability.Cp" in ids
        assert f"{p}.SPC.Capability.Cpk" in ids
        assert f"{p}.SPC.Capability.Pp" in ids
        assert f"{p}.SPC.Capability.Ppk" in ids
        assert f"{p}.SPC.Capability.SigmaLevel" in ids
        assert f"{p}.SPC.Status.InControl" in ids
        assert f"{p}.SPC.Status.NumSubgroups" in ids

    def test_machine_tags(self, balanced_line_config):
        conf = generate_telegraf_conf(balanced_line_config)
        assert 'source="Machine1"' in conf
        assert 'source_type="machine"' in conf
        assert 'source="Machine3"' in conf


# ---------------------------------------------------------------------------
# Tests: buffer nodes
# ---------------------------------------------------------------------------
class TestBufferNodes:
    def test_buffer_storage_unit_nodes(self, balanced_line_config):
        conf = generate_telegraf_conf(balanced_line_config)
        ids = _extract_identifiers(conf)
        res = f"{EP}.Resources"
        assert f"{res}.B1_StorageUnit.CurrentLevel" in ids
        assert f"{res}.B1_StorageUnit.Capacity" in ids
        assert f"{res}.B2_StorageUnit.CurrentLevel" in ids
        assert f"{res}.B2_StorageUnit.Capacity" in ids

    def test_buffer_tags(self, balanced_line_config):
        conf = generate_telegraf_conf(balanced_line_config)
        assert 'source="Buffer1"' in conf
        assert 'source_type="buffer"' in conf


# ---------------------------------------------------------------------------
# Tests: scrap sink nodes
# ---------------------------------------------------------------------------
class TestScrapSinkNodes:
    def test_no_scrap_without_config(self, balanced_line_config):
        conf = generate_telegraf_conf(balanced_line_config)
        assert "SCRAP BINS" not in conf

    def test_scrap_storage_unit_nodes(self, full_feature_2machine_config):
        conf = generate_telegraf_conf(full_feature_2machine_config)
        ids = _extract_identifiers(conf)
        res = f"{EP}.Resources"
        assert f"{res}.ScrapBin1_StorageUnit.CurrentLevel" in ids
        assert f"{res}.ScrapBin2_StorageUnit.CurrentLevel" in ids

    def test_scrap_tags(self, full_feature_2machine_config):
        conf = generate_telegraf_conf(full_feature_2machine_config)
        assert 'source="ScrapBin1"' in conf
        assert 'source_type="scrap"' in conf


# ---------------------------------------------------------------------------
# Tests: shift nodes
# ---------------------------------------------------------------------------
class TestShiftNodes:
    def test_no_shifts_without_config(self, balanced_line_config):
        conf = generate_telegraf_conf(balanced_line_config)
        assert "SHIFTS" not in conf
        ids = _extract_identifiers(conf)
        sm = f"{EP}.SupportFunctions.ShiftManagement"
        assert f"{sm}.CurrentShiftNumber" not in ids

    def test_shift_nodes_when_configured(self, full_feature_2machine_config):
        conf = generate_telegraf_conf(full_feature_2machine_config)
        ids = _extract_identifiers(conf)
        sm = f"{EP}.SupportFunctions.ShiftManagement"
        # Tracking (7)
        assert f"{sm}.CurrentShiftNumber" in ids
        assert f"{sm}.CurrentShiftName" in ids
        assert f"{sm}.ShiftStartTime" in ids
        assert f"{sm}.ShiftEndTime" in ids
        assert f"{sm}.ShiftDuration" in ids
        assert f"{sm}.ShiftElapsedTime" in ids
        assert f"{sm}.ShiftTimeRemaining" in ids
        # Current shift (8)
        assert f"{sm}.CurrentShift.PartsProduced" in ids
        assert f"{sm}.CurrentShift.OEE" in ids
        # Previous shift (7)
        assert f"{sm}.PreviousShift.ShiftNumber" in ids
        assert f"{sm}.PreviousShift.OEE" in ids
        # Totals (5)
        assert f"{sm}.Totals.TotalPartsProduced" in ids
        assert f"{sm}.Totals.TotalShiftsCompleted" in ids

    def test_shift_node_count(self, full_feature_2machine_config):
        """Shifts should add exactly 27 nodes."""
        with_shifts = generate_telegraf_conf(full_feature_2machine_config)
        config_no_shifts = dict(full_feature_2machine_config)
        del config_no_shifts["shifts"]
        without_shifts = generate_telegraf_conf(config_no_shifts)
        shift_node_count = _count_nodes(with_shifts) - _count_nodes(without_shifts)
        assert shift_node_count == 27


# ---------------------------------------------------------------------------
# Tests: node count validation
# ---------------------------------------------------------------------------
class TestNodeCounts:
    def test_balanced_line_node_count(self, balanced_line_config):
        """3 machines (basic only) + 2 buffers + system nodes."""
        conf = generate_telegraf_conf(balanced_line_config)
        count = _count_nodes(conf)
        # System: 1 id (RunID) + 3 ops_state + 12 recipe + 4 ops_perf + 6 OEE + 1 event + 3 maint = 30
        # Per machine (no optional): 1 state + 9 perf + 7 OEE + 4 alarms = 21
        # 3 machines: 63
        # 2 buffers: 4
        expected = 30 + (21 * 3) + (2 * 2)
        assert count == expected, f"Expected {expected} nodes, got {count}"

    def test_full_feature_2machine_node_count(self, full_feature_2machine_config):
        """2-machine full-feature line."""
        conf = generate_telegraf_conf(full_feature_2machine_config)
        count = _count_nodes(conf)
        # System: 30 (1 id + 3 ops_state + 12 recipe + 4 ops_perf + 6 OEE + 1 event + 3 maint)
        # Machine1 (all features, degradation=True):
        #   1+2 ops_state + 9 perf + 7 OEE + 4 alarms
        #   + 1+8 FM + 4 MS + 5 QR + 17 SPC = 58
        # Machine2 (advanced=True → also gets health):
        #   1+2 ops_state + 9 perf + 7 OEE + 4 alarms
        #   + 1+8 FM + 4 MS + 5 QR + 17 SPC = 58
        # 1 buffer: 2
        # 2 scrap sinks: 2
        # Shifts: 27
        expected = 30 + 58 + 58 + 2 + 2 + 27
        assert count == expected, f"Expected {expected} nodes, got {count}"

    def test_eight_machine_node_count(self, eight_machine_config):
        """8-machine full-feature line."""
        conf = generate_telegraf_conf(eight_machine_config)
        count = _count_nodes(conf)
        # System: 30 (1 id + 3 ops_state + 12 recipe + 4 ops_perf + 6 OEE + 1 event + 3 maint)
        # Per machine: 58
        # 8 machines: 464
        # 7 buffers: 14
        # 8 scrap sinks: 8
        # Shifts: 27
        expected = 30 + (58 * 8) + (2 * 7) + 8 + 27
        assert count == expected, f"Expected {expected} nodes, got {count}"


# ---------------------------------------------------------------------------
# Tests: 8-machine naming
# ---------------------------------------------------------------------------
class TestEightMachineNaming:
    def test_machine8_nodes_exist(self, eight_machine_config):
        conf = generate_telegraf_conf(eight_machine_config)
        ids = _extract_identifiers(conf)
        res = f"{EP}.Resources"
        assert f"{res}.M8_Equipment.OperationsState.State" in ids
        assert f"{res}.M8_Equipment.OEE.OEE" in ids
        assert f"{res}.M8_Equipment.SPC.Capability.Cpk" in ids

    def test_buffer7_exists(self, eight_machine_config):
        conf = generate_telegraf_conf(eight_machine_config)
        ids = _extract_identifiers(conf)
        res = f"{EP}.Resources"
        assert f"{res}.B7_StorageUnit.CurrentLevel" in ids
        assert f"{res}.B7_StorageUnit.Capacity" in ids

    def test_scrapbin8_exists(self, eight_machine_config):
        conf = generate_telegraf_conf(eight_machine_config)
        ids = _extract_identifiers(conf)
        res = f"{EP}.Resources"
        assert f"{res}.ScrapBin8_StorageUnit.CurrentLevel" in ids

    def test_abbreviated_names(self, eight_machine_config):
        """Field names use M{i}_ prefix for InfluxDB brevity."""
        conf = generate_telegraf_conf(eight_machine_config)
        assert 'name="M8_State"' in conf
        assert 'name="B7_Level"' in conf
        assert 'name="Scrap8_Level"' in conf


# ---------------------------------------------------------------------------
# Tests: identifier pattern validation
# ---------------------------------------------------------------------------
class TestIdentifierPatterns:
    def test_all_identifiers_start_with_enterprise(self, full_feature_2machine_config):
        conf = generate_telegraf_conf(full_feature_2machine_config)
        ids = _extract_identifiers(conf)
        for node_id in ids:
            assert node_id.startswith("WeylandIndustries."), f"Bad prefix: {node_id}"

    def test_no_duplicate_identifiers(self, eight_machine_config):
        conf = generate_telegraf_conf(eight_machine_config)
        ids = _extract_identifiers(conf)
        seen = set()
        for node_id in ids:
            assert node_id not in seen, f"Duplicate identifier: {node_id}"
            seen.add(node_id)

    def test_no_duplicate_names(self, eight_machine_config):
        """All Telegraf field names must be unique."""
        import re
        conf = generate_telegraf_conf(eight_machine_config)
        names = re.findall(r'\{name="([^"]+)"', conf)
        seen = set()
        for name in names:
            assert name not in seen, f"Duplicate name: {name}"
            seen.add(name)


# ---------------------------------------------------------------------------
# Tests: failure mode capitalization
# ---------------------------------------------------------------------------
class TestFailureModeCapitalization:
    def test_capitalize_matches_opcua_server(self):
        """Generator should use .capitalize() like opcua_server.py does."""
        config = {
            "machines": [{
                "name": "M1", "cycle_time": 1,
                "enable_advanced_failures": True,
                "failure_modes": [
                    {"name": "bearing_wear", "type": "wearout",
                     "mttf": {"distribution": "exponential", "mean": 500},
                     "mttr": {"distribution": "exponential", "mean": 10}},
                ],
            }],
            "buffers": [],
        }
        conf = generate_telegraf_conf(config)
        ids = _extract_identifiers(conf)
        res = f"{EP}.Resources"
        p = f"{res}.M1_Equipment"
        # Python .capitalize() on "bearing_wear" gives "Bearing_wear"
        assert f"{p}.FailureModes.Bearing_wearFailureCount" in ids
        assert f"{p}.FailureModes.Bearing_wearMTBF" in ids


# ---------------------------------------------------------------------------
# Tests: round-trip with YAML file
# ---------------------------------------------------------------------------
class TestYAMLRoundTrip:
    def test_generate_from_yaml_file(self):
        """Load actual YAML config and generate for balanced_line."""
        import yaml
        yaml_path = os.path.join(_project_root, "config", "line_models.yaml")
        if not os.path.exists(yaml_path):
            pytest.skip("YAML config file not found")

        with open(yaml_path) as f:
            all_configs = yaml.safe_load(f)

        config = all_configs["balanced_line"]
        conf = generate_telegraf_conf(config)
        count = _count_nodes(conf)
        assert count > 0
        assert "Machine1" in conf

    def test_generate_from_yaml_full_feature(self):
        """Load actual full_feature_line and verify node count."""
        import yaml
        yaml_path = os.path.join(_project_root, "config", "line_models.yaml")
        if not os.path.exists(yaml_path):
            pytest.skip("YAML config file not found")

        with open(yaml_path) as f:
            all_configs = yaml.safe_load(f)

        config = all_configs["full_feature_line"]
        conf = generate_telegraf_conf(config)
        count = _count_nodes(conf)
        # ISA-95 system nodes are 17 (up from 13), so ~152+ nodes
        assert count >= 140, f"Expected ~152 nodes, got {count}"

    def test_generate_from_yaml_8_machine(self):
        """Load actual full_feature_8_machine_line scenario."""
        import yaml
        yaml_path = os.path.join(_project_root, "config", "line_models.yaml")
        if not os.path.exists(yaml_path):
            pytest.skip("YAML config file not found")

        with open(yaml_path) as f:
            all_configs = yaml.safe_load(f)

        config = all_configs["full_feature_8_machine_line"]
        conf = generate_telegraf_conf(config)
        ids = _extract_identifiers(conf)
        res = f"{EP}.Resources"
        # Verify all 8 machines present
        for i in range(1, 9):
            assert f"{res}.M{i}_Equipment.OperationsState.State" in ids
        # Verify all 7 buffers
        for i in range(1, 8):
            assert f"{res}.B{i}_StorageUnit.CurrentLevel" in ids
        # Verify all 8 scrap bins
        for i in range(1, 9):
            assert f"{res}.ScrapBin{i}_StorageUnit.CurrentLevel" in ids
        # Verify shifts present
        sm = f"{EP}.SupportFunctions.ShiftManagement"
        assert f"{sm}.CurrentShiftNumber" in ids
        # Verify node count is large (500+)
        count = _count_nodes(conf)
        assert count >= 500, f"Expected 500+ nodes, got {count}"


# ---------------------------------------------------------------------------
# Tests: empty/minimal configs
# ---------------------------------------------------------------------------
class TestEdgeCases:
    def test_single_machine_no_buffers(self):
        config = {
            "machines": [{"name": "M1", "cycle_time": 1.0}],
            "buffers": [],
        }
        conf = generate_telegraf_conf(config)
        count = _count_nodes(conf)
        # 30 system + 21 machine = 51
        assert count == 51

    def test_empty_machines_list(self):
        config = {"machines": [], "buffers": []}
        conf = generate_telegraf_conf(config)
        count = _count_nodes(conf)
        # Only system nodes (including RunID + 12 recipe)
        assert count == 30

    def test_quality_routing_disabled_explicitly(self):
        config = {
            "machines": [{
                "name": "M1", "cycle_time": 1,
                "quality_routing": {"enabled": False},
            }],
            "buffers": [],
        }
        conf = generate_telegraf_conf(config)
        ids = _extract_identifiers(conf)
        res = f"{EP}.Resources"
        assert f"{res}.M1_Equipment.QualityRouting.ScrapCount" not in ids


class TestRunID:
    """Tests for run_id in generated Telegraf config."""

    def test_global_tags_with_run_id(self, balanced_line_config):
        conf = generate_telegraf_conf(
            balanced_line_config,
            run_id="balanced_line_20260224_143000"
        )
        assert '[global_tags]' in conf
        assert 'run_id = "balanced_line_20260224_143000"' in conf

    def test_global_tags_empty_run_id(self, balanced_line_config):
        conf = generate_telegraf_conf(balanced_line_config)
        assert '[global_tags]' in conf
        assert 'run_id = ""' in conf

    def test_run_id_node_in_identification(self, balanced_line_config):
        conf = generate_telegraf_conf(balanced_line_config)
        ids = _extract_identifiers(conf)
        assert f"{EP}.Identification.RunID" in ids

    def test_run_id_in_header_comment(self, balanced_line_config):
        conf = generate_telegraf_conf(
            balanced_line_config,
            run_id="test_run_123"
        )
        assert "RunID: test_run_123" in conf
