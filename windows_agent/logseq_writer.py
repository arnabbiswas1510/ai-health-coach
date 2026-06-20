#!/usr/bin/env python3
"""
windows_agent/logseq_writer.py
===============================
Tiny HTTP server that receives health properties from the AI Health Coach
container and writes them directly to today's Logseq journal .md file.

Run once on any Windows machine where Logseq is installed:

    python windows_agent/logseq_writer.py --graph "C:\\Users\\arnab\\logseq"

Or set env vars and run without arguments:

    set LOGSEQ_GRAPH=C:\\Users\\arnab\\logseq
    python windows_agent/logseq_writer.py

Setup (one-time per machine):
    # Allow inbound on port 12316
    New-NetFirewallRule -DisplayName "Health Coach Logseq Writer" ^
        -Direction Inbound -LocalPort 12316 -Protocol TCP -Action Allow
    # Forward from LAN to localhost (so server can reach it)
    netsh interface portproxy add v4tov4 ^
        listenport=12316 listenaddress=0.0.0.0 ^
        connectport=12316 connectaddress=127.0.0.1

The container sends a POST to http://<WINDOWS_IP>:12316/health with JSON:
    {
        "sleep/duration": 7.5,
        "sleep/bed-time": "23:30",
        "sleep/wake-up-time": "06:45",
        "sleep/quality": 78,
        "run/distance": 6.2,
        "run/avg-speed": 5.75,
        "run/avg-heart-rate": 152
    }

Properties are written/updated as page-level properties at the TOP of the
Logseq journal .md file for today, in the format:
    key:: value

If the file already contains those properties, they are updated in-place.
If the file does not exist it is created with just the properties.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from datetime import date
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

logging.basicConfig(
    format="%(asctime)s [logseq-writer] %(levelname)s %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("logseq_writer")

# ── Configuration ─────────────────────────────────────────────────────────────

DEFAULT_PORT = int(os.environ.get("LOGSEQ_WRITER_PORT", "12316"))
GRAPH_DIR    = Path(os.environ.get("LOGSEQ_GRAPH", ""))


# ── Journal file helpers ───────────────────────────────────────────────────────

def journal_path(graph_dir: Path, for_date: date | None = None) -> Path:
    """Return the .md path for today's journal page (format: YYYY_MM_DD.md)."""
    d = for_date or date.today()
    return graph_dir / "journals" / f"{d.strftime('%Y_%m_%d')}.md"


def _is_property_line(line: str) -> bool:
    """Return True if line looks like a Logseq property (key:: value)."""
    return bool(re.match(r"^[a-zA-Z0-9_/\-].*::.*", line))


def write_properties(graph_dir: Path, props: dict) -> None:
    """Write/update Logseq page-level properties in today's journal file.

    Strategy:
    - If the file doesn't exist: create it with just the property lines.
    - If the file exists:
        - Lines that match an existing property key are replaced.
        - New property keys are prepended before the rest of the content.
    """
    journal = journal_path(graph_dir)
    journal.parent.mkdir(parents=True, exist_ok=True)

    # Format: "key:: value" — one per line
    new_prop_lines: dict[str, str] = {
        k: f"{k}:: {v}" for k, v in props.items() if v is not None
    }

    if not journal.exists():
        content = "\n".join(new_prop_lines.values()) + "\n"
        journal.write_text(content, encoding="utf-8")
        logger.info("Created journal %s with %d properties", journal.name, len(new_prop_lines))
        return

    existing = journal.read_text(encoding="utf-8").splitlines(keepends=True)

    # Separate existing property block (top of file) from body
    prop_block: list[str] = []
    body: list[str] = []
    in_props = True
    for line in existing:
        stripped = line.rstrip("\n\r")
        if in_props and (not stripped or _is_property_line(stripped)):
            prop_block.append(line)
        else:
            in_props = False
            body.append(line)

    # Build updated property map from existing file
    existing_props: dict[str, str] = {}
    for line in prop_block:
        stripped = line.rstrip("\n\r")
        if _is_property_line(stripped):
            key = stripped.split("::")[0].strip()
            existing_props[key] = stripped

    # Merge: new values overwrite, new keys added
    merged = {**existing_props, **{k: v for k, v in new_prop_lines.items()}}

    # Rebuild: sorted so health props appear consistently at top
    prop_output = [f"{v}\n" for v in merged.values()]

    # Write back
    result = prop_output + ([""] if body and prop_output else []) + body
    journal.write_text("".join(result), encoding="utf-8")
    logger.info(
        "Updated journal %s — wrote %d props (%s)",
        journal.name,
        len(new_prop_lines),
        ", ".join(new_prop_lines.keys()),
    )


# ── HTTP handler ───────────────────────────────────────────────────────────────

class HealthHandler(BaseHTTPRequestHandler):
    graph_dir: Path  # set by factory below

    def log_message(self, fmt, *args):  # suppress default access log
        pass

    def do_GET(self):
        if self.path == "/health":
            self._respond(200, {"status": "ok", "graph": str(self.graph_dir)})
        else:
            self._respond(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/health":
            self._respond(404, {"error": "not found"})
            return

        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            props: dict = json.loads(body)
        except json.JSONDecodeError as e:
            logger.warning("Bad JSON: %s", e)
            self._respond(400, {"error": f"invalid JSON: {e}"})
            return

        try:
            write_properties(self.graph_dir, props)
            self._respond(200, {"status": "written", "properties": list(props.keys())})
        except Exception as e:
            logger.exception("Failed to write properties: %s", e)
            self._respond(500, {"error": str(e)})

    def _respond(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def make_handler(graph_dir: Path):
    class Handler(HealthHandler):
        pass
    Handler.graph_dir = graph_dir
    return Handler


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Logseq journal writer agent")
    parser.add_argument(
        "--graph", "-g",
        default=str(GRAPH_DIR),
        help="Path to Logseq graph directory (default: $LOGSEQ_GRAPH env var)",
    )
    parser.add_argument(
        "--port", "-p",
        type=int,
        default=DEFAULT_PORT,
        help=f"Port to listen on (default: {DEFAULT_PORT})",
    )
    args = parser.parse_args()

    graph = Path(args.graph).expanduser().resolve()
    if not graph.exists():
        logger.error("Graph directory does not exist: %s", graph)
        sys.exit(1)

    journals = graph / "journals"
    if not journals.exists():
        logger.warning("No journals/ folder found in %s — will create on first write", graph)

    logger.info("Logseq graph: %s", graph)
    logger.info("Listening on 0.0.0.0:%d", args.port)
    logger.info("POST http://localhost:%d/health  with JSON health props", args.port)
    logger.info("GET  http://localhost:%d/health  to check status", args.port)

    server = HTTPServer(("0.0.0.0", args.port), make_handler(graph))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Stopped.")


if __name__ == "__main__":
    main()
