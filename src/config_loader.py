"""
Configuration Loader for Simantha OPC UA Server

Loads and validates line topology configurations from YAML files.
"""
import os
import yaml
from pathlib import Path
from typing import Dict, List, Any


def load_line_config(scenario_name: str = "balanced_line") -> Dict[str, Any]:
    """
    Load line configuration from YAML file.

    Args:
        scenario_name: Key from line_models.yaml (e.g., "balanced_line", "extended_line")

    Returns:
        Dict with keys: machines, buffers, maintainer

    Raises:
        ValueError: If scenario not found or config is invalid
    """
    config_path = Path(os.environ.get(
        "SIMANTHA_CONFIG_PATH",
        str(Path(__file__).parent.parent / "config" / "line_models.yaml")
    ))

    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    with open(config_path, "r") as f:
        all_configs = yaml.safe_load(f)

    if scenario_name not in all_configs:
        available = list(all_configs.keys())
        raise ValueError(
            f"Scenario '{scenario_name}' not found in line_models.yaml. "
            f"Available scenarios: {available}"
        )

    config = all_configs[scenario_name]

    # Validate config structure
    validate_serial_topology(config)

    return config


def validate_serial_topology(config: Dict[str, Any]) -> None:
    """
    Validate that config represents a valid serial line topology.

    Args:
        config: Configuration dictionary

    Raises:
        ValueError: If config is invalid or represents non-serial topology
    """
    # Check required fields
    if "machines" not in config or "buffers" not in config:
        raise ValueError("Config must have 'machines' and 'buffers' fields")

    machines = config["machines"]
    buffers = config["buffers"]

    # Must have at least 2 machines
    if len(machines) < 2:
        raise ValueError(f"Must have at least 2 machines, got {len(machines)}")

    # Serial topology: N machines require N-1 buffers
    if len(buffers) != len(machines) - 1:
        raise ValueError(
            f"Serial topology requires {len(machines)-1} buffers for {len(machines)} machines, "
            f"got {len(buffers)} buffers"
        )

    # Validate machine names are unique
    machine_names = [m["name"] for m in machines]
    if len(machine_names) != len(set(machine_names)):
        raise ValueError("Machine names must be unique")

    # Validate buffer names are unique
    buffer_names = [b["name"] for b in buffers]
    if len(buffer_names) != len(set(buffer_names)):
        raise ValueError("Buffer names must be unique")

    # Validate each machine has required fields
    for i, machine in enumerate(machines):
        if "name" not in machine:
            raise ValueError(f"Machine at index {i} missing 'name' field")

        # Validate quality parameters (Phase 8)
        validate_machine_quality_config(machine)

        # Validate advanced failure modes (Phase 10)
        if machine.get("enable_advanced_failures", False):
            validate_failure_modes(machine)
            validate_maintenance_strategy(machine)

    # Validate each buffer has required fields and correct routing
    for i, buffer in enumerate(buffers):
        if "name" not in buffer:
            raise ValueError(f"Buffer at index {i} missing 'name' field")

        if "upstream" not in buffer or "downstream" not in buffer:
            raise ValueError(f"Buffer '{buffer['name']}' missing upstream/downstream routing")

        expected_upstream = machine_names[i]
        expected_downstream = machine_names[i + 1]

        if buffer["upstream"] != expected_upstream or buffer["downstream"] != expected_downstream:
            raise ValueError(
                f"Buffer '{buffer['name']}' routing invalid. "
                f"Expected {expected_upstream}→{expected_downstream}, "
                f"got {buffer['upstream']}→{buffer['downstream']}"
            )

    # Validate quality routing (Phase 14)
    for machine in machines:
        validate_quality_routing(machine)
    validate_scrap_sinks(config)

    # Validate historian config (Phase 13)
    validate_historian_config(config)

    print(f"[OK] Configuration validated: {len(machines)} machines, {len(buffers)} buffers")


def validate_machine_quality_config(machine_cfg: dict) -> None:
    """
    Validate machine quality parameters.

    Args:
        machine_cfg: Machine configuration dictionary

    Raises:
        ValueError: If quality parameters are invalid
    """
    if "defect_rate" in machine_cfg:
        rate = machine_cfg["defect_rate"]
        if not (0.0 <= rate <= 1.0):
            raise ValueError(
                f"Machine '{machine_cfg['name']}': defect_rate must be 0.0-1.0, got {rate}"
            )

    if "health_multiplier" in machine_cfg:
        mult = machine_cfg["health_multiplier"]
        if mult < 0:
            raise ValueError(
                f"Machine '{machine_cfg['name']}': health_multiplier must be >= 0, got {mult}"
            )
