"""
Tests for the Run Recipe feature.

Covers:
  - Recipe YAML loading and parsing
  - Validation (base_scenario, overrides, changeover distributions)
  - Override application
  - Changeover sampling (seeded reproducibility)
  - SegmentConfig/RecipeConfig data structures
  - CLI arg parsing (--recipe vs --scenario mutual exclusion)
  - Stop conditions parsing
  - Edge cases (single segment, no changeover, last segment changeover)
"""
import os

import pytest
import yaml

from simengine.runtime.recipe_runner import (
    ChangeoverConfig,
    RecipeConfig,
    SegmentConfig,
    SegmentResult,
    apply_segment_overrides,
    load_recipe_config,
    parse_recipe,
    sample_changeover,
    validate_recipe,
    _parse_segment,
    _parse_changeover,
    _validate_segment_overrides,
)


# ========== Fixtures ==========


@pytest.fixture
def minimal_recipe_dict():
    """Minimal valid recipe dict."""
    return {
        "name": "Test Recipe",
        "description": "A test recipe",
        "base_scenario": "balanced_line",
        "segments": [
            {"name": "Seg1", "quantity": 100, "max_duration": 3600},
        ],
    }


@pytest.fixture
def full_recipe_dict():
    """Full recipe dict with multiple segments and changeovers."""
    return {
        "name": "Full Recipe",
        "description": "Multi-segment recipe",
        "base_scenario": "balanced_line",
        "segments": [
            {
                "name": "Product A",
                "quantity": 50,
                "max_duration": 1800,
                "overrides": {
                    "stations": [
                        {"name": "M1", "cycle_time": 10},
                    ],
                },
                "changeover": {
                    "target": 300,
                    "distribution": "constant",
                    "value": 300,
                },
            },
            {
                "name": "Product B",
                "duration": 600,
            },
        ],
    }


@pytest.fixture
def base_config():
    """Minimal base config matching balanced_line structure."""
    return {
        "stations": [
            {"name": "M1", "cycle_time": 5},
            {"name": "M2", "cycle_time": 5},
            {"name": "M3", "cycle_time": 5},
        ],
        "buffers": [
            {"name": "B1", "capacity": 10, "upstream": "M1", "downstream": "M2"},
            {"name": "B2", "capacity": 10, "upstream": "M2", "downstream": "M3"},
        ],
    }


# ========== Recipe YAML Loading ==========


class TestLoadRecipeConfig:
    """Test loading recipe YAML files."""

    def test_load_existing_recipe(self):
        """Load the quick_test recipe from config/recipes/."""
        raw = load_recipe_config("quick_test")
        assert raw["name"] == "Quick Test Recipe"
        assert raw["base_scenario"] == "demo_line"
        assert len(raw["segments"]) == 2

    def test_load_monday_schedule(self):
        """Load the monday_schedule recipe."""
        raw = load_recipe_config("monday_schedule")
        assert raw["name"] == "Monday Production Schedule"
        assert raw["base_scenario"] == "press_line_8"
        assert len(raw["segments"]) == 3

    def test_load_single_product(self):
        """Load the single_product recipe."""
        raw = load_recipe_config("single_product")
        assert raw["name"] == "Single Product Run"
        assert len(raw["segments"]) == 1

    def test_load_nonexistent_recipe(self):
        """FileNotFoundError for missing recipe."""
        with pytest.raises(FileNotFoundError, match="not found"):
            load_recipe_config("nonexistent_recipe_xyz")

    def test_load_from_env_var(self, tmp_path):
        """Load recipe from SIMENGINE_RECIPE_PATH env var."""
        recipe_data = {
            "name": "Env Recipe",
            "base_scenario": "balanced_line",
            "segments": [{"name": "S1", "quantity": 10}],
        }
        recipe_file = tmp_path / "env_recipe.yaml"
        recipe_file.write_text(yaml.dump(recipe_data))

        old = os.environ.get("SIMENGINE_RECIPE_PATH")
        try:
            os.environ["SIMENGINE_RECIPE_PATH"] = str(tmp_path)
            raw = load_recipe_config("env_recipe")
            assert raw["name"] == "Env Recipe"
        finally:
            if old is None:
                os.environ.pop("SIMENGINE_RECIPE_PATH", None)
            else:
                os.environ["SIMENGINE_RECIPE_PATH"] = old


