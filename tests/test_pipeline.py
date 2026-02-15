"""Integration tests for aggregate_monthly(), aggregate_repo_stats(), and end-to-end pipeline."""

import datetime
import math
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scan import (
    aggregate_monthly, aggregate_repo_stats, fit_models,
    compute_sophistication, smooth_sophistication, logistic, CATEGORIES,
)


# ─── Helpers ──────────────────────────────────────────────────────────────

EPOCH = datetime.date(2025, 1, 1)


def _make_scored(date, total, cats, repo="repo-a", message="test commit",
                 hash_id="abc123"):
    """Build a scored commit tuple: (date, total, cats, message, repo, hash_id)."""
    return (date, total, cats, message, repo, hash_id)


def _logistic(t, L, r, t_mid):
    return L / (1.0 + math.exp(-r * (t - t_mid)))


# ─── TestAggregateMonthly ────────────────────────────────────────────────

class TestAggregateMonthly(unittest.TestCase):
    """Test the extracted aggregate_monthly() function."""

    def test_single_commit_one_month(self):
        scored = [_make_scored(datetime.date(2025, 1, 15), 10.0,
                               {"foundation": 5, "agents": 5})]
        end = datetime.date(2025, 1, 31)
        monthly, _, _ = aggregate_monthly(scored, EPOCH, end)
        self.assertEqual(len(monthly), 1)
        self.assertEqual(monthly[0]["commits"], 1)
        self.assertEqual(monthly[0]["cumulative_commits"], 1)
        self.assertEqual(monthly[0]["cumulative_capability"], 10)

    def test_two_commits_same_month_sum(self):
        scored = [
            _make_scored(datetime.date(2025, 1, 10), 10.0,
                         {"foundation": 5, "agents": 5}, hash_id="a1"),
            _make_scored(datetime.date(2025, 1, 20), 15.0,
                         {"foundation": 8, "agents": 7}, hash_id="a2"),
        ]
        end = datetime.date(2025, 1, 31)
        monthly, _, _ = aggregate_monthly(scored, EPOCH, end)
        self.assertEqual(monthly[0]["commits"], 2)
        self.assertEqual(monthly[0]["cumulative_capability"], 25)

    def test_cumulative_commits_monotonic(self):
        scored = [
            _make_scored(datetime.date(2025, 1, 10), 5.0, {"foundation": 5},
                         hash_id="a1"),
            _make_scored(datetime.date(2025, 2, 10), 8.0, {"agents": 8},
                         hash_id="a2"),
            _make_scored(datetime.date(2025, 3, 10), 3.0, {"meta": 3},
                         hash_id="a3"),
        ]
        end = datetime.date(2025, 3, 31)
        monthly, _, _ = aggregate_monthly(scored, EPOCH, end)
        prev = 0
        for m in monthly:
            self.assertGreaterEqual(m["cumulative_commits"], prev)
            prev = m["cumulative_commits"]

    def test_cumulative_capability_monotonic(self):
        scored = [
            _make_scored(datetime.date(2025, 1, 10), 5.0, {"foundation": 5},
                         hash_id="a1"),
            _make_scored(datetime.date(2025, 2, 10), 8.0, {"agents": 8},
                         hash_id="a2"),
        ]
        end = datetime.date(2025, 2, 28)
        monthly, _, _ = aggregate_monthly(scored, EPOCH, end)
        prev = 0
        for m in monthly:
            self.assertGreaterEqual(m["cumulative_capability"], prev)
            prev = m["cumulative_capability"]

    def test_empty_months_filled(self):
        """Months between epoch and first commit should have 0 commits."""
        scored = [_make_scored(datetime.date(2025, 3, 10), 10.0, {"agents": 10})]
        end = datetime.date(2025, 3, 31)
        monthly, _, _ = aggregate_monthly(scored, EPOCH, end)
        self.assertEqual(len(monthly), 3)
        self.assertEqual(monthly[0]["commits"], 0)
        self.assertEqual(monthly[1]["commits"], 0)
        self.assertEqual(monthly[2]["commits"], 1)

    def test_month_format(self):
        scored = [_make_scored(datetime.date(2025, 1, 15), 10.0, {"foundation": 10})]
        end = datetime.date(2025, 3, 31)
        monthly, _, _ = aggregate_monthly(scored, EPOCH, end)
        import re
        for m in monthly:
            self.assertRegex(m["month"], r"^\d{4}-\d{2}$")

    def test_capability_rounded(self):
        scored = [_make_scored(datetime.date(2025, 1, 15), 10.7, {"foundation": 10.7})]
        end = datetime.date(2025, 1, 31)
        monthly, _, _ = aggregate_monthly(scored, EPOCH, end)
        self.assertIsInstance(monthly[0]["capability"], int)
        self.assertIsInstance(monthly[0]["cumulative_capability"], int)

    def test_sophistication_bounded(self):
        scored = [
            _make_scored(datetime.date(2025, 1, 10), 5.0, {"foundation": 5},
                         hash_id="a1"),
            _make_scored(datetime.date(2025, 2, 10), 8.0, {"agents": 8},
                         hash_id="a2"),
            _make_scored(datetime.date(2025, 3, 10), 3.0, {"meta": 3},
                         hash_id="a3"),
        ]
        end = datetime.date(2025, 3, 31)
        monthly, _, _ = aggregate_monthly(scored, EPOCH, end)
        for m in monthly:
            self.assertGreaterEqual(m["sophistication"], 0)
            self.assertLessEqual(m["sophistication"], 1)

    def test_sophistication_ema_applied(self):
        """EMA smoothing should make values differ from raw compute_sophistication()."""
        scored = [
            _make_scored(datetime.date(2025, 1, 10), 5.0,
                         {"foundation": 5, "agents": 0}, hash_id="a1"),
            _make_scored(datetime.date(2025, 2, 10), 8.0,
                         {"agents": 8, "meta": 8}, hash_id="a2"),
        ]
        end = datetime.date(2025, 2, 28)
        monthly, _, _ = aggregate_monthly(scored, EPOCH, end)

        # Compute raw sophistication for month 2
        raw_soph_m2 = compute_sophistication({"agents": 8, "meta": 8})
        # After EMA, month 2 should differ from raw (unless alpha=1)
        if raw_soph_m2 > 0:
            # The smoothed value blends with month 1, so it won't equal raw
            raw_soph_m1 = compute_sophistication({"foundation": 5, "agents": 0})
            if abs(raw_soph_m1 - raw_soph_m2) > 0.01:
                self.assertNotAlmostEqual(monthly[1]["sophistication"],
                                          round(raw_soph_m2, 3), places=3)

    def test_multi_repo_merged_into_months(self):
        scored = [
            _make_scored(datetime.date(2025, 1, 10), 5.0, {"foundation": 5},
                         repo="repo-a", hash_id="a1"),
            _make_scored(datetime.date(2025, 1, 20), 10.0, {"agents": 10},
                         repo="repo-b", hash_id="b1"),
        ]
        end = datetime.date(2025, 1, 31)
        monthly, _, _ = aggregate_monthly(scored, EPOCH, end)
        self.assertEqual(monthly[0]["commits"], 2)
        self.assertEqual(monthly[0]["cumulative_capability"], 15)

    def test_category_monthly_populated(self):
        scored = [_make_scored(datetime.date(2025, 1, 15), 10.0,
                               {"foundation": 4, "agents": 6})]
        end = datetime.date(2025, 1, 31)
        _, _, cat_monthly = aggregate_monthly(scored, EPOCH, end)
        key = (2025, 1)
        self.assertIn(key, cat_monthly)
        self.assertEqual(cat_monthly[key]["foundation"], 4)
        self.assertEqual(cat_monthly[key]["agents"], 6)

    def test_dual_scoring_regex_data(self):
        scored = [_make_scored(datetime.date(2025, 1, 15), 10.0, {"agents": 10})]
        scored_regex = [_make_scored(datetime.date(2025, 1, 15), 5.0,
                                     {"foundation": 5})]
        end = datetime.date(2025, 1, 31)
        monthly, regex_monthly, _ = aggregate_monthly(
            scored, EPOCH, end, scored_regex=scored_regex
        )
        self.assertEqual(len(regex_monthly), 1)
        self.assertEqual(regex_monthly[0]["cumulative_capability"], 5)
        self.assertEqual(monthly[0]["cumulative_capability"], 10)


