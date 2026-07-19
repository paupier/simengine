"""SparkplugB publisher (build plan P7.2).

Implementation note (binding fallback taken): ``mqtt-spb-wrapper`` hard-pins
``paho_mqtt==1.6.1``, which conflicts with the core ``paho-mqtt>=2.0``
dependency — the packaging-failure case the build plan anticipated. Per the
plan's fallback, ``sparkplug_b.proto`` is vendored from Eclipse Tahu, the
generated ``sparkplug_b_pb2.py`` is committed under ``_sparkplug_pb/``, and
paho-mqtt is used directly. Requires the ``sparkplug`` extra (protobuf).

Topics:
  spBv1.0/{group_id}/NBIRTH|NDATA|NDEATH/{edge_node_id}
  spBv1.0/{group_id}/DBIRTH|DDATA|DDEATH/{edge_node_id}/{station}
  spBv1.0/{group_id}/NCMD/{edge_node_id}          (subscribed: rebirth requests)

Spec behavior: DBIRTH declares every metric with name, stable alias, datatype
and initial value; NDATA/DDATA send only changed metrics by alias; full
rebirth on NCMD "Node Control/Rebirth"; NDEATH via MQTT Will with bdSeq;
seq number cycling 0-255 across all messages of the session.
"""
import logging
import threading
import time
from typing import Dict, Optional, Tuple

from simengine.publishers import StatePublisher
from simengine.publishers.metrics import line_metrics, station_metrics
from simengine.publishers.opcua_mqtt import _parse_mqtt_url

logger = logging.getLogger(__name__)

try:
    import paho.mqtt.client as mqtt
    _PAHO_AVAILABLE = True
except ImportError:  # pragma: no cover
    mqtt = None
    _PAHO_AVAILABLE = False


def _load_pb2():
    try:
        from simengine.publishers._sparkplug_pb import sparkplug_b_pb2
        return sparkplug_b_pb2
    except ImportError as e:  # protobuf runtime missing
        raise RuntimeError(
            "SparkplugB publisher requires the 'sparkplug' extra: "
            "pip install simengine[sparkplug]"
        ) from e


# proto DataType enum values (sparkplug_b.proto)
_DATATYPE = {"Int32": 3, "UInt64": 8, "Float": 9, "Boolean": 11, "String": 12}


def _set_metric_value(metric, value, datatype: str) -> None:
    metric.datatype = _DATATYPE[datatype]
    if datatype == "Int32":
        metric.int_value = int(value)
    elif datatype == "UInt64":
        metric.long_value = int(value)
    elif datatype == "Float":
        metric.float_value = float(value)
    elif datatype == "Boolean":
        metric.boolean_value = bool(value)
    else:
        metric.string_value = str(value)


