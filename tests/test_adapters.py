"""Unit tests for adapter loading and mock invocation."""

from __future__ import annotations

import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))

from adapters import invoke, load_adapters  # noqa: E402


class TestLoadAdapters(unittest.TestCase):
    def test_default_adapters_load(self):
        adapters = load_adapters()
        self.assertIn("claude", adapters)
        self.assertIn("codex", adapters)
        self.assertIn("gemini", adapters)
        self.assertEqual(adapters["claude"].binary, "claude")

    def test_adapters_have_known_prompt_modes(self):
        adapters = load_adapters()
        valid_modes = {"argv", "argv-after-flag", "stdin"}
        for name, a in adapters.items():
            self.assertIn(a.prompt_via, valid_modes, f"{name} has bad prompt_via")


class TestMockInvocation(unittest.TestCase):
    def test_mock_returns_recorded_response(self):
        adapters = load_adapters()
        with tempfile.TemporaryDirectory() as tmp:
            mock_dir = Path(tmp)
            (mock_dir / "claude.txt").write_text("# canned\n\nhello\n")
            result = invoke(
                adapters["claude"],
                prompt="ignored",
                workdir=Path.cwd(),
                mock_dir=mock_dir,
            )
            self.assertTrue(result.ok)
            self.assertIn("hello", result.stdout)

    def test_mock_missing_file_returns_error(self):
        adapters = load_adapters()
        with tempfile.TemporaryDirectory() as tmp:
            mock_dir = Path(tmp)
            result = invoke(
                adapters["claude"],
                prompt="ignored",
                workdir=Path.cwd(),
                mock_dir=mock_dir,
            )
            self.assertFalse(result.ok)
            self.assertIn("mock file not found", result.error or "")


if __name__ == "__main__":
    unittest.main()
