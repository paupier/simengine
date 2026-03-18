"""
Inject InfluxDB historian config into all scenarios for Docker deployment.

Reads line_models.yaml, adds historian block (with InfluxDB enabled) to any
scenario that lacks one, and writes the result to line_models_runtime.yaml.
Scenarios that already have a historian block are updated to enable InfluxDB
and point at the Docker-internal InfluxDB URL.

If line_models_runtime.yaml already exists (i.e. user has edited it via the
web UI), non-historian fields (like warm_up_time) are preserved from the
runtime file so that web UI edits survive container restarts.
"""
import os
from pathlib import Path

from ruamel.yaml import YAML

_ryaml = YAML()
_ryaml.preserve_quotes = True


def inject_historian_config():
    """Pre-process line_models.yaml to enable InfluxDB for all scenarios."""
    config_dir = Path("/app/config")
    source_path = config_dir / "line_models.yaml"
    output_path = config_dir / "line_models_runtime.yaml"

    with open(source_path, "r") as f:
        all_configs = _ryaml.load(f)

    # Load existing runtime YAML if it exists so we can preserve user edits
    # (e.g. warm_up_time changed via the web UI config editor).
    existing_runtime = {}
    if output_path.exists():
        try:
            with open(output_path, "r") as f:
                existing_runtime = _ryaml.load(f) or {}
            print(f"[Docker] Existing runtime config found — preserving user edits")
        except Exception as e:
            print(f"[Docker] Warning: could not read existing runtime config: {e}")

    influxdb_url = os.environ.get("INFLUXDB_URL", "http://influxdb:8086")
    influxdb_token = os.environ.get("INFLUXDB_TOKEN", "simantha-dev-token")
    influxdb_org = os.environ.get("INFLUXDB_ORG", "simantha")
    influxdb_bucket = os.environ.get("INFLUXDB_BUCKET", "manufacturing")

    historian_block = {
        "enabled": True,
        "csv": {
            "enabled": True,
            "output_dir": "results/historian",
            "max_file_size_mb": 50,
            "rotate_on_shift": True,
        },
        "influxdb": {
            "enabled": True,
            "url": influxdb_url,
            "token": influxdb_token,
            "org": influxdb_org,
            "bucket": influxdb_bucket,
            "batch_size": 100,
        },
        "events": {
            "state_changes": True,
            "alarms": True,
            "shift_changes": True,
            "maintenance": True,
            "spc_violations": True,
            "buffer_level_changes": True,
            "production_summary": True,
            "production_summary_interval": 60,
        },
    }

    for scenario_name, scenario_cfg in all_configs.items():
        if not isinstance(scenario_cfg, dict):
            continue

        # If the runtime YAML already has this scenario, overlay the user's
        # non-historian fields on top of the source config so edits are kept.
        existing_scenario = existing_runtime.get(scenario_name)
        if isinstance(existing_scenario, dict):
            # Preserve user-edited scalar fields (warm_up_time, description, …)
            # but NOT machines/buffers/historian — those come from source or
            # are handled below.
            preserved_keys = {
                "warm_up_time", "description", "source",
                "enterprise", "site", "area", "line_name",
            }
            for key in preserved_keys:
                if key in existing_scenario:
                    scenario_cfg[key] = existing_scenario[key]
            # Also preserve user-edited machines and buffers lists if present
            for key in ("machines", "buffers", "scrap_sinks", "shifts",
                        "maintainer"):
                if key in existing_scenario:
                    scenario_cfg[key] = existing_scenario[key]

        if "historian" not in scenario_cfg:
            # Scenario has no historian - inject full block
            scenario_cfg["historian"] = historian_block.copy()
        else:
            # Scenario has historian - ensure InfluxDB is enabled with Docker URL
            hist = scenario_cfg["historian"]
            hist["enabled"] = True
            if "influxdb" not in hist:
                hist["influxdb"] = {}
            hist["influxdb"]["enabled"] = True
            hist["influxdb"]["url"] = influxdb_url
            hist["influxdb"]["token"] = influxdb_token
            hist["influxdb"]["org"] = influxdb_org
            hist["influxdb"]["bucket"] = influxdb_bucket

    with open(output_path, "w") as f:
        _ryaml.dump(all_configs, f)

    print(f"[Docker] Generated runtime config: {output_path}")
    print(f"[Docker] InfluxDB URL: {influxdb_url}")
    print(f"[Docker] {len(all_configs)} scenarios configured with historian")


if __name__ == "__main__":
    inject_historian_config()
