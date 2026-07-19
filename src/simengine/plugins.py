"""Plugin registry (clone_target_architecture §2 — deliberately boring).

Optional capability = optional package. A configured historian name maps to a
package ``simengine_historian_{name}`` that exposes ``register(registry)``;
missing packages or missing third-party deps fail with a clear install hint.
"""
import importlib

HISTORIAN_BACKENDS = {}  # name -> factory(scenario_name, run_id) -> EventHistorian


def load_configured_plugins(config: dict) -> None:
    """Import and register every historian named in config['historians']."""
    for name in config.get("historians", []):
        module_name = f"simengine_historian_{name.replace('-', '_')}"
        try:
            module = importlib.import_module(module_name)
            module.register(HISTORIAN_BACKENDS)
        except ImportError as e:
            raise RuntimeError(
                f"historian '{name}' configured but not installed: "
                f"pip install simengine[historian-{name}]"
            ) from e


def build_historians(config: dict, scenario_name: str, run_id: str):
    """CompositeHistorian over every configured backend (None if none)."""
    from simengine.events import CompositeHistorian

    names = config.get("historians", [])
    if not names:
        return None
    load_configured_plugins(config)
    backends = []
    for name in names:
        factory = HISTORIAN_BACKENDS.get(name)
        if factory is None:
            raise RuntimeError(
                f"historian '{name}' did not register a backend factory")
        backends.append(factory(scenario_name, run_id))
    return CompositeHistorian(backends)
