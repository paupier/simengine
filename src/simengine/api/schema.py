"""Wire-schema export for OPC UA / MQTT / SparkplugB — the literal address
space / topic / metric structure a given scenario config will publish, with
no engine run and no broker/server connection required. See
docs/superpowers/specs/2026-07-24-schema-export-design.md.

Everything here is derived from the *same* builders the live publishers use
(``build_address_space`` for OPC UA, ``metrics.py``'s schema constants for
MQTT/SparkplugB), so the exported schema cannot drift from what a run
actually serves — the no-drift assertions in tests/test_schema.py pin that.
"""
from __future__ import annotations

import io
from contextlib import contextmanager

from asyncua import ua
from asyncua.common.xmlexporter import XmlExporter

from simengine.publishers.metrics import line_metric_schema, station_metric_schema
from simengine.publishers.opcua_mqtt import flat_topic
from simengine.publishers.opcua_server import build_address_space, close_unstarted

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


@contextmanager
def _throwaway_address_space(config: dict, port: int):
    """Build the address space, yield (server, namespace_idx), always release.

    asyncua.sync.Server() starts a ThreadLoop in its constructor, so every
    schema request would leak two threads without this teardown — these
    servers are built purely to be walked and are never started.
    """
    server, _, idx = build_address_space(config, port, run_id="", speed_ratio=1.0)
    try:
        yield server, idx
    finally:
        close_unstarted(server)


async def _walk(node) -> dict:
    node_class = (await node.read_node_class()).name
    entry = {
        "name": (await node.read_browse_name()).Name,
        "node_id": node.nodeid.to_string(),
        "node_class": node_class,
    }
    if node_class == "Variable":
        vtype = await node.read_data_type_as_variant_type()
        entry["data_type"] = _DATATYPE_NAMES.get(vtype, str(vtype))
    children = await node.get_children()
    if children:
        entry["children"] = [await _walk(c) for c in children]
    return entry


async def _own_type_nodes(aio_server, idx) -> list:
    """The ObjectTypes this address space declares (StationType, …).

    Instances carry HasTypeDefinition references to these, so any export that
    omitted them would import as instances of an undefined type.
    """
    base = aio_server.get_node(ua.NodeId(ua.ObjectIds.BaseObjectType))
    return [c for c in await base.get_children()
            if c.nodeid.NamespaceIndex == idx]


async def _walk_own_children(aio_server, idx) -> list:
    """Walk every simengine-namespace subtree under Objects, skipping the
    standard ns=0 Server boilerplate node."""
    return [await _walk(c)
            for c in await aio_server.nodes.objects.get_children()
            if c.nodeid.NamespaceIndex == idx]


async def _walk_own_types(aio_server, idx) -> list:
    return [await _walk(t) for t in await _own_type_nodes(aio_server, idx)]


def build_opcua_schema(config: dict, port: int = 4840) -> dict:
    """The real ISA-95 address-space tree for `config`, built and walked in
    memory (no `.start()`, no sockets) — same builder functions the live
    OPC UA server publisher uses, so this cannot drift from what a run
    actually serves.
    """
    with _throwaway_address_space(config, port) as (server, idx):
        # One coroutine for the whole walk: each SyncNode attribute read is a
        # separate thread round-trip onto the event loop, and the tree runs to
        # hundreds of nodes.
        children = server.tloop.post(_walk_own_children(server.aio_obj, idx))
        object_types = server.tloop.post(_walk_own_types(server.aio_obj, idx))
    return {
        "endpoint": f"opc.tcp://<host>:{port}/simengine/",
        "namespace_uri": "http://simengine.local/",
        "object_types": object_types,
        "address_space": {
            "name": "Objects",
            "node_class": "Object",
            "children": children,
        },
    }


def build_nodeset2_xml(config: dict, port: int = 4840) -> str:
    """OPC UA NodeSet2 (``UANodeSet``) XML for `config` — the standard,
    tool-neutral information-model exchange format.

    Importable offline by FactoryTalk Optix, Ignition, UaExpert and any other
    OPC UA client, so an integrator can bind screens against the scenario's
    address space without ever starting the engine. Instance nodes only (the
    address space declares no custom ObjectTypes); the ns=0 Server subtree is
    excluded.
    """
    with _throwaway_address_space(config, port) as (server, idx):
        aio_server = server.aio_obj

        async def _export() -> str:
            nodes = []

            async def collect(node):
                nodes.append(node)
                for child in await node.get_children():
                    await collect(child)

            # ObjectTypes first: instances reference them via HasTypeDefinition.
            for type_node in await _own_type_nodes(aio_server, idx):
                await collect(type_node)

            for child in await aio_server.nodes.objects.get_children():
                if child.nodeid.NamespaceIndex == idx:
                    await collect(child)

            exporter = XmlExporter(aio_server)
            await exporter.build_etree(nodes)
            buf = io.BytesIO()
            await exporter.write_xml(buf)
            return buf.getvalue().decode("utf-8")

        # asyncua's XmlExporter is async-only; run the whole export as one
        # coroutine on the server's own ThreadLoop (post() blocks and returns
        # the coroutine's result).
        return server.tloop.post(_export())


def build_mqtt_schema(config: dict, mqtt_cfg: dict) -> dict:
    """Part 14 JSON envelope shape + flat-topic list for `config` — derived
    from the same metric name/datatype schema the real publisher uses
    (metrics.py), so the Payload keys cannot drift from what
    OPCUAMqttPublisher.publish() actually writes.
    """
    line = config.get("line_name", "Line1")
    publisher_id = mqtt_cfg.get("publisher_id", "simengine-line1")
    publish_interval = mqtt_cfg.get("publish_interval", 1)
    flat_topics_enabled = mqtt_cfg.get("flat_topics", True)
    stations = config.get("stations", [])
    buffers = config.get("buffers", [])

    payload: dict = {}
    for name, dtype in line_metric_schema([b["name"] for b in buffers]):
        payload[f"Line.{name.replace('/', '.')}"] = dtype

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
                    "payload": {"value": dtype, "sim_time": "Float",
                                "run_id": "String"},
                })

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
    # The {"enabled": True} fallback applies only when the whole comms.opcua
    # key is absent — a block that exists but omits "enabled" is disabled,
    # matching how build_publishers() reads it.
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
