"""Tests for the dynamic Telegraf config generator."""
import os
import sys

# Add docker/telegraf to path so we can import the generator
_test_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_test_dir)
sys.path.insert(0, os.path.join(_project_root, "docker", "telegraf"))

from generate_telegraf_conf import generate_telegraf_conf  # noqa: E402
import pytest  # noqa: E402


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


# ---------------------------------------------------------------------------
# Tests: static system nodes
# ---------------------------------------------------------------------------
class TestSystemNodes:
    def test_system_nodes_always_present(self, balanced_line_config):
        conf = generate_telegraf_conf(balanced_line_config)
        ids = _extract_identifiers(conf)
        expected_system = [
            "Line1.System.SimTime",
            "Line1.System.Throughput",
            "Line1.LineKPIs.TotalWIP",
            "Line1.LineKPIs.TotalScrap",
            "Line1.LineKPIs.ScrapRate",
            "Line1.LineKPIs.LineOEE.OEE",
            "Line1.LineKPIs.LineOEE.Availability",
            "Line1.LineKPIs.LineOEE.Performance",
            "Line1.LineKPIs.LineOEE.Quality",
            "Line1.EventLog.TotalEventsGenerated",
            "Line1.Maintenance.MaintenanceActive",
            "Line1.Maintenance.QueueLength",
            "Line1.Maintenance.TotalRepairs",
        ]
        for node_id in expected_system:
            assert node_id in ids, f"Missing system node: {node_id}"


# ---------------------------------------------------------------------------
# Tests: per-machine nodes
# ---------------------------------------------------------------------------
class TestMachineNodes:
    def test_basic_nodes_for_each_machine(self, balanced_line_config):
        """3-machine line should have basic + time + OEE + alarms for each."""
        conf = generate_telegraf_conf(balanced_line_config)
        ids = _extract_identifiers(conf)
        for i in range(1, 4):
            mn = f"Machine{i}"
            assert f"Line1.{mn}.State" in ids
            assert f"Line1.{mn}.PartCount" in ids
            assert f"Line1.{mn}.Utilisation" in ids
            assert f"Line1.{mn}.TargetPPM" in ids
            assert f"Line1.{mn}.ActualPPM" in ids
            assert f"Line1.{mn}.BlockedTime" in ids
            assert f"Line1.{mn}.OEE.OEE" in ids
            assert f"Line1.{mn}.Alarms.ActiveAlarmCount" in ids

    def test_no_health_without_degradation(self, balanced_line_config):
        """Machines without degradation should not have health nodes."""
        conf = generate_telegraf_conf(balanced_line_config)
        ids = _extract_identifiers(conf)
        assert "Line1.Machine1.HealthState" not in ids
        assert "Line1.Machine1.HealthPercent" not in ids

    def test_health_with_degradation(self, full_feature_2machine_config):
        """Machine1 has enable_degradation=True, should have health nodes."""
        conf = generate_telegraf_conf(full_feature_2machine_config)
        ids = _extract_identifiers(conf)
        assert "Line1.Machine1.HealthState" in ids
        assert "Line1.Machine1.HealthPercent" in ids

    def test_health_with_advanced_failures_only(self):
        """Machine with advanced failures but no degradation still gets health."""
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
        assert "Line1.Machine1.HealthState" in ids

    def test_no_failure_modes_without_advanced(self, balanced_line_config):
        conf = generate_telegraf_conf(balanced_line_config)
        ids = _extract_identifiers(conf)
        assert "Line1.Machine1.FailureModes.ActiveFailureMode" not in ids
        assert "Line1.Machine1.MaintenanceStrategy.StrategyType" not in ids

    def test_failure_mode_nodes_with_advanced(self, full_feature_2machine_config):
        conf = generate_telegraf_conf(full_feature_2machine_config)
        ids = _extract_identifiers(conf)
        # ActiveFailureMode
        assert "Line1.Machine1.FailureModes.ActiveFailureMode" in ids
        # Per-mode nodes (capitalized)
        assert "Line1.Machine1.FailureModes.MechanicalFailureCount" in ids
        assert "Line1.Machine1.FailureModes.MechanicalTotalDowntime" in ids
        assert "Line1.Machine1.FailureModes.MechanicalMTBF" in ids
        assert "Line1.Machine1.FailureModes.MechanicalMTTR" in ids
        assert "Line1.Machine1.FailureModes.ElectricalFailureCount" in ids
        # Maintenance strategy
        assert "Line1.Machine1.MaintenanceStrategy.StrategyType" in ids
        assert "Line1.Machine1.MaintenanceStrategy.PMCount" in ids

    def test_no_quality_routing_without_enabled(self, balanced_line_config):
        conf = generate_telegraf_conf(balanced_line_config)
        ids = _extract_identifiers(conf)
        assert "Line1.Machine1.QualityRouting.ScrapCount" not in ids

    def test_quality_routing_when_enabled(self, full_feature_2machine_config):
        conf = generate_telegraf_conf(full_feature_2machine_config)
        ids = _extract_identifiers(conf)
        assert "Line1.Machine1.QualityRouting.ScrapCount" in ids
        assert "Line1.Machine1.QualityRouting.ReworkCount" in ids
        assert "Line1.Machine1.QualityRouting.GoodCount" in ids

    def test_no_spc_without_enabled(self, balanced_line_config):
        conf = generate_telegraf_conf(balanced_line_config)
        ids = _extract_identifiers(conf)
        assert "Line1.Machine1.SPC.XBarChart.XBar" not in ids

    def test_spc_when_enabled(self, full_feature_2machine_config):
        conf = generate_telegraf_conf(full_feature_2machine_config)
        ids = _extract_identifiers(conf)
        # X-bar chart
        assert "Line1.Machine1.SPC.XBarChart.XBar" in ids
        assert "Line1.Machine1.SPC.XBarChart.UCL" in ids
        assert "Line1.Machine1.SPC.XBarChart.CL" in ids
        assert "Line1.Machine1.SPC.XBarChart.LCL" in ids
        # R chart
        assert "Line1.Machine1.SPC.RChart.Range" in ids
        assert "Line1.Machine1.SPC.RChart.UCL" in ids
        # Capability
        assert "Line1.Machine1.SPC.Capability.Cp" in ids
        assert "Line1.Machine1.SPC.Capability.Cpk" in ids
        assert "Line1.Machine1.SPC.Capability.Pp" in ids
        assert "Line1.Machine1.SPC.Capability.Ppk" in ids
        assert "Line1.Machine1.SPC.Capability.SigmaLevel" in ids
        # Status
        assert "Line1.Machine1.SPC.Status.InControl" in ids
        assert "Line1.Machine1.SPC.Status.NumSubgroups" in ids

    def test_machine_tags(self, balanced_line_config):
        conf = generate_telegraf_conf(balanced_line_config)
        assert 'source="Machine1"' in conf
        assert 'source_type="machine"' in conf
        assert 'source="Machine3"' in conf


