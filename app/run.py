"""Entry point: `python run.py` serves the API on 0.0.0.0:$PORT (reachable from outside a container)."""
from __future__ import annotations

import os

import uvicorn

from app.config import load_dotenv


def main() -> None:
    load_dotenv()
    uvicorn.run("app.main:create_app", factory=True, host="0.0.0.0", port=int(os.getenv("PORT", "8000")),
                log_level=os.getenv("LOG_LEVEL", "info").lower())


if __name__ == "__main__":
    main()
