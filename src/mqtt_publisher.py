"""OPC UA PubSub over MQTT publisher (Part 14 JSON + flat JSON).

Activated by the --mqtt CLI flag. Non-blocking; QoS 0 fire-and-forget.
Broker unreachable → simulation continues normally, steps are dropped silently.
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


def _parse_mqtt_url(url: str) -> tuple[str, int]:
    """Parse 'mqtt://host:port' → (host, port).

    Raises ValueError on malformed input.
    """
    if not url.startswith("mqtt://"):
        raise ValueError(f"MQTT broker URL must start with mqtt:// — got: {url!r}")
    rest = url[len("mqtt://"):]
    if ":" not in rest:
        raise ValueError(
            f"MQTT broker URL must include a port (e.g. mqtt://mosquitto:1883) — got: {url!r}"
        )
    host, port_str = rest.rsplit(":", 1)
    try:
        port = int(port_str)
    except ValueError:
        raise ValueError(f"MQTT broker port must be an integer — got: {port_str!r}")
    if not host:
        raise ValueError(f"MQTT broker URL has empty host — got: {url!r}")
    return host, port
