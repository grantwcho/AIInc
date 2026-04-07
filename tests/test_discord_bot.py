import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_ceo.discord_bot import (
    _assigned_employee_slot,
    _assign_employee_slots,
    _autonomous_trigger,
    _ceo_discord_token,
    _cycle_has_momentum,
    _clean_discord_content,
    _discover_employee_slots,
    _env_flag,
    _format_admin_dm,
    _format_agent_report_for_channel,
    _format_cycle_summary,
    _load_persona_prompt,
    _render_report_reply,
    _slugify_channel_name,
)
from ai_ceo.models import AgentAction, AgentSpec, ObjectiveState, CycleResult
from ai_ceo.store import MemoryStore


class DiscordBotTests(unittest.TestCase):
    def test_clean_discord_content_removes_bot_mentions(self) -> None:
        message = type("Message", (), {"content": "<@12345> give me the quarterly plan"})()
        cleaned = _clean_discord_content(message, 12345)
        self.assertEqual(cleaned, "give me the quarterly plan")

    def test_render_report_reply_includes_summary_and_deliverables(self) -> None:
        report = {
            "summary": "Ryan set the next move.",
            "deliverables": ["Launch customer interviews.", "Stand up a metrics dashboard."],
            "needs": ["Need budget constraints."],
        }
        rendered = _render_report_reply(report)
        self.assertIn("Ryan set the next move.", rendered)
        self.assertIn("- Launch customer interviews.", rendered)
        self.assertIn("Needs:", rendered)

    def test_render_report_reply_prefers_direct_response(self) -> None:
        report = {
            "summary": "Internal summary.",
            "direct_response": "Hey Grant, yes, I'm here. What's the most important thing you want me focused on?",
            "deliverables": ["Should not be rendered."],
        }
        rendered = _render_report_reply(report)
        self.assertEqual(
            rendered,
            "Hey Grant, yes, I'm here. What's the most important thing you want me focused on?",
        )

    def test_load_persona_prompt_prefers_prompt_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            prompt_path = Path(temp_dir) / "ryan.txt"
            prompt_path.write_text("You are Ryan.", encoding="utf-8")

            original = os.environ.get("AI_CEO_DISCORD_SYSTEM_PROMPT_FILE")
            os.environ["AI_CEO_DISCORD_SYSTEM_PROMPT_FILE"] = str(prompt_path)
            try:
                self.assertEqual(_load_persona_prompt(), "You are Ryan.")
            finally:
                if original is None:
                    os.environ.pop("AI_CEO_DISCORD_SYSTEM_PROMPT_FILE", None)
                else:
                    os.environ["AI_CEO_DISCORD_SYSTEM_PROMPT_FILE"] = original

    def test_slugify_channel_name_matches_discord_style(self) -> None:
        self.assertEqual(_slugify_channel_name("Market Analyst_1"), "market-analyst-1")

    def test_format_agent_report_for_channel(self) -> None:
        report = {
            "agent_name": "Growth Architect",
            "summary": "I mapped the first growth loop.",
            "deliverables": ["Acquisition loop draft", "Activation experiment"],
        }
        rendered = _format_agent_report_for_channel(report)
        self.assertIn("**Growth Architect**", rendered)
        self.assertIn("- Acquisition loop draft", rendered)

    def test_format_cycle_summary_mentions_created_agents(self) -> None:
        result = CycleResult(
            cycle_id="cycle_1",
            objective=ObjectiveState(
                company_name="Go Unicorn",
                ultimate_objective="Win.",
                strategy="Move fast.",
            ),
            reflection_summary="I staffed the next wedge.",
            self_prompt="What's next?",
            applied_agent_actions=[
                AgentAction(action="create", agent_id="growth_architect", name="Growth Architect")
            ],
            queued_work_items=[],
        )
        rendered = _format_cycle_summary(result, [{"agent_id": "growth_architect"}])
        self.assertIn("Created agents: Growth Architect", rendered)

    def test_env_flag_parses_truthy_values(self) -> None:
        original = os.environ.get("AI_CEO_AUTONOMOUS_ENABLED")
        os.environ["AI_CEO_AUTONOMOUS_ENABLED"] = "true"
        try:
            self.assertTrue(_env_flag("AI_CEO_AUTONOMOUS_ENABLED"))
        finally:
            if original is None:
                os.environ.pop("AI_CEO_AUTONOMOUS_ENABLED", None)
            else:
                os.environ["AI_CEO_AUTONOMOUS_ENABLED"] = original

    def test_autonomous_trigger_uses_env_override(self) -> None:
        original = os.environ.get("AI_CEO_AUTONOMOUS_TRIGGER")
        os.environ["AI_CEO_AUTONOMOUS_TRIGGER"] = "Do the next thing."
        try:
            self.assertEqual(_autonomous_trigger(), "Do the next thing.")
        finally:
            if original is None:
                os.environ.pop("AI_CEO_AUTONOMOUS_TRIGGER", None)
            else:
                os.environ["AI_CEO_AUTONOMOUS_TRIGGER"] = original

    def test_format_admin_dm_includes_decisions_and_reports(self) -> None:
        result = CycleResult(
            cycle_id="cycle_1",
            objective=ObjectiveState(
                company_name="Go Unicorn",
                ultimate_objective="Win.",
                strategy="Move fast.",
            ),
            reflection_summary="I pushed the company toward PMF.",
            self_prompt="What unlocks revenue fastest?",
            applied_agent_actions=[
                AgentAction(action="create", agent_id="head_of_product", name="Head of Product")
            ],
            recorded_decisions=[
                type(
                    "Decision",
                    (),
                    {"title": "Ship MVP fast", "summary": "Use the narrowest wedge first"},
                )()
            ],
        )
        rendered = _format_admin_dm(
            result,
            [{"agent_name": "Head of Product", "summary": "I scoped the MVP."}],
        )
        self.assertIn("Ryan CEO update", rendered)
        self.assertIn("Created agents: Head of Product", rendered)
        self.assertIn("- Ship MVP fast: Use the narrowest wedge first", rendered)

    def test_cycle_has_momentum_when_agents_created(self) -> None:
        result = CycleResult(
            cycle_id="cycle_1",
            objective=ObjectiveState(
                company_name="Go Unicorn",
                ultimate_objective="Win.",
                strategy="Move fast.",
            ),
            reflection_summary="I created a team.",
            self_prompt="What's next?",
            applied_agent_actions=[
                AgentAction(action="create", agent_id="head_of_product", name="Head of Product")
            ],
        )
        self.assertTrue(_cycle_has_momentum({"cycle_result": result, "reports": []}))

    def test_cycle_has_no_momentum_when_nothing_changed(self) -> None:
        result = CycleResult(
            cycle_id="cycle_1",
            objective=ObjectiveState(
                company_name="Go Unicorn",
                ultimate_objective="Win.",
                strategy="Move fast.",
            ),
            reflection_summary="No change.",
            self_prompt="What's next?",
        )
        self.assertFalse(_cycle_has_momentum({"cycle_result": result, "reports": []}))

    def test_ceo_discord_token_prefers_ceo_specific_env_var(self) -> None:
        original_ceo = os.environ.get("CEO_DISCORD_BOT_TOKEN")
        original_generic = os.environ.get("DISCORD_BOT_TOKEN")
        os.environ["CEO_DISCORD_BOT_TOKEN"] = "ceo-token"
        os.environ["DISCORD_BOT_TOKEN"] = "generic-token"
        try:
            self.assertEqual(_ceo_discord_token(), "ceo-token")
        finally:
            if original_ceo is None:
                os.environ.pop("CEO_DISCORD_BOT_TOKEN", None)
            else:
                os.environ["CEO_DISCORD_BOT_TOKEN"] = original_ceo
            if original_generic is None:
                os.environ.pop("DISCORD_BOT_TOKEN", None)
            else:
                os.environ["DISCORD_BOT_TOKEN"] = original_generic

    def test_discover_employee_slots_sorts_by_index(self) -> None:
        originals = {key: os.environ.get(key) for key in [
            "EMPLOYEE_2_DISCORD_BOT_TOKEN",
            "EMPLOYEE_1_DISCORD_BOT_TOKEN",
        ]}
        os.environ["EMPLOYEE_2_DISCORD_BOT_TOKEN"] = "token-2"
        os.environ["EMPLOYEE_1_DISCORD_BOT_TOKEN"] = "token-1"
        try:
            slots = _discover_employee_slots()
            filtered = [item for item in slots if item["slot_id"] in {"employee_1", "employee_2"}]
            self.assertEqual([item["slot_id"] for item in filtered], ["employee_1", "employee_2"])
        finally:
            for key, value in originals.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def test_assign_employee_slots_assigns_first_available_employee(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = MemoryStore(db_path=str(Path(temp_dir) / "ai_ceo.sqlite3"))
            ceo = AgentSpec(
                agent_id="ryan_whitaker",
                name="Ryan Whitaker",
                role="CEO",
                mandate="Lead the company.",
                system_prompt="You are the CEO.",
            )
            worker = AgentSpec(
                agent_id="technical_lead",
                name="Technical Lead",
                role="Engineering",
                mandate="Ship the product.",
                system_prompt="You are the technical lead.",
            )
            store.upsert_agent(ceo)
            store.upsert_agent(worker)

            assigned = _assign_employee_slots(
                store,
                "ryan_whitaker",
                [
                    {
                        "slot_id": "employee_1",
                        "token_env": "EMPLOYEE_1_DISCORD_BOT_TOKEN",
                        "token": "token-1",
                        "index": "1",
                    }
                ],
            )

            refreshed = store.get_agent("technical_lead")
            self.assertEqual(assigned, ["technical_lead"])
            self.assertEqual(_assigned_employee_slot(refreshed), "employee_1")


if __name__ == "__main__":
    unittest.main()