# ─── TestAggregateRepoStats ──────────────────────────────────────────────

class TestAggregateRepoStats(unittest.TestCase):
    """Test the extracted aggregate_repo_stats() function."""

    def test_single_repo(self):
        scored = [
            _make_scored(datetime.date(2025, 1, 10), 10.0, {"foundation": 10},
                         repo="/path/to/repo-a", hash_id="a1"),
            _make_scored(datetime.date(2025, 2, 10), 15.0, {"agents": 15},
                         repo="/path/to/repo-a", hash_id="a2"),
        ]
        result = aggregate_repo_stats(scored, 25.0)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["commits"], 2)
        self.assertEqual(result[0]["capability"], 25)

    def test_multi_repo_sorted_by_capability(self):
        scored = [
            _make_scored(datetime.date(2025, 1, 10), 5.0, {"foundation": 5},
                         repo="/path/to/small", hash_id="s1"),
            _make_scored(datetime.date(2025, 1, 10), 20.0, {"agents": 20},
                         repo="/path/to/big", hash_id="b1"),
        ]
        result = aggregate_repo_stats(scored, 25.0)
        self.assertEqual(len(result), 2)
        self.assertGreater(result[0]["capability"], result[1]["capability"])

    def test_pct_contribution_sums_near_100(self):
        scored = [
            _make_scored(datetime.date(2025, 1, 10), 30.0, {"foundation": 30},
                         repo="/path/to/a", hash_id="a1"),
            _make_scored(datetime.date(2025, 1, 10), 70.0, {"agents": 70},
                         repo="/path/to/b", hash_id="b1"),
        ]
        result = aggregate_repo_stats(scored, 100.0)
        total_pct = sum(r["pct_contribution"] for r in result)
        self.assertAlmostEqual(total_pct, 100.0, places=0)

    def test_top_categories_max_3(self):
        cats = {c: 1.0 for c in list(CATEGORIES.keys())[:5]}
        scored = [_make_scored(datetime.date(2025, 1, 10), 5.0, cats,
                               repo="/path/to/repo")]
        result = aggregate_repo_stats(scored, 5.0)
        self.assertLessEqual(len(result[0]["top_categories"]), 3)

    def test_top_categories_sorted(self):
        scored = [_make_scored(datetime.date(2025, 1, 10), 15.0,
                               {"foundation": 1, "agents": 10, "meta": 4},
                               repo="/path/to/repo")]
        result = aggregate_repo_stats(scored, 15.0)
        tops = result[0]["top_categories"]
        self.assertEqual(tops[0], "agents")
        self.assertEqual(tops[1], "meta")
        self.assertEqual(tops[2], "foundation")

    def test_date_range(self):
        scored = [
            _make_scored(datetime.date(2025, 1, 10), 5.0, {"foundation": 5},
                         repo="/path/to/repo", hash_id="a1"),
            _make_scored(datetime.date(2025, 3, 20), 5.0, {"agents": 5},
                         repo="/path/to/repo", hash_id="a2"),
        ]
        result = aggregate_repo_stats(scored, 10.0)
        self.assertLessEqual(result[0]["first_activity"],
                             result[0]["last_activity"])

    def test_capability_rounded(self):
        scored = [_make_scored(datetime.date(2025, 1, 10), 10.7,
                               {"foundation": 10.7}, repo="/path/to/repo")]
        result = aggregate_repo_stats(scored, 10.7)
        self.assertIsInstance(result[0]["capability"], int)

    def test_duplicate_basename_disambiguated(self):
        scored = [
            _make_scored(datetime.date(2025, 1, 10), 5.0, {"foundation": 5},
                         repo="/parent1/foo", hash_id="a1"),
            _make_scored(datetime.date(2025, 1, 10), 5.0, {"agents": 5},
                         repo="/parent2/foo", hash_id="b1"),
        ]
        result = aggregate_repo_stats(scored, 10.0)
        names = [r["name"] for r in result]
        self.assertEqual(len(set(names)), 2, "Names should be unique")
        # Both should contain "foo" and a parent disambiguator
        for name in names:
            self.assertIn("foo", name)

    def test_empty_scored_list(self):
        result = aggregate_repo_stats([], 100.0)
        self.assertEqual(result, [])

    def test_zero_total_cap(self):
        scored = [_make_scored(datetime.date(2025, 1, 10), 0.0, {},
                               repo="/path/to/repo")]
        result = aggregate_repo_stats(scored, 0)
        self.assertEqual(result[0]["pct_contribution"], 0)


