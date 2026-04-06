import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_ceo.utils import load_env_file, load_text_file


class UtilsTests(unittest.TestCase):
    def test_load_env_file_reads_key_values(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / ".env.local"
            env_path.write_text(
                "ALPHA=one\nBETA=\"two words\"\n# comment\nGAMMA='three'\n",
                encoding="utf-8",
            )

            loaded = load_env_file(str(env_path), override=True)

            self.assertEqual(loaded["ALPHA"], "one")
            self.assertEqual(loaded["BETA"], "two words")
            self.assertEqual(loaded["GAMMA"], "three")
            self.assertEqual(os.environ["ALPHA"], "one")

    def test_load_text_file_returns_trimmed_contents(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            prompt_path = Path(temp_dir) / "prompt.txt"
            prompt_path.write_text("Hello world\n", encoding="utf-8")

            loaded = load_text_file(str(prompt_path))

            self.assertEqual(loaded, "Hello world")


if __name__ == "__main__":
    unittest.main()
