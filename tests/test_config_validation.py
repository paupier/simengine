"""
Configuration Validation Tests — §3 schema (clone_build_plan.md).

Covers the stations/buffers topology, health, process_values, cycle_stops,
comms, and historians validators, plus the carried failure-mode and
distribution validation.
"""
import pytest

from simengine.config.loader import (
    load_line_config,
    validate_serial_topology,
    validate_health,
    validate_process_values,
    validate_cycle_stops,
    validate_comms,
    validate_historians,
    validate_failure_modes,
    validate_distribution_config,
    resolve_cycle_time,
)


def minimal_config(**overrides):
    cfg = {
        "stations": [
            {"name": "S1", "cycle_time": 2.0},
            {"name": "S2", "cycle_time": 2.0},
        ],
        "buffers": [{"name": "B1", "capacity": 10}],
    }
    cfg.update(overrides)
    return cfg


class TestLoadFixtureScenarios:
    def test_load_balanced_line(self):
        config = load_line_config("balanced_line")
        assert len(config["stations"]) == 2
        assert config["stations"][0]["name"] == "M1"

    def test_load_full_feature_line(self):
        config = load_line_config("full_feature_line")
        st = config["stations"][0]
        assert st["health"]["h_max"] == 3
        assert st["process_values"][0]["profile"] == "first_order_lag"
        assert st["cycle_stops"][0]["reason"] == "CS_JAM"

    def test_load_advanced_failure_line(self):
        config = load_line_config("advanced_failure_line")
        assert len(config["stations"][0]["failure_modes"]) == 2

    def test_unknown_scenario(self):
        with pytest.raises(ValueError, match="not found"):
            load_line_config("nonexistent_scenario_xyz")


class TestShippedScenarios:
    """The shipped config/scenarios.yaml must validate."""

    @pytest.mark.parametrize("name", ["demo_line", "two_station_minimal", "press_line_8"])
    def test_shipped_scenario_validates(self, name, monkeypatch):
        monkeypatch.delenv("SIMENGINE_CONFIG_PATH", raising=False)
        config = load_line_config(name)
        assert len(config["stations"]) >= 2


class TestTopology:
    def test_missing_stations(self):
        with pytest.raises(ValueError, match="stations"):
            validate_serial_topology({"buffers": []})

    def test_min_two_stations(self):
        cfg = minimal_config()
        cfg["stations"] = cfg["stations"][:1]
        cfg["buffers"] = []
        with pytest.raises(ValueError, match="at least 2 stations"):
            validate_serial_topology(cfg)

    def test_buffer_count_rule(self):
        cfg = minimal_config()
        cfg["buffers"] = []
        with pytest.raises(ValueError, match="requires 1 buffers"):
            validate_serial_topology(cfg)

    def test_duplicate_station_names(self):
        cfg = minimal_config()
        cfg["stations"][1]["name"] = "S1"
        with pytest.raises(ValueError, match="unique"):
            validate_serial_topology(cfg)

    def test_bad_buffer_capacity(self):
        cfg = minimal_config()
        cfg["buffers"][0]["capacity"] = 0
        with pytest.raises(ValueError, match="capacity"):
            validate_serial_topology(cfg)

    def test_missing_cycle_time_and_ppm(self):
        cfg = minimal_config()
        del cfg["stations"][0]["cycle_time"]
        with pytest.raises(ValueError, match="cycle_time.*target_ppm"):
            validate_serial_topology(cfg)

    def test_negative_cycle_time(self):
        cfg = minimal_config()
        cfg["stations"][0]["cycle_time"] = -1
        with pytest.raises(ValueError, match="positive"):
            validate_serial_topology(cfg)

    def test_valid_config_passes(self):
        validate_serial_topology(minimal_config())


class TestResolveCycleTime:
    def test_cycle_time_direct(self):
        assert resolve_cycle_time({"cycle_time": 12.0}) == 12.0

    def test_target_ppm_derivation(self):
        assert resolve_cycle_time({"target_ppm": 6.0}) == 10.0

    def test_target_ppm_precedence(self):
        assert resolve_cycle_time({"cycle_time": 99.0, "target_ppm": 30.0}) == 2.0


