"""
Recipe config parsing, validation, and segment-override machinery.

A recipe defines an ordered list of segments, each referencing a base scenario
(with optional overrides), separated by changeover periods with stochastic
durations. This enables planned-vs-actual changeover analysis and
multi-product production scheduling without permanently modifying scenario
configs.

The segment loop itself is owned by ``runtime.run_manager.RunManager._run_recipe``,
which calls into this module for parsing (``parse_recipe``), validation
(``validate_recipe``), per-segment config derivation (``apply_segment_overrides``),
and changeover sampling (``sample_changeover``).
"""

import copy
import os
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import numpy as np

import yaml

from simengine.config.loader import load_line_config, validate_distribution_config
from simengine.config.distributions import DistributionFactory


# ========== DATA CLASSES ==========


@dataclass
class ChangeoverConfig:
    """Changeover specification between two segments."""
    target: float               # planned changeover time (seconds)
    distribution_config: dict   # DistributionFactory-compatible dict


@dataclass
class SegmentConfig:
    """Single production segment within a recipe."""
    name: str
    quantity: Optional[int] = None      # stop after N parts (batch mode)
    duration: Optional[float] = None    # stop after N sim-seconds (time-boxed)
    max_duration: Optional[float] = None  # safety timeout for quantity mode
    overrides: dict = field(default_factory=dict)
    changeover: Optional[ChangeoverConfig] = None


@dataclass
class RecipeConfig:
    """Complete recipe definition."""
    name: str
    description: str
    base_scenario: str
    segments: List[SegmentConfig]


@dataclass
class SegmentResult:
    """Result of a completed segment."""
    name: str
    segment_index: int
    start_sim_time: float
    end_sim_time: float
    parts_produced: int
    target_quantity: Optional[int]
    stop_reason: str            # "quantity_reached", "duration_reached", "max_duration_reached"
    changeover_target: Optional[float] = None
    changeover_actual: Optional[float] = None
    oee: float = 0.0


# ========== CONFIG LOADING ==========


def load_recipe_config(recipe_name: str) -> dict:
    """Load raw recipe YAML from config/recipes/{name}.yaml.

    Also checks the SIMENGINE_RECIPE_PATH env var, then falls back to
    ``config/recipes/`` relative to the project root.

    Returns:
        Raw dict from YAML.

    Raises:
        FileNotFoundError: If recipe file does not exist.
    """
    # Recipe names arrive from REST/MCP callers — reject path traversal
    import re
    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$", recipe_name or "") \
            or ".." in recipe_name:
        raise ValueError(
            f"invalid recipe name {recipe_name!r} — use letters, digits, '_', '-'")

    # Check env var first
    recipe_dir = os.environ.get("SIMENGINE_RECIPE_PATH")
    if recipe_dir:
        recipe_path = Path(recipe_dir) / f"{recipe_name}.yaml"
    else:
        project_root = Path(__file__).parents[3]
        recipe_path = project_root / "config" / "recipes" / f"{recipe_name}.yaml"

    if not recipe_path.exists():
        raise FileNotFoundError(
            f"Recipe file not found: {recipe_path}"
        )

    with open(recipe_path, "r") as f:
        return yaml.safe_load(f)


def parse_recipe(raw: dict) -> RecipeConfig:
    """Parse raw YAML dict into a RecipeConfig dataclass.

    Raises:
        ValueError: If required fields are missing or invalid.
    """
    if not isinstance(raw, dict):
        raise ValueError("Recipe must be a YAML mapping")

    name = raw.get("name")
    if not name:
        raise ValueError("Recipe missing 'name' field")

    base_scenario = raw.get("base_scenario")
    if not base_scenario:
        raise ValueError("Recipe missing 'base_scenario' field")

    raw_segments = raw.get("segments")
    if not raw_segments or not isinstance(raw_segments, list):
        raise ValueError("Recipe must have a non-empty 'segments' list")

    segments = []
    for i, seg_raw in enumerate(raw_segments):
        seg = _parse_segment(seg_raw, i)
        segments.append(seg)

    return RecipeConfig(
        name=name,
        description=raw.get("description", ""),
        base_scenario=base_scenario,
        segments=segments,
    )


