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
