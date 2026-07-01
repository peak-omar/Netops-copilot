# NetOps Copilot

A multi-agent assistant for network operations. It does two things:

1. **Self-service checks** for non-technical teams: ask in plain English whether a
   source can reach a destination, or whether a VIP/pool is healthy, and get a
   clear answer with the firewall rule or member status it relied on.
2. **P1 root-cause analysis**: given an outage, a chain of agents pulls from the
   firewall, load balancer, Kubernetes, and telemetry, correlates the signals to
   separate cause from symptom, retrieves the relevant runbook, and drafts an
   incident summary.

Writes (ServiceNow tickets) are never automatic. The agent proposes a ticket and a
person approves it in the UI before anything is filed.

Built with Python, FastAPI, LangGraph, OpenAI tool-calling, a small RAG store over
runbooks, and MCP servers that expose the same tools to any MCP client.

## Lab environment

There is no physical network here. Each device (Palo Alto Panorama, F5, Azure AKS,
Splunk, ServiceNow) is a small FastAPI service under `backend/mock_apis/` that
returns responses shaped like the real APIs. The agent tools call these over HTTP,
so pointing them at real device endpoints is a change of base URL, not a rewrite.

## The demo scenario

Start state is healthy. Injecting the P1 outage applies a single change: a Panorama
rule that denies `app-tier -> db-tier` on TCP 5432. That one change cascades:
checkout pods CrashLoop because they can't reach the database, F5 pool members fail
their health checks, the VIP degrades, and 5xx errors spike. The correlation agent
identifies the firewall change as the cause and flags the rest as downstream
symptoms.

## Layout

| Path | What |
|------|------|
| `frontend/` | Chat UI, live agent trace, root-cause and ticket cards, graph viewer |
| `backend/agents/graph.py` | LangGraph state machine (router, RCA pipeline, ticket proposal) |
| `backend/agents/reasoner.py` | OpenAI tool-calling loop with an offline fallback |
| `backend/agents/rag.py` | In-memory vector store over `data/runbooks/` |
| `backend/tools/network_tools.py` | REST clients for each device |
| `backend/mock_apis/` | The lab device APIs and scenario state |
| `mcp_servers/` | The same tools exposed over MCP |

The in-app agents and the MCP servers call the same tool functions, so device
access lives in one place.

## Running it

```
python -m venv .venv
.venv\Scripts\activate            # Windows  (source .venv/bin/activate elsewhere)
pip install -r requirements.txt

copy .env.example .env            # then set OPENAI_API_KEY
python run.py                     # http://127.0.0.1:8000
```

Open the URL, click one of the example chips, or hit **Inject P1 outage** and then
the **P1 root-cause** chip.

It also runs without an API key: the reasoner falls back to a deterministic path so
the flows still work, just without live model reasoning or embedding-based
retrieval.

### MCP servers

Each server runs standalone over stdio and can be wired into any MCP client:

```
python -m mcp_servers.panorama_mcp
python -m mcp_servers.f5_mcp
python -m mcp_servers.observability_mcp
```

## Author

Omar - supax82@gmail.com