class SparkplugBPublisher(StatePublisher):
    """Sparkplug B edge node: one device per station."""

    def __init__(self, config: dict, spb_cfg: dict):
        self._pb2 = _load_pb2()
        self._host, self._port = _parse_mqtt_url(spb_cfg["broker"])
        self.group_id = spb_cfg["group_id"]
        self.edge_node_id = spb_cfg["edge_node_id"]
        self._client = None
        self._connected = False
        self._seq = 0
        self._bd_seq = 0
        self._rebirth_requested = threading.Event()
        # alias registry: device (None = node) -> metric name -> alias
        self._aliases: Dict[Optional[str], Dict[str, int]] = {}
        self._next_alias = 1
        # last-sent values for delta publishing: (device, name) -> value
        self._last_sent: Dict[Tuple[Optional[str], str], object] = {}
        self._birth_snapshot = None

    # ----- topics -----

    def _topic(self, msg_type: str, device: Optional[str] = None) -> str:
        base = f"spBv1.0/{self.group_id}/{msg_type}/{self.edge_node_id}"
        return f"{base}/{device}" if device else base

    @property
    def ncmd_topic(self) -> str:
        return self._topic("NCMD")

    # ----- seq / payload helpers -----

    def _next_seq(self) -> int:
        seq = self._seq
        self._seq = (self._seq + 1) % 256
        return seq

    def _new_payload(self, with_seq: bool = True):
        payload = self._pb2.Payload()
        payload.timestamp = int(time.time() * 1000)
        if with_seq:
            payload.seq = self._next_seq()
        return payload

    def _alias_for(self, device: Optional[str], name: str) -> int:
        device_aliases = self._aliases.setdefault(device, {})
        if name not in device_aliases:
            device_aliases[name] = self._next_alias
            self._next_alias += 1
        return device_aliases[name]

    def _add_birth_metric(self, payload, device, name, value, datatype):
        metric = payload.metrics.add()
        metric.name = name
        metric.alias = self._alias_for(device, name)
        metric.timestamp = payload.timestamp
        _set_metric_value(metric, value, datatype)
        self._last_sent[(device, name)] = value

    def _add_data_metric(self, payload, device, name, value, datatype):
        metric = payload.metrics.add()
        metric.alias = self._alias_for(device, name)
        metric.timestamp = payload.timestamp
        _set_metric_value(metric, value, datatype)
        self._last_sent[(device, name)] = value

    def _publish(self, topic: str, payload) -> None:
        if self._client is not None:
            self._client.publish(topic, payload.SerializeToString(), qos=0)

    # ----- births / deaths -----

    def _ndeath_payload(self):
        payload = self._pb2.Payload()
        payload.timestamp = int(time.time() * 1000)
        metric = payload.metrics.add()
        metric.name = "bdSeq"
        _set_metric_value(metric, self._bd_seq, "UInt64")
        return payload

    def _publish_births(self, snapshot) -> None:
        """NBIRTH then one DBIRTH per station; NBIRTH resets seq to 0."""
        self._seq = 0
        nbirth = self._new_payload()  # seq 0
        m = nbirth.metrics.add()
        m.name = "bdSeq"
        _set_metric_value(m, self._bd_seq, "UInt64")
        m = nbirth.metrics.add()
        m.name = "Node Control/Rebirth"
        _set_metric_value(m, False, "Boolean")
        for name, (value, dtype) in line_metrics(snapshot).items():
            self._add_birth_metric(nbirth, None, name, value, dtype)
        self._publish(self._topic("NBIRTH"), nbirth)

        for station_name, st in snapshot.stations.items():
            dbirth = self._new_payload()
            for name, (value, dtype) in station_metrics(st).items():
                self._add_birth_metric(dbirth, station_name, name, value, dtype)
            self._publish(self._topic("DBIRTH", station_name), dbirth)

    # ----- lifecycle -----

    def on_run_start(self, snapshot) -> None:
        self._birth_snapshot = snapshot
        if not _PAHO_AVAILABLE:  # pragma: no cover
            logger.warning("paho-mqtt not installed; SparkplugB publisher disabled")
            return
        try:
            client = mqtt.Client(
                mqtt.CallbackAPIVersion.VERSION2,
                client_id=f"simengine-spb-{self.edge_node_id}",
                protocol=mqtt.MQTTv311,
            )
            client.will_set(self._topic("NDEATH"),
                            self._ndeath_payload().SerializeToString(),
                            qos=0, retain=False)

            def _on_connect(c, userdata, flags, reason_code, properties=None):
                if int(getattr(reason_code, "value", reason_code)) == 0:
                    self._connected = True
                    c.subscribe(self.ncmd_topic, qos=0)
                    self._publish_births(self._birth_snapshot)
                    logger.info("SparkplugB connected: %s", self._topic("NBIRTH"))

            def _on_message(c, userdata, msg):
                self._handle_ncmd(msg.payload)

            def _on_disconnect(c, userdata, disconnect_flags, reason_code,
                               properties=None):
                self._connected = False

            client.on_connect = _on_connect
            client.on_message = _on_message
            client.on_disconnect = _on_disconnect
            client.reconnect_delay_set(min_delay=1, max_delay=30)
            client.connect_async(self._host, self._port)
            client.loop_start()
            self._client = client
        except Exception as e:
            logger.warning("SparkplugB broker unreachable (%s); disabled", e)

    def _handle_ncmd(self, raw: bytes) -> None:
        try:
            payload = self._pb2.Payload()
            payload.ParseFromString(raw)
            for metric in payload.metrics:
                if metric.name == "Node Control/Rebirth" and metric.boolean_value:
                    self._rebirth_requested.set()
        except Exception:
            logger.warning("SparkplugB: malformed NCMD ignored")

    def publish(self, snapshot) -> None:
        self._birth_snapshot = snapshot
        if not self._connected:
            return

        if self._rebirth_requested.is_set():
            self._rebirth_requested.clear()
            self._publish_births(snapshot)
            return

        # NDATA: changed node-level metrics only
        changed_node = [
            (name, value, dtype)
            for name, (value, dtype) in line_metrics(snapshot).items()
            if self._last_sent.get((None, name)) != value
        ]
        if changed_node:
            ndata = self._new_payload()
            for name, value, dtype in changed_node:
                self._add_data_metric(ndata, None, name, value, dtype)
            self._publish(self._topic("NDATA"), ndata)

        # DDATA per station: changed metrics only, by alias
        for station_name, st in snapshot.stations.items():
            changed = [
                (name, value, dtype)
                for name, (value, dtype) in station_metrics(st).items()
                if self._last_sent.get((station_name, name)) != value
            ]
            if changed:
                ddata = self._new_payload()
                for name, value, dtype in changed:
                    self._add_data_metric(ddata, station_name, name, value, dtype)
                self._publish(self._topic("DDATA", station_name), ddata)

    def on_run_end(self) -> None:
        if self._client is not None and self._connected:
            for station_name in (self._birth_snapshot.stations
                                 if self._birth_snapshot else {}):
                self._publish(self._topic("DDEATH", station_name),
                              self._new_payload())
            self._publish(self._topic("NDEATH"), self._ndeath_payload())

    def close(self) -> None:
        if self._client is not None:
            try:
                self._client.loop_stop()
                self._client.disconnect()
            except Exception:
                pass
        self._bd_seq += 1