# ========== Recipe Parsing ==========


class TestParseRecipe:
    """Test parsing raw YAML dicts into RecipeConfig."""

    def test_parse_minimal(self, minimal_recipe_dict):
        """Parse a minimal recipe dict."""
        recipe = parse_recipe(minimal_recipe_dict)
        assert recipe.name == "Test Recipe"
        assert recipe.base_scenario == "balanced_line"
        assert len(recipe.segments) == 1
        assert recipe.segments[0].name == "Seg1"
        assert recipe.segments[0].quantity == 100

    def test_parse_full(self, full_recipe_dict):
        """Parse a full recipe with overrides and changeovers."""
        recipe = parse_recipe(full_recipe_dict)
        assert recipe.name == "Full Recipe"
        assert len(recipe.segments) == 2

        seg1 = recipe.segments[0]
        assert seg1.quantity == 50
        assert seg1.max_duration == 1800
        assert seg1.changeover is not None
        assert seg1.changeover.target == 300

        seg2 = recipe.segments[1]
        assert seg2.duration == 600
        assert seg2.changeover is None

    def test_parse_missing_name(self):
        """Missing 'name' raises ValueError."""
        with pytest.raises(ValueError, match="missing 'name'"):
            parse_recipe({"base_scenario": "x", "segments": [{"name": "S", "quantity": 1}]})

    def test_parse_missing_base_scenario(self):
        """Missing 'base_scenario' raises ValueError."""
        with pytest.raises(ValueError, match="missing 'base_scenario'"):
            parse_recipe({"name": "X", "segments": [{"name": "S", "quantity": 1}]})

    def test_parse_empty_segments(self):
        """Empty segments list raises ValueError."""
        with pytest.raises(ValueError, match="non-empty 'segments'"):
            parse_recipe({"name": "X", "base_scenario": "y", "segments": []})

    def test_parse_no_segments(self):
        """Missing segments key raises ValueError."""
        with pytest.raises(ValueError, match="non-empty 'segments'"):
            parse_recipe({"name": "X", "base_scenario": "y"})

    def test_parse_not_dict(self):
        """Non-dict raises ValueError."""
        with pytest.raises(ValueError, match="YAML mapping"):
            parse_recipe("not a dict")

    def test_description_default(self):
        """Missing description defaults to empty string."""
        raw = {"name": "X", "base_scenario": "y",
               "segments": [{"name": "S", "quantity": 1}]}
        recipe = parse_recipe(raw)
        assert recipe.description == ""


# ========== Segment Parsing ==========


