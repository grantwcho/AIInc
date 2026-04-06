import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_ceo.models import AgentSpec, MemoryNote, MessagePlan, WorkItemPlan
from ai_ceo.store import MemoryStore


class MemoryStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test.sqlite3"
        self.store = MemoryStore(str(self.db_path))

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_bootstrap_creates_objective(self) -> None:
        objective = self.store.bootstrap_objective(
            company_name="AI Inc",
            ultimate_objective="Build the best AI company in the world.",
        )
        loaded = self.store.load_objective()
        self.assertIsNotNone(loaded)
        self.assertEqual(objective.company_name, loaded.company_name)
        self.assertIn("best AI company", loaded.ultimate_objective)

    def test_memory_search_returns_recorded_note(self) -> None:
        self.store.bootstrap_objective(
            company_name="AI Inc",
            ultimate_objective="Build the best AI company in the world.",
        )
        self.store.record_memory(
            source_agent_id="ceo",
            note=MemoryNote(
                title="Customer urgency",
                content="Buyers act fastest when the problem is high-frequency and revenue-adjacent.",
                category="market",
                importance=8,
                tags=["customer", "urgency"],
            ),
        )
        results = self.store.search_memories("revenue-adjacent", limit=5)
        self.assertTrue(results)
        self.assertEqual(results[0]["title"], "Customer urgency")

    def test_runnable_agents_are_unique_when_agent_has_work_and_messages(self) -> None:
        self.store.bootstrap_objective(
            company_name="AI Inc",
            ultimate_objective="Build the best AI company in the world.",
        )
        self.store.upsert_agent(
            AgentSpec(
                agent_id="ops_agent",
                name="Ops Agent",
                role="Operations",
                mandate="Coordinate execution.",
                system_prompt="Be an excellent operator.",
            )
        )
        self.store.create_work_item(
            WorkItemPlan(
                owner_agent_id="ops_agent",
                title="Build plan",
                description="Create the initial operating plan.",
            )
        )
        self.store.enqueue_message(
            MessagePlan(
                recipient_agent_id="ops_agent",
                subject="Priority",
                body="Bias toward urgent customer pain.",
                sender_type="human",
                sender_id="grant",
            )
        )
        runnable = self.store.list_runnable_agents(limit=10)
        self.assertEqual([agent.agent_id for agent in runnable], ["ops_agent"])


if __name__ == "__main__":
    unittest.main()
