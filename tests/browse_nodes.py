"""
Browse OPC UA Address Space

Quick script to discover the correct node paths in the server.
"""
from opcua import Client


def browse_nodes():
    """Browse and print the OPC UA address space"""
    print("Connecting to OPC UA server...")
    client = Client("opc.tcp://localhost:4840/simantha/")
    client.connect()

    print("\nBrowsing address space...\n")

    # Get the root Objects node
    root = client.get_objects_node()
    print(f"Root: {root}")

    # Browse children
    def print_tree(node, indent=0):
        try:
            children = node.get_children()
            for child in children:
                name = child.get_browse_name()
                print("  " * indent + f"├─ {name.Name} (NodeId: {child.nodeid})")
                print_tree(child, indent + 1)
        except Exception as e:
            pass

    print_tree(root)

    client.disconnect()


if __name__ == "__main__":
    browse_nodes()
