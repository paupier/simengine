"""
Inject InfluxDB historian config into all scenarios for Docker deployment.

Reads line_models.yaml, adds historian block (with InfluxDB enabled) to any
scenario that lacks one, and writes the result to line_models_runtime.yaml.
Scenarios that already have a historian block are updated to enable InfluxDB
and point at the Docker-internal InfluxDB URL.
"""
import os
import yaml
from pathlib import Path


def inject_historian_config():
    """Pre-process line_models.yaml to enable InfluxDB for all scenarios."""
    config_dir = Path("/app/config")
    source_path = config_dir / "line_models.yaml"
    output_path = config_dir / "line_models_runtime.yaml"

    with open(source_path, "r") as f:
        all_configs = yaml.safe_load(f)

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
        yaml.dump(all_configs, f, default_flow_style=False, sort_keys=False)

    print(f"[Docker] Generated runtime config: {output_path}")
    print(f"[Docker] InfluxDB URL: {influxdb_url}")
    print(f"[Docker] {len(all_configs)} scenarios configured with historian")


if __name__ == "__main__":
    inject_historian_config()