# ---------------------------------------------------------------------------
# Tests: buffer nodes
# ---------------------------------------------------------------------------
class TestBufferNodes:
    def test_buffer_nodes(self, balanced_line_config):
        conf = generate_telegraf_conf(balanced_line_config)
        ids = _extract_identifiers(conf)
        assert "Line1.Buffer1.CurrentLevel" in ids
        assert "Line1.Buffer1.Capacity" in ids
        assert "Line1.Buffer2.CurrentLevel" in ids
        assert "Line1.Buffer2.Capacity" in ids

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

    def test_scrap_nodes_when_configured(self, full_feature_2machine_config):
        conf = generate_telegraf_conf(full_feature_2machine_config)
        ids = _extract_identifiers(conf)
        assert "Line1.ScrapBin1.CurrentLevel" in ids
        assert "Line1.ScrapBin2.CurrentLevel" in ids

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
        assert "Line1.Shift.CurrentShiftNumber" not in ids

    def test_shift_nodes_when_configured(self, full_feature_2machine_config):
        conf = generate_telegraf_conf(full_feature_2machine_config)
        ids = _extract_identifiers(conf)
        # Tracking (7)
        assert "Line1.Shift.CurrentShiftNumber" in ids
        assert "Line1.Shift.CurrentShiftName" in ids
        assert "Line1.Shift.ShiftStartTime" in ids
        assert "Line1.Shift.ShiftEndTime" in ids
        assert "Line1.Shift.ShiftDuration" in ids
        assert "Line1.Shift.ShiftElapsedTime" in ids
        assert "Line1.Shift.ShiftTimeRemaining" in ids
        # Current shift (8)
        assert "Line1.Shift.CurrentShift.PartsProduced" in ids
        assert "Line1.Shift.CurrentShift.OEE" in ids
        # Previous shift (7)
        assert "Line1.Shift.PreviousShift.ShiftNumber" in ids
        assert "Line1.Shift.PreviousShift.OEE" in ids
        # Totals (5)
        assert "Line1.Shift.Totals.TotalPartsProduced" in ids
        assert "Line1.Shift.Totals.TotalShiftsCompleted" in ids

    def test_shift_node_count(self, full_feature_2machine_config):
        """Shifts should add exactly 27 nodes."""
        with_shifts = generate_telegraf_conf(full_feature_2machine_config)
        # Remove shifts and regenerate
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
        # System: 13
        # Per machine (no optional): 5 basic + 5 time + 7 OEE + 4 alarms = 21
        # 3 machines: 63
        # 2 buffers: 4
        # No scrap, no shifts
        expected = 13 + (21 * 3) + (2 * 2)
        assert count == expected, f"Expected {expected} nodes, got {count}"

    def test_full_feature_2machine_node_count(self, full_feature_2machine_config):
        """2-machine full-feature line should match ~148 nodes from static conf."""
        conf = generate_telegraf_conf(full_feature_2machine_config)
        count = _count_nodes(conf)
        # System: 13
        # Machine1 (all features, degradation=True):
        #   5 basic + 5 time + 2 health + 7 OEE + 4 alarms
        #   + 1+8 failure modes + 4 maint strategy
        #   + 5 quality routing + 17 SPC = 58
        # Machine2 (all features, no explicit degradation but advanced=True):
        #   5 basic + 5 time + 2 health + 7 OEE + 4 alarms
        #   + 1+8 failure modes + 4 maint strategy
        #   + 5 quality routing + 17 SPC = 58
        # 1 buffer: 2
        # 2 scrap sinks: 2
        # Shifts: 27
        expected = 13 + 58 + 58 + 2 + 2 + 27
        assert count == expected, f"Expected {expected} nodes, got {count}"

    def test_eight_machine_node_count(self, eight_machine_config):
        """8-machine full-feature line."""
        conf = generate_telegraf_conf(eight_machine_config)
        count = _count_nodes(conf)
        # System: 13
        # Per machine (all features, degradation+advanced):
        #   5 basic + 5 time + 2 health + 7 OEE + 4 alarms
        #   + 1+8 failure modes + 4 maint strategy
        #   + 5 quality routing + 17 SPC = 58
        # 8 machines: 464
        # 7 buffers: 14
        # 8 scrap sinks: 8
        # Shifts: 27
        expected = 13 + (58 * 8) + (2 * 7) + 8 + 27
        assert count == expected, f"Expected {expected} nodes, got {count}"


