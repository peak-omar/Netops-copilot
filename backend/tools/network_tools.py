"""Network operation tools.

Each tool calls the device REST APIs over httpx. The same functions are used by
the LangGraph agents and by the MCP servers under /mcp_servers, so device access
is defined in one place.
"""
from __future__ import annotations
from typing import Any, Dict
import httpx

from ..config import INTERNAL_API_BASE

_TIMEOUT = 10.0


def _get(path: str, **params) -> Any:
    r = httpx.get(f"{INTERNAL_API_BASE}{path}", params=params, timeout=_TIMEOUT)
    r.raise_for_status()
    return r.json().get("result")


def _post(path: str, body: dict) -> Any:
    r = httpx.post(f"{INTERNAL_API_BASE}{path}", json=body, timeout=_TIMEOUT)
    r.raise_for_status()
    return r.json().get("result")


# ----------------------------- read-only tools -----------------------------
def check_connectivity(src: str, dst: str, port: int, proto: str = "tcp") -> Dict:
    """Test whether source IP can reach destination IP on a port through the
    Palo Alto firewall policy (like 'test security-policy-match')."""
    return _post("/api/panorama/connectivity-check",
                 {"src": src, "dst": dst, "port": port, "proto": proto})


def get_firewall_rules() -> Dict:
    """Return the current Palo Alto security policy (top-down, first match wins)."""
    return _get("/api/panorama/rules")


def list_virtual_servers() -> Any:
    """List all F5 virtual servers (VIPs) and their availability."""
    return _get("/api/f5/virtuals")


def get_vip_status(name: str) -> Dict:
    """Get an F5 virtual server (VIP): destination, pool, availability, members."""
    return _get(f"/api/f5/virtual/{name}")


def get_pool_health(pool: str) -> Dict:
    """Get F5 pool health: how many members are up/down and why."""
    return _get(f"/api/f5/pool/{pool}")


def get_aks_workload(name: str) -> Dict:
    """Get an Azure AKS workload: desired vs ready replicas and pod status."""
    return _get(f"/api/aks/workload/{name}")


def list_aks_workloads() -> Any:
    """List Azure AKS workloads and their ready/desired replica counts."""
    return _get("/api/aks/workloads")


def get_metrics(service: str, window: str = "now") -> Dict:
    """Get Splunk metrics for a service. window is 'now' or 'baseline'."""
    return _get("/api/splunk/metrics", service=service, window=window)


def compare_to_baseline(service: str) -> Dict:
    """Pull Splunk 'baseline' vs 'now' metrics for a service and compute the delta
    for each signal -- the core of needle-in-the-haystack triage."""
    base = _get("/api/splunk/metrics", service=service, window="baseline")["metrics"]
    now = _get("/api/splunk/metrics", service=service, window="now")["metrics"]
    deltas = {}
    for k in now:
        b, n = base.get(k, 0), now[k]
        deltas[k] = {"baseline": b, "now": n, "delta": round(n - b, 2),
                     "anomalous": abs(n - b) > (abs(b) * 0.5 + 1)}
    return {"service": service, "deltas": deltas}


def search_logs(query: str) -> Dict:
    """Run a Splunk search across firewall/LB/pod/app logs."""
    return _post("/api/splunk/search", {"query": query})


# ------------------------- write tool (HITL-gated) -------------------------
def create_servicenow_ticket(short_description: str, description: str,
                             priority: str = "2 - High",
                             cmdb_ci: str = "",
                             assignment_group: str = "Network Engineering") -> Dict:
    """Create a ServiceNow incident. WRITE ACTION -- only ever called after a
    human approves the proposed ticket in the UI."""
    return _post("/api/servicenow/incident", {
        "short_description": short_description, "description": description,
        "priority": priority, "cmdb_ci": cmdb_ci,
        "assignment_group": assignment_group,
    })


# tool registry: name -> handler, schema, read/write flag
# schema is JSON-schema 'parameters' for OpenAI/MCP tool definitions.
TOOL_REGISTRY: Dict[str, Dict] = {
    "check_connectivity": {
        "func": check_connectivity, "readonly": True,
        "description": check_connectivity.__doc__,
        "parameters": {"type": "object", "properties": {
            "src": {"type": "string", "description": "source IP, e.g. 10.20.4.12"},
            "dst": {"type": "string", "description": "destination IP, e.g. 10.30.5.10"},
            "port": {"type": "integer"}, "proto": {"type": "string", "default": "tcp"},
        }, "required": ["src", "dst", "port"]},
    },
    "get_firewall_rules": {
        "func": get_firewall_rules, "readonly": True,
        "description": get_firewall_rules.__doc__,
        "parameters": {"type": "object", "properties": {}},
    },
    "list_virtual_servers": {
        "func": list_virtual_servers, "readonly": True,
        "description": list_virtual_servers.__doc__,
        "parameters": {"type": "object", "properties": {}},
    },
    "get_vip_status": {
        "func": get_vip_status, "readonly": True,
        "description": get_vip_status.__doc__,
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string", "description": "VIP name, e.g. checkout_vip"}},
            "required": ["name"]},
    },
    "get_pool_health": {
        "func": get_pool_health, "readonly": True,
        "description": get_pool_health.__doc__,
        "parameters": {"type": "object", "properties": {
            "pool": {"type": "string", "description": "pool name, e.g. checkout_pool"}},
            "required": ["pool"]},
    },
    "get_aks_workload": {
        "func": get_aks_workload, "readonly": True,
        "description": get_aks_workload.__doc__,
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string", "description": "workload, e.g. checkout-api"}},
            "required": ["name"]},
    },
    "list_aks_workloads": {
        "func": list_aks_workloads, "readonly": True,
        "description": list_aks_workloads.__doc__,
        "parameters": {"type": "object", "properties": {}},
    },
    "get_metrics": {
        "func": get_metrics, "readonly": True, "description": get_metrics.__doc__,
        "parameters": {"type": "object", "properties": {
            "service": {"type": "string"}, "window": {"type": "string",
            "enum": ["now", "baseline"], "default": "now"}}, "required": ["service"]},
    },
    "compare_to_baseline": {
        "func": compare_to_baseline, "readonly": True,
        "description": compare_to_baseline.__doc__,
        "parameters": {"type": "object", "properties": {
            "service": {"type": "string"}}, "required": ["service"]},
    },
    "search_logs": {
        "func": search_logs, "readonly": True, "description": search_logs.__doc__,
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string"}}, "required": ["query"]},
    },
    "create_servicenow_ticket": {
        "func": create_servicenow_ticket, "readonly": False,
        "description": create_servicenow_ticket.__doc__,
        "parameters": {"type": "object", "properties": {
            "short_description": {"type": "string"},
            "description": {"type": "string"},
            "priority": {"type": "string", "default": "2 - High"},
            "cmdb_ci": {"type": "string"},
            "assignment_group": {"type": "string", "default": "Network Engineering"},
        }, "required": ["short_description", "description"]},
    },
}


def openai_tool_specs(names: list[str]) -> list[dict]:
    """Build OpenAI-style tool specs for the given tool names."""
    specs = []
    for n in names:
        t = TOOL_REGISTRY[n]
        specs.append({"type": "function", "function": {
            "name": n,
            "description": (t["description"] or "").strip(),
            "parameters": t["parameters"],
        }})
    return specs


def call_tool(name: str, args: dict) -> Any:
    if name not in TOOL_REGISTRY:
        raise KeyError(f"unknown tool {name!r}")
    return TOOL_REGISTRY[name]["func"](**args)
