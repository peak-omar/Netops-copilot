"""FastAPI app: serves the web UI, the agent endpoints
(/api/chat, /api/approve-ticket, /api/graph), and the lab device APIs
(/api/panorama, /api/f5, /api/aks, /api/splunk, /api/servicenow, /api/sim).
"""
from __future__ import annotations
import asyncio
import os

from fastapi import FastAPI, Body
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import config
from .mock_apis.routes import router as mock_router
from .agents.graph import run_graph, GRAPH
from .tools import network_tools as nt

_FRONTEND = os.path.join(os.path.dirname(__file__), "..", "frontend")

app = FastAPI(title="NetOps Copilot",
              description="Network automation and AI assistant",
              version="1.0.0")

app.include_router(mock_router)


@app.get("/api/health")
def health():
    return {"status": "ok", "llm": "openai:" + config.OPENAI_MODEL
            if not config.USE_MOCK_LLM else "mock (no key)"}


@app.post("/api/chat")
async def chat(payload: dict = Body(...)):
    query = (payload.get("message") or "").strip()
    if not query:
        return JSONResponse({"error": "empty message"}, status_code=400)
    # Run the (synchronous, REST-calling) graph off the event loop so its
    # self-directed httpx calls to our own mock APIs never deadlock uvicorn.
    result = await asyncio.to_thread(run_graph, query)
    return result


@app.post("/api/approve-ticket")
async def approve_ticket(payload: dict = Body(...)):
    """Create the ServiceNow incident. Only reached after a human approves."""
    ticket = payload.get("ticket") or {}
    created = await asyncio.to_thread(
        nt.create_servicenow_ticket,
        short_description=ticket.get("short_description", "Network automation ticket"),
        description=ticket.get("description", ""),
        priority=ticket.get("priority", "3 - Moderate"),
        cmdb_ci=ticket.get("cmdb_ci", ""),
        assignment_group=ticket.get("assignment_group", "Network Engineering"),
    )
    return {"created": created}


@app.get("/api/graph")
def graph_diagram():
    """Return the compiled LangGraph as Mermaid text (for the UI diagram)."""
    try:
        mermaid = GRAPH.get_graph().draw_mermaid()
    except Exception as e:
        mermaid = f"%% could not render graph: {e}"
    return {"mermaid": mermaid}


# ------------------------------ static UI ------------------------------
app.mount("/static", StaticFiles(directory=_FRONTEND), name="static")


@app.get("/")
def index():
    return FileResponse(os.path.join(_FRONTEND, "index.html"))
