"""
Configuration Validation Tests

Tests YAML configuration validation for advanced failure modes.
"""
import pytest
from src.config_loader import (
    load_line_config,
    validate_failure_modes,
    validate_distribution_config,
    validate_maintenance_strategy,
    validate_historian_config,
)


class TestLoadAdvancedFailureConfig:
    """Test loading advanced_failure_line scenario."""

    def test_load_advanced_failure_line(self):
        """advanced_failure_line scenario loads and validates successfully."""
        config = load_line_config("advanced_failure_line")

        assert "machines" in config
        assert "buffers" in config
        assert len(config["machines"]) == 2
        assert config["machines"][0]["name"] == "M1"
        assert config["machines"][0]["enable_advanced_failures"] is True
        assert "failure_modes" in config["machines"][0]
        assert len(config["machines"][0]["failure_modes"]) == 2


class TestDistributionValidation:
    """Test distribution configuration validation."""

    def test_constant_valid(self):
        """Valid constant distribution passes validation."""
        dist_cfg = {"distribution": "constant", "value": 10}
        validate_distribution_config(dist_cfg, "test")  # Should not raise

    def test_constant_missing_value(self):
        """Constant distribution without value raises error."""
        dist_cfg = {"distribution": "constant"}
        with pytest.raises(ValueError, match="requires 'value' parameter"):
            validate_distribution_config(dist_cfg, "test")

    def test_constant_negative_value(self):
        """Constant distribution with negative value raises error."""
        dist_cfg = {"distribution": "constant", "value": -5}
        with pytest.raises(ValueError, match="must be positive"):
            validate_distribution_config(dist_cfg, "test")

    def test_exponential_valid(self):
        """Valid exponential distribution passes validation."""
        dist_cfg = {"distribution": "exponential", "mean": 100}
        validate_distribution_config(dist_cfg, "test")

    def test_exponential_missing_mean(self):
        """Exponential distribution without mean raises error."""
        dist_cfg = {"distribution": "exponential"}
        with pytest.raises(ValueError, match="requires 'mean' parameter"):
            validate_distribution_config(dist_cfg, "test")

    def test_exponential_negative_mean(self):
        """Exponential distribution with negative mean raises error."""
        dist_cfg = {"distribution": "exponential", "mean": -10}
        with pytest.raises(ValueError, match="must be positive"):
            validate_distribution_config(dist_cfg, "test")

    def test_weibull_valid(self):
        """Valid Weibull distribution passes validation."""
        dist_cfg = {"distribution": "weibull", "shape": 2.5, "scale": 500}
        validate_distribution_config(dist_cfg, "test")

    def test_weibull_missing_parameters(self):
        """Weibull distribution without shape/scale raises error."""
        dist_cfg = {"distribution": "weibull", "shape": 2.5}
        with pytest.raises(ValueError, match="requires 'shape' and 'scale' parameters"):
            validate_distribution_config(dist_cfg, "test")

    def test_weibull_negative_parameters(self):
        """Weibull distribution with negative parameters raises error."""
        dist_cfg = {"distribution": "weibull", "shape": -1, "scale": 500}
        with pytest.raises(ValueError, match="must be positive"):
            validate_distribution_config(dist_cfg, "test")

    def test_lognormal_valid(self):
        """Valid lognormal distribution passes validation."""
        dist_cfg = {"distribution": "lognormal", "mean": 15, "std": 5}
        validate_distribution_config(dist_cfg, "test")

    def test_lognormal_missing_parameters(self):
        """Lognormal distribution without mean/std raises error."""
        dist_cfg = {"distribution": "lognormal", "mean": 15}
        with pytest.raises(ValueError, match="requires 'mean' and 'std' parameters"):
            validate_distribution_config(dist_cfg, "test")

    def test_normal_valid(self):
        """Valid normal distribution passes validation."""
        dist_cfg = {"distribution": "normal", "mean": 50, "std": 10}
        validate_distribution_config(dist_cfg, "test")

    def test_uniform_valid(self):
        """Valid uniform distribution passes validation."""
        dist_cfg = {"distribution": "uniform", "min": 10, "max": 20}
        validate_distribution_config(dist_cfg, "test")

    def test_uniform_invalid_range(self):
        """Uniform distribution with min >= max raises error."""
        dist_cfg = {"distribution": "uniform", "min": 20, "max": 10}
        with pytest.raises(ValueError, match="min must be less than max"):
            validate_distribution_config(dist_cfg, "test")

    def test_unknown_distribution(self):
        """Unknown distribution type raises error."""
        dist_cfg = {"distribution": "gamma"}  # Not supported
        with pytest.raises(ValueError, match="unknown distribution type"):
            validate_distribution_config(dist_cfg, "test")

    def test_missing_distribution_key(self):
        """Missing 'distribution' key raises error."""
        dist_cfg = {"mean": 100}
        with pytest.raises(ValueError, match="missing 'distribution' field"):
            validate_distribution_config(dist_cfg, "test")


