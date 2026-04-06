from __future__ import annotations

import argparse
import json
import sys
from typing import Any, List, Optional

from .brain import resolve_brain
from .engine import CEOEngine
from .store import MemoryStore
from .utils import load_env_file


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ai-ceo",
        description="Persistent AI CEO orchestrator with long-term memory and scalable agent registry.",
    )
    parser.add_argument(
        "--db",
        default="state/ai_ceo.sqlite3",
        help="Path to the SQLite database file.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Initialize the CEO objective.")
    init_parser.add_argument("--company", required=True, help="Company name.")
    init_parser.add_argument("--objective", required=True, help="Ultimate objective.")

    cycle_parser = subparsers.add_parser("cycle", help="Run one CEO planning cycle.")
    cycle_parser.add_argument("--input", required=True, help="Trigger or context for this cycle.")
    cycle_parser.add_argument(
        "--brain",
        default="auto",
        choices=["auto", "openai", "anthropic", "heuristic"],
        help="Which brain implementation to use.",
    )
    cycle_parser.add_argument(
        "--model",
        default=None,
        help="Model name for OpenAI-backed cycles. Falls back to AI_CEO_MODEL if omitted.",
    )
    cycle_parser.add_argument(
        "--max-agents",
        type=int,
        default=25,
        help="How many runnable agents to process after the CEO cycle.",
    )

    process_parser = subparsers.add_parser(
        "process-queue", help="Process queued agents without running a new CEO planning cycle."
    )
    process_parser.add_argument("--trigger", default="", help="Optional trigger text.")
    process_parser.add_argument(
        "--brain",
        default="auto",
        choices=["auto", "openai", "anthropic", "heuristic"],
        help="Which brain implementation to use.",
    )
    process_parser.add_argument("--model", default=None, help="Model name for OpenAI mode.")
    process_parser.add_argument(
        "--max-agents",
        type=int,
        default=25,
        help="How many runnable agents to process.",
    )

    status_parser = subparsers.add_parser(
        "status", help="Show objective, system overview, and agent queue summary."
    )
    status_parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="How many recent or runnable agents to show.",
    )

    agents_parser = subparsers.add_parser("agents", help="List agents.")
    agents_parser.add_argument("--status", default=None, help="Optional agent status filter.")
    agents_parser.add_argument("--limit", type=int, default=100, help="How many agents to show.")
    agents_parser.add_argument("--offset", type=int, default=0, help="Offset for pagination.")

    create_agent_parser = subparsers.add_parser(
        "create-agent", help="Persist a human-created or externally defined agent."
    )
    create_agent_parser.add_argument("--agent-id", required=True, help="Stable agent ID.")
    create_agent_parser.add_argument("--name", required=True, help="Human-readable name.")
    create_agent_parser.add_argument("--role", required=True, help="Short role label.")
    create_agent_parser.add_argument("--mandate", required=True, help="Why this agent exists.")
    create_agent_parser.add_argument(
        "--system-prompt", required=True, help="Core instructions for the agent."
    )
    create_agent_parser.add_argument(
        "--creator-id",
        default="human",
        help="ID of the human or external creator.",
    )
    create_agent_parser.add_argument(
        "--creator-type",
        default="human",
        choices=["human", "ceo", "agent"],
        help="What kind of actor is creating this agent.",
    )
    create_agent_parser.add_argument("--current-focus", default="", help="Current focus.")
    create_agent_parser.add_argument("--success-metric", default="", help="Success metric.")
    create_agent_parser.add_argument("--parent-agent-id", default="", help="Optional parent.")
    create_agent_parser.add_argument("--model", default="", help="Optional preferred model.")

    work_parser = subparsers.add_parser("queue-work", help="Queue a work item for an agent.")
    work_parser.add_argument("--to", required=True, help="Recipient agent ID.")
    work_parser.add_argument("--title", required=True, help="Work title.")
    work_parser.add_argument("--description", required=True, help="Work description.")
    work_parser.add_argument(
        "--priority",
        default="high",
        choices=["high", "medium", "low"],
        help="Priority.",
    )
    work_parser.add_argument(
        "--from-type",
        default="human",
        choices=["human", "ceo", "agent"],
        help="Requester actor type.",
    )
    work_parser.add_argument("--from-id", default="human", help="Requester actor ID.")

    message_parser = subparsers.add_parser("message-agent", help="Send a message to an agent.")
    message_parser.add_argument("--to", required=True, help="Recipient agent ID.")
    message_parser.add_argument("--subject", required=True, help="Message subject.")
    message_parser.add_argument("--body", required=True, help="Message body.")
    message_parser.add_argument(
        "--from-type",
        default="human",
        choices=["human", "ceo", "agent"],
        help="Sender actor type.",
    )
    message_parser.add_argument("--from-id", default="human", help="Sender actor ID.")
    message_parser.add_argument("--thread-id", default="", help="Optional thread ID.")

    messages_parser = subparsers.add_parser("messages", help="List queued or processed messages.")
    messages_parser.add_argument("--agent", default=None, help="Optional recipient agent ID.")
    messages_parser.add_argument("--status", default=None, help="Optional message status filter.")
    messages_parser.add_argument("--limit", type=int, default=100, help="How many to show.")
    messages_parser.add_argument("--offset", type=int, default=0, help="Offset for pagination.")

    decisions_parser = subparsers.add_parser("decisions", help="List recent decisions.")
    decisions_parser.add_argument("--limit", type=int, default=10, help="How many decisions to show.")

    memory_parser = subparsers.add_parser("memory", help="Search long-term memory.")
    memory_parser.add_argument("--query", required=True, help="Text to search for.")
    memory_parser.add_argument("--limit", type=int, default=10, help="How many memory items to show.")

    return parser


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, indent=2))


