import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_ceo.brain import Brain, HeuristicBrain
from ai_ceo.engine import CEOEngine
from ai_ceo.models import (
    AgentAction,
    AgentReport,
    BrainOutput,
    DecisionPlan,
    MessagePlan,
    WorkItemPlan,
)
from ai_ceo.store import MemoryStore


class RelayBrain(Brain):
    def run_ceo_cycle(self, context):
        return BrainOutput(
            reflection_summary="No-op CEO cycle.",
            self_prompt="What should we queue next?",
            updated_strategy=context["objective"]["strategy"],
            updated_operating_principles=context["objective"]["operating_principles"],
        )

    def run_agent_cycle(self, agent, context):
        if agent.agent_id == "founder_ops":
            return AgentReport(
                summary="Founder Ops spawned an analyst and delegated work.",
                deliverables=["Delegation lane created."],
                decision_proposals=[
                    DecisionPlan(
                        title="Create analyst",
                        summary="A market analyst is needed.",
                        rationale="The operator found a clear need for research support.",
                        expected_impact="Execution can branch into a new specialist lane.",
                    )
                ],
                follow_up_work_items=[
                    WorkItemPlan(
                        owner_agent_id="market_analyst_1",
                        title="Map customer pain",
                        description="Identify the highest-frequency painful workflows.",
                    )
                ],
                outbound_messages=[
                    MessagePlan(
                        recipient_agent_id="market_analyst_1",
                        subject="Start research",
                        body="Map the most painful customer workflow first.",
                    )
                ],
                agent_actions=[
                    AgentAction(
                        action="create",
                        agent_id="market_analyst_1",
                        name="Market Analyst 1",
                        role="Research",
                        mandate="Map customer pain and demand signals.",
                        system_prompt="Act like a sharp market analyst and surface demand signals.",
                    )
                ],
            )
        return AgentReport(summary="Completed assigned work.")


class EngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "engine.sqlite3"
        self.store = MemoryStore(str(self.db_path))
        self.engine = CEOEngine(store=self.store, brain=HeuristicBrain())
        self.engine.bootstrap(
            company_name="AI Inc",
            ultimate_objective="Build the most successful company in the world.",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_cycle_creates_agent_and_records_decisions(self) -> None:
        result = self.engine.run_cycle("Find the best initial wedge.")
        self.assertTrue(result.applied_agent_actions)
        self.assertTrue(result.recorded_decisions)
        self.assertTrue(self.store.list_agents(status="active"))
        self.assertTrue(self.store.recent_decisions(limit=5))

    def test_human_created_agent_can_be_queued_without_scanning_entire_roster(self) -> None:
        agent = self.engine.create_agent(
            agent_id="human_ops",
            name="Human Ops",
            role="Operations",
            mandate="Coordinate operating work.",
            system_prompt="Be a strong operator.",
            creator_type="human",
            creator_id="grant",
        )
        self.assertEqual(agent.creator_type, "human")
        self.assertEqual(agent.creator_id, "grant")

        self.engine.queue_work_item(
            owner_agent_id="human_ops",
            title="Prepare operating plan",
            description="Define the initial operating cadence.",
            priority="high",
            requested_by_type="human",
            requested_by_id="grant",
        )
        runnable = self.store.list_runnable_agents(limit=10)
        self.assertEqual([item.agent_id for item in runnable], ["human_ops"])

    def test_agent_can_create_new_agent_and_queue_follow_up_work(self) -> None:
        relay_engine = CEOEngine(store=self.store, brain=RelayBrain())
        relay_engine.create_agent(
            agent_id="founder_ops",
            name="Founder Ops",
            role="Operator",
            mandate="Coordinate execution.",
            system_prompt="Operate like a world-class operator.",
            creator_type="human",
            creator_id="grant",
        )
        relay_engine.queue_work_item(
            owner_agent_id="founder_ops",
            title="Create support lane",
            description="Add whatever specialist is needed next.",
            priority="high",
            requested_by_type="human",
            requested_by_id="grant",
        )

        first_pass = relay_engine.process_agent_queue(
            trigger="Delegate into research.", max_agents=10
        )
        self.assertTrue(first_pass)

        spawned = self.store.get_agent("market_analyst_1")
        self.assertIsNotNone(spawned)
        self.assertEqual(spawned.creator_type, "agent")
        self.assertEqual(spawned.creator_id, "founder_ops")

        queued_messages = self.store.list_messages(
            recipient_agent_id="market_analyst_1", status="queued"
        )
        queued_work = self.store.list_work_items(
            owner_agent_id="market_analyst_1", status="queued"
        )
        self.assertTrue(queued_messages)
        self.assertTrue(queued_work)

    def test_seed_demo_swarm_creates_visible_agent_conversation_flow(self) -> None:
        self.engine.seed_demo_swarm()
        self.engine.process_agent_queue(trigger="Demo pulse", max_agents=10)
        agent_messages = [
            item for item in self.store.recent_messages(limit=20) if item["sender_type"] == "agent"
        ]
        self.assertTrue(agent_messages)


if __name__ == "__main__":
    unittest.main()
