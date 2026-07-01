"""In-memory state backing the lab network devices.

Two scenarios:
  healthy             everything nominal, baseline == now
  p1_checkout_outage  a Panorama policy change denies app-tier -> db-tier on
                      5432. checkout pods then CrashLoop (no DB), F5 members fail
                      health checks, the VIP degrades, and 5xx errors spike. The
                      firewall change is the cause; the rest are symptoms.

Toggle at runtime via POST /api/sim/incident.
"""
from __future__ import annotations
import copy
from threading import Lock

_lock = Lock()

SCENARIOS = ("healthy", "p1_checkout_outage")
_scenario = "healthy"

# Monotonic-ish counter for ServiceNow ticket numbers (no wall-clock in demo).
_ticket_seq = 1000
_TICKETS: dict[str, dict] = {}


def current_scenario() -> str:
    return _scenario


def set_scenario(name: str) -> str:
    global _scenario
    if name not in SCENARIOS:
        raise ValueError(f"unknown scenario {name!r}; expected one of {SCENARIOS}")
    with _lock:
        _scenario = name
    return _scenario


def is_incident() -> bool:
    return _scenario == "p1_checkout_outage"


# ---------------------------------------------------------------------------
# Palo Alto Panorama: address objects + security policy
# ---------------------------------------------------------------------------
ADDRESS_OBJECTS = {
    "web-tier":       {"cidr": "10.2.0.0/16"},
    "api-tier":       {"cidr": "10.9.0.0/16"},
    "app-tier":       {"cidr": "10.20.0.0/16"},
    "db-tier":        {"cidr": "10.30.5.0/24"},
    "checkout-db":    {"cidr": "10.30.5.10/32"},
}

# Baseline (healthy) security rules, evaluated top-down, first match wins.
_BASE_RULES = [
    {"name": "web-to-api-https", "src": "10.2.0.0/16", "dst": "10.9.0.0/16",
     "port": 443, "proto": "tcp", "action": "allow", "log": True},
    {"name": "app-to-db-postgres", "src": "10.20.0.0/16", "dst": "10.30.5.0/24",
     "port": 5432, "proto": "tcp", "action": "allow", "log": True},
    {"name": "app-to-api-https", "src": "10.20.0.0/16", "dst": "10.9.0.0/16",
     "port": 443, "proto": "tcp", "action": "allow", "log": True},
    {"name": "default-deny", "src": "0.0.0.0/0", "dst": "0.0.0.0/0",
     "port": 0, "proto": "any", "action": "deny", "log": True},
]

# The injected change for the P1 scenario: a deny rule shadowing the postgres allow.
_INJECTED_DENY = {
    "name": "block-app-db-CHG0092841", "src": "10.20.0.0/16", "dst": "10.30.5.0/24",
    "port": 5432, "proto": "tcp", "action": "deny", "log": True,
    "note": "Added by change CHG0092841 (misconfigured cleanup rule)",
}


def security_rules() -> list[dict]:
    rules = copy.deepcopy(_BASE_RULES)
    if is_incident():
        # Injected deny is placed ABOVE the postgres allow -> it shadows it.
        rules.insert(1, copy.deepcopy(_INJECTED_DENY))
    return rules


# ---------------------------------------------------------------------------
# F5 BIG-IP: virtual servers (VIPs) + pools
# ---------------------------------------------------------------------------
def f5_virtuals() -> list[dict]:
    checkout_members = [
        {"name": "checkout-node1", "addr": "10.20.4.11:8443", "status": "up"},
        {"name": "checkout-node2", "addr": "10.20.4.12:8443",
         "status": "down" if is_incident() else "up",
         "reason": "health monitor /healthz -> 503 (db unreachable)" if is_incident() else "ok"},
        {"name": "checkout-node3", "addr": "10.20.4.13:8443",
         "status": "down" if is_incident() else "up",
         "reason": "health monitor /healthz -> 503 (db unreachable)" if is_incident() else "ok"},
    ]
    up = sum(1 for m in checkout_members if m["status"] == "up")
    return [
        {
            "name": "checkout_vip", "destination": "10.9.0.5:443",
            "pool": "checkout_pool",
            "availability": "available" if up == len(checkout_members)
                            else ("degraded" if up > 0 else "offline"),
            "members": checkout_members,
        },
        {
            "name": "catalog_vip", "destination": "10.9.0.6:443",
            "pool": "catalog_pool", "availability": "available",
            "members": [
                {"name": "catalog-node1", "addr": "10.20.5.11:8443", "status": "up"},
                {"name": "catalog-node2", "addr": "10.20.5.12:8443", "status": "up"},
            ],
        },
    ]


