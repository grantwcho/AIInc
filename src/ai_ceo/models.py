from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from .utils import utc_now


@dataclass
class ObjectiveState:
    company_name: str
    ultimate_objective: str
    strategy: str
    operating_principles: List[str] = field(default_factory=list)
    last_self_prompt: str = ""
    updated_at: str = field(default_factory=utc_now)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AgentSpec:
    agent_id: str
    name: str
    role: str
    mandate: str
    system_prompt: str
    status: str = "active"
    current_focus: str = ""
    success_metric: str = ""
    parent_agent_id: str = "ceo"
    creator_type: str = "ceo"
    creator_id: str = "ceo"
    model: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    version: int = 1
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AgentAction:
    action: str
    agent_id: str
    name: str = ""
    role: str = ""
    mandate: str = ""
    system_prompt: str = ""
    current_focus: str = ""
    success_metric: str = ""
    parent_agent_id: str = ""
    model: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    reason: str = ""

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "AgentAction":
        metadata = raw.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}
        return cls(
            action=str(raw.get("action", "")).strip().lower(),
            agent_id=str(raw.get("agent_id", "")).strip(),
            name=str(raw.get("name", "")).strip(),
            role=str(raw.get("role", "")).strip(),
            mandate=str(raw.get("mandate", "")).strip(),
            system_prompt=str(raw.get("system_prompt", "")).strip(),
            current_focus=str(raw.get("current_focus", "")).strip(),
            success_metric=str(raw.get("success_metric", "")).strip(),
            parent_agent_id=str(raw.get("parent_agent_id", "")).strip(),
            model=str(raw.get("model", "")).strip(),
            metadata=metadata,
            reason=str(raw.get("reason", "")).strip(),
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DecisionPlan:
    title: str
    summary: str
    rationale: str
    expected_impact: str

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "DecisionPlan":
        return cls(
            title=str(raw.get("title", "")).strip(),
            summary=str(raw.get("summary", "")).strip(),
            rationale=str(raw.get("rationale", "")).strip(),
            expected_impact=str(raw.get("expected_impact", "")).strip(),
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class WorkItemPlan:
    owner_agent_id: str
    title: str
    description: str
    priority: str = "high"
    requested_by_type: str = ""
    requested_by_id: str = ""

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "WorkItemPlan":
        return cls(
            owner_agent_id=str(raw.get("owner_agent_id", "")).strip(),
            title=str(raw.get("title", "")).strip(),
            description=str(raw.get("description", "")).strip(),
            priority=str(raw.get("priority", "high")).strip() or "high",
            requested_by_type=str(raw.get("requested_by_type", "")).strip(),
            requested_by_id=str(raw.get("requested_by_id", "")).strip(),
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class MessagePlan:
    recipient_agent_id: str
    subject: str
    body: str
    sender_type: str = ""
    sender_id: str = ""
    thread_id: str = ""

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "MessagePlan":
        return cls(
            recipient_agent_id=str(raw.get("recipient_agent_id", "")).strip(),
            subject=str(raw.get("subject", "")).strip(),
            body=str(raw.get("body", "")).strip(),
            sender_type=str(raw.get("sender_type", "")).strip(),
            sender_id=str(raw.get("sender_id", "")).strip(),
            thread_id=str(raw.get("thread_id", "")).strip(),
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class MemoryNote:
    title: str
    content: str
    category: str = "note"
    importance: int = 3
    tags: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "MemoryNote":
        tags = raw.get("tags", [])
        if not isinstance(tags, list):
            tags = []
        return cls(
            title=str(raw.get("title", "")).strip(),
            content=str(raw.get("content", "")).strip(),
            category=str(raw.get("category", "note")).strip() or "note",
            importance=int(raw.get("importance", 3) or 3),
            tags=[str(tag).strip() for tag in tags if str(tag).strip()],
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AgentReport:
    summary: str
    direct_response: str = ""
    deliverables: List[str] = field(default_factory=list)
    memory_notes: List[MemoryNote] = field(default_factory=list)
    decision_proposals: List[DecisionPlan] = field(default_factory=list)
    follow_up_work_items: List[WorkItemPlan] = field(default_factory=list)
    outbound_messages: List[MessagePlan] = field(default_factory=list)
    agent_actions: List[AgentAction] = field(default_factory=list)
    needs: List[str] = field(default_factory=list)
    status: str = "complete"

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "AgentReport":
        return cls(
            summary=str(raw.get("summary", "")).strip(),
            direct_response=str(raw.get("direct_response", "")).strip(),
            deliverables=[
                str(item).strip()
                for item in raw.get("deliverables", [])
                if str(item).strip()
            ],
            memory_notes=[
                MemoryNote.from_dict(item)
                for item in raw.get("memory_notes", [])
                if isinstance(item, dict)
            ],
            decision_proposals=[
                DecisionPlan.from_dict(item)
                for item in raw.get("decision_proposals", [])
                if isinstance(item, dict)
            ],
            follow_up_work_items=[
                WorkItemPlan.from_dict(item)
                for item in raw.get("follow_up_work_items", [])
                if isinstance(item, dict)
            ],
            outbound_messages=[
                MessagePlan.from_dict(item)
                for item in raw.get("outbound_messages", [])
                if isinstance(item, dict)
            ],
            agent_actions=[
                AgentAction.from_dict(item)
                for item in raw.get("agent_actions", [])
                if isinstance(item, dict)
            ],
            needs=[
                str(item).strip() for item in raw.get("needs", []) if str(item).strip()
            ],
            status=str(raw.get("status", "complete")).strip() or "complete",
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "summary": self.summary,
            "direct_response": self.direct_response,
            "deliverables": list(self.deliverables),
            "memory_notes": [note.to_dict() for note in self.memory_notes],
            "decision_proposals": [item.to_dict() for item in self.decision_proposals],
            "follow_up_work_items": [item.to_dict() for item in self.follow_up_work_items],
            "outbound_messages": [item.to_dict() for item in self.outbound_messages],
            "agent_actions": [asdict(item) for item in self.agent_actions],
            "needs": list(self.needs),
            "status": self.status,
        }


@dataclass
class BrainOutput:
    reflection_summary: str
    self_prompt: str
    updated_strategy: str
    updated_operating_principles: List[str] = field(default_factory=list)
    decisions: List[DecisionPlan] = field(default_factory=list)
    agent_actions: List[AgentAction] = field(default_factory=list)
    work_items: List[WorkItemPlan] = field(default_factory=list)
    outbound_messages: List[MessagePlan] = field(default_factory=list)
    memory_notes: List[MemoryNote] = field(default_factory=list)

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "BrainOutput":
        return cls(
            reflection_summary=str(raw.get("reflection_summary", "")).strip(),
            self_prompt=str(raw.get("self_prompt", "")).strip(),
            updated_strategy=str(raw.get("updated_strategy", "")).strip(),
            updated_operating_principles=[
                str(item).strip()
                for item in raw.get("updated_operating_principles", [])
                if str(item).strip()
            ],
            decisions=[
                DecisionPlan.from_dict(item)
                for item in raw.get("decisions", [])
                if isinstance(item, dict)
            ],
            agent_actions=[
                AgentAction.from_dict(item)
                for item in raw.get("agent_actions", [])
                if isinstance(item, dict)
            ],
            work_items=[
                WorkItemPlan.from_dict(item)
                for item in raw.get("work_items", [])
                if isinstance(item, dict)
            ],
            outbound_messages=[
                MessagePlan.from_dict(item)
                for item in raw.get("outbound_messages", [])
                if isinstance(item, dict)
            ],
            memory_notes=[
                MemoryNote.from_dict(item)
                for item in raw.get("memory_notes", [])
                if isinstance(item, dict)
            ],
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "reflection_summary": self.reflection_summary,
            "self_prompt": self.self_prompt,
            "updated_strategy": self.updated_strategy,
            "updated_operating_principles": list(self.updated_operating_principles),
            "decisions": [item.to_dict() for item in self.decisions],
            "agent_actions": [asdict(item) for item in self.agent_actions],
            "work_items": [item.to_dict() for item in self.work_items],
            "outbound_messages": [item.to_dict() for item in self.outbound_messages],
            "memory_notes": [item.to_dict() for item in self.memory_notes],
        }


@dataclass
class CycleResult:
    cycle_id: str
    objective: ObjectiveState
    reflection_summary: str
    self_prompt: str
    applied_agent_actions: List[AgentAction] = field(default_factory=list)
    recorded_decisions: List[DecisionPlan] = field(default_factory=list)
    queued_work_items: List[WorkItemPlan] = field(default_factory=list)
    queued_messages: List[MessagePlan] = field(default_factory=list)
    agent_reports: List[Dict[str, Any]] = field(default_factory=list)
    memory_notes: List[MemoryNote] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cycle_id": self.cycle_id,
            "objective": self.objective.to_dict(),
            "reflection_summary": self.reflection_summary,
            "self_prompt": self.self_prompt,
            "applied_agent_actions": [asdict(item) for item in self.applied_agent_actions],
            "recorded_decisions": [item.to_dict() for item in self.recorded_decisions],
            "queued_work_items": [item.to_dict() for item in self.queued_work_items],
            "queued_messages": [item.to_dict() for item in self.queued_messages],
            "agent_reports": list(self.agent_reports),
            "memory_notes": [item.to_dict() for item in self.memory_notes],
        }
