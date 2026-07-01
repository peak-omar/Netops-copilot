"""LangGraph orchestration.

The router sends a request down one of two paths:

    query flow: single node that answers self-service questions
                (connectivity / VIP / pool).
    rca flow:   telemetry -> firewall -> f5 -> aks -> correlation ->
                knowledge (RAG) -> synthesis.

Both paths end at the `propose` node, which drafts a ServiceNow ticket when one
is warranted. The graph never files the ticket itself; that happens only after a
person approves it in the UI.
"""
from __future__ import annotations
import operator
from typing import Annotated, TypedDict

from langgraph.graph import StateGraph, START, END

from .reasoner import llm_tool_loop, narrate
from .rag import get_store
from ..tools import network_tools as nt

# service under investigation for the RCA flow (demo is checkout-centric)
RCA_SERVICE = "checkout-api"


def _merge(a: dict, b: dict) -> dict:
    out = dict(a or {})
    out.update(b or {})
    return out


class GraphState(TypedDict, total=False):
    query: str
    mode: str
    steps: Annotated[list, operator.add]
    findings: Annotated[dict, _merge]
    answer: str
    root_cause: dict
    citations: list
    proposed_ticket: dict


def _step(agent: str, tool: str, args: dict, result, ok: bool = True) -> dict:
    return {"agent": agent, "tool": tool, "args": args, "result": result, "ok": ok}


# ------------------------------- router -------------------------------
_RCA_HINTS = ("outage", "p1", "root cause", "incident", " down", "5xx",
              "why is", "broken", "degrad", "not working", "failing")
_QUERY_HINTS = ("can ", "reach", "vip", "pool", "port", "healthy", "acl",
                "allowed", "connect", "created")


def router_node(state: GraphState) -> dict:
    q = state["query"].lower()
    if any(h in q for h in _RCA_HINTS):
        mode = "rca"
    else:
        mode = "query"
    return {"mode": mode,
            "steps": [_step("router", "classify", {"query": state["query"]}, {"mode": mode})]}


def route_from_router(state: GraphState) -> str:
    return state["mode"]


# ------------------------- Flow 1: self-service -------------------------
_QUERY_SYSTEM = (
    "You are a self-service network assistant for non-technical teams. Answer "
    "network questions precisely using the provided tools. Always state a clear "
    "verdict (ALLOWED/BLOCKED, healthy/unhealthy) and cite the firewall rule name "
    "or the specific pool member status you relied on. Keep it to a few sentences. "
    "Do not make any changes; if a change is needed, say so and a ticket will be "
    "proposed for human approval."
)
_QUERY_TOOLS = ["check_connectivity", "get_firewall_rules", "list_virtual_servers",
                "get_vip_status", "get_pool_health", "get_aks_workload",
                "list_aks_workloads"]


def query_node(state: GraphState) -> dict:
    steps: list = []
    answer = llm_tool_loop(_QUERY_SYSTEM, state["query"], _QUERY_TOOLS, steps.append)
    return {"answer": answer, "steps": steps}


# ------------------------- Flow 2: RCA pipeline -------------------------
def telemetry_node(state: GraphState) -> dict:
    cmp = nt.compare_to_baseline(RCA_SERVICE)
    anomalies = {k: v for k, v in cmp["deltas"].items() if v["anomalous"]}
    return {"findings": {"telemetry": {"service": RCA_SERVICE, "anomalies": anomalies,
                                       "deltas": cmp["deltas"]}},
            "steps": [_step("telemetry", "compare_to_baseline", {"service": RCA_SERVICE},
                            {"anomalous_signals": list(anomalies)})]}


def firewall_node(state: GraphState) -> dict:
    logs = nt.search_logs("firewall deny 5432")
    match = nt.check_connectivity("10.20.4.12", "10.30.5.10", 5432)
    return {"findings": {"firewall": {"policy_match": match, "deny_logs": logs["events"]}},
            "steps": [_step("firewall", "search_logs", {"query": "firewall deny 5432"},
                            {"events": logs["events"]}),
                      _step("firewall", "check_connectivity",
                            {"src": "10.20.4.12", "dst": "10.30.5.10", "port": 5432}, match)]}