class TestFailureModeValidation:
    """Test failure mode configuration validation."""

    def test_valid_failure_modes(self):
        """Valid failure modes configuration passes validation."""
        machine_cfg = {
            "name": "M1",
            "failure_modes": [
                {
                    "name": "mechanical",
                    "type": "wearout",
                    "mttf": {"distribution": "weibull", "shape": 2.5, "scale": 500},
                    "mttr": {"distribution": "constant", "value": 10}
                }
            ]
        }
        validate_failure_modes(machine_cfg)  # Should not raise

    def test_multiple_failure_modes(self):
        """Multiple failure modes pass validation."""
        machine_cfg = {
            "name": "M1",
            "failure_modes": [
                {
                    "name": "mechanical",
                    "type": "wearout",
                    "mttf": {"distribution": "constant", "value": 100},
                    "mttr": {"distribution": "constant", "value": 10}
                },
                {
                    "name": "electrical",
                    "type": "random",
                    "mttf": {"distribution": "exponential", "mean": 200},
                    "mttr": {"distribution": "constant", "value": 5}
                }
            ]
        }
        validate_failure_modes(machine_cfg)

    def test_failure_modes_not_list(self):
        """failure_modes as non-list raises error."""
        machine_cfg = {
            "name": "M1",
            "failure_modes": "not_a_list"
        }
        with pytest.raises(ValueError, match="must be a list"):
            validate_failure_modes(machine_cfg)

    def test_failure_modes_empty_list(self):
        """Empty failure_modes list raises error."""
        machine_cfg = {
            "name": "M1",
            "failure_modes": []
        }
        with pytest.raises(ValueError, match="list is empty"):
            validate_failure_modes(machine_cfg)

    def test_failure_mode_missing_name(self):
        """Failure mode without name raises error."""
        machine_cfg = {
            "name": "M1",
            "failure_modes": [
                {
                    "type": "wearout",
                    "mttf": {"distribution": "constant", "value": 100},
                    "mttr": {"distribution": "constant", "value": 10}
                }
            ]
        }
        with pytest.raises(ValueError, match="missing 'name' field"):
            validate_failure_modes(machine_cfg)

    def test_failure_mode_missing_type(self):
        """Failure mode without type raises error."""
        machine_cfg = {
            "name": "M1",
            "failure_modes": [
                {
                    "name": "mechanical",
                    "mttf": {"distribution": "constant", "value": 100},
                    "mttr": {"distribution": "constant", "value": 10}
                }
            ]
        }
        with pytest.raises(ValueError, match="missing 'type' field"):
            validate_failure_modes(machine_cfg)

    def test_failure_mode_invalid_type(self):
        """Failure mode with invalid type raises error."""
        machine_cfg = {
            "name": "M1",
            "failure_modes": [
                {
                    "name": "mechanical",
                    "type": "invalid_type",
                    "mttf": {"distribution": "constant", "value": 100},
                    "mttr": {"distribution": "constant", "value": 10}
                }
            ]
        }
        with pytest.raises(ValueError, match="invalid type"):
            validate_failure_modes(machine_cfg)

    def test_failure_mode_missing_mttf(self):
        """Failure mode without mttf raises error."""
        machine_cfg = {
            "name": "M1",
            "failure_modes": [
                {
                    "name": "mechanical",
                    "type": "wearout",
                    "mttr": {"distribution": "constant", "value": 10}
                }
            ]
        }
        with pytest.raises(ValueError, match="missing 'mttf' field"):
            validate_failure_modes(machine_cfg)

    def test_failure_mode_missing_mttr(self):
        """Failure mode without mttr raises error."""
        machine_cfg = {
            "name": "M1",
            "failure_modes": [
                {
                    "name": "mechanical",
                    "type": "wearout",
                    "mttf": {"distribution": "constant", "value": 100}
                }
            ]
        }
        with pytest.raises(ValueError, match="missing 'mttr' field"):
            validate_failure_modes(machine_cfg)

    def test_duplicate_failure_mode_names(self):
        """Duplicate failure mode names raise error."""
        machine_cfg = {
            "name": "M1",
            "failure_modes": [
                {
                    "name": "mechanical",
                    "type": "wearout",
                    "mttf": {"distribution": "constant", "value": 100},
                    "mttr": {"distribution": "constant", "value": 10}
                },
                {
                    "name": "mechanical",  # Duplicate
                    "type": "random",
                    "mttf": {"distribution": "constant", "value": 100},
                    "mttr": {"distribution": "constant", "value": 10}
                }
            ]
        }
        with pytest.raises(ValueError, match="must be unique"):
            validate_failure_modes(machine_cfg)

    def test_no_failure_modes_field(self):
        """Machine without failure_modes field passes validation."""
        machine_cfg = {"name": "M1"}
        validate_failure_modes(machine_cfg)  # Should not raise (optional field)