class TestValidateHealth:
    def base(self, **health):
        cfg = {"name": "S1", "cycle_time": 1.0, "health": {
            "h_max": 5, "p_degrade": 0.01,
            "mttr": {"distribution": "constant", "value": 60},
        }}
        cfg["health"].update(health)
        return cfg

    def test_valid(self):
        validate_health(self.base())

    def test_absent_ok(self):
        validate_health({"name": "S1", "cycle_time": 1.0})

    def test_bad_h_max(self):
        with pytest.raises(ValueError, match="h_max"):
            validate_health(self.base(h_max=0))

    def test_p_degrade_range(self):
        with pytest.raises(ValueError, match="p_degrade"):
            validate_health(self.base(p_degrade=1.5))

    def test_stray_cbm_threshold_key_tolerated(self):
        """Unknown-key tolerance (CLAUDE.md): an old config with a leftover
        cbm_threshold key must still validate — it's simply never read. Probe value
        (6) is deliberately set to violate the old bounds check (0 < cbm <= h_max=5)
        to ensure regression detection."""
        validate_health(self.base(cbm_threshold=6))

    def test_missing_mttr(self):
        cfg = self.base()
        del cfg["health"]["mttr"]
        with pytest.raises(ValueError, match="mttr"):
            validate_health(cfg)


class TestValidateProcessValues:
    def station(self, pv):
        return {"name": "S1", "cycle_time": 1.0, "process_values": [pv]}

    def test_valid_profiles(self):
        validate_process_values(self.station({
            "name": "RamForce", "unit": "kN", "profile": "cycle_peak",
            "baseline": 0.0, "peak": {"distribution": "normal", "mean": 850, "std": 15},
        }))
        validate_process_values(self.station({
            "name": "OilTemp", "unit": "degC", "profile": "first_order_lag",
            "setpoint": 55.0, "tau": 300, "initial": 20.0,
        }))
        validate_process_values(self.station({
            "name": "StrokePos", "unit": "mm", "profile": "cycle_ramp",
            "range": [0.0, 320.0],
        }))
        validate_process_values(self.station({
            "name": "FeedSpeed", "unit": "mm_s", "profile": "constant_noise",
            "mean": 450.0,
        }))

    def test_invalid_profile(self):
        with pytest.raises(ValueError, match="invalid profile"):
            validate_process_values(self.station({
                "name": "X", "unit": "u", "profile": "sawtooth", "mean": 1,
            }))

    def test_missing_required_key(self):
        with pytest.raises(ValueError, match="missing required key 'tau'"):
            validate_process_values(self.station({
                "name": "T", "unit": "degC", "profile": "first_order_lag",
                "setpoint": 55.0, "initial": 20.0,
            }))

    def test_missing_unit(self):
        with pytest.raises(ValueError, match="unit"):
            validate_process_values(self.station({
                "name": "X", "profile": "constant_noise", "mean": 1,
            }))

    def test_bad_range(self):
        with pytest.raises(ValueError, match="range"):
            validate_process_values(self.station({
                "name": "X", "unit": "mm", "profile": "cycle_ramp",
                "range": [10.0, 5.0],
            }))

    def test_alarm_high_le_low(self):
        with pytest.raises(ValueError, match="alarm_high"):
            validate_process_values(self.station({
                "name": "X", "unit": "u", "profile": "constant_noise",
                "mean": 1, "alarm_high": 5, "alarm_low": 10,
            }))

    def test_invalid_noise_distribution(self):
        with pytest.raises(ValueError):
            validate_process_values(self.station({
                "name": "X", "unit": "u", "profile": "constant_noise",
                "mean": 1, "noise": {"distribution": "bogus"},
            }))

    def test_duplicate_pv_names(self):
        cfg = {"name": "S1", "cycle_time": 1.0, "process_values": [
            {"name": "X", "unit": "u", "profile": "constant_noise", "mean": 1},
            {"name": "X", "unit": "u", "profile": "constant_noise", "mean": 2},
        ]}
        with pytest.raises(ValueError, match="unique"):
            validate_process_values(cfg)


