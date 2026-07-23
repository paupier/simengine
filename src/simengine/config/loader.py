"""
Configuration Loader for Simantha OPC UA Server

Loads and validates line topology configurations from YAML files.
"""
import os
import yaml
from pathlib import Path
from typing import Dict, List, Any


def get_config_path() -> Path:
    """Path of the scenario YAML file (SIMENGINE_CONFIG_PATH overrides)."""
    return Path(os.environ.get(
        "SIMENGINE_CONFIG_PATH",
        str(Path(__file__).parents[3] / "config" / "scenarios.yaml")
    ))


def get_recipes_dir() -> Path:
    """Directory of recipe YAML files (SIMENGINE_RECIPE_PATH overrides)."""
    return Path(os.environ.get(
        "SIMENGINE_RECIPE_PATH",
        str(Path(__file__).parents[3] / "config" / "recipes")
    ))


def load_line_config(scenario_name: str = "balanced_line") -> Dict[str, Any]:
    """
    Load line configuration from YAML file.

    Args:
        scenario_name: Key from line_models.yaml (e.g., "balanced_line", "extended_line")

    Returns:
        Dict with keys: stations, buffers, comms, ...

    Raises:
        ValueError: If scenario not found or config is invalid
    """
    config_path = get_config_path()

    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    with open(config_path, "r") as f:
        all_configs = yaml.safe_load(f)

    if scenario_name not in all_configs:
        available = list(all_configs.keys())
        raise ValueError(
            f"Scenario '{scenario_name}' not found in scenario config. "
            f"Available scenarios: {available}"
        )

    config = all_configs[scenario_name]

    # Validate config structure
    validate_serial_topology(config)

    return config


def validate_serial_topology(config: Dict[str, Any]) -> None:
    """
    Validate that config represents a valid serial line topology (§3 schema).

    Stations are connected in list order through the buffers, which carry no
    explicit routing: Source -> S1 -> B1 -> S2 -> ... -> Sink.

    Args:
        config: Configuration dictionary

    Raises:
        ValueError: If config is invalid or represents non-serial topology
    """
    # Check required fields
    if "stations" not in config or "buffers" not in config:
        raise ValueError("Config must have 'stations' and 'buffers' fields")

    stations = config["stations"]
    buffers = config["buffers"]

    # Must have at least 2 stations
    if len(stations) < 2:
        raise ValueError(f"Must have at least 2 stations, got {len(stations)}")

    # Serial topology: N stations require N-1 buffers
    if len(buffers) != len(stations) - 1:
        raise ValueError(
            f"Serial topology requires {len(stations)-1} buffers for {len(stations)} stations, "
            f"got {len(buffers)} buffers"
        )

    # Validate station names are unique
    station_names = [s.get("name") for s in stations]
    if len(station_names) != len(set(station_names)):
        raise ValueError("Station names must be unique")

    # Validate buffer names are unique
    buffer_names = [b.get("name") for b in buffers]
    if len(buffer_names) != len(set(buffer_names)):
        raise ValueError("Buffer names must be unique")

    # Validate each station has required fields
    for i, station in enumerate(stations):
        if "name" not in station:
            raise ValueError(f"Station at index {i} missing 'name' field")

        if "cycle_time" not in station and "target_ppm" not in station:
            raise ValueError(
                f"Station '{station['name']}': must specify 'cycle_time' or 'target_ppm'"
            )
        if "cycle_time" in station:
            ct = station["cycle_time"]
            if not isinstance(ct, (int, float)) or ct <= 0:
                raise ValueError(
                    f"Station '{station['name']}': cycle_time must be positive, got {ct}"
                )

        # Validate quality parameters (defect_rate, target_ppm)
        validate_machine_quality_config(station)

        # Validate optional per-station blocks
        validate_failure_modes(station)
        validate_health(station)
        validate_process_values(station)
        validate_cycle_stops(station)

    # Validate each buffer has required fields
    for i, buffer in enumerate(buffers):
        if "name" not in buffer:
            raise ValueError(f"Buffer at index {i} missing 'name' field")
        capacity = buffer.get("capacity")
        if not isinstance(capacity, int) or capacity <= 0:
            raise ValueError(
                f"Buffer '{buffer['name']}': capacity must be a positive integer, got {capacity}"
            )

    # Validate optional scenario-level blocks
    validate_comms(config)
    validate_historians(config)
    validate_warm_up(config)
    validate_fault_injection(config)

    print(f"[OK] Configuration validated: {len(stations)} stations, {len(buffers)} buffers")


def resolve_cycle_time(station_cfg: dict) -> float:
    """Return the effective cycle time: target_ppm takes precedence (60/ppm)."""
    if "target_ppm" in station_cfg:
        return 60.0 / float(station_cfg["target_ppm"])
    return float(station_cfg["cycle_time"])


VALID_PV_PROFILES = ("cycle_peak", "first_order_lag", "cycle_ramp", "constant_noise")

# Required keys per profile (§5); distributions validated separately.
_PV_REQUIRED_KEYS = {
    "cycle_peak": ("baseline", "peak"),
    "first_order_lag": ("setpoint", "tau", "initial"),
    "cycle_ramp": ("range",),
    "constant_noise": ("mean",),
}

