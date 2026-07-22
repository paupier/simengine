"""Gate P7 — OPC UA PubSub over MQTT publisher (mocked paho client, no real
broker). Covers OPCUAMqttPublisher, the class build_publishers() actually
wires up (src/simengine/publishers/__init__.py) — the only MQTT-over-OPC-UA
class in this codebase; the legacy MQTTPublisher this file used to test was
never instantiated anywhere in src/ and has been removed."""
import json
from unittest.mock import MagicMock, patch

import pytest

from simengine.engine.line import LineEngine
from simengine.publishers.metrics import line_metrics, station_metrics
from simengine.publishers.opcua_mqtt import (
    OPCUAMqttPublisher,
    _parse_mqtt_url,
    flat_topic,
)


def demo_config():
    return {
        "line_name": "Line1",
        "stations": [
            {"name": "Press01", "cycle_time": 3.0, "defect_rate": 0.05,
             "process_values": [
                 {"name": "OilTemp", "unit": "degC", "profile": "first_order_lag",
                  "setpoint": 55.0, "tau": 60, "initial": 20.0}]},
            {"name": "Pack02", "cycle_time": 2.0},
        ],
        "buffers": [{"name": "B1", "capacity": 5}],
    }


MQTT_CFG = {"broker": "mqtt://mosquitto:1883", "publisher_id": "simengine-line1"}


@pytest.fixture
def pub_engine():
    engine = LineEngine(demo_config(), "demo", seed=1, run_id="mqtt_test")
    pub = OPCUAMqttPublisher(demo_config(), MQTT_CFG)
    pub._client = MagicMock()
    pub._connected = True
    return pub, engine


def sent_messages(pub):
    """[(topic, parsed JSON payload)] from the mocked client, in call order."""
    out = []
    for call in pub._client.publish.call_args_list:
        topic = call.args[0]
        out.append((topic, json.loads(call.args[1])))
    return out


# ---------------------------------------------------------------------------
# _parse_mqtt_url / flat_topic — module-level helpers, still live
# ---------------------------------------------------------------------------

class TestParseMqttUrl:
    def test_valid(self):
        host, port = _parse_mqtt_url("mqtt://mosquitto:1883")
        assert host == "mosquitto"
        assert port == 1883

    def test_missing_port_raises(self):
        with pytest.raises(ValueError, match="port"):
            _parse_mqtt_url("mqtt://mosquitto")

    def test_wrong_scheme_raises(self):
        with pytest.raises(ValueError, match="mqtt://"):
            _parse_mqtt_url("tcp://mosquitto:1883")


class TestFlatTopic:
    def test_shape_and_lowercasing(self):
        assert flat_topic("Line1", "Press01", "PV/OilTemp") == "simengine/Line1/Press01/pv_oiltemp"


# ---------------------------------------------------------------------------
# OPCUAMqttPublisher.__init__ / properties
# ---------------------------------------------------------------------------

class TestConfig:
    def test_topics_use_publisher_id(self):
        pub = OPCUAMqttPublisher(demo_config(), MQTT_CFG)
        assert pub.status_topic == "opcua/simengine-line1/status"
        assert pub.data_topic == "opcua/simengine-line1/json"

    def test_publisher_id_defaults_when_absent(self):
        pub = OPCUAMqttPublisher(demo_config(), {"broker": "mqtt://mosquitto:1883"})
        assert pub.status_topic == "opcua/simengine-line1/status"

    def test_flat_topics_defaults_true(self):
        pub = OPCUAMqttPublisher(demo_config(), {"broker": "mqtt://mosquitto:1883"})
        assert pub._flat_topics is True

    def test_flat_topic_method_delegates_to_module_function(self):
        pub = OPCUAMqttPublisher(demo_config(), MQTT_CFG)
        assert pub.flat_topic("Press01", "PV/OilTemp") == flat_topic("Line1", "Press01", "PV/OilTemp")

    def test_bad_broker_url_raises_at_construction(self):
        with pytest.raises(ValueError, match="mqtt://"):
            OPCUAMqttPublisher(demo_config(), {"broker": "tcp://mosquitto:1883"})


# ---------------------------------------------------------------------------
# publish() — envelope shape, gating, flat topics, dropped-count behavior
# ---------------------------------------------------------------------------