class TestValidateCycleStops:
    def station(self, stop):
        return {"name": "S1", "cycle_time": 1.0, "cycle_stops": [stop]}

    def test_valid(self):
        validate_cycle_stops(self.station({
            "reason": "CS_JAM",
            "mtbe": {"distribution": "exponential", "mean": 900},
            "duration": {"distribution": "lognormal", "mean": 25, "std": 10},
        }))

    def test_missing_reason(self):
        with pytest.raises(ValueError, match="reason"):
            validate_cycle_stops(self.station({
                "mtbe": {"distribution": "exponential", "mean": 900},
                "duration": {"distribution": "constant", "value": 5},
            }))

    def test_missing_duration(self):
        with pytest.raises(ValueError, match="duration"):
            validate_cycle_stops(self.station({
                "reason": "CS_JAM",
                "mtbe": {"distribution": "exponential", "mean": 900},
            }))

    def test_invalid_distribution(self):
        with pytest.raises(ValueError):
            validate_cycle_stops(self.station({
                "reason": "CS_JAM",
                "mtbe": {"distribution": "nope"},
                "duration": {"distribution": "constant", "value": 5},
            }))


class TestValidateComms:
    def test_absent_ok(self):
        validate_comms({})

    def test_valid_full_block(self):
        validate_comms({"comms": {
            "opcua": {"enabled": True, "port": 4840},
            "opcua_mqtt": {"enabled": True, "broker": "mqtt://localhost:1883",
                           "publisher_id": "x", "publish_interval": 1},
            "sparkplugb": {"enabled": True, "broker": "mqtt://localhost:1883",
                           "group_id": "G", "edge_node_id": "E"},
        }})

    def test_bad_port(self):
        with pytest.raises(ValueError, match="port"):
            validate_comms({"comms": {"opcua": {"enabled": True, "port": 99999}}})

    def test_bad_broker_scheme(self):
        with pytest.raises(ValueError, match="broker"):
            validate_comms({"comms": {"opcua_mqtt": {
                "enabled": True, "broker": "tcp://localhost:1883"}}})

    def test_broker_missing_port(self):
        with pytest.raises(ValueError, match="port"):
            validate_comms({"comms": {"opcua_mqtt": {
                "enabled": True, "broker": "mqtt://localhost"}}})

    def test_broker_required_when_enabled(self):
        with pytest.raises(ValueError, match="broker required"):
            validate_comms({"comms": {"sparkplugb": {
                "enabled": True, "group_id": "G", "edge_node_id": "E"}}})

    def test_sparkplug_ids_required(self):
        with pytest.raises(ValueError, match="group_id"):
            validate_comms({"comms": {"sparkplugb": {
                "enabled": True, "broker": "mqtt://localhost:1883"}}})

    def test_disabled_needs_no_broker(self):
        validate_comms({"comms": {"opcua_mqtt": {"enabled": False}}})


class TestValidateHistorians:
    def test_absent_ok(self):
        validate_historians({})

    def test_valid_list(self):
        validate_historians({"historians": ["csv", "influx"]})

    def test_not_a_list(self):
        with pytest.raises(ValueError, match="list"):
            validate_historians({"historians": "csv"})

    def test_non_string_entry(self):
        with pytest.raises(ValueError, match="list"):
            validate_historians({"historians": [1]})


class TestCarriedFailureModeValidation:
    def test_valid_failure_modes(self):
        validate_failure_modes({
            "name": "S1",
            "failure_modes": [{
                "name": "bearing_wear", "type": "wearout",
                "mttf": {"distribution": "weibull", "shape": 2.0, "scale": 20000},
                "mttr": {"distribution": "lognormal", "mean": 300, "std": 60},
            }],
        })

    def test_invalid_type(self):
        with pytest.raises(ValueError, match="invalid type"):
            validate_failure_modes({
                "name": "S1",
                "failure_modes": [{
                    "name": "x", "type": "cosmic_ray",
                    "mttf": {"distribution": "constant", "value": 1},
                    "mttr": {"distribution": "constant", "value": 1},
                }],
            })

    def test_missing_mttr(self):
        with pytest.raises(ValueError, match="mttr"):
            validate_failure_modes({
                "name": "S1",
                "failure_modes": [{
                    "name": "x", "type": "random",
                    "mttf": {"distribution": "constant", "value": 1},
                }],
            })

    def test_distribution_validation(self):
        validate_distribution_config(
            {"distribution": "weibull", "shape": 2.0, "scale": 100}, "ctx")
        with pytest.raises(ValueError):
            validate_distribution_config({"distribution": "weibull"}, "ctx")
        with pytest.raises(ValueError):
            validate_distribution_config({}, "ctx")
