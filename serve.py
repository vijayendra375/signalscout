#!/usr/bin/env python3
"""SignalScout live lookup server launcher.

Starts a local HTTP server on 127.0.0.1:8765 that serves the dashboard UI
with an embedded live company lookup form.

Usage:
    python serve.py [--port 8765]

The server binds to 127.0.0.1 only — it is not exposed to the network.
No API keys or paid services are required. Deterministic mode is the default.
"""

from __future__ import annotations

import argparse
import signal
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from app.ui.server import LookupServer


def main() -> None:
    parser = argparse.ArgumentParser(
        description="SignalScout live company lookup server"
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host to bind to (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Port to listen on (default: 8765)",
    )
    args = parser.parse_args()

    server = LookupServer(host=args.host, port=args.port)

    def shutdown(signum, frame):  # noqa: ARG001
        print("\n[!] Shutting down SignalScout lookup server...")
        server.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        server.start()
    except KeyboardInterrupt:
        server.stop()
        sys.exit(0)


if __name__ == "__main__":
    main()