def f5_node(state: GraphState) -> dict:
    pool = nt.get_pool_health("checkout_pool")
    vip = nt.get_vip_status("checkout_vip")
    return {"findings": {"f5": {"pool": pool, "vip": {"name": vip["name"],
                                "availability": vip["availability"]}}},
            "steps": [_step("f5", "get_pool_health", {"pool": "checkout_pool"}, pool),
                      _step("f5", "get_vip_status", {"name": "checkout_vip"},
                            {"availability": vip["availability"]})]}


def aks_node(state: GraphState) -> dict:
    wl = nt.get_aks_workload(RCA_SERVICE)
    crashing = [p for p in wl["pods"] if p["status"] != "Running"]
    return {"findings": {"aks": {"ready": wl["ready"], "desired": wl["desired"],
                                 "crashing": crashing}},
            "steps": [_step("aks", "get_aks_workload", {"name": RCA_SERVICE},
                            {"ready": wl["ready"], "desired": wl["desired"],
                             "crashing": [p["name"] for p in crashing]})]}


def correlation_node(state: GraphState) -> dict:
    f = state.get("findings", {})
    fw = f.get("firewall", {})
    aks = f.get("aks", {})
    f5 = f.get("f5", {})
    match = fw.get("policy_match", {})
    hypotheses = []

    db_blocked = match.get("allowed") is False and match.get("port") == 5432
    pods_db_timeout = any("5432" in (p.get("last_error", "")) for p in aks.get("crashing", []))
    pool_down = f5.get("pool", {}).get("members_up", 99) < f5.get("pool", {}).get("members_total", 0)

    if db_blocked:
        hypotheses.append({
            "rank": 1, "confidence": 0.94,
            "root_cause": "Palo Alto policy change is denying app-tier -> db-tier on TCP 5432",
            "matched_rule": match.get("matched_rule"),
            "why": "Firewall denies on 5432 line up in time with checkout pod DB-timeout "
                   "CrashLoops and F5 members failing /healthz. The firewall change is the "
                   "cause; the pool-down and 5xx are downstream symptoms.",
            "evidence": [
                f"firewall policy match app->db:5432 = {match.get('action')} "
                f"(rule {match.get('matched_rule')})",
                "checkout pods CrashLoopBackOff with 'dial tcp 10.30.5.10:5432: timed out'"
                if pods_db_timeout else "checkout pods not ready",
                f"F5 checkout_pool {f5.get('pool', {}).get('members_up')}/"
                f"{f5.get('pool', {}).get('members_total')} members up",
            ],
            "blast_radius": "checkout-api (VIP checkout_vip degraded)",
            "recommended_fix": "Roll back/correct Panorama rule "
                               f"{match.get('matched_rule')} so app->db:5432 is allow; commit + push.",
        })
    elif pool_down:
        hypotheses.append({"rank": 1, "confidence": 0.55,
                           "root_cause": "F5 pool members down - investigate backing workload",
                           "why": "Pool members failing health checks without a clear upstream cause.",
                           "evidence": ["pool members down"], "blast_radius": "checkout_vip",
                           "recommended_fix": "Inspect checkout-api workload and dependencies."})

    if not hypotheses:
        return {"root_cause": {"summary": "No anomalies detected - all signals at baseline.",
                               "hypotheses": []},
                "steps": [_step("correlation", "correlate", {},
                                {"result": "nominal"})]}

    root = {"summary": hypotheses[0]["root_cause"], "hypotheses": hypotheses}
    return {"root_cause": root,
            "steps": [_step("correlation", "correlate", {"signals": ["firewall", "aks", "f5", "telemetry"]},
                            {"top_hypothesis": hypotheses[0]["root_cause"],
                             "confidence": hypotheses[0]["confidence"]})]}


def knowledge_node(state: GraphState) -> dict:
    root = state.get("root_cause", {})
    query = root.get("summary", state["query"])
    hits = get_store().search(query, k=2)
    return {"citations": hits,
            "steps": [_step("knowledge", "rag_search", {"query": query},
                            {"sources": [h["source"] for h in hits]})]}


