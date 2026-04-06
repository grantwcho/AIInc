from __future__ import annotations

from typing import Any, Dict, List, Optional

from .brain import Brain
from .models import (
    AgentAction,
    AgentSpec,
    CycleResult,
    MemoryNote,
    MessagePlan,
    WorkItemPlan,
)
from .store import MemoryStore


class CEOEngine:
    def __init__(self, store: MemoryStore, brain: Brain) -> None:
        self.store = store
        self.brain = brain

    def bootstrap(self, company_name: str, ultimate_objective: str) -> Dict[str, Any]:
        objective = self.store.bootstrap_objective(
            company_name=company_name, ultimate_objective=ultimate_objective
        )
        return objective.to_dict()

    def create_agent(
        self,
        agent_id: str,
        name: str,
        role: str,
        mandate: str,
        system_prompt: str,
        creator_type: str,
        creator_id: str,
        current_focus: str = "",
        success_metric: str = "",
        parent_agent_id: str = "",
        model: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AgentSpec:
        parent = parent_agent_id or creator_id or creator_type
        agent = AgentSpec(
            agent_id=agent_id,
            name=name,
            role=role,
            mandate=mandate,
            system_prompt=system_prompt,
            current_focus=current_focus,
            success_metric=success_metric,
            parent_agent_id=parent,
            creator_type=creator_type,
            creator_id=creator_id,
            model=model,
            metadata=metadata or {},
        )
        saved = self.store.upsert_agent(agent)
        self.store.record_memory(
            source_agent_id=creator_id,
            note=MemoryNote(
                title=f"Agent created: {saved.name}",
                content=(
                    f"{creator_type}:{creator_id} created {saved.agent_id} with mandate: {saved.mandate}"
                ),
                category="org",
                importance=7,
                tags=["agent", "creation", saved.agent_id, creator_type],
            ),
        )
        return saved

    def queue_work_item(
        self,
        owner_agent_id: str,
        title: str,
        description: str,
        priority: str,
        requested_by_type: str,
        requested_by_id: str,
    ) -> str:
        plan = WorkItemPlan(
            owner_agent_id=owner_agent_id,
            title=title,
            description=description,
            priority=priority,
            requested_by_type=requested_by_type,
            requested_by_id=requested_by_id,
        )
        return self.store.create_work_item(plan)

    def send_message(
        self,
        recipient_agent_id: str,
        subject: str,
        body: str,
        sender_type: str,
        sender_id: str,
        thread_id: str = "",
    ) -> str:
        message = MessagePlan(
            recipient_agent_id=recipient_agent_id,
            subject=subject,
            body=body,
            sender_type=sender_type,
            sender_id=sender_id,
            thread_id=thread_id,
        )
        return self.store.enqueue_message(message)

    def seed_demo_swarm(self) -> Dict[str, Any]:
        objective = self.store.load_objective()
        if objective is None:
            objective = self.store.bootstrap_objective(
                company_name="AI Inc",
                ultimate_objective=(
                    "Build the most successful company in the world through compounding AI products, "
                    "talent, and distribution."
                ),
            )

        demo_agents = [
            {
                "agent_id": "founder_ops",
                "name": "Founder Ops",
                "role": "Executive operations",
                "mandate": "Convert strategy into crisp execution across the company.",
                "system_prompt": "Operate like a relentless chief of staff with startup urgency.",
                "creator_type": "human",
                "creator_id": "grant",
                "current_focus": "Turn strategic intent into a weekly operating rhythm.",
            },
            {
                "agent_id": "market_intelligence",
                "name": "Market Intelligence",
                "role": "Market sensing",
                "mandate": "Map urgent buyer pain, timing, and willingness to pay.",
                "system_prompt": "Act like an elite market analyst focused on painful high-frequency problems.",
                "creator_type": "ceo",
                "creator_id": "ceo",
                "current_focus": "Find the sharpest painful wedge and strongest signals.",
            },
            {
                "agent_id": "growth_architect",
                "name": "Growth Architect",
                "role": "Growth systems",
                "mandate": "Design compounding acquisition and retention loops.",
                "system_prompt": "Think in compounding growth loops, activation, and durable distribution moats.",
                "creator_type": "ceo",
                "creator_id": "ceo",
                "current_focus": "Design the first repeatable distribution experiments.",
            },
        ]

        created_agents: List[str] = []
        for spec in demo_agents:
            if self.store.get_agent(spec["agent_id"]) is None:
                self.create_agent(**spec)
                created_agents.append(spec["agent_id"])

        if not self.store.list_work_items(status="queued", limit=1):
            self.queue_work_item(
                owner_agent_id="founder_ops",
                title="Build the first execution map",
                description="Define the first bottlenecks, owners, and operating cadence.",
                priority="high",
                requested_by_type="human",
                requested_by_id="grant",
            )
            self.queue_work_item(
                owner_agent_id="market_intelligence",
                title="Map the narrowest painful wedge",
                description="Identify the buyer pain with the highest urgency and clearest willingness to pay.",
                priority="high",
                requested_by_type="ceo",
                requested_by_id="ceo",
            )
            self.queue_work_item(
                owner_agent_id="growth_architect",
                title="Sketch the first growth loop",
                description="Propose the first repeatable acquisition and activation loops for the wedge.",
                priority="medium",
                requested_by_type="ceo",
                requested_by_id="ceo",
            )

        if not self.store.list_messages(status="queued", limit=1):
            self.send_message(
                recipient_agent_id="founder_ops",
                subject="Company priority",
                body="Bias toward the narrowest painful wedge with obvious urgency and willingness to pay.",
                sender_type="human",
                sender_id="grant",
            )
            self.send_message(
                recipient_agent_id="market_intelligence",
                subject="Research constraint",
                body="Favor real customer urgency over broad market size narratives.",
                sender_type="ceo",
                sender_id="ceo",
            )

        return {
            "objective": objective.to_dict(),
            "created_agents": created_agents,
            "system_overview": self.store.system_overview(),
        }

    def run_cycle(self, trigger: str, max_agent_executions: int = 25) -> CycleResult:
        objective = self.store.load_objective()
        if objective is None:
            raise RuntimeError("The CEO is not initialized. Run `ai-ceo init` first.")

        context = self._build_ceo_context(trigger=trigger, objective=objective)
        brain_output = self.brain.run_ceo_cycle(context)
        cycle_id = self.store.record_cycle(
            trigger_text=trigger,
            reflection_summary=brain_output.reflection_summary,
            self_prompt=brain_output.self_prompt,
        )

        objective.strategy = brain_output.updated_strategy or objective.strategy
        if brain_output.updated_operating_principles:
            objective.operating_principles = brain_output.updated_operating_principles
        if brain_output.self_prompt:
            objective.last_self_prompt = brain_output.self_prompt
        self.store.save_objective(objective)

        for decision in brain_output.decisions:
            self.store.record_decision(cycle_id=cycle_id, agent_id="ceo", decision=decision)

        for note in brain_output.memory_notes:
            self.store.record_memory(source_agent_id="ceo", note=note)

        applied_actions = self._apply_agent_actions(
            brain_output.agent_actions, actor_type="ceo", actor_id="ceo"
        )
        queued_work_items = self._queue_work_items(
            brain_output.work_items, requested_by_type="ceo", requested_by_id="ceo"
        )
        queued_messages = self._queue_messages(
            brain_output.outbound_messages, sender_type="ceo", sender_id="ceo"
        )

        agent_reports = self.process_agent_queue(
            trigger=trigger,
            cycle_id=cycle_id,
            max_agents=max_agent_executions,
        )

        return CycleResult(
            cycle_id=cycle_id,
            objective=objective,
            reflection_summary=brain_output.reflection_summary,
            self_prompt=brain_output.self_prompt,
            applied_agent_actions=applied_actions,
            recorded_decisions=brain_output.decisions,
            queued_work_items=queued_work_items,
            queued_messages=queued_messages,
            agent_reports=agent_reports,
            memory_notes=brain_output.memory_notes,
        )

    def process_agent_queue(
        self,
        trigger: str,
        cycle_id: Optional[str] = None,
        max_agents: int = 25,
        max_work_items_per_agent: int = 25,
        max_messages_per_agent: int = 25,
    ) -> List[Dict[str, Any]]:
        objective = self.store.load_objective()
        if objective is None:
            raise RuntimeError("The CEO is not initialized. Run `ai-ceo init` first.")

        if cycle_id is None:
            cycle_id = self.store.record_cycle(
                trigger_text=trigger or "Queued agent processing",
                reflection_summary="Processed queued agents without a new CEO planning cycle.",
                self_prompt=objective.last_self_prompt,
            )

        reports: List[Dict[str, Any]] = []
        runnable_agents = self.store.list_runnable_agents(limit=max_agents)
        for agent in runnable_agents:
            claimed_work = self.store.claim_work_items(
                owner_agent_id=agent.agent_id, limit=max_work_items_per_agent
            )
            claimed_messages = self.store.claim_messages(
                recipient_agent_id=agent.agent_id, limit=max_messages_per_agent
            )
            if not claimed_work and not claimed_messages:
                continue

            context = {
                "trigger": trigger,
                "surface": agent.metadata.get("surface", ""),
                "objective": objective.to_dict(),
                "assigned_work_items": claimed_work,
                "inbox_messages": claimed_messages,
                "peer_agents": [
                    item
                    for item in self.store.summarize_agents(limit=20, status="active")
                    if item["agent_id"] != agent.agent_id
                ],
                "relevant_memories": self.store.search_memories(
                    agent.role or agent.agent_id, limit=5
                ),
                "recent_decisions": self.store.recent_decisions(limit=5),
                "system_overview": self.store.system_overview(),
            }
            report = self.brain.run_agent_cycle(agent=agent, context=context)

            work_status = "blocked" if report.status == "blocked" else "completed"
            self.store.close_work_items(
                [item["work_item_id"] for item in claimed_work],
                status=work_status,
                resolution=report.summary,
            )
            self.store.close_messages(
                [item["message_id"] for item in claimed_messages],
                status="processed" if report.status == "blocked" else "delivered",
            )

            for note in report.memory_notes:
                self.store.record_memory(source_agent_id=agent.agent_id, note=note)

            for deliverable in report.deliverables:
                self.store.record_memory(
                    source_agent_id=agent.agent_id,
                    note=MemoryNote(
                        title=f"{agent.name} deliverable",
                        content=deliverable,
                        category="note",
                        importance=5,
                        tags=[agent.agent_id, "deliverable"],
                    ),
                )

            for decision in report.decision_proposals:
                self.store.record_decision(
                    cycle_id=cycle_id, agent_id=agent.agent_id, decision=decision
                )

            applied_actions = self._apply_agent_actions(
                report.agent_actions, actor_type="agent", actor_id=agent.agent_id
            )
            queued_follow_up_work = self._queue_work_items(
                report.follow_up_work_items,
                requested_by_type="agent",
                requested_by_id=agent.agent_id,
            )
            queued_outbound_messages = self._queue_messages(
                report.outbound_messages,
                sender_type="agent",
                sender_id=agent.agent_id,
            )

            reports.append(
                {
                    "agent_id": agent.agent_id,
                    "agent_name": agent.name,
                    "summary": report.summary,
                    "direct_response": report.direct_response,
                    "deliverables": list(report.deliverables),
                    "needs": list(report.needs),
                    "status": report.status,
                    "processed_work_items": len(claimed_work),
                    "processed_messages": len(claimed_messages),
                    "applied_agent_actions": [action.to_dict() for action in applied_actions],
                    "queued_follow_up_work_items": [
                        item.to_dict() for item in queued_follow_up_work
                    ],
                    "queued_outbound_messages": [
                        item.to_dict() for item in queued_outbound_messages
                    ],
                }
            )
        return reports

    def _build_ceo_context(self, trigger: str, objective: Any) -> Dict[str, Any]:
        return {
            "trigger": trigger,
            "objective": objective.to_dict(),
            "agent_overview": self.store.system_overview(),
            "recent_active_agents": self.store.summarize_agents(limit=20, status="active"),
            "runnable_agents": [agent.to_dict() for agent in self.store.list_runnable_agents(limit=20)],
            "recent_decisions": self.store.recent_decisions(limit=10),
            "recent_cycles": self.store.recent_cycles(limit=5),
            "relevant_memories": self.store.search_memories(trigger or objective.strategy, limit=8),
        }

    def _apply_agent_actions(
        self, actions: List[AgentAction], actor_type: str, actor_id: str
    ) -> List[AgentAction]:
        applied: List[AgentAction] = []
        for action in actions:
            if not action.agent_id or action.action not in {"create", "update", "terminate"}:
                continue

            existing = self.store.get_agent(action.agent_id)
            if action.action == "terminate":
                terminated = self.store.terminate_agent(action.agent_id, action.reason)
                if terminated is not None:
                    self.store.record_memory(
                        source_agent_id=actor_id,
                        note=MemoryNote(
                            title=f"Agent terminated: {terminated.name}",
                            content=action.reason or f"{actor_type}:{actor_id} terminated {terminated.name}.",
                            category="org",
                            importance=5,
                            tags=["agent", "termination", action.agent_id, actor_type],
                        ),
                    )
                    applied.append(action)
                continue

            if existing is None:
                created = self.create_agent(
                    agent_id=action.agent_id,
                    name=action.name or action.agent_id.replace("_", " ").title(),
                    role=action.role or "Generalist",
                    mandate=action.mandate or "Expand company leverage.",
                    system_prompt=action.system_prompt or action.mandate or "Execute the assigned role.",
                    creator_type=actor_type,
                    creator_id=actor_id,
                    current_focus=action.current_focus,
                    success_metric=action.success_metric,
                    parent_agent_id=action.parent_agent_id,
                    model=action.model,
                    metadata=action.metadata,
                )
                self.store.record_memory(
                    source_agent_id=actor_id,
                    note=MemoryNote(
                        title=f"Agent creation rationale: {created.name}",
                        content=action.reason or created.mandate,
                        category="org",
                        importance=6,
                        tags=["agent", "creation_reason", created.agent_id],
                    ),
                )
                applied.append(action)
                continue

            existing.name = action.name or existing.name
            existing.role = action.role or existing.role
            existing.mandate = action.mandate or existing.mandate
            existing.system_prompt = action.system_prompt or existing.system_prompt
            existing.current_focus = action.current_focus or existing.current_focus
            existing.success_metric = action.success_metric or existing.success_metric
            existing.parent_agent_id = action.parent_agent_id or existing.parent_agent_id
            existing.model = action.model or existing.model
            if action.metadata:
                existing.metadata = action.metadata
            existing.status = "active"
            updated = self.store.upsert_agent(existing)
            self.store.record_memory(
                source_agent_id=actor_id,
                note=MemoryNote(
                    title=f"Agent updated: {updated.name}",
                    content=action.reason or f"{actor_type}:{actor_id} updated {updated.name}.",
                    category="org",
                    importance=5,
                    tags=["agent", "update", updated.agent_id, actor_type],
                ),
            )
            applied.append(action)
        return applied

    def _queue_work_items(
        self,
        items: List[WorkItemPlan],
        requested_by_type: str,
        requested_by_id: str,
    ) -> List[WorkItemPlan]:
        queued: List[WorkItemPlan] = []
        for item in items:
            item.requested_by_type = item.requested_by_type or requested_by_type
            item.requested_by_id = item.requested_by_id or requested_by_id
            if not item.owner_agent_id or not item.title or not item.description:
                continue
            self.store.create_work_item(item)
            queued.append(item)
        return queued

    def _queue_messages(
        self,
        messages: List[MessagePlan],
        sender_type: str,
        sender_id: str,
    ) -> List[MessagePlan]:
        queued: List[MessagePlan] = []
        for message in messages:
            message.sender_type = message.sender_type or sender_type
            message.sender_id = message.sender_id or sender_id
            if not message.recipient_agent_id or not message.subject or not message.body:
                continue
            self.store.enqueue_message(message)
            queued.append(message)
        return queued
