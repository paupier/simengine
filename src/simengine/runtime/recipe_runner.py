"""
Run Recipe Feature — multi-segment production scheduling.

A recipe defines an ordered list of segments, each referencing a base scenario
(with optional overrides), separated by changeover periods with stochastic
durations.  This enables planned-vs-actual changeover analysis and
multi-product production scheduling without permanently modifying scenario
configs.

Usage:
    python src/opcua_server.py --recipe monday_schedule --seed 42
"""

import copy
import os
import random
import time as _time
from dataclasses import dataclass, field
from datetime import datetime
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


# ========== RECIPE ORCHESTRATION ==========


def run_recipe(
    recipe: RecipeConfig,
    sim_seed: int,
    args,
    run_id: str,
    mqtt_publisher=None,
):
    """Orchestrate multi-segment recipe execution.

    Builds the OPC UA server once, then runs each segment in sequence,
    applying overrides and handling changeovers between segments.

    This function imports from opcua_server to avoid circular imports.
    """
    from opcua_server import (
        build_simantha_system,
        build_opcua_server,
        run_segment,
        create_shift_manager_from_config,
        _wrap_opcua_vars_with_cache,
    )
    from simengine.events import create_historian_from_config
    from simengine.events.neo4j_historian import create_neo4j_historian_from_config

    base_config = load_line_config(recipe.base_scenario)

    # Apply --no-csv demo mode flag to suppress CSV historian
    if getattr(args, 'no_csv', False):
        csv_cfg = base_config.get("historian", {}).get("csv")
        if isinstance(csv_cfg, dict):
            csv_cfg["enabled"] = False

    # Build OPC UA server ONCE (topology doesn't change)
    server, opcua_vars, idx = build_opcua_server(base_config)
    _wrap_opcua_vars_with_cache(opcua_vars)
    opcua_vars["system"]["run_id"].set_value(run_id)

    # Initialize recipe OPC UA vars (if present)
    recipe_vars = opcua_vars.get("recipe", {})
    if recipe_vars:
        recipe_vars["recipe_name"].set_value(recipe.name)
        recipe_vars["recipe_description"].set_value(recipe.description)
        recipe_vars["total_segments"].set_value(len(recipe.segments))
        recipe_vars["changeover_state"].set_value(False)

    # Create shift manager and historian from base config
    machine_names = [m["name"] for m in base_config["stations"]]
    shift_manager = create_shift_manager_from_config(base_config, machine_names)
    historian = create_historian_from_config(
        base_config, recipe.base_scenario, run_id=run_id
    )
    neo4j_hist = create_neo4j_historian_from_config(
        base_config, recipe.base_scenario, run_id=run_id
    )
    if neo4j_hist:
        neo4j_hist.create_topology(base_config)

    server.start()
    print("OPC UA server started at opc.tcp://localhost:4840/simantha/")
    print(f"Recipe: {recipe.name} ({len(recipe.segments)} segments)")
    print(f"Base scenario: {recipe.base_scenario}")
    print(f"RunID: {run_id}")
    print("Press Ctrl+C to stop.\n")

    segment_results = []
    cumulative_sim_time = 0.0

    try:
        for i, segment in enumerate(recipe.segments):
            is_last = (i == len(recipe.segments) - 1)

            # Apply overrides to get effective config for this segment
            effective_config = apply_segment_overrides(
                base_config, segment.overrides
            )

            # Rebuild Simantha system with effective config
            # (needed because cycle_time cannot be changed after init)
            system, source, sink, machines, buffers, maintainer, scrap_sinks = \
                build_simantha_system(effective_config)

            # Update recipe OPC UA vars
            if recipe_vars:
                recipe_vars["segment_name"].set_value(segment.name)
                recipe_vars["segment_index"].set_value(i + 1)
                recipe_vars["segment_stop_mode"].set_value(
                    "quantity" if segment.quantity else "duration"
                )
                recipe_vars["segment_quantity_target"].set_value(
                    segment.quantity or 0
                )
                recipe_vars["changeover_state"].set_value(False)

            # Determine stop condition
            if segment.quantity:
                target_quantity = segment.quantity
                max_sim_time = segment.max_duration or float('inf')
            else:
                target_quantity = None
                max_sim_time = segment.duration

            print(f"--- Segment {i+1}/{len(recipe.segments)}: "
                  f"{segment.name} ---")
            if target_quantity:
                max_info = " (max %ds)" % max_sim_time if max_sim_time != float('inf') else ""
                print(f"    Target: {target_quantity} parts{max_info}")
            else:
                print(f"    Duration: {max_sim_time}s")

            segment_start = cumulative_sim_time

            # Record SEGMENT_START event
            if historian:
                _record_recipe_event(
                    historian, neo4j_hist, cumulative_sim_time,
                    "SEGMENT_START", "INFO",
                    f"Starting segment '{segment.name}' ({i+1}/{len(recipe.segments)})",
                    extra={
                        "recipe": recipe.name,
                        "segment": segment.name,
                        "segment_index": i + 1,
                        "stop_mode": "quantity" if segment.quantity else "duration",
                        "target_quantity": segment.quantity,
                        "target_duration": segment.duration or segment.max_duration,
                    },
                )

            extra_base = {
                "recipe": recipe.name,
                "segment": segment.name,
                "segment_index": i + 1,
            }

            # Run the segment
            final_sim_time, parts_produced, stop_reason, segment_oee = \
                run_segment(
                    system=system,
                    source=source,
                    sink=sink,
                    machines=machines,
                    buffers=buffers,
                    maintainer=maintainer,
                    scrap_sinks=scrap_sinks,
                    server=server,
                    opcua_vars=opcua_vars,
                    config=effective_config,
                    sim_seed=sim_seed,
                    max_sim_time=max_sim_time,
                    target_quantity=target_quantity,
                    segment_name=segment.name,
                    extra_base=extra_base,
                    trace=args.trace,
                    shift_manager=shift_manager,
                    historian=historian,
                    neo4j_hist=neo4j_hist,
                    recipe_vars=recipe_vars,
                    mqtt_publisher=mqtt_publisher,
                )

            cumulative_sim_time = segment_start + final_sim_time

            print(f"    Completed: {parts_produced} parts in "
                  f"{final_sim_time:.0f}s ({stop_reason})")

            # Record SEGMENT_END event
            if historian:
                _record_recipe_event(
                    historian, neo4j_hist, cumulative_sim_time,
                    "SEGMENT_END", "INFO",
                    f"Segment '{segment.name}' complete: {parts_produced} parts, "
                    f"{stop_reason}",
                    extra={
                        "recipe": recipe.name,
                        "segment": segment.name,
                        "segment_index": i + 1,
                        "parts_produced": parts_produced,
                        "duration": final_sim_time,
                        "stop_reason": stop_reason,
                        "oee": segment_oee,
                    },
                )

            result = SegmentResult(
                name=segment.name,
                segment_index=i + 1,
                start_sim_time=segment_start,
                end_sim_time=cumulative_sim_time,
                parts_produced=parts_produced,
                target_quantity=segment.quantity,
                stop_reason=stop_reason,
                oee=segment_oee,
            )

            # Handle changeover (if not last segment)
            if segment.changeover and not is_last:
                co_seed = sim_seed + (i + 1) * 10000
                actual_co = sample_changeover(segment.changeover, co_seed)

                result.changeover_target = segment.changeover.target
                result.changeover_actual = actual_co

                print(f"    Changeover: planned={segment.changeover.target:.0f}s "
                      f"actual={actual_co:.0f}s "
                      f"(delta={actual_co - segment.changeover.target:+.0f}s)")

                # Update OPC UA state during changeover
                if recipe_vars:
                    recipe_vars["changeover_state"].set_value(True)
                    recipe_vars["last_changeover_planned"].set_value(
                        segment.changeover.target
                    )
                    recipe_vars["last_changeover_actual"].set_value(actual_co)
                opcua_vars["system"]["line_state"].set_value("CHANGEOVER")

                # Record CHANGEOVER event
                if historian:
                    next_seg_name = recipe.segments[i + 1].name
                    _record_recipe_event(
                        historian, neo4j_hist, cumulative_sim_time,
                        "CHANGEOVER", "LOW",
                        f"Changeover from '{segment.name}' to '{next_seg_name}': "
                        f"planned={segment.changeover.target:.0f}s "
                        f"actual={actual_co:.0f}s",
                        extra={
                            "recipe": recipe.name,
                            "from_segment": segment.name,
                            "to_segment": next_seg_name,
                            "planned": segment.changeover.target,
                            "actual": actual_co,
                            "delta": actual_co - segment.changeover.target,
                        },
                    )

                # Advance sim time through changeover
                # Sleep real-time proportionally (1s real per 1s sim)
                changeover_steps = int(actual_co)
                for step in range(changeover_steps):
                    cumulative_sim_time += 1.0
                    opcua_vars["system"]["simtime"].set_value(cumulative_sim_time)
                    if recipe_vars:
                        recipe_vars["segment_time_remaining"].set_value(
                            float(changeover_steps - step - 1)
                        )
                    _time.sleep(1.0)

                if recipe_vars:
                    recipe_vars["changeover_state"].set_value(False)

            segment_results.append(result)

        # Recipe complete
        print(f"\n=== Recipe Complete: {recipe.name} ===")
        total_parts = sum(r.parts_produced for r in segment_results)
        total_co_time = sum(
            r.changeover_actual or 0 for r in segment_results
        )
        print(f"Total segments: {len(segment_results)}")
        print(f"Total parts: {total_parts}")
        print(f"Total sim time: {cumulative_sim_time:.0f}s")
        print(f"Total changeover time: {total_co_time:.0f}s")

        for r in segment_results:
            co_info = ""
            if r.changeover_actual is not None:
                delta = r.changeover_actual - r.changeover_target
                co_info = (f" | CO: {r.changeover_actual:.0f}s "
                           f"({delta:+.0f}s vs plan)")
            print(f"  {r.segment_index}. {r.name}: {r.parts_produced} parts, "
                  f"{r.end_sim_time - r.start_sim_time:.0f}s, "
                  f"OEE={r.oee:.1%}{co_info}")

        # Record RECIPE_COMPLETE event
        if historian:
            _record_recipe_event(
                historian, neo4j_hist, cumulative_sim_time,
                "RECIPE_COMPLETE", "INFO",
                f"Recipe '{recipe.name}' complete: {total_parts} parts, "
                f"{len(segment_results)} segments",
                extra={
                    "recipe": recipe.name,
                    "total_parts": total_parts,
                    "total_segments": len(segment_results),
                    "total_sim_time": cumulative_sim_time,
                    "total_changeover_time": total_co_time,
                    "segment_summary": [
                        {
                            "name": r.name,
                            "parts": r.parts_produced,
                            "oee": r.oee,
                            "stop_reason": r.stop_reason,
                        }
                        for r in segment_results
                    ],
                },
            )

    except KeyboardInterrupt:
        print("\n\nRecipe stopped by user")

    finally:
        if historian:
            historian.flush()
            historian.close()
            print(f"Event historian closed ({historian.get_event_count()} events)")
        if neo4j_hist:
            neo4j_hist.close()
        server.stop()
        print("Server stopped.")

    return segment_results


def _record_recipe_event(
    historian, neo4j_hist, sim_time: float,
    event_type: str, severity: str, message: str,
    extra: dict = None,
):
    """Record a recipe-level event to all historian backends."""
    from simengine.events import SimEvent

    event = SimEvent(
        timestamp=sim_time,
        wall_clock=datetime.now().isoformat(),
        event_type=event_type,
        source="Line1",
        source_type="line",
        severity=severity,
        message=message,
        extra=extra or {},
    )
    historian.record_event(event)
    if neo4j_hist:
        neo4j_hist.record_event(event)