class TestParseSegment:
    """Test segment-level parsing."""

    def test_quantity_segment(self):
        """Quantity-based segment parses correctly."""
        seg = _parse_segment({"name": "Batch", "quantity": 100, "max_duration": 3600}, 0)
        assert seg.quantity == 100
        assert seg.duration is None
        assert seg.max_duration == 3600

    def test_duration_segment(self):
        """Duration-based segment parses correctly."""
        seg = _parse_segment({"name": "Timed", "duration": 7200}, 0)
        assert seg.duration == 7200
        assert seg.quantity is None
        assert seg.max_duration is None

    def test_no_stop_condition(self):
        """Missing both quantity and duration raises ValueError."""
        with pytest.raises(ValueError, match="must specify 'quantity' or 'duration'"):
            _parse_segment({"name": "Bad"}, 0)

    def test_both_stop_conditions(self):
        """Both quantity and duration raises ValueError."""
        with pytest.raises(ValueError, match="not both"):
            _parse_segment({"name": "Bad", "quantity": 10, "duration": 100}, 0)

    def test_negative_quantity(self):
        """Negative quantity raises ValueError."""
        with pytest.raises(ValueError, match="positive integer"):
            _parse_segment({"name": "Bad", "quantity": -5}, 0)

    def test_zero_quantity(self):
        """Zero quantity raises ValueError."""
        with pytest.raises(ValueError, match="positive integer"):
            _parse_segment({"name": "Bad", "quantity": 0}, 0)

    def test_float_quantity(self):
        """Float quantity raises ValueError."""
        with pytest.raises(ValueError, match="positive integer"):
            _parse_segment({"name": "Bad", "quantity": 10.5}, 0)

    def test_negative_duration(self):
        """Negative duration raises ValueError."""
        with pytest.raises(ValueError, match="positive number"):
            _parse_segment({"name": "Bad", "duration": -100}, 0)

    def test_max_duration_with_duration(self):
        """max_duration with duration-based segment raises ValueError."""
        with pytest.raises(ValueError, match="only applies to quantity"):
            _parse_segment({"name": "Bad", "duration": 100, "max_duration": 200}, 0)

    def test_negative_max_duration(self):
        """Negative max_duration raises ValueError."""
        with pytest.raises(ValueError, match="positive number"):
            _parse_segment({"name": "Bad", "quantity": 10, "max_duration": -100}, 0)

    def test_missing_segment_name(self):
        """Missing segment name raises ValueError."""
        with pytest.raises(ValueError, match="missing 'name'"):
            _parse_segment({"quantity": 10}, 0)

    def test_segment_with_changeover(self):
        """Segment with changeover parses correctly."""
        seg = _parse_segment({
            "name": "S1",
            "quantity": 10,
            "changeover": {
                "target": 60,
                "distribution": "constant",
                "value": 60,
            },
        }, 0)
        assert seg.changeover is not None
        assert seg.changeover.target == 60
        assert seg.changeover.distribution_config["distribution"] == "constant"

    def test_segment_without_changeover(self):
        """Segment without changeover has None."""
        seg = _parse_segment({"name": "Last", "quantity": 10}, 0)
        assert seg.changeover is None

    def test_default_overrides(self):
        """No overrides key results in empty dict."""
        seg = _parse_segment({"name": "S1", "quantity": 10}, 0)
        assert seg.overrides == {}


# ========== Changeover Parsing ==========


class TestParseChangeover:
    """Test changeover configuration parsing."""

    def test_constant_changeover(self):
        """Constant changeover parses correctly."""
        co = _parse_changeover(
            {"target": 120, "distribution": "constant", "value": 120},
            "test_seg",
        )
        assert co.target == 120
        assert co.distribution_config["distribution"] == "constant"
        assert co.distribution_config["value"] == 120

    def test_lognormal_changeover(self):
        """Lognormal changeover parses correctly."""
        co = _parse_changeover(
            {"target": 300, "distribution": "lognormal", "mean": 300, "std": 60},
            "test_seg",
        )
        assert co.target == 300
        assert co.distribution_config["distribution"] == "lognormal"

    def test_missing_target(self):
        """Missing target raises ValueError."""
        with pytest.raises(ValueError, match="'target' must be"):
            _parse_changeover({"distribution": "constant", "value": 10}, "s")

    def test_negative_target(self):
        """Negative target raises ValueError."""
        with pytest.raises(ValueError, match="'target' must be"):
            _parse_changeover(
                {"target": -5, "distribution": "constant", "value": 10}, "s"
            )

    def test_missing_distribution(self):
        """Missing distribution key raises ValueError."""
        with pytest.raises(ValueError, match="missing 'distribution'"):
            _parse_changeover({"target": 100}, "s")

    def test_zero_target_allowed(self):
        """Zero target is allowed (instant planned changeover)."""
        co = _parse_changeover(
            {"target": 0, "distribution": "constant", "value": 0}, "s"
        )
        assert co.target == 0


# ========== Recipe Validation ==========


