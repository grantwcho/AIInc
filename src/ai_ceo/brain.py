from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from .models import (
    AgentAction,
    AgentReport,
    AgentSpec,
    BrainOutput,
    DecisionPlan,
    MemoryNote,
    MessagePlan,
    WorkItemPlan,
)
from .prompts import (
    build_agent_system_prompt,
    build_agent_user_prompt,
    build_ceo_system_prompt,
    build_ceo_user_prompt,
)
from .utils import extract_json_object


class BrainError(RuntimeError):
    pass


class Brain:
    def run_ceo_cycle(self, context: Dict[str, Any]) -> BrainOutput:
        raise NotImplementedError

    def run_agent_cycle(self, agent: AgentSpec, context: Dict[str, Any]) -> AgentReport:
        raise NotImplementedError


class HeuristicBrain(Brain):
    def __init__(self) -> None:
        self.role_templates = [
            {
                "agent_id": "chief_of_staff",
                "name": "Chief of Staff Agent",
                "role": "Execution cadence",
                "mandate": "Translate CEO strategy into concrete operating rhythms and cross-functional coordination.",
                "system_prompt": "Run the company operating system, keep priorities aligned, and force clarity on blockers.",
                "current_focus": "Stand up the initial operating cadence and clarify near-term priorities.",
                "success_metric": "Leadership work is converted into crisp workstreams with tight feedback loops.",
            },
            {
                "agent_id": "market_intelligence",
                "name": "Market Intelligence Agent",
                "role": "Market sensing",
                "mandate": "Continuously map customer pain, market timing, and category whitespace.",
                "system_prompt": "Act like a world-class market analyst looking for asymmetric opportunities and demand signals.",
                "current_focus": "Identify the sharpest initial wedge with clear urgency and willingness to pay.",
                "success_metric": "The company has a credible wedge backed by repeated demand signals.",
            },
            {
                "agent_id": "growth_architect",
                "name": "Growth Architect Agent",
                "role": "Distribution system design",
                "mandate": "Design repeatable acquisition, retention, and virality loops.",
                "system_prompt": "Think in compounding distribution channels, activation loops, and durable growth moats.",
                "current_focus": "Draft the first compounding growth loops for the company.",
                "success_metric": "The business has measurable, repeatable distribution experiments underway.",
            },
        ]

    def run_ceo_cycle(self, context: Dict[str, Any]) -> BrainOutput:
        objective = context["objective"]["ultimate_objective"]
        overview = context.get("agent_overview", {})
        active_count = int(overview.get("active_agents", 0))
        trigger = str(context.get("trigger", "")).strip()

        agent_actions: List[AgentAction] = []
        decisions: List[DecisionPlan] = []
        work_items: List[WorkItemPlan] = []
        memory_notes: List[MemoryNote] = []

        if active_count < len(self.role_templates):
            template = self.role_templates[active_count]
            agent_actions.append(AgentAction(action="create", **template))
            decisions.append(
                DecisionPlan(
                    title=f"Create {template['name']}",
                    summary=f"Add {template['name']} to increase execution leverage.",
                    rationale=(
                        f"{template['role']} is a missing capability and will help the company compound faster."
                    ),
                    expected_impact="The company gains more focused execution without requiring the CEO to hold every thread directly.",
                )
            )
            work_items.append(
                WorkItemPlan(
                    owner_agent_id=template["agent_id"],
                    title="Stand up operating lane",
                    description=(
                        f"Define the first high-leverage agenda for {template['role'].lower()} in service of the company objective. "
                        f"Trigger context: {trigger or 'No external trigger provided.'}"
                    ),
                    priority="high",
                )
            )
        else:
            for agent in context.get("runnable_agents", [])[:5]:
                work_items.append(
                    WorkItemPlan(
                        owner_agent_id=agent["agent_id"],
                        title=f"Advance {agent['role'].lower()} agenda",
                        description=(
                            "Produce the next highest-leverage recommendation based on current queue pressure, "
                            f"company objective, and trigger context: {trigger or 'No external trigger provided.'}"
                        ),
                        priority="high",
                    )
                )

        memory_notes.append(
            MemoryNote(
                title="Scalable operating stance",
                content=(
                    "Treat the company as a network of specialized agents coordinated through queues, not as a single loop over every active worker."
                ),
                category="reflection",
                importance=8,
                tags=["architecture", "scale", "queues"],
            )
        )

        updated_strategy = (
            "Operate as a persistent multi-agent company: keep the CEO focused on leverage, use a queue-driven runtime for execution, "
            "and let humans or agents add specialists without forcing full-roster scans."
        )
        principles = [
            "Keep the ultimate objective fixed and visible every cycle.",
            "Design for queue pressure and routing, not blanket iteration over the whole workforce.",
            "Preserve creator lineage so human-made and agent-made workers are both first-class citizens.",
            "Capture durable memory so the organization compounds rather than relearns.",
        ]
        reflection = (
            f"The company objective remains: {objective}. "
            "The system should behave like a scalable operating network where only runnable agents consume compute."
        )
        self_prompt = (
            "What routing, memory, or delegation bottleneck most limits our ability to coordinate a very large agent workforce?"
        )

        return BrainOutput(
            reflection_summary=reflection,
            self_prompt=self_prompt,
            updated_strategy=updated_strategy,
            updated_operating_principles=principles,
            decisions=decisions,
            agent_actions=agent_actions,
            work_items=work_items,
            outbound_messages=[],
            memory_notes=memory_notes,
        )

    def run_agent_cycle(self, agent: AgentSpec, context: Dict[str, Any]) -> AgentReport:
        work_items = context.get("assigned_work_items", [])
        inbox_messages = context.get("inbox_messages", [])
        peer_agents = sorted(
            context.get("peer_agents", []), key=lambda item: item.get("agent_id", "")
        )
        trigger = str(context.get("trigger", "")).strip()

        if not work_items and not inbox_messages:
            return AgentReport(
                summary="No queued work or messages were available for this cycle.",
                deliverables=[],
                memory_notes=[],
                decision_proposals=[],
                follow_up_work_items=[],
                outbound_messages=[],
                agent_actions=[],
                needs=[],
                status="complete",
            )

        deliverables = []
        for item in work_items:
            deliverables.append(
                f"{agent.name} recommends: {item['title']} -> {item['description']}"
            )
        for message in inbox_messages:
            deliverables.append(
                f"{agent.name} received message '{message['subject']}' from {message['sender_type']}:{message['sender_id']}"
            )

        recommendation = (
            f"{agent.name} should focus on {agent.current_focus or agent.mandate.lower()}."
        )
        if trigger:
            recommendation += f" External trigger considered: {trigger}"

        outbound_messages: List[MessagePlan] = []
        if work_items and peer_agents:
            collaborator = peer_agents[0]
            outbound_messages.append(
                MessagePlan(
                    recipient_agent_id=collaborator["agent_id"],
                    subject=f"{agent.name} sync",
                    body=(
                        f"I'm advancing '{work_items[0]['title']}' and want your input on the highest-leverage next move."
                    ),
                )
            )

        return AgentReport(
            summary=(
                f"{agent.name} processed {len(work_items)} work item(s) and {len(inbox_messages)} message(s)."
            ),
            deliverables=deliverables,
            memory_notes=[
                MemoryNote(
                    title=f"{agent.name} cycle insight",
                    content=recommendation,
                    category="note",
                    importance=6,
                    tags=[agent.agent_id, "agent_cycle"],
                )
            ],
            decision_proposals=[
                DecisionPlan(
                    title=f"{agent.name} recommendation",
                    summary=recommendation,
                    rationale="The current mandate should be converted into tangible operating leverage.",
                    expected_impact="The company gains clearer execution and faster learning loops.",
                )
            ],
            follow_up_work_items=[],
            outbound_messages=outbound_messages,
            agent_actions=[],
            needs=["A sharper KPI for the next cycle would improve prioritization."],
            status="complete",
        )