# ---------------------------------------------------------------------------
# Tests: 8-machine naming
# ---------------------------------------------------------------------------
class TestEightMachineNaming:
    def test_machine8_nodes_exist(self, eight_machine_config):
        conf = generate_telegraf_conf(eight_machine_config)
        ids = _extract_identifiers(conf)
        assert "Line1.Machine8.State" in ids
        assert "Line1.Machine8.OEE.OEE" in ids
        assert "Line1.Machine8.SPC.Capability.Cpk" in ids

    def test_buffer7_exists(self, eight_machine_config):
        conf = generate_telegraf_conf(eight_machine_config)
        ids = _extract_identifiers(conf)
        assert "Line1.Buffer7.CurrentLevel" in ids
        assert "Line1.Buffer7.Capacity" in ids

    def test_scrapbin8_exists(self, eight_machine_config):
        conf = generate_telegraf_conf(eight_machine_config)
        ids = _extract_identifiers(conf)
        assert "Line1.ScrapBin8.CurrentLevel" in ids

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
    def test_all_identifiers_start_with_line1(self, full_feature_2machine_config):
        conf = generate_telegraf_conf(full_feature_2machine_config)
        ids = _extract_identifiers(conf)
        for node_id in ids:
            assert node_id.startswith("Line1."), f"Bad prefix: {node_id}"

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
        # Python .capitalize() on "bearing_wear" gives "Bearing_wear"
        assert "Line1.Machine1.FailureModes.Bearing_wearFailureCount" in ids
        assert "Line1.Machine1.FailureModes.Bearing_wearMTBF" in ids


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
        # Should be close to the 148 nodes in the static config
        assert count >= 140, f"Expected ~148 nodes, got {count}"

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
        # Verify all 8 machines present
        for i in range(1, 9):
            assert f"Line1.Machine{i}.State" in ids
        # Verify all 7 buffers
        for i in range(1, 8):
            assert f"Line1.Buffer{i}.CurrentLevel" in ids
        # Verify all 8 scrap bins
        for i in range(1, 9):
            assert f"Line1.ScrapBin{i}.CurrentLevel" in ids
        # Verify shifts present
        assert "Line1.Shift.CurrentShiftNumber" in ids
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
        # 13 system + 21 machine = 34
        assert count == 34

    def test_empty_machines_list(self):
        config = {"machines": [], "buffers": []}
        conf = generate_telegraf_conf(config)
        count = _count_nodes(conf)
        # Only system nodes
        assert count == 13

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
        assert "Line1.Machine1.QualityRouting.ScrapCount" not in ids
