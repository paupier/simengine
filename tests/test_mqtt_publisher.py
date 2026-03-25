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
