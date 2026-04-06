from __future__ import annotations

import argparse
import json
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from .brain import resolve_brain
from .engine import CEOEngine
from .store import MemoryStore


ASSETS_DIR = Path(__file__).resolve().parent / "dashboard_assets"
MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
}


class DashboardApp:
    def __init__(self, db_path: str, brain_mode: str, model: Optional[str] = None) -> None:
        self.store = MemoryStore(db_path=db_path)
        self.engine = CEOEngine(
            store=self.store,
            brain=resolve_brain(mode=brain_mode, model=model),
        )

    def build_state(self) -> Dict[str, Any]:
        objective = self.store.load_objective()
        agent_rows = self.store.list_agent_queue_summaries(limit=60)
        agent_map = {item["agent_id"]: item for item in agent_rows}

        messages = [
            self._serialize_message(item, agent_map)
            for item in reversed(self.store.recent_messages(limit=120))
        ]
        work_items = [
            self._serialize_work_item(item, agent_map)
            for item in self.store.recent_work_items(limit=40)
        ]

        return {
            "objective": objective.to_dict() if objective else None,
            "system_overview": self.store.system_overview(),
            "agents": agent_rows,
            "runnable_agents": [
                agent.to_dict() for agent in self.store.list_runnable_agents(limit=20)
            ],
            "messages": messages,
            "work_items": work_items,
            "decisions": self.store.recent_decisions(limit=12),
            "cycles": self.store.recent_cycles(limit=8),
            "memories": self.store.recent_memories(limit=20),
        }

    def seed_demo_swarm(self) -> Dict[str, Any]:
        self.engine.seed_demo_swarm()
        return self.build_state()

    def run_cycle(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        trigger = str(payload.get("input", "")).strip()
        max_agents = int(payload.get("max_agents", 25) or 25)
        result = self.engine.run_cycle(trigger=trigger, max_agent_executions=max_agents)
        return {"result": result.to_dict(), "state": self.build_state()}

    def process_queue(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        trigger = str(payload.get("trigger", "")).strip()
        max_agents = int(payload.get("max_agents", 25) or 25)
        reports = self.engine.process_agent_queue(trigger=trigger, max_agents=max_agents)
        return {"processed_agents": reports, "state": self.build_state()}

    def send_message(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        message_id = self.engine.send_message(
            recipient_agent_id=str(payload.get("recipient_agent_id", "")).strip(),
            subject=str(payload.get("subject", "")).strip(),
            body=str(payload.get("body", "")).strip(),
            sender_type=str(payload.get("sender_type", "human")).strip() or "human",
            sender_id=str(payload.get("sender_id", "human")).strip() or "human",
            thread_id=str(payload.get("thread_id", "")).strip(),
        )
        return {"message_id": message_id, "state": self.build_state()}

    def queue_work(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        work_item_id = self.engine.queue_work_item(
            owner_agent_id=str(payload.get("owner_agent_id", "")).strip(),
            title=str(payload.get("title", "")).strip(),
            description=str(payload.get("description", "")).strip(),
            priority=str(payload.get("priority", "high")).strip() or "high",
            requested_by_type=str(payload.get("requested_by_type", "human")).strip()
            or "human",
            requested_by_id=str(payload.get("requested_by_id", "human")).strip()
            or "human",
        )
        return {"work_item_id": work_item_id, "state": self.build_state()}

    def _serialize_message(
        self, item: Dict[str, Any], agent_map: Dict[str, Dict[str, Any]]
    ) -> Dict[str, Any]:
        payload = dict(item)
        payload["sender_label"] = self._actor_label(
            actor_type=item["sender_type"],
            actor_id=item["sender_id"],
            agent_map=agent_map,
        )
        payload["recipient_label"] = self._actor_label(
            actor_type="agent",
            actor_id=item["recipient_agent_id"],
            agent_map=agent_map,
        )
        return payload

    def _serialize_work_item(
        self, item: Dict[str, Any], agent_map: Dict[str, Dict[str, Any]]
    ) -> Dict[str, Any]:
        payload = dict(item)
        payload["owner_label"] = self._actor_label(
            actor_type="agent",
            actor_id=item["owner_agent_id"],
            agent_map=agent_map,
        )
        payload["requester_label"] = self._actor_label(
            actor_type=item["requested_by_type"],
            actor_id=item["requested_by_id"],
            agent_map=agent_map,
        )
        return payload

    def _actor_label(
        self, actor_type: str, actor_id: str, agent_map: Dict[str, Dict[str, Any]]
    ) -> str:
        if actor_type == "agent":
            agent = agent_map.get(actor_id)
            if agent is None:
                stored_agent = self.store.get_agent(actor_id)
                agent = stored_agent.to_dict() if stored_agent else None
            return agent["name"] if agent else actor_id
        if actor_type == "ceo":
            return "AI CEO"
        if actor_type == "human":
            return f"Human / {actor_id}"
        return f"{actor_type} / {actor_id}"


class DashboardHandler(BaseHTTPRequestHandler):
    app: DashboardApp

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/state":
            self._send_json(self.app.build_state())
            return

        if parsed.path == "/" or parsed.path == "/index.html":
            self._send_asset("index.html")
            return

        asset_name = parsed.path.lstrip("/")
        if asset_name in {"styles.css", "app.js"}:
            self._send_asset(asset_name)
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            payload = self._read_json()
            if parsed.path == "/api/demo/seed":
                self._send_json(self.app.seed_demo_swarm())
                return
            if parsed.path == "/api/run-cycle":
                self._send_json(self.app.run_cycle(payload))
                return
            if parsed.path == "/api/process-queue":
                self._send_json(self.app.process_queue(payload))
                return
            if parsed.path == "/api/message":
                self._send_json(self.app.send_message(payload))
                return
            if parsed.path == "/api/queue-work":
                self._send_json(self.app.queue_work(payload))
                return
        except Exception as exc:  # pragma: no cover - exercised via smoke test
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return

    def _send_asset(self, asset_name: str) -> None:
        path = ASSETS_DIR / asset_name
        if not path.exists():
            self.send_error(HTTPStatus.NOT_FOUND, "Asset not found")
            return
        body = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header(
            "Content-Type", MIME_TYPES.get(path.suffix, "application/octet-stream")
        )
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, payload: Dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", MIME_TYPES[".json"])
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        if not raw.strip():
            return {}
        return json.loads(raw)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ai-ceo-dashboard",
        description="Run a local dashboard for the AI CEO swarm.",
    )
    parser.add_argument(
        "--db", default="state/ai_ceo.sqlite3", help="Path to the SQLite database file."
    )
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind.")
    parser.add_argument("--port", type=int, default=8765, help="Port to bind.")
    parser.add_argument(
        "--brain",
        default="heuristic",
        choices=["auto", "openai", "heuristic"],
        help="Brain implementation used for dashboard actions.",
    )
    parser.add_argument("--model", default=None, help="Optional OpenAI model.")
    parser.add_argument(
        "--open",
        action="store_true",
        help="Open the dashboard in the default browser after startup.",
    )
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    app = DashboardApp(db_path=args.db, brain_mode=args.brain, model=args.model)
    handler = type("BoundDashboardHandler", (DashboardHandler,), {"app": app})
    server = ThreadingHTTPServer((args.host, args.port), handler)
    url = f"http://{args.host}:{args.port}"
    print(f"AI CEO dashboard running at {url}")
    if args.open:
        webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
