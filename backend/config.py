"""Central configuration. Reads .env; degrades gracefully with no API key."""
import os
from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()
OPENAI_EMBED_MODEL = os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small").strip()

HOST = os.getenv("HOST", "127.0.0.1").strip()
PORT = int(os.getenv("PORT", "8000"))

# Base URL the agent tools use to reach the (local) mock network REST APIs.
# Everything is served from the same FastAPI process, so this points at ourselves.
INTERNAL_API_BASE = f"http://{HOST}:{PORT}"

# When True, agents run on a deterministic rules-based reasoner instead of the LLM.
# Auto-enabled when no OpenAI key is present so the demo always works.
USE_MOCK_LLM = not bool(OPENAI_API_KEY)
