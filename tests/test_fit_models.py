"""Integration tests for fit_models() with synthetic data from known logistic parameters."""

import datetime
import math
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scan import fit_models, logistic, logistic_deriv, linreg


# ─── Helpers ──────────────────────────────────────────────────────────────

def _logistic(t, L, r, t_mid):
    """Pure logistic for generating synthetic data (no clamping)."""
    return L / (1.0 + math.exp(-r * (t - t_mid)))


def _make_monthly_data(n_months, commit_L, commit_r, commit_tmid,
                       cap_L, cap_r, cap_tmid,
                       soph_slope, soph_intercept,
                       epoch_date=None):
    """Generate synthetic monthly_data from known logistic/linear parameters.

    All cumulative values follow logistic curves so fit_models() can recover
    the original parameters. Sophistication follows a linear trend.
    """
    if epoch_date is None:
        epoch_date = datetime.date(2025, 1, 1)

    data = []
    prev_cum_commits = 0
    prev_cum_cap = 0

    for t in range(n_months):
        cum_commits = round(_logistic(t, commit_L, commit_r, commit_tmid))
        cum_cap = round(_logistic(t, cap_L, cap_r, cap_tmid))

        commits = max(0, cum_commits - prev_cum_commits)
        cap = max(0, cum_cap - prev_cum_cap)

        soph = max(0.0, min(1.0, soph_intercept + soph_slope * t))

        month_date = epoch_date + datetime.timedelta(days=t * 30.44)
        data.append({
            "month": month_date.strftime("%Y-%m"),
            "commits": commits,
            "capability": cap,
            "sophistication": round(soph, 3),
            "cumulative_commits": cum_commits,
            "cumulative_capability": cum_cap,
        })

        prev_cum_commits = cum_commits
        prev_cum_cap = cum_cap

    return data


# Standard parameters chosen to fall on grid points
EPOCH = datetime.date(2025, 1, 1)
COMMIT_L, COMMIT_R, COMMIT_TMID = 100, 0.8, 4.0
CAP_L, CAP_R, CAP_TMID = 250, 0.6, 4.0
SOPH_SLOPE, SOPH_INTERCEPT = 0.05, 0.15


def _standard_monthly_data(n_months=12):
    return _make_monthly_data(
        n_months, COMMIT_L, COMMIT_R, COMMIT_TMID,
        CAP_L, CAP_R, CAP_TMID,
        SOPH_SLOPE, SOPH_INTERCEPT, EPOCH,
    )


@patch("builtins.print")
class TestFitModelsKeys(unittest.TestCase):
    """Test that fit_models returns correctly structured output."""

    def test_returns_all_model_keys(self, mock_print):
        data = _standard_monthly_data()
        models = fit_models(data, EPOCH)
        for key in ("commit_rate", "capability", "sophistication", "convergence_date"):
            self.assertIn(key, models, f"Missing key: {key}")

    def test_commit_rate_has_expected_keys(self, mock_print):
        data = _standard_monthly_data()
        models = fit_models(data, EPOCH)
        cr = models["commit_rate"]
        for key in ("L", "r", "t_mid", "r_squared", "zero_date", "projection"):
            self.assertIn(key, cr, f"commit_rate missing: {key}")

    def test_capability_has_expected_keys(self, mock_print):
        data = _standard_monthly_data()
        models = fit_models(data, EPOCH)
        cap = models["capability"]
        for key in ("L", "r", "t_mid", "r_squared", "pct_95_date",
                     "pct_99_date", "pct_now", "projection"):
            self.assertIn(key, cap, f"capability missing: {key}")

    def test_sophistication_has_expected_keys(self, mock_print):
        data = _standard_monthly_data()
        models = fit_models(data, EPOCH)
        soph = models["sophistication"]
        for key in ("slope", "intercept", "pct_100_date"):
            self.assertIn(key, soph, f"sophistication missing: {key}")


@patch("builtins.print")
class TestFitModelsCommitRate(unittest.TestCase):
    """Test commit rate model recovery from clean logistic data."""

    def test_r_squared_high(self, mock_print):
        data = _standard_monthly_data()
        models = fit_models(data, EPOCH)
        self.assertGreater(models["commit_rate"]["r_squared"], 0.90)

    def test_L_recoverable(self, mock_print):
        data = _standard_monthly_data()
        models = fit_models(data, EPOCH)
        recovered_L = models["commit_rate"]["L"]
        self.assertAlmostEqual(recovered_L, COMMIT_L, delta=COMMIT_L * 0.3,
                               msg=f"L={recovered_L}, expected ~{COMMIT_L}")

    def test_zero_date_exists(self, mock_print):
        data = _standard_monthly_data()
        models = fit_models(data, EPOCH)
        zd = models["commit_rate"]["zero_date"]
        self.assertIsNotNone(zd)
        datetime.date.fromisoformat(zd)  # Should not raise

    def test_projection_12_months(self, mock_print):
        data = _standard_monthly_data()
        models = fit_models(data, EPOCH)
        self.assertEqual(len(models["commit_rate"]["projection"]), 12)

    def test_projection_months_after_data(self, mock_print):
        data = _standard_monthly_data()
        models = fit_models(data, EPOCH)
        last_data_month = data[-1]["month"]
        first_proj_month = models["commit_rate"]["projection"][0]["month"]
        self.assertGreater(first_proj_month, last_data_month)


