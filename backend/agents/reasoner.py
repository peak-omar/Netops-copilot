"""Reasoning helpers shared by the agents.

`llm_tool_loop` is a small ReAct-style tool-calling loop on the OpenAI API.
Every model tool-call is executed against the real network tools and recorded as
a step so the UI can render the agent's chain of reasoning. When no API key is
present, deterministic fallbacks keep the whole demo working offline.
"""
from __future__ import annotations
import json
import re
from typing import Callable

from .. import config
from ..tools import network_tools as nt


def _client():
    from openai import OpenAI
    return OpenAI(api_key=config.OPENAI_API_KEY)


def narrate(system: str, user: str, fallback: str) -> str:
    """One-shot LLM text generation with an offline fallback."""
    if config.USE_MOCK_LLM:
        return fallback
    try:
        resp = _client().chat.completions.create(
            model=config.OPENAI_MODEL, temperature=0.2,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
        )
        return resp.choices[0].message.content.strip()
    except Exception:
        return fallback


def llm_tool_loop(system: str, user: str, tool_names: list[str],
                  on_step: Callable[[dict], None], max_iters: int = 6) -> str:
    """Run a tool-calling loop. Executes tool calls, streams steps via on_step,
    returns the model's final natural-language answer."""
    if config.USE_MOCK_LLM:
        return _mock_loop(user, tool_names, on_step)

    client = _client()
    specs = nt.openai_tool_specs(tool_names)
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": user}]
    final = ""
    for _ in range(max_iters):
        resp = client.chat.completions.create(
            model=config.OPENAI_MODEL, temperature=0.1,
            messages=messages, tools=specs, tool_choice="auto")
        msg = resp.choices[0].message
        if not msg.tool_calls:
            final = (msg.content or "").strip()
            break
        messages.append({"role": "assistant", "content": msg.content,
                         "tool_calls": [tc.model_dump() for tc in msg.tool_calls]})
        for tc in msg.tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            try:
                result = nt.call_tool(name, args)
                ok = True
            except Exception as e:  # surface tool errors back to the model
                result, ok = {"error": str(e)}, False
            on_step({"agent": "query", "tool": name, "args": args,
                     "result": result, "ok": ok})
            messages.append({"role": "tool", "tool_call_id": tc.id,
                             "content": json.dumps(result)[:4000]})
    return final or "I gathered the data above."


# ---------------------------------------------------------------------------
# Offline deterministic planner for the self-service (Flow 1) queries.
# ---------------------------------------------------------------------------
_IP_RE = re.compile(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b")
_PORT_RE = re.compile(r"\b(?:port\s*)?(\d{2,5})\b")


def _mock_loop(user: str, tool_names: list[str], on_step) -> str:
    text = user.lower()
    ips = _IP_RE.findall(user)

    if "check_connectivity" in tool_names and len(ips) >= 2:
        ports = [int(p) for p in _PORT_RE.findall(user) if p not in ips[0] and p not in ips[1]]
        port = ports[0] if ports else 443
        res = nt.check_connectivity(ips[0], ips[1], port)
        on_step({"agent": "query", "tool": "check_connectivity",
                 "args": {"src": ips[0], "dst": ips[1], "port": port}, "result": res, "ok": True})
        verdict = "ALLOWED" if res["allowed"] else "BLOCKED"
        return (f"{ips[0]} -> {ips[1]}:{port} is **{verdict}** "
                f"(matched rule `{res['matched_rule']}`).")

    m = re.search(r"([a-z0-9_]+_vip)", text)
    if m and "get_vip_status" in tool_names:
        res = nt.get_vip_status(m.group(1))
        on_step({"agent": "query", "tool": "get_vip_status",
                 "args": {"name": m.group(1)}, "result": res, "ok": True})
        up = sum(1 for x in res["members"] if x["status"] == "up")
        return (f"VIP `{res['name']}` ({res['destination']}) is **{res['availability']}** "
                f"with {up}/{len(res['members'])} pool members up.")

    m = re.search(r"([a-z0-9_]+_pool)", text)
    if m and "get_pool_health" in tool_names:
        res = nt.get_pool_health(m.group(1))
        on_step({"agent": "query", "tool": "get_pool_health",
                 "args": {"pool": m.group(1)}, "result": res, "ok": True})
        return (f"Pool `{m.group(1)}`: {res['members_up']}/{res['members_total']} members up.")

    vips = nt.list_virtual_servers()
    on_step({"agent": "query", "tool": "list_virtual_servers", "args": {},
             "result": vips, "ok": True})
    return ("I can check connectivity (src/dst/port), VIP status, or pool health. "
            f"Known VIPs: {', '.join(v['name'] for v in vips)}.")