def synthesis_node(state: GraphState) -> dict:
    root = state.get("root_cause", {})
    cites = state.get("citations", [])
    if not root.get("hypotheses"):
        return {"answer": "No anomalies detected across firewall, F5, AKS, or Splunk "
                          "telemetry for checkout-api - everything is at baseline."}
    top = root["hypotheses"][0]
    ev = "\n".join(f"- {e}" for e in top["evidence"])
    src = ", ".join(c["source"] for c in cites) or "n/a"
    fallback = (f"**Root cause ({int(top['confidence']*100)}% confidence):** "
                f"{top['root_cause']}.\n\n{top['why']}\n\n**Evidence:**\n{ev}\n\n"
                f"**Recommended fix:** {top['recommended_fix']}\n\n_Runbooks: {src}_")
    user = (f"Write a crisp P1 root-cause summary for a NOC engineer.\n"
            f"Root cause: {top['root_cause']}\nWhy: {top['why']}\n"
            f"Evidence:\n{ev}\nRecommended fix: {top['recommended_fix']}\n"
            f"Relevant runbooks: {src}\nKeep it under 150 words, decisive.")
    answer = narrate("You are a senior network incident commander.", user, fallback)
    return {"answer": answer}


# ------------------------------- propose (HITL) -------------------------------
def propose_node(state: GraphState) -> dict:
    # Flow 2: propose an incident ticket for a confirmed root cause.
    root = state.get("root_cause", {})
    if root.get("hypotheses"):
        top = root["hypotheses"][0]
        ticket = {
            "short_description": f"P1: {top['root_cause']}",
            "description": f"{top['why']}\n\nEvidence:\n" +
                           "\n".join(f"- {e}" for e in top["evidence"]) +
                           f"\n\nRecommended fix: {top['recommended_fix']}",
            "priority": "1 - Critical",
            "cmdb_ci": top.get("blast_radius", ""),
            "assignment_group": "Network Engineering",
        }
        return {"proposed_ticket": ticket}

    # Flow 1: propose a firewall change request if a check came back BLOCKED.
    for s in state.get("steps", []):
        r = s.get("result")
        if s.get("tool") == "check_connectivity" and isinstance(r, dict) and r.get("allowed") is False:
            ticket = {
                "short_description": f"Firewall change: allow {r['src']} -> {r['dst']}:{r['port']}",
                "description": f"Self-service request. Policy match returned "
                               f"{r['action']} (rule {r['matched_rule']}). Requesting review to "
                               f"permit {r['src']} -> {r['dst']} on {r['port']}/{r.get('proto','tcp')}.",
                "priority": "3 - Moderate",
                "cmdb_ci": r["dst"],
                "assignment_group": "Network Engineering",
            }
            return {"proposed_ticket": ticket}
    return {}


# ------------------------------- build graph -------------------------------
def _build():
    g = StateGraph(GraphState)
    g.add_node("router", router_node)
    g.add_node("query", query_node)
    g.add_node("telemetry", telemetry_node)
    g.add_node("firewall", firewall_node)
    g.add_node("f5", f5_node)
    g.add_node("aks", aks_node)
    g.add_node("correlation", correlation_node)
    g.add_node("knowledge", knowledge_node)
    g.add_node("synthesis", synthesis_node)
    g.add_node("propose", propose_node)

    g.add_edge(START, "router")
    g.add_conditional_edges("router", route_from_router,
                            {"query": "query", "rca": "telemetry"})
    g.add_edge("query", "propose")
    g.add_edge("telemetry", "firewall")
    g.add_edge("firewall", "f5")
    g.add_edge("f5", "aks")
    g.add_edge("aks", "correlation")
    g.add_edge("correlation", "knowledge")
    g.add_edge("knowledge", "synthesis")
    g.add_edge("synthesis", "propose")
    g.add_edge("propose", END)
    return g.compile()


GRAPH = _build()


def run_graph(query: str) -> dict:
    state = GRAPH.invoke({"query": query, "steps": [], "findings": {}})
    return {
        "mode": state.get("mode"),
        "answer": state.get("answer", ""),
        "steps": state.get("steps", []),
        "root_cause": state.get("root_cause"),
        "citations": state.get("citations", []),
        "proposed_ticket": state.get("proposed_ticket"),
    }