class TestMaintenanceStrategyValidation:
    """Test maintenance strategy configuration validation."""

    def test_corrective_strategy(self):
        """Corrective maintenance strategy passes validation."""
        machine_cfg = {
            "name": "M1",
            "maintenance_strategy": {
                "type": "corrective"
            }
        }
        validate_maintenance_strategy(machine_cfg)

    def test_preventive_strategy_valid(self):
        """Preventive maintenance strategy with pm_interval passes validation."""
        machine_cfg = {
            "name": "M1",
            "maintenance_strategy": {
                "type": "preventive",
                "pm_interval": 100
            }
        }
        validate_maintenance_strategy(machine_cfg)

    def test_preventive_missing_pm_interval(self):
        """Preventive strategy without pm_interval raises error."""
        machine_cfg = {
            "name": "M1",
            "maintenance_strategy": {
                "type": "preventive"
            }
        }
        with pytest.raises(ValueError, match="requires 'pm_interval' parameter"):
            validate_maintenance_strategy(machine_cfg)

    def test_preventive_negative_pm_interval(self):
        """Preventive strategy with negative pm_interval raises error."""
        machine_cfg = {
            "name": "M1",
            "maintenance_strategy": {
                "type": "preventive",
                "pm_interval": -10
            }
        }
        with pytest.raises(ValueError, match="must be positive"):
            validate_maintenance_strategy(machine_cfg)

    def test_predictive_strategy_valid(self):
        """Predictive maintenance strategy with cbm_threshold passes validation."""
        machine_cfg = {
            "name": "M1",
            "maintenance_strategy": {
                "type": "predictive",
                "cbm_threshold": 1
            }
        }
        validate_maintenance_strategy(machine_cfg)

    def test_predictive_missing_cbm_threshold(self):
        """Predictive strategy without cbm_threshold raises error."""
        machine_cfg = {
            "name": "M1",
            "maintenance_strategy": {
                "type": "predictive"
            }
        }
        with pytest.raises(ValueError, match="requires 'cbm_threshold' parameter"):
            validate_maintenance_strategy(machine_cfg)

    def test_predictive_negative_cbm_threshold(self):
        """Predictive strategy with negative cbm_threshold raises error."""
        machine_cfg = {
            "name": "M1",
            "maintenance_strategy": {
                "type": "predictive",
                "cbm_threshold": -1
            }
        }
        with pytest.raises(ValueError, match="must be non-negative"):
            validate_maintenance_strategy(machine_cfg)

    def test_invalid_strategy_type(self):
        """Invalid maintenance strategy type raises error."""
        machine_cfg = {
            "name": "M1",
            "maintenance_strategy": {
                "type": "invalid_type"
            }
        }
        with pytest.raises(ValueError, match="invalid maintenance strategy type"):
            validate_maintenance_strategy(machine_cfg)

    def test_strategy_not_dict(self):
        """maintenance_strategy as non-dict raises error."""
        machine_cfg = {
            "name": "M1",
            "maintenance_strategy": "not_a_dict"
        }
        with pytest.raises(ValueError, match="must be a dictionary"):
            validate_maintenance_strategy(machine_cfg)

    def test_strategy_missing_type(self):
        """maintenance_strategy without type raises error."""
        machine_cfg = {
            "name": "M1",
            "maintenance_strategy": {}
        }
        with pytest.raises(ValueError, match="missing 'type' field"):
            validate_maintenance_strategy(machine_cfg)

    def test_no_maintenance_strategy_field(self):
        """Machine without maintenance_strategy field passes validation."""
        machine_cfg = {"name": "M1"}
        validate_maintenance_strategy(machine_cfg)  # Should not raise (optional field)