_PV_DIST_KEYS = ("peak", "noise")


def validate_health(station_cfg: dict) -> None:
    """
    Validate the per-station health block (§3): h_max, p_degrade, mttr.

    Raises:
        ValueError: If the health configuration is invalid.
    """
    if "health" not in station_cfg:
        return

    name = station_cfg["name"]
    health = station_cfg["health"]
    if not isinstance(health, dict):
        raise ValueError(f"Station '{name}': health must be a mapping")

    h_max = health.get("h_max")
    if not isinstance(h_max, int) or h_max < 1:
        raise ValueError(f"Station '{name}': health.h_max must be a positive integer")

    p_degrade = health.get("p_degrade")
    if p_degrade is None or not isinstance(p_degrade, (int, float)) or not (0.0 <= p_degrade <= 1.0):
        raise ValueError(f"Station '{name}': health.p_degrade must be in [0, 1]")

    if "mttr" not in health:
        raise ValueError(f"Station '{name}': health block requires 'mttr' distribution")
    validate_distribution_config(health["mttr"], f"{name}.health.mttr")


def validate_process_values(station_cfg: dict) -> None:
    """
    Validate the per-station process_values list (§3/§5).

    Raises:
        ValueError: If any process value config is invalid.
    """
    if "process_values" not in station_cfg:
        return

    name = station_cfg["name"]
    pvs = station_cfg["process_values"]
    if not isinstance(pvs, list):
        raise ValueError(f"Station '{name}': process_values must be a list")

    pv_names = []
    for i, pv in enumerate(pvs):
        if not isinstance(pv, dict) or "name" not in pv:
            raise ValueError(f"Station '{name}': process value at index {i} missing 'name'")
        pv_name = pv["name"]
        pv_names.append(pv_name)

        if "unit" not in pv:
            raise ValueError(f"Station '{name}': process value '{pv_name}' missing 'unit'")

        profile = pv.get("profile")
        if profile not in VALID_PV_PROFILES:
            raise ValueError(
                f"Station '{name}': process value '{pv_name}' has invalid profile "
                f"'{profile}'. Must be one of: {', '.join(VALID_PV_PROFILES)}"
            )

        for key in _PV_REQUIRED_KEYS[profile]:
            if key not in pv:
                raise ValueError(
                    f"Station '{name}': process value '{pv_name}' (profile {profile}) "
                    f"missing required key '{key}'"
                )

        if profile == "cycle_ramp":
            rng = pv["range"]
            if (not isinstance(rng, list) or len(rng) != 2
                    or not all(isinstance(v, (int, float)) for v in rng)
                    or rng[0] >= rng[1]):
                raise ValueError(
                    f"Station '{name}': process value '{pv_name}': range must be "
                    f"[low, high] with low < high"
                )

        for key in _PV_DIST_KEYS:
            if key in pv:
                validate_distribution_config(pv[key], f"{name}.{pv_name}.{key}")

        if "health_drift" in pv:
            hd = pv["health_drift"]
            if not isinstance(hd, (int, float)) or hd < 0:
                raise ValueError(
                    f"Station '{name}': process value '{pv_name}': health_drift must be >= 0"
                )

        alarm_high = pv.get("alarm_high")
        alarm_low = pv.get("alarm_low")
        if alarm_high is not None and alarm_low is not None and alarm_high <= alarm_low:
            raise ValueError(
                f"Station '{name}': process value '{pv_name}': alarm_high must be "
                f"greater than alarm_low"
            )

    if len(pv_names) != len(set(pv_names)):
        raise ValueError(f"Station '{name}': process value names must be unique")


def validate_cycle_stops(station_cfg: dict) -> None:
    """
    Validate the per-station cycle_stops list (§3): reason + mtbe/duration
    distributions.

    Raises:
        ValueError: If any cycle stop config is invalid.
    """
    if "cycle_stops" not in station_cfg:
        return

    name = station_cfg["name"]
    stops = station_cfg["cycle_stops"]
    if not isinstance(stops, list):
        raise ValueError(f"Station '{name}': cycle_stops must be a list")

    reasons = []
    for i, stop in enumerate(stops):
        if not isinstance(stop, dict) or "reason" not in stop:
            raise ValueError(f"Station '{name}': cycle stop at index {i} missing 'reason'")
        reasons.append(stop["reason"])

        for key in ("mtbe", "duration"):
            if key not in stop:
                raise ValueError(
                    f"Station '{name}': cycle stop '{stop['reason']}' missing '{key}' distribution"
                )
            validate_distribution_config(stop[key], f"{name}.{stop['reason']}.{key}")

    if len(reasons) != len(set(reasons)):
        raise ValueError(f"Station '{name}': cycle stop reasons must be unique")


def _validate_broker_url(url: str, context: str) -> None:
    if not isinstance(url, str) or not url.startswith("mqtt://"):
        raise ValueError(f"{context}: broker must be an mqtt://host:port URL, got {url!r}")
    rest = url[len("mqtt://"):]
    if ":" not in rest:
        raise ValueError(f"{context}: broker URL must include a port, got {url!r}")
    host, _, port = rest.rpartition(":")
    if not host or not port.isdigit() or not (0 < int(port) < 65536):
        raise ValueError(f"{context}: broker URL must be mqtt://host:port, got {url!r}")