class OpenAIBrain(Brain):
    def __init__(self, model: Optional[str] = None) -> None:
        self.model = model or os.getenv("AI_CEO_MODEL", "gpt-4.1-mini")
        self._client = self._build_client()

    def _build_client(self) -> Any:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise BrainError(
                "The openai package is not installed. Install dependencies or use --brain heuristic."
            ) from exc
        return OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    def _call_json(self, system_prompt: str, user_prompt: str) -> Dict[str, Any]:
        try:
            response = self._client.responses.create(
                model=self.model,
                instructions=system_prompt,
                input=user_prompt,
            )
        except Exception as exc:
            raise BrainError(f"OpenAI request failed: {exc}") from exc

        text = getattr(response, "output_text", "") or ""
        if not text:
            raise BrainError("Model returned no text output.")
        try:
            return extract_json_object(text)
        except Exception as exc:
            raise BrainError(f"Failed to parse model output as JSON: {exc}") from exc

    def run_ceo_cycle(self, context: Dict[str, Any]) -> BrainOutput:
        payload = self._call_json(
            system_prompt=build_ceo_system_prompt(),
            user_prompt=build_ceo_user_prompt(context),
        )
        return BrainOutput.from_dict(payload)

    def run_agent_cycle(self, agent: AgentSpec, context: Dict[str, Any]) -> AgentReport:
        agent_context = dict(context)
        agent_context["agent"] = agent.to_dict()
        payload = self._call_json(
            system_prompt=build_agent_system_prompt(),
            user_prompt=build_agent_user_prompt(agent_context),
        )
        return AgentReport.from_dict(payload)


def resolve_brain(mode: str, model: Optional[str] = None) -> Brain:
    lowered = (mode or "auto").strip().lower()
    if lowered == "heuristic":
        return HeuristicBrain()
    if lowered == "openai":
        return OpenAIBrain(model=model)
    if lowered == "auto":
        if os.getenv("OPENAI_API_KEY"):
            try:
                return OpenAIBrain(model=model)
            except BrainError:
                return HeuristicBrain()
        return HeuristicBrain()
    raise BrainError(f"Unknown brain mode: {mode}")
