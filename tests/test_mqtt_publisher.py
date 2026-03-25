"""Tests for MQTTPublisher — all use a mock paho client, no real broker."""
import json
import pytest
from unittest.mock import MagicMock, patch, call


# ---------------------------------------------------------------------------
# _parse_mqtt_url
# ---------------------------------------------------------------------------

def test_parse_mqtt_url_valid():
    from mqtt_publisher import _parse_mqtt_url
    host, port = _parse_mqtt_url("mqtt://mosquitto:1883")
    assert host == "mosquitto"
    assert port == 1883


def test_parse_mqtt_url_invalid_no_port():
    from mqtt_publisher import _parse_mqtt_url
    with pytest.raises(ValueError, match="port"):
        _parse_mqtt_url("mqtt://mosquitto")


def test_parse_mqtt_url_invalid_scheme():
    from mqtt_publisher import _parse_mqtt_url
    with pytest.raises(ValueError, match="mqtt://"):
        _parse_mqtt_url("tcp://mosquitto:1883")


# ---------------------------------------------------------------------------
# Helpers — shared test data
# ---------------------------------------------------------------------------

RUN_ID = "test_run_20260325_120000"

def _make_machine_snapshot(n=2):
    """Return a machine_snapshot dict with n machines (M1..Mn)."""
    snap = {}
    for i in range(1, n + 1):
        snap[f"M{i}"] = {
            "State": "PROCESSING",
            "OEE": 0.85,
            "Availability": 0.92,
            "Performance": 0.96,
            "Quality": 0.96,
            "PartCount": 100 * i,
            "GoodParts": 95 * i,
            "DefectiveParts": 5 * i,
            "HealthPct": 100.0,
            "Utilisation": 0.90,
            "ActualPPM": 48.0,
            "TargetPPM": 50.0,
            "DownTime": 0.0,
            "BlockedTime": 2.0,
            "StarvedTime": 3.0,
            "ProcessingTime": 55.0,
            "IdleTime": 0.0,
        }
    return snap


def _make_system_kpis():
    return {
        "SimTime": 120.0,
        "LineState": "RUNNING",
        "Throughput": 46.0,
        "TotalWIP": 10,
        "LineOEE": 0.83,
        "GoodParts": 950,
        "DefectiveParts": 50,
        "TotalScrap": 10,
        "ScrapRate": 0.01,
        "MaintenanceQueueLength": 0,
    }


def _make_publisher(run_id=RUN_ID):
    """Create MQTTPublisher with mocked paho Client."""
    from mqtt_publisher import MQTTPublisher
    with patch("mqtt_publisher.mqtt.Client") as MockClient:
        mock_client = MagicMock()
        MockClient.return_value = mock_client
        pub = MQTTPublisher("localhost", 1883, run_id)
        pub._client = mock_client
        pub._connected = True   # skip real connect for message tests
    return pub, mock_client


# ---------------------------------------------------------------------------
# Message format tests
# ---------------------------------------------------------------------------

def test_ua_message_envelope():
    """Part 14 envelope must have all required top-level fields."""
    pub, _ = _make_publisher()
    snap = _make_machine_snapshot(1)
    msg_str = pub._build_ua_message("M1", snap["M1"], step=5)
    msg = json.loads(msg_str)
    for field in ("MessageId", "MessageType", "PublisherId", "DataSetWriterId",
                  "Timestamp", "Payload"):
        assert field in msg, f"Missing field: {field}"
    assert msg["MessageType"] == "ua-data"
    assert msg["PublisherId"] == "simantha-opcua"
    assert "M1" in msg["MessageId"]
    assert isinstance(msg["Payload"], dict)
    assert msg["Payload"]["State"] == "PROCESSING"


def test_flat_message_fields():
    """Flat JSON must include run_id, sim_time, source and key KPI fields."""
    pub, _ = _make_publisher()
    snap = _make_machine_snapshot(1)
    msg_str = pub._build_flat_message("M1", snap["M1"], sim_time=120.0)
    msg = json.loads(msg_str)
    for field in ("run_id", "sim_time", "source", "State", "OEE"):
        assert field in msg, f"Missing field: {field}"
    assert msg["run_id"] == RUN_ID
    assert msg["sim_time"] == 120.0
    assert msg["source"] == "M1"


def test_topic_format_machine():
    pub, _ = _make_publisher()
    # Verify topic string construction directly
    expected_ua = f"opcua/simantha/{RUN_ID}/machines/M1"
    expected_flat = f"simantha/{RUN_ID}/machines/M1"
    assert pub._machine_ua_topic("M1") == expected_ua
    assert pub._machine_flat_topic("M1") == expected_flat


def test_topic_format_system():
    pub, _ = _make_publisher()
    expected_ua = f"opcua/simantha/{RUN_ID}/system"
    expected_flat = f"simantha/{RUN_ID}/system"
    assert pub._system_ua_topic() == expected_ua
    assert pub._system_flat_topic() == expected_flat
