"""MCP server (AI interface spec §2): FastMCP, streamable HTTP, :8765/mcp.

Runs in the engine process alongside REST — direct access to the run manager,
live snapshot, knowledge graph, and validators; no OPC UA round-trips.

Security note (by design): control tools are always on. Treat :8765 exactly
like :8080 — a trusted-network interface. Anything that can reach it can
start/stop runs and edit configs. Put a reverse proxy with auth in front of
both for anything beyond a trusted network.
"""
import logging
import threading

from simengine.api.tools import ToolRegistry

logger = logging.getLogger(__name__)

MCP_PORT = 8765
MCP_PATH = "/mcp"


def create_mcp_server(registry: ToolRegistry, host: str = "0.0.0.0",
                      port: int = MCP_PORT):
    """Build the FastMCP server with every registry tool attached."""
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP(
        "simengine",
        instructions=(
            "Live control and observation of a simengine station-simulation "
            "run: read line/station state, resolve metrics to wire addresses "
            "through the knowledge graph, and start/stop/configure runs."
        ),
        host=host,
        port=port,
        streamable_http_path=MCP_PATH,
        stateless_http=True,
    )
    for name, func in registry.all_tools():
        mcp.add_tool(func, name=name)
    return mcp


def start_mcp_server_thread(registry: ToolRegistry, host: str = "0.0.0.0",
                            port: int = MCP_PORT) -> threading.Thread:
    """Run the MCP server on a daemon thread next to the Flask app."""
    mcp = create_mcp_server(registry, host=host, port=port)

    def _serve():
        try:
            mcp.run(transport="streamable-http")
        except Exception:  # pragma: no cover - server crash is logged, not fatal
            logger.exception("MCP server crashed")

    thread = threading.Thread(target=_serve, daemon=True, name="mcp-server")
    thread.start()
    logger.info("MCP server listening on http://%s:%s%s", host, port, MCP_PATH)
    return thread
