"""Diagnostics — a protocol-level connectivity probe, independent of the
engine/knowledge-graph/publisher stack. A raw MQTT one-shot publish and an
in-memory REST scratch value, both for confirming this box is reachable
without needing a run active. See
docs/superpowers/specs/2026-07-23-diagnostics-tab-design.md.
"""
from __future__ import annotations

import paho.mqtt.publish as mqtt_publish

from simengine.publishers.opcua_mqtt import _parse_mqtt_url

_state: dict = {"value": None}


def get_value() -> str | None:
    return _state["value"]


def set_value(value: str) -> None:
    _state["value"] = value


def mqtt_publish_once(broker: str, topic: str, value: str) -> None:
    """One-shot connect/publish/disconnect against `broker`. Raises
    ValueError for a malformed broker URL (same message `_parse_mqtt_url`
    raises for the real MQTT publisher), or OSError for a network failure
    (refused, unreachable, DNS failure, timeout)."""
    host, port = _parse_mqtt_url(broker)
    mqtt_publish.single(topic, payload=value, hostname=host, port=port)
