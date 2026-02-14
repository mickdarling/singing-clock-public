"""Tests for CLI argument parsing."""

import unittest
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scan import parse_args


class TestParseArgs(unittest.TestCase):
    """Tests for parse_args() — command line argument parsing."""

    def test_defaults(self):
        with mock.patch("sys.argv", ["scan.py"]):
            args = parse_args()
            self.assertFalse(args["enrich"])
            self.assertEqual(args["enrich_model"], "haiku")

    def test_enrich_flag(self):
        with mock.patch("sys.argv", ["scan.py", "--enrich"]):
            args = parse_args()
            self.assertTrue(args["enrich"])

    def test_enrich_model_sonnet(self):
        with mock.patch("sys.argv", ["scan.py", "--enrich", "--enrich-model", "sonnet"]):
            args = parse_args()
            self.assertTrue(args["enrich"])
            self.assertEqual(args["enrich_model"], "sonnet")

    def test_enrich_model_haiku(self):
        with mock.patch("sys.argv", ["scan.py", "--enrich-model", "haiku"]):
            args = parse_args()
            self.assertEqual(args["enrich_model"], "haiku")

    def test_unknown_model_defaults_haiku(self):
        with mock.patch("sys.argv", ["scan.py", "--enrich-model", "gpt4"]):
            args = parse_args()
            self.assertEqual(args["enrich_model"], "haiku")

    def test_enrich_model_case_insensitive(self):
        with mock.patch("sys.argv", ["scan.py", "--enrich-model", "SONNET"]):
            args = parse_args()
            self.assertEqual(args["enrich_model"], "sonnet")

    def test_enrich_model_without_value(self):
        # --enrich-model at end with no following arg
        with mock.patch("sys.argv", ["scan.py", "--enrich-model"]):
            args = parse_args()
            # Should just use default
            self.assertEqual(args["enrich_model"], "haiku")


if __name__ == "__main__":
    unittest.main()