def validate_comms(config: Dict[str, Any]) -> None:
    """
    Validate the scenario-level comms block (§3): opcua, opcua_mqtt, sparkplugb.

    Raises:
        ValueError: If the comms configuration is invalid.
    """
    if "comms" not in config:
        return

    comms = config["comms"]
    if not isinstance(comms, dict):
        raise ValueError("comms must be a mapping")

    for proto in ("opcua", "opcua_mqtt", "sparkplugb"):
        block = comms.get(proto)
        if block is None:
            continue
        if not isinstance(block, dict):
            raise ValueError(f"comms.{proto} must be a mapping")
        enabled = block.get("enabled", False)
        if not isinstance(enabled, bool):
            raise ValueError(f"comms.{proto}.enabled must be a boolean")

    opcua = comms.get("opcua", {})
    if "port" in opcua:
        port = opcua["port"]
        if not isinstance(port, int) or not (0 < port < 65536):
            raise ValueError(f"comms.opcua.port must be an integer in 1-65535, got {port}")

    for proto in ("opcua_mqtt", "sparkplugb"):
        block = comms.get(proto, {})
        if block.get("enabled", False):
            if "broker" not in block:
                raise ValueError(f"comms.{proto}: broker required when enabled")
            _validate_broker_url(block["broker"], f"comms.{proto}")

    mqtt_block = comms.get("opcua_mqtt", {})
    if "publish_interval" in mqtt_block:
        interval = mqtt_block["publish_interval"]
        if not isinstance(interval, (int, float)) or interval <= 0:
            raise ValueError("comms.opcua_mqtt.publish_interval must be positive")

    spb = comms.get("sparkplugb", {})
    if spb.get("enabled", False):
        for key in ("group_id", "edge_node_id"):
            if not isinstance(spb.get(key), str) or not spb.get(key):
                raise ValueError(f"comms.sparkplugb.{key} required when enabled")


def validate_historians(config: Dict[str, Any]) -> None:
    """
    Validate the scenario-level historians list (§3): plugin name strings.

    Raises:
        ValueError: If the historians configuration is invalid.
    """
    if "historians" not in config:
        return
    historians = config["historians"]
    if not isinstance(historians, list) or not all(
        isinstance(h, str) and h for h in historians
    ):
        raise ValueError("historians must be a list of plugin name strings")


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

    if "target_ppm" in machine_cfg:
        ppm = machine_cfg["target_ppm"]
        if not isinstance(ppm, (int, float)) or ppm <= 0:
            raise ValueError(
                f"Machine '{machine_cfg['name']}': target_ppm must be positive, got {ppm}"
            )
        if "cycle_time" in machine_cfg:
            import logging
            logging.warning(
                f"Machine '{machine_cfg['name']}': target_ppm overrides cycle_time"
            )


# ========== Advanced Failure Mode Validation ==========


def validate_failure_modes(machine_cfg: dict) -> None:
    """
    Validate failure_modes configuration.

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
    Validate distribution configuration.

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


def validate_historian_config(config: Dict[str, Any]) -> None:
    """
    Validate historian configuration.

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


def validate_warm_up(config: Dict[str, Any]) -> None:
    """
    Validate warm_up_time configuration.

    Args:
        config: Scenario configuration dictionary

    Raises:
        ValueError: If warm_up_time is negative or non-numeric
    """
    if "warm_up_time" not in config:
        return

    wut = config["warm_up_time"]
    if not isinstance(wut, (int, float)):
        raise ValueError("warm_up_time must be numeric")
    if wut < 0:
        raise ValueError("warm_up_time must be non-negative")


def validate_fault_injection(config: Dict[str, Any]) -> None:
    """Validate the optional fault_injection block at scenario level."""
    fi = config.get("fault_injection")
    if fi is None:
        return

    scale = fi.get("spc_noise_scale", 0.0)
    if not isinstance(scale, (int, float)) or scale < 0:
        raise ValueError(
            f"fault_injection.spc_noise_scale must be a non-negative number, got {scale!r}"
        )

    REQUIRED_FIELDS = {
        "health_delta":      ["machine", "at_sim_time", "health_delta"],
        "noise_ramp":        ["machine", "at_sim_time", "duration", "target_multiplier"],
        "cycle_time_offset": ["machine", "at_sim_time", "offset"],
    }

    for i, inj in enumerate(fi.get("injections", [])):
        t = inj.get("type")
        if t not in REQUIRED_FIELDS:
            raise ValueError(
                f"fault_injection.injections[{i}]: Unknown injection type {t!r}. "
                f"Valid types: {list(REQUIRED_FIELDS)}"
            )
        for field in REQUIRED_FIELDS[t]:
            if field not in inj:
                raise ValueError(
                    f"fault_injection.injections[{i}] (type={t!r}): "
                    f"missing required field '{field}'"
                )