class TestValidateRecipe:
    """Test recipe validation against scenarios."""

    def test_valid_recipe(self, minimal_recipe_dict):
        """Valid recipe with existing base_scenario passes validation."""
        recipe = parse_recipe(minimal_recipe_dict)
        validate_recipe(recipe)  # Should not raise

    def test_invalid_base_scenario(self):
        """Recipe with nonexistent base_scenario raises ValueError."""
        recipe = RecipeConfig(
            name="Bad",
            description="",
            base_scenario="nonexistent_scenario_xyz",
            segments=[SegmentConfig(name="S1", quantity=10)],
        )
        with pytest.raises(ValueError, match="not available"):
            validate_recipe(recipe)

    def test_valid_machine_override(self, full_recipe_dict):
        """Recipe with valid machine override passes validation."""
        recipe = parse_recipe(full_recipe_dict)
        validate_recipe(recipe)  # Should not raise

    def test_invalid_machine_name_override(self):
        """Override referencing unknown machine raises ValueError."""
        recipe = RecipeConfig(
            name="Bad",
            description="",
            base_scenario="balanced_line",
            segments=[
                SegmentConfig(
                    name="S1",
                    quantity=10,
                    overrides={
                        "stations": [
                            {"name": "NONEXISTENT_MACHINE", "cycle_time": 5},
                        ]
                    },
                ),
            ],
        )
        with pytest.raises(ValueError, match="unknown machine"):
            validate_recipe(recipe)

    def test_unsupported_override_key(self):
        """Override with unsupported key raises ValueError."""
        recipe = RecipeConfig(
            name="Bad",
            description="",
            base_scenario="balanced_line",
            segments=[
                SegmentConfig(
                    name="S1",
                    quantity=10,
                    overrides={
                        "stations": [
                            {"name": "M1", "buffer_capacity": 99},
                        ]
                    },
                ),
            ],
        )
        with pytest.raises(ValueError, match="unsupported keys"):
            validate_recipe(recipe)


# ========== Override Application ==========


class TestApplySegmentOverrides:
    """Test applying segment overrides to base config."""

    def test_cycle_time_override(self, base_config):
        """cycle_time override is applied."""
        overrides = {"stations": [{"name": "M1", "cycle_time": 20}]}
        result = apply_segment_overrides(base_config, overrides)
        m1 = next(m for m in result["stations"] if m["name"] == "M1")
        assert m1["cycle_time"] == 20

    def test_defect_rate_override(self, base_config):
        """defect_rate override is applied."""
        overrides = {"stations": [{"name": "M2", "defect_rate": 0.05}]}
        result = apply_segment_overrides(base_config, overrides)
        m2 = next(m for m in result["stations"] if m["name"] == "M2")
        assert m2["defect_rate"] == 0.05

    def test_no_overrides(self, base_config):
        """Empty overrides returns identical copy."""
        result = apply_segment_overrides(base_config, {})
        assert result == base_config
        assert result is not base_config  # deep copy

    def test_base_config_unchanged(self, base_config):
        """Original base_config is not mutated."""
        original_ct = base_config["stations"][0]["cycle_time"]
        overrides = {"stations": [{"name": "M1", "cycle_time": 99}]}
        apply_segment_overrides(base_config, overrides)
        assert base_config["stations"][0]["cycle_time"] == original_ct

    def test_multiple_machine_overrides(self, base_config):
        """Multiple machines can be overridden at once."""
        overrides = {
            "stations": [
                {"name": "M1", "cycle_time": 10},
                {"name": "M3", "cycle_time": 15},
            ]
        }
        result = apply_segment_overrides(base_config, overrides)
        m1 = next(m for m in result["stations"] if m["name"] == "M1")
        m2 = next(m for m in result["stations"] if m["name"] == "M2")
        m3 = next(m for m in result["stations"] if m["name"] == "M3")
        assert m1["cycle_time"] == 10
        assert m2["cycle_time"] == 5  # unchanged
        assert m3["cycle_time"] == 15

    def test_target_ppm_override(self, base_config):
        """target_ppm override is applied."""
        overrides = {"stations": [{"name": "M1", "target_ppm": 12}]}
        result = apply_segment_overrides(base_config, overrides)
        m1 = next(m for m in result["stations"] if m["name"] == "M1")
        assert m1["target_ppm"] == 12

    def test_source_interarrival_override(self, base_config):
        """Source interarrival_time override is applied."""
        overrides = {"source": {"interarrival_time": 2.5}}
        result = apply_segment_overrides(base_config, overrides)
        assert result["source"]["interarrival_time"] == 2.5

    def test_quality_routing_defect_rate_sync(self):
        """defect_rate override also updates quality_routing.defect_rate."""
        config = {
            "stations": [
                {
                    "name": "M1",
                    "cycle_time": 5,
                    "quality_routing": {"enabled": True, "defect_rate": 0.01},
                },
            ],
            "buffers": [],
        }
        overrides = {"stations": [{"name": "M1", "defect_rate": 0.1}]}
        result = apply_segment_overrides(config, overrides)
        m1 = result["stations"][0]
        assert m1["defect_rate"] == 0.1
        assert m1["quality_routing"]["defect_rate"] == 0.1