def _parse_segment(seg_raw: dict, index: int) -> SegmentConfig:
    """Parse a single segment dict."""
    if not isinstance(seg_raw, dict):
        raise ValueError(f"Segment at index {index} must be a mapping")

    name = seg_raw.get("name")
    if not name:
        raise ValueError(f"Segment at index {index} missing 'name'")

    quantity = seg_raw.get("quantity")
    duration = seg_raw.get("duration")

    if quantity is None and duration is None:
        raise ValueError(
            f"Segment '{name}': must specify 'quantity' or 'duration'"
        )
    if quantity is not None and duration is not None:
        raise ValueError(
            f"Segment '{name}': specify 'quantity' or 'duration', not both"
        )

    if quantity is not None:
        if not isinstance(quantity, int) or quantity <= 0:
            raise ValueError(
                f"Segment '{name}': 'quantity' must be a positive integer"
            )

    if duration is not None:
        if not isinstance(duration, (int, float)) or duration <= 0:
            raise ValueError(
                f"Segment '{name}': 'duration' must be a positive number"
            )

    max_duration = seg_raw.get("max_duration")
    if max_duration is not None:
        if not isinstance(max_duration, (int, float)) or max_duration <= 0:
            raise ValueError(
                f"Segment '{name}': 'max_duration' must be a positive number"
            )
        if duration is not None:
            raise ValueError(
                f"Segment '{name}': 'max_duration' only applies to quantity-based segments"
            )

    overrides = seg_raw.get("overrides", {})

    changeover = None
    co_raw = seg_raw.get("changeover")
    if co_raw:
        changeover = _parse_changeover(co_raw, name)

    return SegmentConfig(
        name=name,
        quantity=quantity,
        duration=duration,
        max_duration=max_duration,
        overrides=overrides,
        changeover=changeover,
    )


def _parse_changeover(co_raw: dict, segment_name: str) -> ChangeoverConfig:
    """Parse a changeover dict."""
    if not isinstance(co_raw, dict):
        raise ValueError(f"Segment '{segment_name}': changeover must be a mapping")

    target = co_raw.get("target")
    if target is None or not isinstance(target, (int, float)) or target < 0:
        raise ValueError(
            f"Segment '{segment_name}': changeover 'target' must be a non-negative number"
        )

    # Build DistributionFactory-compatible config
    dist_config = {k: v for k, v in co_raw.items() if k != "target"}
    if "distribution" not in dist_config:
        raise ValueError(
            f"Segment '{segment_name}': changeover missing 'distribution'"
        )

    return ChangeoverConfig(target=target, distribution_config=dist_config)


def validate_recipe(recipe: RecipeConfig, all_scenarios: dict = None) -> None:
    """Validate a parsed recipe against available scenarios and machine names.

    Args:
        recipe: Parsed RecipeConfig.
        all_scenarios: If provided, verify base_scenario exists.
            If None, loads the scenario to validate machine names.

    Raises:
        ValueError: On any validation error.
    """
    # Verify base_scenario exists
    try:
        base_config = load_line_config(recipe.base_scenario)
    except (ValueError, FileNotFoundError) as exc:
        raise ValueError(
            f"Recipe '{recipe.name}': base_scenario '{recipe.base_scenario}' "
            f"not available: {exc}"
        )

    machine_names = {m["name"] for m in base_config["stations"]}

    for i, seg in enumerate(recipe.segments):
        _validate_segment_overrides(seg, machine_names, i)

        # Validate changeover distribution
        if seg.changeover:
            try:
                validate_distribution_config(
                    seg.changeover.distribution_config,
                    f"Segment '{seg.name}' changeover",
                )
            except ValueError:
                raise

    # Last segment should not have changeover (warning, not error)
    if recipe.segments and recipe.segments[-1].changeover:
        import logging
        logging.warning(
            f"Recipe '{recipe.name}': last segment '{recipe.segments[-1].name}' "
            f"has a changeover — it will be ignored"
        )


