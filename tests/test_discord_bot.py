import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_ceo.discord_bot import _clean_discord_content, _render_report_reply


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


if __name__ == "__main__":
    unittest.main()
