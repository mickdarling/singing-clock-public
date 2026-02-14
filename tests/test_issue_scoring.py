"""Tests for issue impact scoring functions."""

import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scan import score_issue, estimate_convergence_impact


class TestScoreIssue(unittest.TestCase):
    """Tests for score_issue() — regex scoring of issue title + body."""

    def test_empty_title(self):
        total, cats = score_issue("")
        self.assertEqual(total, 0.5)
        self.assertEqual(cats, {})

    def test_agent_issue(self):
        total, cats = score_issue("Implement agent execution loop")
        self.assertIn("agents", cats)
        self.assertGreater(total, 0.5)

    def test_foundation_issue(self):
        total, cats = score_issue("Initial setup and scaffold the project structure")
        self.assertIn("foundation", cats)
        self.assertGreater(total, 0.5)

    def test_multi_category_issue(self):
        total, cats = score_issue(
            "Add self-modify capabilities to the agent execution system",
            body="This involves creating runtime agent instances with introspect support"
        )
        # Should match agents, self_modify, meta
        self.assertGreater(len(cats), 1)
        self.assertGreater(total, 3)

    def test_body_contributes_to_score(self):
        title_only, _ = score_issue("Generic task update")
        with_body, _ = score_issue(
            "Generic task update",
            body="Implement agent execution with self-modify and introspect capabilities"
        )
        self.assertGreater(with_body, title_only)

    def test_no_match_gets_floor(self):
        total, cats = score_issue("Fix typo in readme")
        self.assertEqual(total, 0.5)
        self.assertEqual(cats, {})

    def test_safety_issue(self):
        total, cats = score_issue("Add input validation and security sanitization")
        self.assertIn("safety", cats)

    def test_ecosystem_issue(self):
        total, cats = score_issue("Add collection browsing and portfolio sync")
        self.assertIn("ecosystem", cats)


class TestEstimateConvergenceImpact(unittest.TestCase):
    """Tests for estimate_convergence_impact()."""

    def test_no_model_returns_zero(self):
        impact = estimate_convergence_impact(10, {})
        self.assertEqual(impact, 0.0)

    def test_positive_score_negative_impact(self):
        """Higher score should move convergence closer (negative days)."""
        models = {
            "capability": {"L": 1000, "r": 0.6, "t_mid": 5.0, "pct_now": 50.0}
        }
        impact = estimate_convergence_impact(20, models)
        self.assertLess(impact, 0)

    def test_higher_score_more_impact(self):
        """A higher projected score should have more impact."""
        models = {
            "capability": {"L": 1000, "r": 0.6, "t_mid": 5.0, "pct_now": 50.0}
        }
        impact_low = estimate_convergence_impact(5, models)
        impact_high = estimate_convergence_impact(20, models)
        self.assertLess(impact_high, impact_low)  # more negative = more impact

    def test_near_saturation_more_time_impact(self):
        """Near saturation, growth is slow so each point saves more days."""
        models_mid = {
            "capability": {"L": 1000, "r": 0.6, "t_mid": 5.0, "pct_now": 50.0}
        }
        models_high = {
            "capability": {"L": 1000, "r": 0.6, "t_mid": 5.0, "pct_now": 95.0}
        }
        impact_mid = estimate_convergence_impact(10, models_mid)
        impact_high = estimate_convergence_impact(10, models_high)
        # Near saturation, growth is slow so same score saves MORE days
        self.assertLess(impact_high, impact_mid)

    def test_zero_score_zero_impact(self):
        models = {
            "capability": {"L": 1000, "r": 0.6, "t_mid": 5.0, "pct_now": 50.0}
        }
        impact = estimate_convergence_impact(0, models)
        self.assertEqual(impact, 0.0)

    def test_missing_L_returns_zero(self):
        models = {"capability": {"L": 0, "r": 0.6, "t_mid": 5.0, "pct_now": 50.0}}
        impact = estimate_convergence_impact(10, models)
        self.assertEqual(impact, 0.0)


if __name__ == "__main__":
    unittest.main()
