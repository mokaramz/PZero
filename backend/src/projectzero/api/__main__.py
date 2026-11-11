"""Run the API locally: ``python -m projectzero.api`` (reads ``.env``; ``PZ_SCHEMA`` / ``PZ_HOST`` / ``PZ_PORT``).

Binds to 127.0.0.1 by default (decision 0003: single operator, backend-only access). The database URL is never printed.
"""

from __future__ import annotations

import uvicorn

from projectzero.api.app import create_app
from projectzero.core.config import Settings, load_dotenv


def main() -> None:
    load_dotenv()
    settings = Settings.from_env()
    print(f"Project Zero API on http://{settings.host}:{settings.port} (schema {settings.schema})")
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, log_level="warning")


if __name__ == "__main__":
    main()