def main(argv: Optional[List[str]] = None) -> int:
    load_env_file()
    parser = build_parser()
    args = parser.parse_args(argv)

    store = MemoryStore(db_path=args.db)

    if args.command == "init":
        engine = CEOEngine(store=store, brain=resolve_brain("heuristic"))
        payload = engine.bootstrap(company_name=args.company, ultimate_objective=args.objective)
        _print_json({"status": "initialized", "objective": payload})
        return 0

    if args.command == "status":
        objective = store.load_objective()
        if objective is None:
            print("The CEO is not initialized yet. Run `ai-ceo init` first.", file=sys.stderr)
            return 1
        payload = {
            "objective": objective.to_dict(),
            "system_overview": store.system_overview(),
            "recent_active_agents": store.summarize_agents(limit=args.limit, status="active"),
            "runnable_agents": [agent.to_dict() for agent in store.list_runnable_agents(limit=args.limit)],
            "recent_decisions": store.recent_decisions(limit=5),
        }
        _print_json(payload)
        return 0

    if args.command == "agents":
        payload = [
            agent.to_dict()
            for agent in store.list_agents(
                status=args.status, limit=args.limit, offset=args.offset
            )
        ]
        _print_json(payload)
        return 0

    if args.command == "create-agent":
        engine = CEOEngine(store=store, brain=resolve_brain("heuristic"))
        agent = engine.create_agent(
            agent_id=args.agent_id,
            name=args.name,
            role=args.role,
            mandate=args.mandate,
            system_prompt=args.system_prompt,
            creator_type=args.creator_type,
            creator_id=args.creator_id,
            current_focus=args.current_focus,
            success_metric=args.success_metric,
            parent_agent_id=args.parent_agent_id,
            model=args.model,
        )
        _print_json({"status": "created", "agent": agent.to_dict()})
        return 0

    if args.command == "queue-work":
        engine = CEOEngine(store=store, brain=resolve_brain("heuristic"))
        work_item_id = engine.queue_work_item(
            owner_agent_id=args.to,
            title=args.title,
            description=args.description,
            priority=args.priority,
            requested_by_type=args.from_type,
            requested_by_id=args.from_id,
        )
        _print_json({"status": "queued", "work_item_id": work_item_id})
        return 0

    if args.command == "message-agent":
        engine = CEOEngine(store=store, brain=resolve_brain("heuristic"))
        message_id = engine.send_message(
            recipient_agent_id=args.to,
            subject=args.subject,
            body=args.body,
            sender_type=args.from_type,
            sender_id=args.from_id,
            thread_id=args.thread_id,
        )
        _print_json({"status": "queued", "message_id": message_id})
        return 0

    if args.command == "messages":
        _print_json(
            store.list_messages(
                recipient_agent_id=args.agent,
                status=args.status,
                limit=args.limit,
                offset=args.offset,
            )
        )
        return 0

    if args.command == "decisions":
        _print_json(store.recent_decisions(limit=args.limit))
        return 0

    if args.command == "memory":
        _print_json(store.search_memories(query=args.query, limit=args.limit))
        return 0

    if args.command in {"cycle", "process-queue"}:
        brain = resolve_brain(mode=args.brain, model=args.model)
        engine = CEOEngine(store=store, brain=brain)
        if args.command == "cycle":
            result = engine.run_cycle(
                trigger=args.input, max_agent_executions=args.max_agents
            )
            _print_json(result.to_dict())
            return 0

        reports = engine.process_agent_queue(
            trigger=args.trigger, max_agents=args.max_agents
        )
        _print_json({"processed_agents": reports, "system_overview": store.system_overview()})
        return 0

    parser.print_help()
    return 1
