"""State publisher layer (build plan P6.1).

One abstraction, three implementations (OPC UA TCP, OPC UA PubSub over MQTT,
SparkplugB), all selectable independently via the scenario ``comms`` block.
All publishers consume the same per-step ``LineSnapshot``.
"""
from abc import ABC, abstractmethod
from typing import List

from simengine.engine.snapshot import LineSnapshot


class StatePublisher(ABC):
    """Publisher lifecycle: birth -> per-step publish -> death -> close."""

    @abstractmethod
    def on_run_start(self, snapshot: LineSnapshot) -> None:
        """Address space ready / birth messages."""

    @abstractmethod
    def publish(self, snapshot: LineSnapshot) -> None:
        """Called once per engine step (or per publish_interval)."""

    @abstractmethod
    def on_run_end(self) -> None:
        """Death messages / cleanup at run end."""

    def close(self) -> None:
        """Release resources (default: nothing)."""


class CompositePublisher(StatePublisher):
    """Fan-out to all enabled publishers."""

    def __init__(self, publishers: List[StatePublisher]):
        self.publishers = list(publishers)

    def on_run_start(self, snapshot: LineSnapshot) -> None:
        for p in self.publishers:
            p.on_run_start(snapshot)

    def publish(self, snapshot: LineSnapshot) -> None:
        for p in self.publishers:
            p.publish(snapshot)

    def on_run_end(self) -> None:
        for p in self.publishers:
            p.on_run_end()

    def close(self) -> None:
        for p in self.publishers:
            p.close()


def build_publishers(config: dict) -> CompositePublisher:
    """Construct the publisher stack from the scenario ``comms`` block.

    Guarded imports: MQTT-based publishers are only imported when enabled so
    the core runs with zero broker-related setup by default.
    """
    comms = config.get("comms", {}) or {}
    publishers: List[StatePublisher] = []

    opcua_cfg = comms.get("opcua", {"enabled": True})
    if opcua_cfg.get("enabled", False):
        from simengine.publishers.opcua_server import OPCUAServerPublisher
        publishers.append(OPCUAServerPublisher(config, port=opcua_cfg.get("port", 4840)))

    mqtt_cfg = comms.get("opcua_mqtt", {})
    if mqtt_cfg.get("enabled", False):
        from simengine.publishers.opcua_mqtt import OPCUAMqttPublisher
        publishers.append(OPCUAMqttPublisher(config, mqtt_cfg))

    spb_cfg = comms.get("sparkplugb", {})
    if spb_cfg.get("enabled", False):
        from simengine.publishers.sparkplugb import SparkplugBPublisher
        publishers.append(SparkplugBPublisher(config, spb_cfg))

    return CompositePublisher(publishers)
