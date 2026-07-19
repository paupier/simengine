"""OPC UA PubSub over MQTT publisher (Part 14 JSON + flat JSON).

Carried from the parent (build plan P7.1). ``MQTTPublisher`` is the transport
core; ``OPCUAMqttPublisher`` adapts it to the ``StatePublisher`` / LineSnapshot
contract with the clone's topic scheme:

  opcua/{publisher_id}/json               Part 14 NetworkMessage envelope
  opcua/{publisher_id}/status             retained ONLINE / Will OFFLINE
  simengine/{line}/{station}/{metric}     optional flat per-metric JSON

Non-blocking; QoS 0 fire-and-forget. Broker unreachable → simulation continues
normally, steps are dropped silently.
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


class MQTTPublisher:
    """Publishes per-step simulation snapshots to an MQTT broker.

    Two formats per step:
      opcua/simantha/{run_id}/machines/M{i}  — OPC UA Part 14 JSON Network Message
      opcua/simantha/{run_id}/system          — OPC UA Part 14 JSON (line KPIs)
      simantha/{run_id}/machines/M{i}         — flat JSON
      simantha/{run_id}/system                — flat JSON

    QoS 0 (fire-and-forget).  Never blocks the simulation step clock.
    If the broker is unreachable, dropped_steps is incremented and close()
    logs the total.
    """

    MESSAGE_EXPIRY_SECONDS = 5

    def __init__(self, broker_host: str, broker_port: int, run_id: str) -> None:
        self._host = broker_host
        self._port = broker_port
        self._run_id = run_id
        self._connected = False
        self._dropped_steps = 0
        self._logged_errors: set[str] = set()
        self._client: Optional[object] = None

    # ------------------------------------------------------------------
    # Topic helpers
    # ------------------------------------------------------------------

    def _machine_ua_topic(self, mname: str) -> str:
        return f"opcua/simantha/{self._run_id}/machines/{mname}"

    def _machine_flat_topic(self, mname: str) -> str:
        return f"simantha/{self._run_id}/machines/{mname}"

    def _system_ua_topic(self) -> str:
        return f"opcua/simantha/{self._run_id}/system"

    def _system_flat_topic(self) -> str:
        return f"simantha/{self._run_id}/system"

    # ------------------------------------------------------------------
    # Message builders
    # ------------------------------------------------------------------

    def _build_ua_message(self, source: str, payload: dict, step: int) -> str:
        """Build OPC UA Part 14 (pragmatic) JSON Network Message."""
        # DataSetWriterId: extract digit suffix from source (M1→1, system→100)
        try:
            writer_id = int("".join(c for c in source if c.isdigit()) or "100")
        except ValueError:
            writer_id = 100

        envelope = {
            "MessageId": f"step-{step}-{source}",
            "MessageType": "ua-data",
            "PublisherId": "simantha-opcua",
            "DataSetWriterId": writer_id,
            "Timestamp": datetime.now(timezone.utc).isoformat(),
            "Payload": payload,
        }
        return json.dumps(envelope, default=float)

    def _build_flat_message(self, source: str, payload: dict, sim_time: float) -> str:
        """Build flat JSON message with run_id, sim_time, source at top level."""
        msg = {
            "run_id": self._run_id,
            "sim_time": sim_time,
            "source": source,
        }
        msg.update(payload)
        return json.dumps(msg, default=float)

    # ------------------------------------------------------------------
    # Internal publish
    # ------------------------------------------------------------------

    def _publish(self, topic: str, payload_str: str) -> None:
        """Publish QoS 0 with MQTT 5.0 properties."""
        if not _PAHO_AVAILABLE or self._client is None:
            return
        try:
            props = Properties(PacketTypes.PUBLISH)
            props.ContentType = "application/json"
            props.MessageExpiryInterval = self.MESSAGE_EXPIRY_SECONDS
            self._client.publish(topic, payload_str, qos=0, properties=props)
        except Exception as e:
            key = type(e).__name__
            if key not in self._logged_errors:
                logger.warning("MQTT publish error (%s): %s", key, e)
                self._logged_errors.add(key)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Connect to broker.  On failure: log warning, set disconnected state."""
        if not _PAHO_AVAILABLE:
            logger.warning("paho-mqtt not installed; MQTT publisher disabled")
            return

        try:
            client = mqtt.Client(
                mqtt.CallbackAPIVersion.VERSION2,
                protocol=mqtt.MQTTv5,
            )

            def _on_connect(client, userdata, flags, reason_code, properties):
                if reason_code == 0:
                    self._connected = True
                    logger.info("MQTT connected to %s:%s", self._host, self._port)
                else:
                    logger.warning("MQTT connect refused: reason_code=%s", reason_code)

            def _on_disconnect(client, userdata, disconnect_flags, reason_code, properties):
                self._connected = False
                logger.warning("MQTT disconnected (reason=%s); auto-reconnecting…", reason_code)

            client.on_connect = _on_connect
            client.on_disconnect = _on_disconnect
            client.reconnect_delay_set(min_delay=1, max_delay=30)
            client.connect_async(self._host, self._port)
            client.loop_start()
            self._client = client
        except Exception as e:
            logger.warning("MQTT broker unreachable (%s); publisher disabled", e)
            self._connected = False

    def publish_step(
        self,
        machine_snapshot: dict,
        system_kpis: dict,
        sim_time: float,
        step: int,
    ) -> None:
        """Publish one step's worth of data.  QoS 0; never blocks."""
        if not self._connected:
            self._dropped_steps += 1
            return

        try:
            # Per-machine messages
            for mname, payload in machine_snapshot.items():
                ua_msg = self._build_ua_message(mname, payload, step)
                flat_msg = self._build_flat_message(mname, payload, sim_time)
                self._publish(self._machine_ua_topic(mname), ua_msg)
                self._publish(self._machine_flat_topic(mname), flat_msg)

            # System message
            ua_sys = self._build_ua_message("system", system_kpis, step)
            flat_sys = self._build_flat_message("system", system_kpis, sim_time)
            self._publish(self._system_ua_topic(), ua_sys)
            self._publish(self._system_flat_topic(), flat_sys)

        except Exception as e:
            key = f"publish_step:{type(e).__name__}"
            if key not in self._logged_errors:
                logger.warning("MQTT publish_step error: %s", e)
                self._logged_errors.add(key)
            self._dropped_steps += 1

    def close(self) -> None:
        """Disconnect and log dropped step count."""
        if self._client is not None:
            try:
                self._client.loop_stop()
                self._client.disconnect()
            except Exception:
                pass
        if self._dropped_steps > 0:
            logger.info(
                "MQTT publisher closed — dropped %d steps (broker unavailable)",
                self._dropped_steps,
            )


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