# ---------------------------------------------------------------------------
# Azure AKS: workloads + pods
# ---------------------------------------------------------------------------
def aks_workloads() -> list[dict]:
    if is_incident():
        checkout = {
            "name": "checkout-api", "namespace": "prod", "desired": 3, "ready": 1,
            "pods": [
                {"name": "checkout-api-7c9-abcde", "status": "Running", "restarts": 0},
                {"name": "checkout-api-7c9-fghij", "status": "CrashLoopBackOff", "restarts": 7,
                 "last_error": "dial tcp 10.30.5.10:5432: connect: connection timed out"},
                {"name": "checkout-api-7c9-klmno", "status": "CrashLoopBackOff", "restarts": 6,
                 "last_error": "dial tcp 10.30.5.10:5432: connect: connection timed out"},
            ],
        }
    else:
        checkout = {
            "name": "checkout-api", "namespace": "prod", "desired": 3, "ready": 3,
            "pods": [
                {"name": f"checkout-api-7c9-{s}", "status": "Running", "restarts": 0}
                for s in ("abcde", "fghij", "klmno")
            ],
        }
    catalog = {
        "name": "catalog-api", "namespace": "prod", "desired": 2, "ready": 2,
        "pods": [{"name": f"catalog-api-5b2-{s}", "status": "Running", "restarts": 0}
                 for s in ("pqrst", "uvwxy")],
    }
    return [checkout, catalog]


# ---------------------------------------------------------------------------
# Splunk: metrics with a normal baseline vs. the live 'now' window
# ---------------------------------------------------------------------------
def splunk_metrics(service: str, window: str) -> dict:
    """window in {'baseline','now'}. Baseline is always the healthy shape."""
    service = service.lower()
    healthy = {
        "checkout-api": {"error_rate_pct": 0.2, "latency_p95_ms": 240,
                          "http_5xx_per_min": 1, "firewall_denies_5432_per_min": 0,
                          "pool_members_down": 0, "pod_restarts_5m": 0},
        "catalog-api": {"error_rate_pct": 0.1, "latency_p95_ms": 180,
                         "http_5xx_per_min": 0, "firewall_denies_5432_per_min": 0,
                         "pool_members_down": 0, "pod_restarts_5m": 0},
    }
    base = healthy.get(service, {"error_rate_pct": 0.1, "latency_p95_ms": 150,
                                 "http_5xx_per_min": 0, "firewall_denies_5432_per_min": 0,
                                 "pool_members_down": 0, "pod_restarts_5m": 0})
    if window == "baseline" or not is_incident() or service != "checkout-api":
        return dict(base)
    # incident 'now' shape for checkout-api
    return {
        "error_rate_pct": 61.4, "latency_p95_ms": 9800,
        "http_5xx_per_min": 412, "firewall_denies_5432_per_min": 337,
        "pool_members_down": 2, "pod_restarts_5m": 13,
    }


def splunk_search(query: str) -> list[dict]:
    q = query.lower()
    if not is_incident():
        return [{"host": "checkout-api", "level": "INFO", "msg": "request handled 200 in 210ms"}]
    logs = [
        {"host": "panorama", "level": "INFO",
         "msg": "commit pushed: change CHG0092841 added rule block-app-db-CHG0092841 (deny 10.20.0.0/16 -> 10.30.5.0/24:5432)"},
        {"host": "pan-fw-01", "level": "WARN",
         "msg": "DENY 10.20.4.12 -> 10.30.5.10:5432 rule=block-app-db-CHG0092841 (337/min)"},
        {"host": "checkout-api-7c9-fghij", "level": "ERROR",
         "msg": "dial tcp 10.30.5.10:5432: connect: connection timed out"},
        {"host": "f5-bigip-01", "level": "WARN",
         "msg": "pool checkout_pool member checkout-node2 monitor DOWN (/healthz 503)"},
        {"host": "checkout_vip", "level": "ERROR",
         "msg": "HTTP 503 upstream unavailable (1/3 members up)"},
    ]
    if "5432" in q or "deny" in q or "firewall" in q:
        return [l for l in logs if "5432" in l["msg"] or "DENY" in l["msg"] or "CHG" in l["msg"]]
    return logs


# ---------------------------------------------------------------------------
# ServiceNow: incident tickets (human-in-the-loop write target)
# ---------------------------------------------------------------------------
def create_ticket(short_desc: str, description: str, priority: str, cmdb_ci: str,
                  assignment_group: str) -> dict:
    global _ticket_seq
    with _lock:
        _ticket_seq += 1
        number = f"INC{_ticket_seq:07d}"
        ticket = {
            "number": number, "state": "New", "priority": priority,
            "short_description": short_desc, "description": description,
            "cmdb_ci": cmdb_ci, "assignment_group": assignment_group,
            "opened_by": "netops-copilot (agent, human-approved)",
        }
        _TICKETS[number] = ticket
    return ticket


def get_ticket(number: str) -> dict | None:
    return _TICKETS.get(number)
