"""Tests for history tracking with enhanced schema and deduplication."""

import json
import tempfile
import unittest
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import scan


class TestRecordHistory(unittest.TestCase):
    """Tests for record_history() — enhanced history entries."""

    def _make_models(self, convergence_date="2026-06-15"):
        return {
            "convergence_date": convergence_date,
            "commit_rate": {"zero_date": "2026-07-01", "r_squared": 0.85},
            "capability": {
                "pct_95_date": "2026-05-01",
                "pct_99_date": "2026-06-01",
                "L": 350,
                "r_squared": 0.92,
            },
            "sophistication": {"pct_100_date": "2026-08-01"},
        }

    def _make_current(self, total_commits=150):
        return {
            "total_commits": total_commits,
            "total_capability": 230,
            "pct_of_asymptote": 65.7,
        }

    def test_records_entry(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("[]")
            tmp = Path(f.name)
        try:
            with patch.object(scan, "HISTORY_FILE", tmp):
                history = scan.record_history(
                    self._make_models(), self._make_current()
                )
            self.assertEqual(len(history), 1)
            entry = history[0]
            self.assertEqual(entry["convergence_date"], "2026-06-15")
            self.assertEqual(entry["total_commits"], 150)
        finally:
            tmp.unlink()

    def test_scoring_method_default(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("[]")
            tmp = Path(f.name)
        try:
            with patch.object(scan, "HISTORY_FILE", tmp):
                history = scan.record_history(
                    self._make_models(), self._make_current()
                )
            self.assertEqual(history[0]["scoring_method"], "regex")
        finally:
            tmp.unlink()

    def test_scoring_method_llm(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("[]")
            tmp = Path(f.name)
        try:
            with patch.object(scan, "HISTORY_FILE", tmp):
                history = scan.record_history(
                    self._make_models(), self._make_current(), "llm_haiku"
                )
            self.assertEqual(history[0]["scoring_method"], "llm_haiku")
        finally:
            tmp.unlink()

    def test_enhanced_fields_present(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("[]")
            tmp = Path(f.name)
        try:
            with patch.object(scan, "HISTORY_FILE", tmp):
                history = scan.record_history(
                    self._make_models(), self._make_current()
                )
            entry = history[0]
            self.assertEqual(entry["total_capability"], 230)
            self.assertEqual(entry["capability_L"], 350)
            self.assertAlmostEqual(entry["capability_r2"], 0.92)
            self.assertAlmostEqual(entry["commit_rate_r2"], 0.85)
        finally:
            tmp.unlink()

    def test_deduplication_skips_identical(self):
        prev_entry = {
            "convergence_date": "2026-06-15",
            "total_commits": 150,
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump([prev_entry], f)
            tmp = Path(f.name)
        try:
            with patch.object(scan, "HISTORY_FILE", tmp):
                history = scan.record_history(
                    self._make_models(), self._make_current()
                )
            # Should not append — same convergence_date and total_commits
            self.assertEqual(len(history), 1)
        finally:
            tmp.unlink()

    def test_deduplication_allows_different_commits(self):
        prev_entry = {
            "convergence_date": "2026-06-15",
            "total_commits": 100,  # different from 150
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump([prev_entry], f)
            tmp = Path(f.name)
        try:
            with patch.object(scan, "HISTORY_FILE", tmp):
                history = scan.record_history(
                    self._make_models(), self._make_current()
                )
            # Should append — different total_commits
            self.assertEqual(len(history), 2)
        finally:
            tmp.unlink()

    def test_deduplication_allows_different_date(self):
        prev_entry = {
            "convergence_date": "2026-07-01",  # different date
            "total_commits": 150,
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump([prev_entry], f)
            tmp = Path(f.name)
        try:
            with patch.object(scan, "HISTORY_FILE", tmp):
                history = scan.record_history(
                    self._make_models(), self._make_current()
                )
            # Should append — different convergence_date
            self.assertEqual(len(history), 2)
        finally:
            tmp.unlink()

    def test_component_dates(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("[]")
            tmp = Path(f.name)
        try:
            with patch.object(scan, "HISTORY_FILE", tmp):
                history = scan.record_history(
                    self._make_models(), self._make_current()
                )
            dates = history[0]["component_dates"]
            self.assertEqual(dates["commit_zero"], "2026-07-01")
            self.assertEqual(dates["capability_95"], "2026-05-01")
            self.assertEqual(dates["capability_99"], "2026-06-01")
            self.assertEqual(dates["sophistication_100"], "2026-08-01")
        finally:
            tmp.unlink()


if __name__ == "__main__":
    unittest.main()
