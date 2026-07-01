"""Start the app:  python run.py  ->  http://127.0.0.1:8000"""
import uvicorn
from backend import config

if __name__ == "__main__":
    print(f"NetOps Copilot -> http://{config.HOST}:{config.PORT}")
    print(f"LLM: {'mock (no OPENAI_API_KEY)' if config.USE_MOCK_LLM else config.OPENAI_MODEL}")
    uvicorn.run("backend.app:app", host=config.HOST, port=config.PORT, reload=False)
