"""FastAPI routers that make the in-memory world look like real device REST APIs.

These deliberately mirror the *shape* of the real vendor APIs so the agent tools
speak REST exactly as they would against production Panorama / F5 / AKS / Splunk.
"""
from __future__ import annotations
import ipaddress
from fastapi import APIRouter, Body, HTTPException
from . import state

router = APIRouter()


# ============================ Palo Alto Panorama ============================
pan = APIRouter(prefix="/api/panorama", tags=["Palo Alto Panorama"])


@pan.get("/rules")
def list_rules():
    return {"result": {"rules": state.security_rules()}}


@pan.get("/address-objects")
def address_objects():
    return {"result": state.ADDRESS_OBJECTS}


def _in_cidr(ip: str, cidr: str) -> bool:
    if cidr in ("0.0.0.0/0", "any"):
        return True
    try:
        return ipaddress.ip_address(ip) in ipaddress.ip_network(cidr, strict=False)
    except ValueError:
        return False


@pan.post("/connectivity-check")
def connectivity_check(payload: dict = Body(...)):
    """Evaluate whether src can reach dst:port/proto against the live policy.

    Mirrors Panorama's 'test security-policy-match' operational command.
    """
    src = payload.get("src")
    dst = payload.get("dst")
    port = int(payload.get("port", 0))
    proto = str(payload.get("proto", "tcp")).lower()
    if not src or not dst:
        raise HTTPException(400, "src and dst are required")

    for rule in state.security_rules():
        if (_in_cidr(src, rule["src"]) and _in_cidr(dst, rule["dst"])
                and (rule["port"] in (0, port))
                and (rule["proto"] in ("any", proto))):
            return {"result": {
                "src": src, "dst": dst, "port": port, "proto": proto,
                "allowed": rule["action"] == "allow",
                "action": rule["action"],
                "matched_rule": rule["name"],
                "rule_note": rule.get("note"),
                "nat": {"applied": False},
            }}
    return {"result": {"src": src, "dst": dst, "port": port, "proto": proto,
                       "allowed": False, "action": "deny",
                       "matched_rule": "implicit-deny", "nat": {"applied": False}}}


# ================================ F5 BIG-IP ================================
f5 = APIRouter(prefix="/api/f5", tags=["F5 BIG-IP"])


@f5.get("/virtuals")
def virtuals():
    return {"result": [{"name": v["name"], "destination": v["destination"],
                        "pool": v["pool"], "availability": v["availability"]}
                       for v in state.f5_virtuals()]}


@f5.get("/virtual/{name}")
def virtual(name: str):
    for v in state.f5_virtuals():
        if v["name"] == name:
            return {"result": v}
    raise HTTPException(404, f"virtual server {name!r} not found")


@f5.get("/pool/{pool}")
def pool(pool: str):
    for v in state.f5_virtuals():
        if v["pool"] == pool:
            up = sum(1 for m in v["members"] if m["status"] == "up")
            return {"result": {"pool": pool, "members_total": len(v["members"]),
                               "members_up": up, "members": v["members"]}}
    raise HTTPException(404, f"pool {pool!r} not found")


# ============================== Azure / AKS ==============================
aks = APIRouter(prefix="/api/aks", tags=["Azure AKS"])


@aks.get("/workloads")
def workloads():
    return {"result": [{"name": w["name"], "namespace": w["namespace"],
                        "desired": w["desired"], "ready": w["ready"]}
                       for w in state.aks_workloads()]}


@aks.get("/workload/{name}")
def workload(name: str):
    for w in state.aks_workloads():
        if w["name"] == name:
            return {"result": w}
    raise HTTPException(404, f"workload {name!r} not found")


# ================================= Splunk =================================
splunk = APIRouter(prefix="/api/splunk", tags=["Splunk"])


@splunk.get("/metrics")
def metrics(service: str, window: str = "now"):
    if window not in ("now", "baseline"):
        raise HTTPException(400, "window must be 'now' or 'baseline'")
    return {"result": {"service": service, "window": window,
                       "metrics": state.splunk_metrics(service, window)}}


@splunk.post("/search")
def search(payload: dict = Body(...)):
    query = payload.get("query", "*")
    return {"result": {"query": query, "events": state.splunk_search(query)}}


# =============================== ServiceNow ===============================
snow = APIRouter(prefix="/api/servicenow", tags=["ServiceNow"])


@snow.post("/incident")
def create_incident(payload: dict = Body(...)):
    ticket = state.create_ticket(
        short_desc=payload.get("short_description", "Network automation ticket"),
        description=payload.get("description", ""),
        priority=payload.get("priority", "3 - Moderate"),
        cmdb_ci=payload.get("cmdb_ci", ""),
        assignment_group=payload.get("assignment_group", "Network Engineering"),
    )
    return {"result": ticket}


@snow.get("/incident/{number}")
def get_incident(number: str):
    t = state.get_ticket(number)
    if not t:
        raise HTTPException(404, f"incident {number!r} not found")
    return {"result": t}


# ============================ Simulation control ============================
sim = APIRouter(prefix="/api/sim", tags=["Simulation"])


@sim.get("/scenario")
def get_scenario():
    return {"scenario": state.current_scenario(), "incident_active": state.is_incident()}


@sim.post("/incident")
def set_incident(payload: dict = Body(default={})):
    active = bool(payload.get("active", True))
    state.set_scenario("p1_checkout_outage" if active else "healthy")
    return {"scenario": state.current_scenario(), "incident_active": state.is_incident()}


for r in (pan, f5, aks, splunk, snow, sim):
    router.include_router(r)