@patch("builtins.print")
class TestFitModelsCapability(unittest.TestCase):
    """Test capability model recovery."""

    def test_r_squared_high(self, mock_print):
        data = _standard_monthly_data()
        models = fit_models(data, EPOCH)
        self.assertGreater(models["capability"]["r_squared"], 0.90)

    def test_milestones_ordered(self, mock_print):
        data = _standard_monthly_data()
        models = fit_models(data, EPOCH)
        d95 = models["capability"]["pct_95_date"]
        d99 = models["capability"]["pct_99_date"]
        self.assertLess(d95, d99)

    def test_pct_now_reasonable(self, mock_print):
        data = _standard_monthly_data()
        models = fit_models(data, EPOCH)
        pct = models["capability"]["pct_now"]
        self.assertGreater(pct, 30)
        self.assertLessEqual(pct, 100)

    def test_projection_has_pct(self, mock_print):
        data = _standard_monthly_data()
        models = fit_models(data, EPOCH)
        for entry in models["capability"]["projection"]:
            self.assertIn("pct_of_L", entry)
            self.assertIn("predicted_capability", entry)


@patch("builtins.print")
class TestFitModelsSophistication(unittest.TestCase):
    """Test sophistication linear model."""

    def test_slope_positive(self, mock_print):
        data = _standard_monthly_data()
        models = fit_models(data, EPOCH)
        self.assertGreater(models["sophistication"]["slope"], 0)

    def test_pct100_date_valid(self, mock_print):
        data = _standard_monthly_data()
        models = fit_models(data, EPOCH)
        d = models["sophistication"]["pct_100_date"]
        datetime.date.fromisoformat(d)  # Should not raise

    def test_pct100_hand_calculated(self, mock_print):
        """Verify pct_100_date matches hand calculation within 45 days."""
        data = _standard_monthly_data()
        models = fit_models(data, EPOCH)

        # Hand-calculate: the sophistication data in monthly_data is
        # soph_intercept + soph_slope * t, so linreg should recover these.
        # pct100_t = (1.0 - intercept) / slope
        intercept = models["sophistication"]["intercept"]
        slope = models["sophistication"]["slope"]
        expected_t = (1.0 - intercept) / slope
        expected_date = EPOCH + datetime.timedelta(days=expected_t * 30.44)
        actual_date = datetime.date.fromisoformat(models["sophistication"]["pct_100_date"])
        delta = abs((actual_date - expected_date).days)
        self.assertLessEqual(delta, 45, f"pct_100_date off by {delta} days")


@patch("builtins.print")
class TestFitModelsConvergence(unittest.TestCase):
    """Test convergence date calculation."""

    def test_convergence_date_is_component_average(self, mock_print):
        data = _standard_monthly_data()
        models = fit_models(data, EPOCH)

        dates = []
        if models["commit_rate"]["zero_date"]:
            dates.append(datetime.date.fromisoformat(models["commit_rate"]["zero_date"]))
        dates.append(datetime.date.fromisoformat(models["capability"]["pct_95_date"]))
        dates.append(datetime.date.fromisoformat(models["capability"]["pct_99_date"]))
        dates.append(datetime.date.fromisoformat(models["sophistication"]["pct_100_date"]))

        expected_ord = sum(d.toordinal() for d in dates) // len(dates)
        expected = datetime.date.fromordinal(expected_ord)
        actual = datetime.date.fromisoformat(models["convergence_date"])
        self.assertEqual(actual, expected)

    def test_convergence_date_after_epoch(self, mock_print):
        data = _standard_monthly_data()
        models = fit_models(data, EPOCH)
        conv = datetime.date.fromisoformat(models["convergence_date"])
        self.assertGreater(conv, EPOCH)


@patch("builtins.print")
class TestFitModelsEdgeCases(unittest.TestCase):
    """Test edge cases and degenerate inputs."""

    def test_empty_monthly_data(self, mock_print):
        models = fit_models([], EPOCH)
        self.assertEqual(models, {})

    def test_single_month(self, mock_print):
        data = _standard_monthly_data(n_months=1)
        models = fit_models(data, EPOCH)
        # Should not crash; may produce partial or empty models
        self.assertIsInstance(models, dict)

    def test_three_months_minimal(self, mock_print):
        data = _standard_monthly_data(n_months=3)
        models = fit_models(data, EPOCH)
        self.assertIsInstance(models, dict)

    def test_flat_commits(self, mock_print):
        """Constant cumulative commits should produce poor fit or degenerate."""
        data = []
        for t in range(12):
            month_date = EPOCH + datetime.timedelta(days=t * 30.44)
            data.append({
                "month": month_date.strftime("%Y-%m"),
                "commits": 0 if t > 0 else 10,
                "capability": 0 if t > 0 else 50,
                "sophistication": 0.5,
                "cumulative_commits": 10,
                "cumulative_capability": 50,
            })
        models = fit_models(data, EPOCH)
        # With flat cumulative data, R² should be low or model may not fit well
        if "commit_rate" in models:
            # Any R² is acceptable; just shouldn't crash
            self.assertIsInstance(models["commit_rate"]["r_squared"], (int, float))

    def test_all_dates_iso_format(self, mock_print):
        data = _standard_monthly_data()
        models = fit_models(data, EPOCH)

        # Check all date-like string values parse as ISO dates
        date_keys = {
            ("commit_rate", "zero_date"),
            ("capability", "pct_95_date"),
            ("capability", "pct_99_date"),
            ("sophistication", "pct_100_date"),
        }
        for section, key in date_keys:
            if section in models:
                val = models[section][key]
                if val is not None:
                    datetime.date.fromisoformat(val)

        if "convergence_date" in models:
            datetime.date.fromisoformat(models["convergence_date"])


if __name__ == "__main__":
    unittest.main()
