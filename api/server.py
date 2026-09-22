"""Nive Protocol REST Read API & Indexer Service.

Exposes JSON endpoints over HTTP for querying agents, tasks, bids, escrow,
and settlements from deployed Nive contracts without requiring raw RPC knowledge.
Zero third-party dependencies — built on Python's http.server.
"""
from __future__ import annotations

import json
import os
import re
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = REPO_ROOT / "web"
sys.path.insert(0, str(REPO_ROOT))

from api.streamer import global_streamer
from sdk.python.chain import (
    ChainClient,
    capability_word,
    id_from_seed,
)

MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}


class NiveApiHandler(BaseHTTPRequestHandler):
    client: ChainClient | None = None

    def _send_json(self, status: int, data: dict[str, Any]) -> None:
        payload = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(payload)

    def _send_file(self, file_path: Path, content_type: str) -> None:
        try:
            with open(file_path, "rb") as f:
                content = f.read()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(content)
        except OSError:
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "file not found"})

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        query = parse_qs(parsed.query)

        if path == "/health":
            self._handle_health()
            return

        # Serve landing page and explorer dashboard
        if path in ("", "/index.html"):
            index_path = WEB_DIR / "index.html"
            if index_path.exists():
                self._send_file(index_path, "text/html; charset=utf-8")
                return

        if path in ("/explorer", "/app", "/explorer.html"):
            explorer_path = WEB_DIR / "explorer.html"
            if explorer_path.exists():
                self._send_file(explorer_path, "text/html; charset=utf-8")
                return

        static_file = (WEB_DIR / path.lstrip("/")).resolve()
        if static_file.is_file() and str(static_file).startswith(str(WEB_DIR)):
            ext = static_file.suffix.lower()
            content_type = MIME_TYPES.get(ext, "application/octet-stream")
            self._send_file(static_file, content_type)
            return

        # ── Real-time event streaming routes ───────────────────────
        if path == "/api/v1/events/recent":
            self._send_json(HTTPStatus.OK, {"events": global_streamer.get_recent()})
            return

        if path == "/api/v1/events/stream":
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(b": connected to nive event stream (chain 4663)\n\n")
            return

        client = self.client
        if client is None:
            self._send_json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "client not initialized"})
            return

        try:
            # ── Agent routes ─────────────────────────────────────────
            if path == "/api/v1/agents/count":
                count = client.agent_count()
                self._send_json(HTTPStatus.OK, {"count": count})
                return

            if path == "/api/v1/agents/search":
                caps = query.get("capability", [""])[0]
                if not caps:
                    self._send_json(HTTPStatus.BAD_REQUEST, {"error": "missing 'capability' query param"})
                    return
                cap_word = capability_word(caps)
                agents = client.search_by_capability(cap_word)
                self._send_json(HTTPStatus.OK, {"capability": caps, "capability_word": cap_word, "agents": agents})
                return

            m_agent = re.match(r"^/api/v1/agents/([^/]+)$", path)
            if m_agent:
                agent_id = m_agent.group(1)
                if not agent_id.startswith("0x"):
                    agent_id = id_from_seed(agent_id)
                agent = client.get_agent(agent_id)
                self._send_json(HTTPStatus.OK, {"agent": agent})
                return

            # ── Task routes ──────────────────────────────────────────
            if path == "/api/v1/tasks/count":
                count = client.task_count()
                self._send_json(HTTPStatus.OK, {"count": count})
                return

            m_task_bids = re.match(r"^/api/v1/tasks/([^/]+)/bids$", path)
            if m_task_bids:
                task_id = m_task_bids.group(1)
                if not task_id.startswith("0x"):
                    task_id = id_from_seed(task_id)
                bids = client.get_bids(task_id)
                self._send_json(HTTPStatus.OK, {"task_id": task_id, "bids": bids})
                return

            m_task_escrow = re.match(r"^/api/v1/tasks/([^/]+)/escrow$", path)
            if m_task_escrow:
                task_id = m_task_escrow.group(1)
                if not task_id.startswith("0x"):
                    task_id = id_from_seed(task_id)
                escrow_val = client.escrow(task_id)
                self._send_json(HTTPStatus.OK, {"task_id": task_id, "escrow_wei": str(escrow_val)})
                return

            m_task = re.match(r"^/api/v1/tasks/([^/]+)$", path)
            if m_task:
                task_id = m_task.group(1)
                if not task_id.startswith("0x"):
                    task_id = id_from_seed(task_id)
                task = client.get_task(task_id)
                res_hash = client.result_hash(task_id)
                self._send_json(HTTPStatus.OK, {"task": task, "result_hash": res_hash})
                return

            # ── Settlement routes ────────────────────────────────────
            m_settlement = re.match(r"^/api/v1/settlements/([^/]+)$", path)
            if m_settlement:
                task_id = m_settlement.group(1)
                if not task_id.startswith("0x"):
                    task_id = id_from_seed(task_id)
                settlement = client.settlement(task_id)
                verified = client.has_proof_verified(task_id)
                self._send_json(HTTPStatus.OK, {"settlement": settlement, "proof_verified": verified})
                return

            # ── Guardian routes ──────────────────────────────────────
            if path == "/api/v1/guardians/count":
                count = client.guardian_count()
                self._send_json(HTTPStatus.OK, {"count": count})
                return

            self._send_json(HTTPStatus.NOT_FOUND, {"error": f"route not found: {path}"})

        except Exception as exc:  # noqa: BLE001
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path == "/api/v1/events/publish":
            try:
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length)
                body = json.loads(raw.decode("utf-8"))
                evt_type = body.get("event_type", "CustomEvent")
                evt_data = body.get("data", {})
                chain_id = int(body.get("chain_id", 4663))
                evt = global_streamer.publish(evt_type, evt_data, chain_id)
                self._send_json(HTTPStatus.CREATED, {"status": "published", "event": evt.to_dict()})
            except Exception as exc:  # noqa: BLE001
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return

        self._send_json(HTTPStatus.NOT_FOUND, {"error": f"route not found: {path}"})

    def _handle_health(self) -> None:
        chain_id = None
        if self.client:
            try:
                chain_id = self.client.client.chain_id()
            except Exception:  # noqa: BLE001
                chain_id = None
        self._send_json(HTTPStatus.OK, {
            "status": "healthy",
            "service": "nive-rest-api",
            "version": "0.1.4",
            "chain_id": chain_id,
        })

    def log_message(self, format: str, *args: Any) -> None:
        # Suppress noisy stdout logs during automated testing
        if os.environ.get("NIVE_API_QUIET"):
            return
        super().log_message(format, *args)


def create_server(
    host: str = "127.0.0.1",
    port: int = 8080,
    client: ChainClient | None = None,
) -> ThreadingHTTPServer:
    handler = NiveApiHandler
    handler.client = client
    return ThreadingHTTPServer((host, port), handler)


def main() -> None:
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    port = int(os.environ.get("PORT", "8080"))
    host = os.environ.get("HOST", "0.0.0.0")
    client = ChainClient.from_env() if os.environ.get("NIVE_RPC_URL") else None
    server = create_server(host=host, port=port, client=client)
    print(f"🚀 Nive REST API listening on http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server...")
        server.server_close()


if __name__ == "__main__":
    main()