"""
Phase 10 Configuration Validation Extensions

Additional validation functions for advanced failure modes.
These will be integrated into config_loader.py.
"""


def validate_failure_modes(machine_cfg: dict) -> None:
    """
    Validate failure_modes configuration (Phase 10).

    Args:
        machine_cfg: Machine configuration dictionary

    Raises:
        ValueError: If failure modes configuration is invalid
    """
    if "failure_modes" not in machine_cfg:
        return

    failure_modes = machine_cfg["failure_modes"]

    if not isinstance(failure_modes, list):
        raise ValueError(f"Machine '{machine_cfg['name']}': failure_modes must be a list")

    if len(failure_modes) == 0:
        raise ValueError(f"Machine '{machine_cfg['name']}': failure_modes list is empty")

    failure_mode_names = []

    for i, fm in enumerate(failure_modes):
        # Required fields
        if "name" not in fm:
            raise ValueError(
                f"Machine '{machine_cfg['name']}': failure mode at index {i} missing 'name' field"
            )

        fm_name = fm["name"]
        failure_mode_names.append(fm_name)

        if "type" not in fm:
            raise ValueError(
                f"Machine '{machine_cfg['name']}': failure mode '{fm_name}' missing 'type' field"
            )

        # Valid types
        valid_types = ["wearout", "random", "cycle_dependent"]
        if fm["type"] not in valid_types:
            raise ValueError(
                f"Machine '{machine_cfg['name']}': failure mode '{fm_name}' has invalid type '{fm['type']}'. "
                f"Must be one of: {', '.join(valid_types)}"
            )

        # Distribution configs
        if "mttf" not in fm:
            raise ValueError(
                f"Machine '{machine_cfg['name']}': failure mode '{fm_name}' missing 'mttf' field"
            )

        if "mttr" not in fm:
            raise ValueError(
                f"Machine '{machine_cfg['name']}': failure mode '{fm_name}' missing 'mttr' field"
            )

        validate_distribution_config(fm["mttf"], f"{machine_cfg['name']}.{fm_name}.mttf")
        validate_distribution_config(fm["mttr"], f"{machine_cfg['name']}.{fm_name}.mttr")

    # Check for duplicate failure mode names
    if len(failure_mode_names) != len(set(failure_mode_names)):
        raise ValueError(
            f"Machine '{machine_cfg['name']}': failure mode names must be unique"
        )


def validate_distribution_config(dist_cfg: dict, context: str) -> None:
    """
    Validate distribution configuration (Phase 10).

    Args:
        dist_cfg: Distribution configuration dictionary
        context: Context string for error messages (e.g., "M1.mechanical.mttf")

    Raises:
        ValueError: If distribution configuration is invalid
    """
    if "distribution" not in dist_cfg:
        raise ValueError(f"{context}: missing 'distribution' field")

    dist_type = dist_cfg["distribution"]

    # Validate required parameters per distribution type
    if dist_type == "constant":
        if "value" not in dist_cfg:
            raise ValueError(f"{context}: constant distribution requires 'value' parameter")
        if not isinstance(dist_cfg["value"], (int, float)):
            raise ValueError(f"{context}: constant value must be numeric")
        if dist_cfg["value"] <= 0:
            raise ValueError(f"{context}: constant value must be positive")

    elif dist_type == "exponential":
        if "mean" not in dist_cfg:
            raise ValueError(f"{context}: exponential distribution requires 'mean' parameter")
        if not isinstance(dist_cfg["mean"], (int, float)):
            raise ValueError(f"{context}: exponential mean must be numeric")
        if dist_cfg["mean"] <= 0:
            raise ValueError(f"{context}: exponential mean must be positive")

    elif dist_type == "weibull":
        if "shape" not in dist_cfg or "scale" not in dist_cfg:
            raise ValueError(f"{context}: weibull distribution requires 'shape' and 'scale' parameters")
        if not isinstance(dist_cfg["shape"], (int, float)):
            raise ValueError(f"{context}: weibull shape must be numeric")
        if not isinstance(dist_cfg["scale"], (int, float)):
            raise ValueError(f"{context}: weibull scale must be numeric")
        if dist_cfg["shape"] <= 0:
            raise ValueError(f"{context}: weibull shape must be positive")
        if dist_cfg["scale"] <= 0:
            raise ValueError(f"{context}: weibull scale must be positive")

    elif dist_type == "lognormal":
        if "mean" not in dist_cfg or "std" not in dist_cfg:
            raise ValueError(f"{context}: lognormal distribution requires 'mean' and 'std' parameters")
        if not isinstance(dist_cfg["mean"], (int, float)):
            raise ValueError(f"{context}: lognormal mean must be numeric")
        if not isinstance(dist_cfg["std"], (int, float)):
            raise ValueError(f"{context}: lognormal std must be numeric")
        if dist_cfg["mean"] <= 0:
            raise ValueError(f"{context}: lognormal mean must be positive")
        if dist_cfg["std"] <= 0:
            raise ValueError(f"{context}: lognormal std must be positive")

    elif dist_type == "normal":
        if "mean" not in dist_cfg or "std" not in dist_cfg:
            raise ValueError(f"{context}: normal distribution requires 'mean' and 'std' parameters")
        if not isinstance(dist_cfg["mean"], (int, float)):
            raise ValueError(f"{context}: normal mean must be numeric")
        if not isinstance(dist_cfg["std"], (int, float)):
            raise ValueError(f"{context}: normal std must be numeric")
        if dist_cfg["std"] <= 0:
            raise ValueError(f"{context}: normal std must be positive")

    elif dist_type == "uniform":
        if "min" not in dist_cfg or "max" not in dist_cfg:
            raise ValueError(f"{context}: uniform distribution requires 'min' and 'max' parameters")
        if not isinstance(dist_cfg["min"], (int, float)):
            raise ValueError(f"{context}: uniform min must be numeric")
        if not isinstance(dist_cfg["max"], (int, float)):
            raise ValueError(f"{context}: uniform max must be numeric")
        if dist_cfg["min"] >= dist_cfg["max"]:
            raise ValueError(f"{context}: uniform min must be less than max")

    else:
        valid_types = ["constant", "exponential", "weibull", "lognormal", "normal", "uniform"]
        raise ValueError(
            f"{context}: unknown distribution type '{dist_type}'. "
            f"Must be one of: {', '.join(valid_types)}"
        )


