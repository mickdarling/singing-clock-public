"""Tests for diffstat weighting functions."""

import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scan import (
    apply_diffstat_weight,
    LARGE_SOURCE_THRESHOLD,
    MEDIUM_SOURCE_THRESHOLD,
    LARGE_SOURCE_BONUS,
    MEDIUM_SOURCE_BONUS,
    MAJOR_NEW_FILES_THRESHOLD,
    MINOR_NEW_FILES_THRESHOLD,
    MAJOR_NEW_FILES_BONUS,
    MINOR_NEW_FILES_BONUS,
    CONFIG_ONLY_MULTIPLIER,
    DELETION_HEAVY_THRESHOLD,
    DELETION_HEAVY_MULTIPLIER,
    MULTIPLIER_FLOOR,
    MULTIPLIER_CEILING,
    TEST_LINES_THRESHOLD,
    TEST_SAFETY_BONUS,
)


class TestApplyDiffstatWeight(unittest.TestCase):
    """Tests for apply_diffstat_weight() — diffstat-based score adjustment."""

    def test_null_diffstat_passthrough(self):
        total, cats = apply_diffstat_weight(10.0, {"agents": 6}, None)
        self.assertEqual(total, 10.0)
        self.assertEqual(cats, {"agents": 6})

    def test_empty_diffstat_passthrough(self):
        total, cats = apply_diffstat_weight(10.0, {"agents": 6}, {})
        # Empty dict is truthy, so multiplier=1.0, total stays 10.0
        self.assertAlmostEqual(total, 10.0)

    def test_large_source_bonus(self):
        diffstat = {"s": LARGE_SOURCE_THRESHOLD, "a": LARGE_SOURCE_THRESHOLD, "d": 0, "n": 0, "t": 0, "c": 0}
        total, _ = apply_diffstat_weight(10.0, {}, diffstat)
        expected = 10.0 * (1.0 + LARGE_SOURCE_BONUS)
        self.assertAlmostEqual(total, expected)

    def test_medium_source_bonus(self):
        diffstat = {"s": MEDIUM_SOURCE_THRESHOLD, "a": MEDIUM_SOURCE_THRESHOLD, "d": 0, "n": 0, "t": 0, "c": 0}
        total, _ = apply_diffstat_weight(10.0, {}, diffstat)
        expected = 10.0 * (1.0 + MEDIUM_SOURCE_BONUS)
        self.assertAlmostEqual(total, expected)

    def test_below_medium_no_bonus(self):
        diffstat = {"s": MEDIUM_SOURCE_THRESHOLD - 1, "a": 10, "d": 0, "n": 0, "t": 0, "c": 0}
        total, _ = apply_diffstat_weight(10.0, {}, diffstat)
        self.assertAlmostEqual(total, 10.0)

    def test_config_only_dampening(self):
        diffstat = {"s": 0, "t": 0, "c": 20, "a": 20, "d": 0, "n": 0}
        total, _ = apply_diffstat_weight(10.0, {}, diffstat)
        expected = 10.0 * CONFIG_ONLY_MULTIPLIER
        self.assertAlmostEqual(total, expected)

    def test_config_with_source_no_dampening(self):
        diffstat = {"s": 10, "t": 0, "c": 20, "a": 30, "d": 0, "n": 0}
        total, _ = apply_diffstat_weight(10.0, {}, diffstat)
        # Has source, so config-only rule doesn't apply
        self.assertAlmostEqual(total, 10.0)

    def test_major_new_files_bonus(self):
        diffstat = {"s": 0, "a": 0, "d": 0, "n": MAJOR_NEW_FILES_THRESHOLD, "t": 0, "c": 0}
        total, _ = apply_diffstat_weight(10.0, {}, diffstat)
        expected = 10.0 * (1.0 + MAJOR_NEW_FILES_BONUS)
        self.assertAlmostEqual(total, expected)

    def test_minor_new_files_bonus(self):
        diffstat = {"s": 0, "a": 0, "d": 0, "n": MINOR_NEW_FILES_THRESHOLD, "t": 0, "c": 0}
        total, _ = apply_diffstat_weight(10.0, {}, diffstat)
        expected = 10.0 * (1.0 + MINOR_NEW_FILES_BONUS)
        self.assertAlmostEqual(total, expected)

    def test_deletion_heavy_dampening(self):
        dels = DELETION_HEAVY_THRESHOLD + 10
        diffstat = {"s": 0, "a": 5, "d": dels, "n": 0, "t": 0, "c": 0}
        total, _ = apply_diffstat_weight(10.0, {}, diffstat)
        expected = 10.0 * DELETION_HEAVY_MULTIPLIER
        self.assertAlmostEqual(total, expected)

    def test_deletion_not_heavy_when_adds_exceed(self):
        diffstat = {"s": 0, "a": 100, "d": 60, "n": 0, "t": 0, "c": 0}
        total, _ = apply_diffstat_weight(10.0, {}, diffstat)
        # dels < adds, so no dampening
        self.assertAlmostEqual(total, 10.0)

    def test_multiplier_ceiling_clamp(self):
        # Combine all bonuses to exceed ceiling
        diffstat = {
            "s": LARGE_SOURCE_THRESHOLD + 100,
            "a": 500, "d": 0,
            "n": MAJOR_NEW_FILES_THRESHOLD + 5,
            "t": 0, "c": 0,
        }
        total, _ = apply_diffstat_weight(10.0, {}, diffstat)
        max_total = 10.0 * MULTIPLIER_CEILING
        self.assertLessEqual(total, max_total)

    def test_multiplier_floor_clamp(self):
        # Config-only + deletion-heavy to push below floor
        diffstat = {"s": 0, "t": 0, "c": 10, "a": 5, "d": 100, "n": 0}
        total, _ = apply_diffstat_weight(10.0, {}, diffstat)
        min_total = 10.0 * MULTIPLIER_FLOOR
        self.assertGreaterEqual(total, min_total)

    def test_score_floor_half(self):
        # Even with heavy dampening, score should not go below 0.5
        diffstat = {"s": 0, "t": 0, "c": 10, "a": 1, "d": 100, "n": 0}
        total, _ = apply_diffstat_weight(0.5, {}, diffstat)
        self.assertGreaterEqual(total, 0.5)

    def test_test_lines_safety_bonus(self):
        diffstat = {"s": 0, "a": 0, "d": 0, "n": 0, "t": TEST_LINES_THRESHOLD, "c": 0}
        _, cats = apply_diffstat_weight(10.0, {}, diffstat)
        self.assertEqual(cats.get("safety", 0), TEST_SAFETY_BONUS)

    def test_test_lines_safety_additive(self):
        diffstat = {"s": 0, "a": 0, "d": 0, "n": 0, "t": TEST_LINES_THRESHOLD, "c": 0}
        _, cats = apply_diffstat_weight(10.0, {"safety": 4}, diffstat)
        self.assertEqual(cats["safety"], 4 + TEST_SAFETY_BONUS)

    def test_test_lines_below_threshold_no_bonus(self):
        diffstat = {"s": 0, "a": 0, "d": 0, "n": 0, "t": TEST_LINES_THRESHOLD - 1, "c": 0}
        _, cats = apply_diffstat_weight(10.0, {}, diffstat)
        self.assertNotIn("safety", cats)

    def test_cats_dict_not_mutated(self):
        original = {"agents": 6}
        diffstat = {"s": 0, "a": 0, "d": 0, "n": 0, "t": TEST_LINES_THRESHOLD, "c": 0}
        _, new_cats = apply_diffstat_weight(10.0, original, diffstat)
        # Original should not have safety added
        self.assertNotIn("safety", original)
        # New cats should
        self.assertIn("safety", new_cats)


if __name__ == "__main__":
    unittest.main()
