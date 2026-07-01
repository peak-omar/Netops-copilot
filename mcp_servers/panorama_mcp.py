"""Palo Alto Panorama MCP server.

Exposes the firewall tools over MCP so an MCP client can call them. Reuses the
same tool functions as the in-app agents.

Run standalone (stdio):
    python -m mcp_servers.panorama_mcp
"""
from mcp.server.fastmcp import FastMCP
from backend.tools import network_tools as nt

mcp = FastMCP("panorama-netops")


@mcp.tool()
def check_connectivity(src: str, dst: str, port: int, proto: str = "tcp") -> dict:
    """Test whether a source IP can reach a destination IP on a TCP/UDP port
    through the Palo Alto security policy (Panorama 'test security-policy-match')."""
    return nt.check_connectivity(src, dst, port, proto)


@mcp.tool()
def get_firewall_rules() -> dict:
    """Return the current Palo Alto security policy (top-down, first match wins)."""
    return nt.get_firewall_rules()


if __name__ == "__main__":
    mcp.run()