class TestPublish:
    def test_disconnected_drops_and_does_not_call_client(self, pub_engine):
        pub, engine = pub_engine
        pub._connected = False
        pub.publish(engine.snapshot())
        assert pub._dropped == 1
        pub._client.publish.assert_not_called()

    def test_envelope_and_payload_match_snapshot(self, pub_engine):
        pub, engine = pub_engine
        snap = engine.snapshot()
        pub.publish(snap)
        msgs = dict(sent_messages(pub))
        envelope = msgs["opcua/simengine-line1/json"]

        assert envelope["MessageType"] == "ua-data"
        assert envelope["PublisherId"] == "simengine-line1"
        assert envelope["DataSetWriterId"] == 1
        assert envelope["MessageId"] == f"step-{snap.step_count}"
        assert "Timestamp" in envelope

        payload = envelope["Payload"]
        expected_press01_keys = {f"Press01.{k.replace('/', '.')}"
                                  for k in station_metrics(snap.stations["Press01"])}
        assert expected_press01_keys <= payload.keys()
        expected_line_keys = {f"Line.{k.replace('/', '.')}" for k in line_metrics(snap)}
        assert expected_line_keys <= payload.keys()
        # spot-check an actual value round-trips correctly, not just the key
        assert payload["Press01.State"] == snap.stations["Press01"].state

    def test_flat_topics_published_when_enabled(self, pub_engine):
        pub, engine = pub_engine
        pub.publish(engine.snapshot())
        topics = [t for t, _ in sent_messages(pub)]
        assert "simengine/Line1/Press01/state" in topics
        flat_msg = dict(sent_messages(pub))["simengine/Line1/Press01/state"]
        assert set(flat_msg.keys()) == {"value", "sim_time", "run_id"}
        assert flat_msg["run_id"] == "mqtt_test"

    def test_flat_topics_suppressed_when_disabled(self, pub_engine):
        pub, engine = pub_engine
        pub._flat_topics = False
        pub.publish(engine.snapshot())
        topics = [t for t, _ in sent_messages(pub)]
        assert topics == ["opcua/simengine-line1/json"]

    def test_publish_interval_gates_repeated_calls(self, pub_engine):
        pub, engine = pub_engine
        pub._publish_interval = 5.0
        snap1 = engine.snapshot()
        pub.publish(snap1)
        first_call_count = pub._client.publish.call_count
        assert first_call_count > 0

        # one sim step advances sim_time by less than publish_interval — gated
        engine.step()
        snap2 = engine.snapshot()
        assert snap2.sim_time - snap1.sim_time < pub._publish_interval
        pub.publish(snap2)
        assert pub._client.publish.call_count == first_call_count  # no new publishes

    def test_publish_interval_allows_call_once_elapsed(self, pub_engine):
        pub, engine = pub_engine
        pub._publish_interval = 0.0  # always publish
        pub.publish(engine.snapshot())
        first_call_count = pub._client.publish.call_count
        engine.step()
        pub.publish(engine.snapshot())
        assert pub._client.publish.call_count > first_call_count

    def test_client_publish_exception_increments_dropped_without_raising(self, pub_engine):
        pub, engine = pub_engine
        pub._client.publish.side_effect = RuntimeError("boom")
        pub.publish(engine.snapshot())  # must not raise
        assert pub._dropped == 1


# ---------------------------------------------------------------------------
# Lifecycle — on_run_start / on_run_end / close
# ---------------------------------------------------------------------------

class TestLifecycle:
    def test_on_run_start_wires_will_and_connect(self):
        pub = OPCUAMqttPublisher(demo_config(), MQTT_CFG)
        with patch("simengine.publishers.opcua_mqtt.mqtt") as mock_mqtt_module, \
             patch("simengine.publishers.opcua_mqtt._PAHO_AVAILABLE", True):
            mock_client = MagicMock()
            mock_mqtt_module.Client.return_value = mock_client
            mock_mqtt_module.CallbackAPIVersion.VERSION2 = "v2"
            mock_mqtt_module.MQTTv5 = 5

            pub.on_run_start(snapshot=None)

            mock_client.will_set.assert_called_once_with(
                pub.status_topic, "OFFLINE", qos=1, retain=True)
            mock_client.connect_async.assert_called_once_with("mosquitto", 1883)
            mock_client.loop_start.assert_called_once()
            assert pub._client is mock_client

    def test_on_connect_callback_publishes_online_retained(self):
        pub = OPCUAMqttPublisher(demo_config(), MQTT_CFG)
        with patch("simengine.publishers.opcua_mqtt.mqtt") as mock_mqtt_module, \
             patch("simengine.publishers.opcua_mqtt._PAHO_AVAILABLE", True):
            mock_client = MagicMock()
            mock_mqtt_module.Client.return_value = mock_client
            mock_mqtt_module.CallbackAPIVersion.VERSION2 = "v2"
            mock_mqtt_module.MQTTv5 = 5

            pub.on_run_start(snapshot=None)
            on_connect = mock_client.on_connect
            on_connect(mock_client, None, {}, 0, None)  # simulate broker ACK

            assert pub._connected is True
            mock_client.publish.assert_any_call(pub.status_topic, "ONLINE", qos=1, retain=True)

    def test_on_run_end_publishes_offline_when_connected(self, pub_engine):
        pub, _ = pub_engine
        pub.on_run_end()
        pub._client.publish.assert_called_once_with(
            pub.status_topic, "OFFLINE", qos=1, retain=True)

    def test_on_run_end_no_op_when_not_connected(self, pub_engine):
        pub, _ = pub_engine
        pub._connected = False
        pub.on_run_end()
        pub._client.publish.assert_not_called()

    def test_close_disconnects_client(self, pub_engine):
        pub, _ = pub_engine
        pub.close()
        pub._client.loop_stop.assert_called_once()
        pub._client.disconnect.assert_called_once()

    def test_close_logs_dropped_count(self, pub_engine, caplog):
        pub, engine = pub_engine
        pub._connected = False
        pub.publish(engine.snapshot())
        assert pub._dropped == 1
        with caplog.at_level("INFO"):
            pub.close()
        assert "1 publishes dropped" in caplog.text