# ========== Changeover Sampling ==========


class TestSampleChangeover:
    """Test changeover duration sampling."""

    def test_constant_changeover(self):
        """Constant distribution returns exact value."""
        co = ChangeoverConfig(
            target=120,
            distribution_config={"distribution": "constant", "value": 120},
        )
        actual = sample_changeover(co, seed=42)
        assert actual == 120.0

    def test_seeded_reproducibility(self):
        """Same seed produces same result."""
        co = ChangeoverConfig(
            target=300,
            distribution_config={"distribution": "lognormal", "mean": 300, "std": 60},
        )
        result1 = sample_changeover(co, seed=42)
        result2 = sample_changeover(co, seed=42)
        assert result1 == result2

    def test_different_seeds_differ(self):
        """Different seeds produce different results (stochastic distributions)."""
        co = ChangeoverConfig(
            target=300,
            distribution_config={"distribution": "lognormal", "mean": 300, "std": 60},
        )
        result1 = sample_changeover(co, seed=42)
        result2 = sample_changeover(co, seed=99)
        assert result1 != result2

    def test_non_negative_result(self):
        """Result is always non-negative even with normal distribution."""
        co = ChangeoverConfig(
            target=10,
            distribution_config={"distribution": "normal", "mean": 10, "std": 100},
        )
        # Run several times with different seeds
        for seed in range(100):
            actual = sample_changeover(co, seed=seed)
            assert actual >= 0.0

    def test_rng_state_preserved(self):
        """Sampling does not disturb the main RNG state."""
        import random
        import numpy as np

        random.seed(123)
        np.random.seed(123)
        before_py = random.random()

        random.seed(123)
        np.random.seed(123)
        co = ChangeoverConfig(
            target=100,
            distribution_config={"distribution": "exponential", "mean": 100},
        )
        sample_changeover(co, seed=999)
        after_py = random.random()

        assert before_py == after_py

    def test_exponential_changeover(self):
        """Exponential distribution sampling works."""
        co = ChangeoverConfig(
            target=100,
            distribution_config={"distribution": "exponential", "mean": 100},
        )
        actual = sample_changeover(co, seed=42)
        assert actual > 0

    def test_normal_changeover(self):
        """Normal distribution sampling works."""
        co = ChangeoverConfig(
            target=300,
            distribution_config={"distribution": "normal", "mean": 300, "std": 30},
        )
        actual = sample_changeover(co, seed=42)
        assert isinstance(actual, float)


# ========== Data Classes ==========


class TestDataClasses:
    """Test dataclass defaults and construction."""

    def test_segment_config_defaults(self):
        """SegmentConfig defaults are correct."""
        seg = SegmentConfig(name="S1", quantity=100)
        assert seg.duration is None
        assert seg.max_duration is None
        assert seg.overrides == {}
        assert seg.changeover is None

    def test_segment_result_defaults(self):
        """SegmentResult defaults are correct."""
        result = SegmentResult(
            name="S1",
            segment_index=1,
            start_sim_time=0.0,
            end_sim_time=100.0,
            parts_produced=50,
            target_quantity=100,
            stop_reason="max_duration_reached",
        )
        assert result.changeover_target is None
        assert result.changeover_actual is None
        assert result.oee == 0.0

    def test_recipe_config_construction(self):
        """RecipeConfig constructs correctly."""
        recipe = RecipeConfig(
            name="Test",
            description="desc",
            base_scenario="balanced_line",
            segments=[SegmentConfig(name="S1", quantity=10)],
        )
        assert recipe.name == "Test"
        assert len(recipe.segments) == 1

    def test_changeover_config(self):
        """ChangeoverConfig stores target and distribution."""
        co = ChangeoverConfig(
            target=120,
            distribution_config={"distribution": "constant", "value": 120},
        )
        assert co.target == 120
        assert co.distribution_config["distribution"] == "constant"