def validate_maintenance_strategy(machine_cfg: dict) -> None:
    """
    Validate maintenance_strategy configuration (Phase 10).

    Args:
        machine_cfg: Machine configuration dictionary

    Raises:
        ValueError: If maintenance strategy configuration is invalid
    """
    if "maintenance_strategy" not in machine_cfg:
        return

    strategy = machine_cfg["maintenance_strategy"]

    if not isinstance(strategy, dict):
        raise ValueError(f"Machine '{machine_cfg['name']}': maintenance_strategy must be a dictionary")

    if "type" not in strategy:
        raise ValueError(f"Machine '{machine_cfg['name']}': maintenance_strategy missing 'type' field")

    valid_types = ["corrective", "preventive", "predictive"]
    if strategy["type"] not in valid_types:
        raise ValueError(
            f"Machine '{machine_cfg['name']}': invalid maintenance strategy type '{strategy['type']}'. "
            f"Must be one of: {', '.join(valid_types)}"
        )

    # Type-specific validation
    if strategy["type"] == "preventive":
        if "pm_interval" not in strategy:
            raise ValueError(
                f"Machine '{machine_cfg['name']}': preventive strategy requires 'pm_interval' parameter"
            )
        if not isinstance(strategy["pm_interval"], (int, float)):
            raise ValueError(
                f"Machine '{machine_cfg['name']}': pm_interval must be numeric"
            )
        if strategy["pm_interval"] <= 0:
            raise ValueError(
                f"Machine '{machine_cfg['name']}': pm_interval must be positive"
            )

    if strategy["type"] == "predictive":
        if "cbm_threshold" not in strategy:
            raise ValueError(
                f"Machine '{machine_cfg['name']}': predictive strategy requires 'cbm_threshold' parameter"
            )
        if not isinstance(strategy["cbm_threshold"], (int, float)):
            raise ValueError(
                f"Machine '{machine_cfg['name']}': cbm_threshold must be numeric"
            )
        if strategy["cbm_threshold"] < 0:
            raise ValueError(
                f"Machine '{machine_cfg['name']}': cbm_threshold must be non-negative"
            )


