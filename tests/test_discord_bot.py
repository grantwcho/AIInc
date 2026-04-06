import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_ceo.discord_bot import (
    _clean_discord_content,
    _format_agent_report_for_channel,
    _format_cycle_summary,
    _load_persona_prompt,
    _render_report_reply,
    _slugify_channel_name,
)
from ai_ceo.models import AgentAction, ObjectiveState, CycleResult


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


if __name__ == "__main__":
    unittest.main()
