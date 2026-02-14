"""Tests for improved sophistication metric."""

import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scan import compute_sophistication, smooth_sophistication, CATEGORIES


class TestComputeSophistication(unittest.TestCase):
    """Tests for compute_sophistication() — blended weighted ratio + breadth."""

    def test_empty_scores(self):
        self.assertEqual(compute_sophistication({}), 0.0)

    def test_all_high_level(self):
        scores = {"agents": 5, "self_modify": 3, "meta": 2}
        result = compute_sophistication(scores)
        # 100% weighted ratio, 3/N breadth
        self.assertGreater(result, 0.7)

    def test_all_low_level(self):
        scores = {"foundation": 10, "testing": 5}
        result = compute_sophistication(scores)
        # 0% weighted ratio, 2/N breadth -> 0.3 * (2/N)
        self.assertLess(result, 0.15)

    def test_mixed_categories(self):
        scores = {"agents": 3, "foundation": 3}
        result = compute_sophistication(scores)
        # Some high, some low
        self.assertGreater(result, 0.2)
        self.assertLess(result, 0.9)

    def test_breadth_bonus(self):
        # Many categories active = higher score than few categories
        few = compute_sophistication({"agents": 10})
        many = compute_sophistication({
            "agents": 3, "self_modify": 2, "meta": 2,
            "safety": 1, "testing": 1, "ecosystem": 1,
        })
        # With breadth bonus, many categories should score higher
        self.assertGreater(many, few)

    def test_result_bounded(self):
        # Maximum possible: all categories active, all high-level
        scores = {cat: 10 for cat in CATEGORIES}
        result = compute_sophistication(scores)
        self.assertGreaterEqual(result, 0.0)
        self.assertLessEqual(result, 1.0)

    def test_unknown_categories_ignored(self):
        scores = {"nonexistent": 100, "agents": 3}
        result = compute_sophistication(scores)
        # Should still work, ignoring unknown category
        self.assertGreater(result, 0)

    def test_single_high_commit_not_100_percent(self):
        # Key improvement: single agent commit no longer scores 100%
        scores = {"agents": 3}
        result = compute_sophistication(scores)
        # Should be high ratio but low breadth
        self.assertLess(result, 0.85)


class TestSmoothSophistication(unittest.TestCase):
    """Tests for smooth_sophistication() — EMA smoothing."""

    def test_empty_input(self):
        self.assertEqual(smooth_sophistication([]), [])

    def test_single_value(self):
        self.assertEqual(smooth_sophistication([0.5]), [0.5])

    def test_constant_values(self):
        result = smooth_sophistication([0.5, 0.5, 0.5, 0.5])
        for v in result:
            self.assertAlmostEqual(v, 0.5, places=5)

    def test_smoothing_reduces_spike(self):
        # A noisy spike should be dampened
        raw = [0.1, 0.1, 0.9, 0.1, 0.1]
        smoothed = smooth_sophistication(raw)
        # The smoothed peak should be lower than the raw spike
        self.assertLess(max(smoothed), 0.9)
        # But still higher than the baseline
        self.assertGreater(max(smoothed), 0.1)

    def test_monotonic_input_preserved(self):
        raw = [0.1, 0.2, 0.3, 0.4, 0.5]
        smoothed = smooth_sophistication(raw)
        # Smoothed should still be monotonically increasing
        for i in range(1, len(smoothed)):
            self.assertGreaterEqual(smoothed[i], smoothed[i - 1])

    def test_custom_alpha(self):
        raw = [0.0, 1.0]
        high_alpha = smooth_sophistication(raw, alpha=0.9)
        low_alpha = smooth_sophistication(raw, alpha=0.1)
        # Higher alpha = more responsive to the jump
        self.assertGreater(high_alpha[1], low_alpha[1])

    def test_length_preserved(self):
        raw = [0.1, 0.2, 0.3, 0.4]
        self.assertEqual(len(smooth_sophistication(raw)), 4)


if __name__ == "__main__":
    unittest.main()
