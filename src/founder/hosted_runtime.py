"""Hosted container runtime entry points."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence


def health() -> int:
    """Return a process health status for container health checks."""

    print(json.dumps({"status": "ok"}, sort_keys=True))
    return 0


def run_api_placeholder() -> int:
    """Start the API placeholder until the PR96 FastAPI service owns this entry point."""

    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/health":
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"status":"ok"}')
                return
            self.send_response(404)
            self.send_header("content-type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error":"api not implemented"}')

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("0.0.0.0", 8000), Handler)
    server.serve_forever()
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the hosted runtime parser."""

    parser = argparse.ArgumentParser(description="Founder hosted container runtime.")
    parser.add_argument("command", choices=("api", "health"))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run a hosted container entry point."""

    args = build_parser().parse_args(argv)
    if args.command == "health":
        return health()
    return run_api_placeholder()


if __name__ == "__main__":
    raise SystemExit(main())
