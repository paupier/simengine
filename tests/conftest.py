"""
Pytest fixtures for the simengine test suite.

Points the config loader at the test fixture scenario file so tests are
independent of the shipped config/scenarios.yaml.
Shared factory functions are in tests/factories.py.
"""
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _fixture_config_path(monkeypatch):
    """Route load_line_config() at tests/fixtures/line_models_test.yaml."""
    monkeypatch.setenv(
        "SIMENGINE_CONFIG_PATH", str(FIXTURES_DIR / "line_models_test.yaml")
    )
