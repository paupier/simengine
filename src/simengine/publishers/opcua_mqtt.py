"""OPC UA PubSub over MQTT publisher (Part 14 JSON + flat JSON).

``OPCUAMqttPublisher`` adapts the engine's ``StatePublisher`` / LineSnapshot
contract to MQTT, with the clone's topic scheme:

  opcua/{publisher_id}/json               Part 14 NetworkMessage envelope
  opcua/{publisher_id}/status             retained ONLINE / Will OFFLINE
  simengine/{line}/{station}/{metric}     optional flat per-metric JSON

Non-blocking; QoS 0 fire-and-forget. Broker unreachable → simulation continues
normally, steps are dropped silently.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

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


def flat_topic(line: str, station: str, metric: str) -> str:
    """Flat MQTT topic for one metric — single source of truth (KG uses it too)."""
    metric_path = metric.replace("/", "_").lower()
    return f"simengine/{line}/{station}/{metric_path}"


try:
    import paho.mqtt.client as mqtt
    from paho.mqtt.properties import Properties
    from paho.mqtt.packettypes import PacketTypes
    _PAHO_AVAILABLE = True
except ImportError:
    mqtt = None  # type: ignore
    _PAHO_AVAILABLE = False


# ---------------------------------------------------------------------------
# StatePublisher adapter (clone topic scheme, LineSnapshot input)
# ---------------------------------------------------------------------------

from simengine.publishers import StatePublisher  # noqa: E402
from simengine.publishers.metrics import line_metrics, station_metrics  # noqa: E402


class OPCUAMqttPublisher(StatePublisher):
    """OPC UA PubSub (Part 14 JSON) over MQTT, fed from LineSnapshot.

    Session identity: client id ``simengine-uapubsub-{publisher_id}``;
    ``PublisherId`` field inside every message; MQTT 5 ContentType
    ``application/json+opcua``; status-topic Will (architecture §3.2).
    """

    MESSAGE_EXPIRY_SECONDS = 5

    def __init__(self, config: dict, mqtt_cfg: dict) -> None:
        self._host, self._port = _parse_mqtt_url(mqtt_cfg["broker"])
        self._publisher_id = mqtt_cfg.get("publisher_id", "simengine-line1")
        self._flat_topics = bool(mqtt_cfg.get("flat_topics", True))
        self._publish_interval = float(mqtt_cfg.get("publish_interval", 1))
        self._line_name = config.get("line_name", "Line1")
        self._client = None
        self._connected = False
        self._dropped = 0
        self._last_published_sim_time = None
        self._logged_errors: set = set()

    @property
    def status_topic(self) -> str:
        return f"opcua/{self._publisher_id}/status"

    @property
    def data_topic(self) -> str:
        return f"opcua/{self._publisher_id}/json"

    def flat_topic(self, station: str, metric: str) -> str:
        return flat_topic(self._line_name, station, metric)

    # ----- lifecycle -----

    def on_run_start(self, snapshot) -> None:
        if not _PAHO_AVAILABLE:
            logger.warning("paho-mqtt not installed; OPC UA MQTT publisher disabled")
            return
        try:
            client = mqtt.Client(
                mqtt.CallbackAPIVersion.VERSION2,
                client_id=f"simengine-uapubsub-{self._publisher_id}",
                protocol=mqtt.MQTTv5,
            )
            client.will_set(self.status_topic, "OFFLINE", qos=1, retain=True)

            def _on_connect(c, userdata, flags, reason_code, properties):
                if reason_code == 0:
                    self._connected = True
                    c.publish(self.status_topic, "ONLINE", qos=1, retain=True)
                    logger.info("OPC UA MQTT connected to %s:%s", self._host, self._port)

            def _on_disconnect(c, userdata, disconnect_flags, reason_code, properties):
                self._connected = False

            client.on_connect = _on_connect
            client.on_disconnect = _on_disconnect
            client.reconnect_delay_set(min_delay=1, max_delay=30)
            client.connect_async(self._host, self._port)
            client.loop_start()
            self._client = client
        except Exception as e:
            logger.warning("MQTT broker unreachable (%s); publisher disabled", e)

    def publish(self, snapshot) -> None:
        if not self._connected:
            self._dropped += 1
            return
        if (self._last_published_sim_time is not None
                and snapshot.sim_time - self._last_published_sim_time
                < self._publish_interval):
            return
        self._last_published_sim_time = snapshot.sim_time
        try:
            payload = {}
            for name, st in snapshot.stations.items():
                for metric, (value, _dtype) in station_metrics(st).items():
                    payload[f"{name}.{metric.replace('/', '.')}"] = value
            for metric, (value, _dtype) in line_metrics(snapshot).items():
                payload[f"Line.{metric.replace('/', '.')}"] = value

            envelope = {
                "MessageId": f"step-{snapshot.step_count}",
                "MessageType": "ua-data",
                "PublisherId": self._publisher_id,
                "DataSetWriterId": 1,
                "Timestamp": datetime.now(timezone.utc).isoformat(),
                "Payload": payload,
            }
            self._mqtt_publish(self.data_topic, json.dumps(envelope, default=float))

            if self._flat_topics:
                for name, st in snapshot.stations.items():
                    for metric, (value, _dtype) in station_metrics(st).items():
                        self._mqtt_publish(
                            self.flat_topic(name, metric),
                            json.dumps({"value": value, "sim_time": snapshot.sim_time,
                                        "run_id": snapshot.run_id}, default=float),
                        )
        except Exception as e:
            key = f"publish:{type(e).__name__}"
            if key not in self._logged_errors:
                logger.warning("OPC UA MQTT publish error: %s", e)
                self._logged_errors.add(key)
            self._dropped += 1

    def _mqtt_publish(self, topic: str, payload: str) -> None:
        props = Properties(PacketTypes.PUBLISH)
        props.ContentType = "application/json+opcua"
        props.MessageExpiryInterval = self.MESSAGE_EXPIRY_SECONDS
        self._client.publish(topic, payload, qos=0, properties=props)

    def on_run_end(self) -> None:
        if self._client is not None and self._connected:
            try:
                self._client.publish(self.status_topic, "OFFLINE", qos=1, retain=True)
            except Exception:
                pass

    def close(self) -> None:
        if self._client is not None:
            try:
                self._client.loop_stop()
                self._client.disconnect()
            except Exception:
                pass
        if self._dropped:
            logger.info("OPC UA MQTT publisher closed — %d publishes dropped",
                        self._dropped)