# ========== CLI Arg Parsing ==========


class TestCLIArgs:
    """Test --recipe and --scenario mutual exclusion."""

    def test_scenario_only(self):
        """--scenario without --recipe works."""
        import argparse
        parser = argparse.ArgumentParser()
        group = parser.add_mutually_exclusive_group()
        group.add_argument("--scenario", default=None)
        group.add_argument("--recipe", default=None)
        args = parser.parse_args(["--scenario", "balanced_line"])
        assert args.scenario == "balanced_line"
        assert args.recipe is None

    def test_recipe_only(self):
        """--recipe without --scenario works."""
        import argparse
        parser = argparse.ArgumentParser()
        group = parser.add_mutually_exclusive_group()
        group.add_argument("--scenario", default=None)
        group.add_argument("--recipe", default=None)
        args = parser.parse_args(["--recipe", "monday_schedule"])
        assert args.recipe == "monday_schedule"
        assert args.scenario is None

    def test_both_raises_error(self):
        """--recipe and --scenario together raises error."""
        import argparse
        parser = argparse.ArgumentParser()
        group = parser.add_mutually_exclusive_group()
        group.add_argument("--scenario", default=None)
        group.add_argument("--recipe", default=None)
        with pytest.raises(SystemExit):
            parser.parse_args(["--scenario", "balanced_line", "--recipe", "test"])

    def test_neither_defaults_scenario(self):
        """Neither flag defaults to scenario=None (main handles default)."""
        import argparse
        parser = argparse.ArgumentParser()
        group = parser.add_mutually_exclusive_group()
        group.add_argument("--scenario", default=None)
        group.add_argument("--recipe", default=None)
        args = parser.parse_args([])
        assert args.scenario is None
        assert args.recipe is None


# ========== Integration: Parse Example Recipes ==========


class TestExampleRecipes:
    """Test that the shipped example recipes parse and validate."""

    def test_parse_quick_test(self):
        """quick_test recipe parses successfully."""
        raw = load_recipe_config("quick_test")
        recipe = parse_recipe(raw)
        assert recipe.name == "Quick Test Recipe"
        assert len(recipe.segments) == 2
        assert recipe.segments[0].quantity == 20
        assert recipe.segments[0].changeover is not None
        assert recipe.segments[1].duration == 60

    def test_parse_monday_schedule(self):
        """monday_schedule recipe parses successfully."""
        raw = load_recipe_config("monday_schedule")
        recipe = parse_recipe(raw)
        assert recipe.name == "Monday Production Schedule"
        assert len(recipe.segments) == 3
        # First segment: quantity-based with changeover
        assert recipe.segments[0].quantity == 500
        assert recipe.segments[0].changeover is not None
        assert recipe.segments[0].changeover.target == 300
        # Second segment: duration-based with changeover
        assert recipe.segments[1].duration == 7200
        assert recipe.segments[1].changeover is not None
        # Third segment: no changeover
        assert recipe.segments[2].changeover is None

    def test_parse_single_product(self):
        """single_product recipe parses successfully."""
        raw = load_recipe_config("single_product")
        recipe = parse_recipe(raw)
        assert recipe.name == "Single Product Run"
        assert len(recipe.segments) == 1
        assert recipe.segments[0].quantity == 200

    def test_validate_quick_test(self, monkeypatch):
        """quick_test recipe validates against the shipped demo_line scenario."""
        monkeypatch.delenv("SIMENGINE_CONFIG_PATH", raising=False)
        raw = load_recipe_config("quick_test")
        recipe = parse_recipe(raw)
        validate_recipe(recipe)  # Should not raise

    def test_validate_single_product(self, monkeypatch):
        """single_product recipe validates against the shipped demo_line scenario."""
        monkeypatch.delenv("SIMENGINE_CONFIG_PATH", raising=False)
        raw = load_recipe_config("single_product")
        recipe = parse_recipe(raw)
        validate_recipe(recipe)  # Should not raise

    def test_validate_monday_schedule(self, monkeypatch):
        """monday_schedule recipe validates against the shipped press_line_8 scenario."""
        monkeypatch.delenv("SIMENGINE_CONFIG_PATH", raising=False)
        raw = load_recipe_config("monday_schedule")
        recipe = parse_recipe(raw)
        validate_recipe(recipe)  # Should not raise


