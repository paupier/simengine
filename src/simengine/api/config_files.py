"""Scenario/recipe YAML file access shared by the REST API and the tool
registry. ruamel round-trip loading preserves comments on write."""
import io

import yaml as pyyaml
from ruamel.yaml import YAML

from simengine.config.loader import get_config_path, get_recipes_dir  # noqa: F401

_yaml = YAML()
_yaml.preserve_quotes = True


def load_scenarios_file():
    path = get_config_path()
    with open(path) as f:
        return _yaml.load(f) or {}, path


def dump_scenarios_file(data, path):
    with open(path, "w") as f:
        _yaml.dump(data, f)


def load_recipe_file(path):
    with open(path) as f:
        return _yaml.load(f)


def dump_recipe_file(data, path):
    with open(path, "w") as f:
        _yaml.dump(data, f)


def plain(obj):
    """ruamel round-trip objects -> plain dict/list for validation + JSON."""
    buf = io.StringIO()
    _yaml.dump(obj, buf)
    return pyyaml.safe_load(buf.getvalue())
