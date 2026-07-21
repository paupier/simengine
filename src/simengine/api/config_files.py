"""Scenario/recipe YAML file access shared by the REST API and the tool
registry. ruamel round-trip loading preserves comments on write."""
import io
import re

import yaml as pyyaml
from ruamel.yaml import YAML

from simengine.config.loader import get_config_path, get_recipes_dir  # noqa: F401

_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


def _make_yaml():
    """A fresh YAML() per call — ruamel's parser/scanner state is mutated
    per load()/dump(), so a shared instance corrupts concurrent requests
    under Flask's threaded=True dev server, even for pure reads."""
    y = YAML()
    y.preserve_quotes = True
    return y


def recipe_path(name: str):
    """Resolve a recipe name to its YAML path inside the recipes directory.

    Names are user/LLM-supplied (REST routes and MCP tool arguments), so this
    is a security boundary: reject anything that isn't a plain filename stem
    and confirm the resolved path stays under the recipes dir.

    Raises:
        ValueError: If the name is not a safe filename stem.
    """
    if not isinstance(name, str) or not _SAFE_NAME.match(name) or ".." in name:
        raise ValueError(
            f"invalid recipe name {name!r} — use letters, digits, '_', '-'")
    recipes_dir = get_recipes_dir().resolve()
    path = (recipes_dir / f"{name}.yaml").resolve()
    if path.parent != recipes_dir:
        raise ValueError(f"invalid recipe name {name!r}")
    return path


def load_scenarios_file():
    path = get_config_path()
    with open(path) as f:
        return _make_yaml().load(f) or {}, path


def dump_scenarios_file(data, path):
    with open(path, "w") as f:
        _make_yaml().dump(data, f)


def load_recipe_file(path):
    with open(path) as f:
        return _make_yaml().load(f)


def dump_recipe_file(data, path):
    with open(path, "w") as f:
        _make_yaml().dump(data, f)


def plain(obj):
    """ruamel round-trip objects -> plain dict/list for validation + JSON."""
    buf = io.StringIO()
    _make_yaml().dump(obj, buf)
    return pyyaml.safe_load(buf.getvalue())