class TestHistorianConfigValidation:
    """Tests for historian configuration validation."""

    def test_no_historian_config_passes(self):
        """Config without historian section passes validation."""
        config = {"machines": [], "buffers": []}
        validate_historian_config(config)  # Should not raise

    def test_disabled_historian_passes(self):
        """Disabled historian passes validation."""
        config = {"historian": {"enabled": False}}
        validate_historian_config(config)  # Should not raise

    def test_valid_csv_config_passes(self):
        """Valid CSV historian config passes validation."""
        config = {
            "historian": {
                "enabled": True,
                "csv": {"enabled": True, "output_dir": "results/historian"},
            }
        }
        validate_historian_config(config)  # Should not raise

    def test_csv_missing_output_dir_raises(self):
        """CSV enabled without output_dir raises error."""
        config = {
            "historian": {
                "enabled": True,
                "csv": {"enabled": True},
            }
        }
        with pytest.raises(ValueError, match="output_dir"):
            validate_historian_config(config)

    def test_csv_invalid_max_size_raises(self):
        """CSV with non-positive max_file_size_mb raises error."""
        config = {
            "historian": {
                "enabled": True,
                "csv": {"enabled": True, "output_dir": "results", "max_file_size_mb": -1},
            }
        }
        with pytest.raises(ValueError, match="max_file_size_mb"):
            validate_historian_config(config)

    def test_influxdb_missing_fields_raises(self):
        """InfluxDB enabled without required fields raises error."""
        config = {
            "historian": {
                "enabled": True,
                "influxdb": {"enabled": True, "url": "http://localhost:8086"},
            }
        }
        with pytest.raises(ValueError, match="token"):
            validate_historian_config(config)

    def test_neo4j_missing_fields_raises(self):
        """Neo4j enabled without required fields raises error."""
        config = {
            "historian": {
                "enabled": True,
                "neo4j": {"enabled": True, "uri": "bolt://localhost:7687"},
            }
        }
        with pytest.raises(ValueError, match="user"):
            validate_historian_config(config)

    def test_invalid_production_summary_interval_raises(self):
        """Non-positive production_summary_interval raises error."""
        config = {
            "historian": {
                "enabled": True,
                "events": {"production_summary_interval": 0},
            }
        }
        with pytest.raises(ValueError, match="production_summary_interval"):
            validate_historian_config(config)

    def test_historian_line_scenario_loads(self):
        """historian_line scenario loads and validates successfully."""
        config = load_line_config("historian_line")
        assert "historian" in config
        assert config["historian"]["enabled"] is True
        assert config["historian"]["csv"]["enabled"] is True