def _validate_segment_overrides(
    seg: SegmentConfig, machine_names: set, index: int
) -> None:
    """Validate that segment overrides reference valid machine names and params."""
    overrides = seg.overrides
    if not overrides:
        return

    machine_overrides = overrides.get("stations", [])
    if not isinstance(machine_overrides, list):
        raise ValueError(
            f"Segment '{seg.name}': overrides.stations must be a list"
        )

    allowed_params = {
        "name", "cycle_time", "defect_rate", "target_ppm",
        "health_multiplier",
    }

    for mo in machine_overrides:
        if not isinstance(mo, dict):
            raise ValueError(
                f"Segment '{seg.name}': each machine override must be a mapping"
            )
        name = mo.get("name")
        if not name:
            raise ValueError(
                f"Segment '{seg.name}': machine override missing 'name'"
            )
        if name not in machine_names:
            raise ValueError(
                f"Segment '{seg.name}': override references unknown machine '{name}'"
            )
        unknown = set(mo.keys()) - allowed_params
        if unknown:
            raise ValueError(
                f"Segment '{seg.name}': override for '{name}' has unsupported "
                f"keys: {unknown}. Allowed: {sorted(allowed_params - {'name'})}"
            )

    # Validate source overrides
    source_overrides = overrides.get("source", {})
    if source_overrides:
        allowed_source = {"interarrival_time"}
        unknown = set(source_overrides.keys()) - allowed_source
        if unknown:
            raise ValueError(
                f"Segment '{seg.name}': source override has unsupported "
                f"keys: {unknown}. Allowed: {sorted(allowed_source)}"
            )


# ========== OVERRIDE APPLICATION ==========


def apply_segment_overrides(
    base_config: dict, overrides: dict
) -> dict:
    """Return a deep copy of base_config with segment overrides applied.

    Only machine-level parameters (cycle_time, defect_rate, target_ppm,
    health_multiplier) and source interarrival_time may be overridden.
    Topology (machine count, buffer layout, scrap sinks) is unchanged.
    """
    config = copy.deepcopy(base_config)

    machine_overrides = overrides.get("stations", [])
    for mo in machine_overrides:
        name = mo["name"]
        for mc in config["stations"]:
            if mc["name"] == name:
                for key in ("cycle_time", "defect_rate", "target_ppm",
                            "health_multiplier"):
                    if key in mo:
                        mc[key] = mo[key]
                # If target_ppm is set, remove cycle_time to avoid conflict
                if "target_ppm" in mo and "cycle_time" in mc and "cycle_time" not in mo:
                    del mc["cycle_time"]
                # Update quality_routing defect_rate if present
                if "defect_rate" in mo and "quality_routing" in mc:
                    mc["quality_routing"]["defect_rate"] = mo["defect_rate"]
                break

    source_overrides = overrides.get("source", {})
    if "interarrival_time" in source_overrides:
        if "source" not in config:
            config["source"] = {}
        config["source"]["interarrival_time"] = source_overrides["interarrival_time"]

    return config


# ========== CHANGEOVER SAMPLING ==========


def sample_changeover(changeover: ChangeoverConfig, seed: int) -> float:
    """Sample actual changeover duration from configured distribution.

    Uses a dedicated seed for reproducibility without disturbing the
    main simulation RNG state.

    Returns:
        Actual changeover duration in sim-time seconds (>= 0).
    """
    # Save RNG state
    py_state = random.getstate()
    np_state = np.random.get_state()

    try:
        random.seed(seed)
        np.random.seed(seed)
        dist = DistributionFactory.create(changeover.distribution_config)
        actual = max(0.0, float(dist.rvs()))
    finally:
        # Restore RNG state
        random.setstate(py_state)
        np.random.set_state(np_state)

    return actual
