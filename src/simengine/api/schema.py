"""Wire-schema export for OPC UA / MQTT / SparkplugB — the literal address
space / topic / metric structure a given scenario config will publish, with
no engine run and no broker/server connection required. See
docs/superpowers/specs/2026-07-24-schema-export-design.md.
"""
from __future__ import annotations

from opcua import ua

from simengine.publishers.metrics import line_metric_schema, station_metric_schema
from simengine.publishers.opcua_mqtt import flat_topic
from simengine.publishers.opcua_server import build_address_space

_DATATYPE_NAMES = {
    ua.VariantType.String: "String",
    ua.VariantType.Int32: "Int32",
    ua.VariantType.Int64: "Int64",
    ua.VariantType.UInt32: "UInt32",
    ua.VariantType.UInt64: "UInt64",
    ua.VariantType.Double: "Double",
    ua.VariantType.Float: "Float",
    ua.VariantType.Boolean: "Boolean",
    ua.VariantType.DateTime: "DateTime",
}


def _walk(node) -> dict:
    node_class = node.get_node_class().name
    entry = {
        "name": node.get_browse_name().Name,
        "node_id": node.nodeid.to_string(),
        "node_class": node_class,
    }
    if node_class == "Variable":
        vtype = node.get_data_type_as_variant_type()
        entry["data_type"] = _DATATYPE_NAMES.get(vtype, str(vtype))
    children = node.get_children()
    if children:
        entry["children"] = [_walk(c) for c in children]
    return entry


def build_opcua_schema(config: dict, port: int = 4840) -> dict:
    """The real ISA-95 address-space tree for `config`, built and walked in
    memory (no `.start()`, no sockets) — same builder functions the live
    OPC UA server publisher uses, so this cannot drift from what a run
    actually serves.
    """
    server, _, idx = build_address_space(config, port, run_id="", speed_ratio=1.0)
    objects = server.get_objects_node()
    own_children = [c for c in objects.get_children()
                    if c.nodeid.NamespaceIndex == idx]
    return {
        "endpoint": f"opc.tcp://<host>:{port}/simengine/",
        "namespace_uri": "http://simengine.local/",
        "address_space": {
            "name": "Objects",
            "node_class": "Object",
            "children": [_walk(c) for c in own_children],
        },
    }


def build_mqtt_schema(config: dict, mqtt_cfg: dict) -> dict:
    """Part 14 JSON envelope shape + flat-topic list for `config` — derived
    from the same metric name/datatype schema the real publisher uses
    (metrics.py), so the Payload keys cannot drift from what
    OPCUAMqttPublisher.publish() actually writes.
    """
    line = config.get("line_name", "Line1")
    publisher_id = mqtt_cfg.get("publisher_id", "simengine-line1")
    publish_interval = mqtt_cfg.get("publish_interval", 1)
    stations = config.get("stations", [])
    buffers = config.get("buffers", [])

    # Payload key order mirrors OPCUAMqttPublisher.publish() exactly: all
    # station metrics first (config order), then line metrics — so the schema
    # is byte-order-identical to the live envelope, not merely set-equal.
    payload: dict = {}
    flat_topics_enabled = mqtt_cfg.get("flat_topics", True)
    flat_topics = []
    for st_cfg in stations:
        st_name = st_cfg["name"]
        pv_names = [pv["name"] for pv in st_cfg.get("process_values", [])]
        schema = station_metric_schema(pv_names)
        for name, dtype in schema:
            payload[f"{st_name}.{name.replace('/', '.')}"] = dtype
        if flat_topics_enabled:
            for name, dtype in schema:
                flat_topics.append({
                    "topic": flat_topic(line, st_name, name),
                    "payload": {"value": dtype, "sim_time": "Float", "run_id": "String"},
                })
    for name, dtype in line_metric_schema([b["name"] for b in buffers]):
        payload[f"Line.{name.replace('/', '.')}"] = dtype

    return {
        "part14": {
            "data_topic": f"opcua/{publisher_id}/json",
            "status_topic": f"opcua/{publisher_id}/status",
            "publish_interval": publish_interval,
            "envelope": {
                "MessageId": "String",
                "MessageType": "String",
                "PublisherId": "String",
                "DataSetWriterId": "Int32",
                "Timestamp": "String",
                "Payload": payload,
            },
        },
        "flat_topics": flat_topics,
    }


def build_sparkplugb_schema(config: dict, spb_cfg: dict) -> dict:
    """SparkplugB NBIRTH/DBIRTH topic + metric/alias/datatype schema for
    `config`. Replicates SparkplugBPublisher._publish_births()'s exact
    registration order — node metrics (line-level) first, then per station
    in config order — so alias numbers match what a real run assigns,
    without touching protobuf or a broker connection.
    """
    area = config.get("area", "Area")
    line = config.get("line_name", "Line1")
    group_id = spb_cfg.get("group_id", area)
    edge_node_id = spb_cfg.get("edge_node_id", line)
    stations = config.get("stations", [])
    buffers = config.get("buffers", [])

    def topic(msg_type, device=None):
        base = f"spBv1.0/{group_id}/{msg_type}/{edge_node_id}"
        return f"{base}/{device}" if device else base

    next_alias = 1
    node_metrics = [
        {"name": "bdSeq", "alias": None, "datatype": "UInt64"},
        {"name": "Node Control/Rebirth", "alias": None, "datatype": "Boolean"},
    ]
    for name, dtype in line_metric_schema([b["name"] for b in buffers]):
        node_metrics.append({"name": name, "alias": next_alias, "datatype": dtype})
        next_alias += 1

    devices = []
    for st_cfg in stations:
        st_name = st_cfg["name"]
        pv_names = [pv["name"] for pv in st_cfg.get("process_values", [])]
        metrics = []
        for name, dtype in station_metric_schema(pv_names):
            metrics.append({"name": name, "alias": next_alias, "datatype": dtype})
            next_alias += 1
        devices.append({
            "station": st_name,
            "dbirth_topic": topic("DBIRTH", st_name),
            "ddata_topic": topic("DDATA", st_name),
            "ddeath_topic": topic("DDEATH", st_name),
            "metrics": metrics,
        })

    return {
        "group_id": group_id,
        "edge_node_id": edge_node_id,
        "nbirth_topic": topic("NBIRTH"),
        "ndata_topic": topic("NDATA"),
        "ndeath_topic": topic("NDEATH"),
        "ncmd_topic": topic("NCMD"),
        "node_metrics": node_metrics,
        "devices": devices,
    }


def build_schema(config: dict) -> dict:
    """Full schema export for one scenario config: OPC UA address space +
    MQTT (Part 14 + flat) + SparkplugB, each computed regardless of that
    protocol's `enabled` flag (so a protocol's shape can be previewed
    before it's turned on) but carrying that flag for the UI/caller.
    """
    comms = config.get("comms", {}) or {}
    opcua_cfg = comms.get("opcua", {"enabled": True}) or {"enabled": True}
    mqtt_cfg = comms.get("opcua_mqtt", {}) or {}
    spb_cfg = comms.get("sparkplugb", {}) or {}

    opcua_result = build_opcua_schema(config, port=opcua_cfg.get("port", 4840))
    opcua_result["enabled"] = opcua_cfg.get("enabled", False)

    mqtt_result = build_mqtt_schema(config, mqtt_cfg)
    mqtt_result["enabled"] = mqtt_cfg.get("enabled", False)

    spb_result = build_sparkplugb_schema(config, spb_cfg)
    spb_result["enabled"] = spb_cfg.get("enabled", False)

    return {"opcua": opcua_result, "mqtt": mqtt_result, "sparkplugb": spb_result}
