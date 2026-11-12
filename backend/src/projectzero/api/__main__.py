"""Run the API locally: ``python -m projectzero.api`` (reads ``.env``; ``PZ_SCHEMA`` / ``PZ_HOST`` / ``PZ_PORT``).

Binds to 127.0.0.1 by default (decision 0003: single operator, backend-only access). The database URL is never printed.

``PZ_EVENTS_FETCHER_FIXTURE=<file.json>`` (``{url: {text} | {error, message}}``) replaces the network of the event
source scan with recorded responses, for previews and browser tests. It is refused for the live ``pz`` schema.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import uvicorn

from projectzero.api.app import create_app
from projectzero.core.config import Settings, load_dotenv


def main() -> None:
    load_dotenv()
    settings = Settings.from_env()
    app = create_app(settings)
    fixture = os.environ.get("PZ_EVENTS_FETCHER_FIXTURE")
    if fixture:
        if settings.schema == "pz":
            raise SystemExit("PZ_EVENTS_FETCHER_FIXTURE is for scratch schemas only, never the live pz schema")
        from projectzero.ops.parity_events_scan import RecordedFetcher

        app.state.events_fetcher = RecordedFetcher(json.loads(Path(fixture).read_text(encoding="utf-8")))
        print("event source scan: recorded responses (no network)")
    print(f"Project Zero API on http://{settings.host}:{settings.port} (schema {settings.schema})")
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="warning")


if __name__ == "__main__":
    main()
