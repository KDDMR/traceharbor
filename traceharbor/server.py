"""TraceHarbor process entry point."""

from __future__ import annotations

import json
import logging
import signal
from threading import Thread

from .config import Settings
from .http_api import create_http_server
from .service import TelemetryService
from .storage import EventStore


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(
            {
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
            },
            separators=(",", ":"),
        )


def configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)


def main() -> None:
    configure_logging()
    settings = Settings.from_env()
    store = EventStore(settings.database_path)
    service = TelemetryService(store, settings.api_key, settings.rate_limit_per_minute)
    server = create_http_server(service, settings)

    def stop_server(_signum: int, _frame: object) -> None:
        Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGINT, stop_server)
    signal.signal(signal.SIGTERM, stop_server)
    logging.getLogger("traceharbor").info(
        "server_started host=%s port=%s database=%s",
        settings.host,
        settings.port,
        settings.database_path,
    )
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
