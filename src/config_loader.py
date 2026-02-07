"""
Configuration Loader for Simantha OPC UA Server

Loads and validates line topology configurations from YAML files.
"""
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
    config_path = Path(__file__).parent.parent / "config" / "line_models.yaml"

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

    print(f"[OK] Configuration validated: {len(machines)} machines, {len(buffers)} buffers")
