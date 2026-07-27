"""Scenario YAML file access shared by the REST API and the tool registry.
ruamel round-trip loading preserves comments on write."""
import io

import yaml as pyyaml
from ruamel.yaml import YAML

from simengine.config.loader import get_config_path


def _make_yaml():
    """A fresh YAML() per call — ruamel's parser/scanner state is mutated
    per load()/dump(), so a shared instance corrupts concurrent requests
    under Flask's threaded=True dev server, even for pure reads."""
    y = YAML()
    y.preserve_quotes = True
    return y


def load_scenarios_file():
    path = get_config_path()
    with open(path) as f:
        return _make_yaml().load(f) or {}, path


def dump_scenarios_file(data, path):
    with open(path, "w") as f:
        _make_yaml().dump(data, f)


def plain(obj):
    """ruamel round-trip objects -> plain dict/list for validation + JSON."""
    buf = io.StringIO()
    _make_yaml().dump(obj, buf)
    return pyyaml.safe_load(buf.getvalue())
