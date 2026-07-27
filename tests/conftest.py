"""
Pytest fixtures for the simengine test suite.

Points the config loader at the test fixture scenario file so tests are
independent of the shipped config/scenarios.yaml.
Shared factory functions are in tests/factories.py.
"""
import os
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _fixture_config_path(monkeypatch):
    """Route load_line_config() at tests/fixtures/line_models_test.yaml."""
    monkeypatch.setenv(
        "SIMENGINE_CONFIG_PATH", str(FIXTURES_DIR / "line_models_test.yaml")
    )


@pytest.fixture(scope="session", autouse=True)
def _opcua_standard_aspace_shelf(tmp_path_factory):
    """Cache asyncua's standard address space for the whole test session.

    Every asyncua Server() construction loads the ~7000-node standard OPC UA
    namespace. The OPC UA tests build dozens of throwaway address spaces, and
    that load — ~1.3 s on CPython 3.10 but ~24 s on 3.12 — dominated the run
    (the 3.12 CI leg took 20 min against under 4 min for 3.10/3.11/3.13).
    Built once per session, then reloaded in ~0.01 s.

    Session-scoped and set via os.environ rather than monkeypatch, which is
    function-scoped and cannot be used from a session fixture.
    """
    shelf_dir = tmp_path_factory.mktemp("opcua-shelf")
    previous = os.environ.get("SIMENGINE_OPCUA_SHELF")
    os.environ["SIMENGINE_OPCUA_SHELF"] = str(shelf_dir)
    yield
    if previous is None:
        os.environ.pop("SIMENGINE_OPCUA_SHELF", None)
    else:
        os.environ["SIMENGINE_OPCUA_SHELF"] = previous
