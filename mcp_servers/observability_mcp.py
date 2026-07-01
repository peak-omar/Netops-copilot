"""Observability MCP server: Splunk telemetry and AKS workload tools over MCP.

Run standalone (stdio):
    python -m mcp_servers.observability_mcp
"""
from mcp.server.fastmcp import FastMCP
from backend.tools import network_tools as nt

mcp = FastMCP("observability-netops")


@mcp.tool()
def compare_to_baseline(service: str) -> dict:
    """Pull Splunk 'baseline' vs 'now' metrics for a service and return the per-signal
    delta (error rate, latency, 5xx, firewall denies, pool-down, pod restarts)."""
    return nt.compare_to_baseline(service)


@mcp.tool()
def search_logs(query: str) -> dict:
    """Run a Splunk search across firewall / load balancer / pod / app logs."""
    return nt.search_logs(query)


@mcp.tool()
def get_aks_workload(name: str) -> dict:
    """Get an Azure AKS workload: desired vs ready replicas and pod status."""
    return nt.get_aks_workload(name)


if __name__ == "__main__":
    mcp.run()