# ─── TestEndToEnd ────────────────────────────────────────────────────────

class TestEndToEnd(unittest.TestCase):
    """Full pipeline: scored commits → aggregate_monthly → fit_models."""

    @staticmethod
    def _make_pipeline_data(n_months=12, cap_multiplier=1.0):
        """Generate scored commits that produce nice logistic curves."""
        scored = []
        for t in range(n_months):
            month_date = EPOCH + datetime.timedelta(days=t * 30.44)
            commit_date = month_date + datetime.timedelta(days=5)

            # Number of commits per month following rough logistic growth
            n_commits = max(1, round(5 + 10 / (1 + math.exp(-0.5 * (t - 4)))))
            for i in range(n_commits):
                d = commit_date + datetime.timedelta(days=i)
                # Mix of categories for realistic sophistication
                if t < 4:
                    cats = {"foundation": 3 * cap_multiplier,
                            "elements": 2 * cap_multiplier}
                else:
                    cats = {"agents": 4 * cap_multiplier,
                            "meta": 3 * cap_multiplier,
                            "self_modify": 2 * cap_multiplier}
                total = sum(cats.values())
                scored.append(_make_scored(d, total, cats,
                                           hash_id=f"h{t}-{i}"))
        return scored

    @patch("builtins.print")
    def test_full_pipeline_produces_convergence(self, mock_print):
        scored = self._make_pipeline_data()
        end = EPOCH + datetime.timedelta(days=12 * 30.44)
        monthly, _, _ = aggregate_monthly(scored, EPOCH, end)
        models = fit_models(monthly, EPOCH)
        self.assertIn("convergence_date", models)

    @patch("builtins.print")
    def test_pipeline_deterministic(self, mock_print):
        scored = self._make_pipeline_data()
        end = EPOCH + datetime.timedelta(days=12 * 30.44)

        monthly1, _, _ = aggregate_monthly(scored, EPOCH, end)
        models1 = fit_models(monthly1, EPOCH)

        monthly2, _, _ = aggregate_monthly(scored, EPOCH, end)
        models2 = fit_models(monthly2, EPOCH)

        self.assertEqual(models1, models2)

    @patch("builtins.print")
    def test_monthly_keys_complete(self, mock_print):
        scored = self._make_pipeline_data()
        end = EPOCH + datetime.timedelta(days=12 * 30.44)
        monthly, _, _ = aggregate_monthly(scored, EPOCH, end)
        required = {"month", "commits", "capability", "sophistication",
                     "cumulative_commits", "cumulative_capability"}
        for m in monthly:
            self.assertEqual(set(m.keys()), required)

    @patch("builtins.print")
    def test_models_keys_complete(self, mock_print):
        scored = self._make_pipeline_data()
        end = EPOCH + datetime.timedelta(days=12 * 30.44)
        monthly, _, _ = aggregate_monthly(scored, EPOCH, end)
        models = fit_models(monthly, EPOCH)
        for key in ("commit_rate", "capability", "sophistication",
                     "convergence_date"):
            self.assertIn(key, models)

    @patch("builtins.print")
    def test_capability_model_keys(self, mock_print):
        scored = self._make_pipeline_data()
        end = EPOCH + datetime.timedelta(days=12 * 30.44)
        monthly, _, _ = aggregate_monthly(scored, EPOCH, end)
        models = fit_models(monthly, EPOCH)
        cap = models["capability"]
        for key in ("L", "r", "t_mid", "r_squared", "pct_95_date",
                     "pct_99_date", "pct_now", "projection"):
            self.assertIn(key, cap)

    @patch("builtins.print")
    def test_commit_rate_model_keys(self, mock_print):
        scored = self._make_pipeline_data()
        end = EPOCH + datetime.timedelta(days=12 * 30.44)
        monthly, _, _ = aggregate_monthly(scored, EPOCH, end)
        models = fit_models(monthly, EPOCH)
        cr = models["commit_rate"]
        for key in ("L", "r", "t_mid", "r_squared", "zero_date", "projection"):
            self.assertIn(key, cr)

    @patch("builtins.print")
    def test_projection_entry_keys(self, mock_print):
        scored = self._make_pipeline_data()
        end = EPOCH + datetime.timedelta(days=12 * 30.44)
        monthly, _, _ = aggregate_monthly(scored, EPOCH, end)
        models = fit_models(monthly, EPOCH)

        for entry in models["commit_rate"]["projection"]:
            self.assertIn("month", entry)
            self.assertIn("predicted_commits", entry)

        for entry in models["capability"]["projection"]:
            self.assertIn("month", entry)
            self.assertIn("predicted_capability", entry)
            self.assertIn("pct_of_L", entry)

    @patch("builtins.print")
    def test_more_advanced_commits_earlier_convergence(self, mock_print):
        """Higher-weight commits should produce an earlier convergence date."""
        scored_low = self._make_pipeline_data(cap_multiplier=1.0)
        scored_high = self._make_pipeline_data(cap_multiplier=3.0)
        end = EPOCH + datetime.timedelta(days=12 * 30.44)

        monthly_low, _, _ = aggregate_monthly(scored_low, EPOCH, end)
        monthly_high, _, _ = aggregate_monthly(scored_high, EPOCH, end)

        models_low = fit_models(monthly_low, EPOCH)
        models_high = fit_models(monthly_high, EPOCH)

        if "convergence_date" in models_low and "convergence_date" in models_high:
            conv_low = datetime.date.fromisoformat(models_low["convergence_date"])
            conv_high = datetime.date.fromisoformat(models_high["convergence_date"])
            # Higher capability should converge no later
            self.assertLessEqual(conv_high, conv_low)


if __name__ == "__main__":
    unittest.main()