# ========== Edge Cases ==========


class TestEdgeCases:
    """Test edge cases for recipe parsing and validation."""

    def test_single_segment_no_changeover(self):
        """Single segment with no changeover is valid."""
        raw = {
            "name": "Single",
            "base_scenario": "balanced_line",
            "segments": [{"name": "Only", "quantity": 10}],
        }
        recipe = parse_recipe(raw)
        assert len(recipe.segments) == 1
        assert recipe.segments[0].changeover is None

    def test_last_segment_changeover_warning(self, minimal_recipe_dict):
        """Last segment with changeover triggers warning (not error)."""
        minimal_recipe_dict["segments"][0]["changeover"] = {
            "target": 60,
            "distribution": "constant",
            "value": 60,
        }
        recipe = parse_recipe(minimal_recipe_dict)
        # Should not raise, just warn
        validate_recipe(recipe)

    def test_segment_not_dict(self):
        """Non-dict segment raises ValueError."""
        with pytest.raises(ValueError, match="must be a mapping"):
            _parse_segment("not a dict", 0)

    def test_changeover_not_dict(self):
        """Non-dict changeover raises ValueError."""
        with pytest.raises(ValueError, match="must be a mapping"):
            _parse_changeover("not a dict", "s")

    def test_overrides_machines_not_list(self):
        """overrides.machines as non-list raises ValueError."""
        seg = SegmentConfig(
            name="S1",
            quantity=10,
            overrides={"stations": "not a list"},
        )
        with pytest.raises(ValueError, match="must be a list"):
            _validate_segment_overrides(seg, {"M1"}, 0)

    def test_override_missing_name(self):
        """Machine override without name raises ValueError."""
        seg = SegmentConfig(
            name="S1",
            quantity=10,
            overrides={"stations": [{"cycle_time": 5}]},
        )
        with pytest.raises(ValueError, match="missing 'name'"):
            _validate_segment_overrides(seg, {"M1"}, 0)

    def test_override_not_dict(self):
        """Machine override as non-dict raises ValueError."""
        seg = SegmentConfig(
            name="S1",
            quantity=10,
            overrides={"stations": ["not a dict"]},
        )
        with pytest.raises(ValueError, match="must be a mapping"):
            _validate_segment_overrides(seg, {"M1"}, 0)

    def test_constant_changeover_zero_value(self):
        """Zero target with small constant changeover."""
        # constant distribution requires value > 0 in validate_distribution_config
        # So we test with value=1 and target=0
        co2 = ChangeoverConfig(
            target=0,
            distribution_config={"distribution": "constant", "value": 1},
        )
        actual = sample_changeover(co2, seed=42)
        assert actual == 1.0

    def test_weibull_changeover(self):
        """Weibull distribution changeover sampling works."""
        co = ChangeoverConfig(
            target=200,
            distribution_config={"distribution": "weibull", "shape": 2.0, "scale": 200},
        )
        actual = sample_changeover(co, seed=42)
        assert actual >= 0
        assert isinstance(actual, float)

    def test_uniform_changeover(self):
        """Uniform distribution changeover sampling works."""
        co = ChangeoverConfig(
            target=150,
            distribution_config={"distribution": "uniform", "min": 100, "max": 200},
        )
        actual = sample_changeover(co, seed=42)
        assert 100 <= actual <= 200