def validate_historian_config(config: Dict[str, Any]) -> None:
    """
    Validate historian configuration (Phase 13).

    Args:
        config: Full scenario configuration dictionary

    Raises:
        ValueError: If historian configuration is invalid
    """
    historian_cfg = config.get("historian")
    if not historian_cfg or not historian_cfg.get("enabled", False):
        return

    # Validate CSV backend
    csv_cfg = historian_cfg.get("csv", {})
    if csv_cfg.get("enabled", False):
        if "output_dir" not in csv_cfg:
            raise ValueError("historian.csv: 'output_dir' is required when CSV is enabled")
        max_size = csv_cfg.get("max_file_size_mb", 50)
        if not isinstance(max_size, (int, float)) or max_size <= 0:
            raise ValueError("historian.csv: 'max_file_size_mb' must be a positive number")

    # Validate InfluxDB backend
    influx_cfg = historian_cfg.get("influxdb", {})
    if influx_cfg.get("enabled", False):
        required_fields = ["url", "token", "org", "bucket"]
        for field in required_fields:
            if field not in influx_cfg:
                raise ValueError(f"historian.influxdb: '{field}' is required when InfluxDB is enabled")

    # Validate Neo4j backend
    neo4j_cfg = historian_cfg.get("neo4j", {})
    if neo4j_cfg.get("enabled", False):
        required_fields = ["uri", "user", "password"]
        for field in required_fields:
            if field not in neo4j_cfg:
                raise ValueError(f"historian.neo4j: '{field}' is required when Neo4j is enabled")
        max_parts = neo4j_cfg.get("max_parts", 10000)
        if not isinstance(max_parts, int) or max_parts <= 0:
            raise ValueError("historian.neo4j: 'max_parts' must be a positive integer")

    # Validate events config
    events_cfg = historian_cfg.get("events", {})
    interval = events_cfg.get("production_summary_interval", 60)
    if not isinstance(interval, (int, float)) or interval <= 0:
        raise ValueError("historian.events: 'production_summary_interval' must be a positive number")


def validate_quality_routing(machine_cfg: dict) -> None:
    """
    Validate quality_routing configuration for a machine (Phase 14).

    Args:
        machine_cfg: Machine configuration dictionary

    Raises:
        ValueError: If quality_routing configuration is invalid
    """
    qr = machine_cfg.get("quality_routing")
    if not qr or not qr.get("enabled", False):
        return

    name = machine_cfg.get("name", "unknown")

    mode = qr.get("mode", "scrap")
    if mode not in ("scrap", "rework", "scrap_and_rework"):
        raise ValueError(
            f"Machine '{name}': quality_routing.mode must be "
            f"'scrap', 'rework', or 'scrap_and_rework', got '{mode}'"
        )

    if mode in ("scrap", "scrap_and_rework") and "scrap_sink" not in qr:
        raise ValueError(
            f"Machine '{name}': quality_routing mode '{mode}' requires 'scrap_sink'"
        )

    if "defect_rate" in qr:
        dr = qr["defect_rate"]
        if not isinstance(dr, (int, float)) or not (0.0 <= dr <= 1.0):
            raise ValueError(
                f"Machine '{name}': quality_routing.defect_rate must be 0.0-1.0, got {dr}"
            )

    if "health_multiplier" in qr:
        hm = qr["health_multiplier"]
        if not isinstance(hm, (int, float)) or hm < 0:
            raise ValueError(
                f"Machine '{name}': quality_routing.health_multiplier must be >= 0, got {hm}"
            )

    if mode in ("rework", "scrap_and_rework"):
        rsr = qr.get("rework_success_rate", 0.8)
        if not isinstance(rsr, (int, float)) or not (0.0 <= rsr <= 1.0):
            raise ValueError(
                f"Machine '{name}': quality_routing.rework_success_rate must be 0.0-1.0, got {rsr}"
            )

        mr = qr.get("max_rework", 3)
        if not isinstance(mr, int) or mr < 1:
            raise ValueError(
                f"Machine '{name}': quality_routing.max_rework must be a positive integer, got {mr}"
            )


def validate_scrap_sinks(config: Dict[str, Any]) -> None:
    """
    Validate scrap_sinks configuration and cross-references (Phase 14).

    Args:
        config: Full scenario configuration dictionary

    Raises:
        ValueError: If scrap_sinks are invalid or referenced sinks don't exist
    """
    scrap_sinks = config.get("scrap_sinks", [])
    if not scrap_sinks:
        # No scrap sinks - verify no machine references one
        for m in config.get("machines", []):
            qr = m.get("quality_routing", {})
            if qr.get("enabled", False) and qr.get("scrap_sink"):
                raise ValueError(
                    f"Machine '{m['name']}' references scrap_sink '{qr['scrap_sink']}' "
                    f"but no 'scrap_sinks' section defined"
                )
        return

    # Validate scrap sink entries
    scrap_names = set()
    for i, s in enumerate(scrap_sinks):
        if "name" not in s:
            raise ValueError(f"Scrap sink at index {i} missing 'name' field")
        if s["name"] in scrap_names:
            raise ValueError(f"Duplicate scrap sink name: '{s['name']}'")
        scrap_names.add(s["name"])

    # Verify all referenced scrap sinks exist
    for m in config.get("machines", []):
        qr = m.get("quality_routing", {})
        if qr.get("enabled", False):
            ref = qr.get("scrap_sink")
            if ref and ref not in scrap_names:
                raise ValueError(
                    f"Machine '{m['name']}' references undefined scrap_sink '{ref}'"
                )
