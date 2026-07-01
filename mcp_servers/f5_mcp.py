"""F5 BIG-IP MCP server: VIP and pool health tools over MCP.

Run standalone (stdio):
    python -m mcp_servers.f5_mcp
"""
from mcp.server.fastmcp import FastMCP
from backend.tools import network_tools as nt

mcp = FastMCP("f5-netops")


@mcp.tool()
def list_virtual_servers() -> list:
    """List all F5 virtual servers (VIPs) and their availability."""
    return nt.list_virtual_servers()


@mcp.tool()
def get_vip_status(name: str) -> dict:
    """Get an F5 virtual server (VIP): destination, pool, availability, members."""
    return nt.get_vip_status(name)


@mcp.tool()
def get_pool_health(pool: str) -> dict:
    """Get F5 pool health: how many members are up/down and why."""
    return nt.get_pool_health(pool)


if __name__ == "__main__":
    mcp.run()
