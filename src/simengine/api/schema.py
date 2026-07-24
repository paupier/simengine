"""Wire-schema export for OPC UA / MQTT / SparkplugB — the literal address
space / topic / metric structure a given scenario config will publish, with
no engine run and no broker/server connection required. See
docs/superpowers/specs/2026-07-24-schema-export-design.md.
"""
from __future__ import annotations

from opcua import ua

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
