"""Tests for math helpers and model fitting functions."""

import unittest
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scan import linreg, r_squared, logistic, logistic_deriv, fit_logistic


class TestLinreg(unittest.TestCase):
    """Tests for linreg() — linear regression."""

    def test_perfect_line(self):
        x = [1, 2, 3, 4, 5]
        y = [2, 4, 6, 8, 10]  # y = 2x
        a, b = linreg(x, y)
        self.assertAlmostEqual(b, 2.0, places=5)
        self.assertAlmostEqual(a, 0.0, places=5)

    def test_with_intercept(self):
        x = [0, 1, 2, 3]
        y = [3, 5, 7, 9]  # y = 2x + 3
        a, b = linreg(x, y)
        self.assertAlmostEqual(b, 2.0, places=5)
        self.assertAlmostEqual(a, 3.0, places=5)

    def test_single_point(self):
        a, b = linreg([1], [5])
        self.assertEqual(a, 0)
        self.assertEqual(b, 0)

    def test_empty_input(self):
        a, b = linreg([], [])
        self.assertEqual(a, 0)
        self.assertEqual(b, 0)

    def test_constant_y(self):
        x = [1, 2, 3]
        y = [5, 5, 5]
        a, b = linreg(x, y)
        self.assertAlmostEqual(b, 0.0, places=5)
        self.assertAlmostEqual(a, 5.0, places=5)

    def test_negative_slope(self):
        x = [0, 1, 2, 3]
        y = [10, 7, 4, 1]  # y = -3x + 10
        a, b = linreg(x, y)
        self.assertAlmostEqual(b, -3.0, places=5)
        self.assertAlmostEqual(a, 10.0, places=5)


class TestRSquared(unittest.TestCase):
    """Tests for r_squared() — coefficient of determination."""

    def test_perfect_fit(self):
        y = [1, 2, 3, 4, 5]
        r2 = r_squared(y, y)
        self.assertAlmostEqual(r2, 1.0, places=5)

    def test_poor_fit(self):
        y_actual = [1, 2, 3, 4, 5]
        y_pred = [5, 4, 3, 2, 1]
        r2 = r_squared(y_actual, y_pred)
        self.assertLess(r2, 0.5)

    def test_constant_actual(self):
        y_actual = [5, 5, 5]
        y_pred = [5, 5, 5]
        r2 = r_squared(y_actual, y_pred)
        # ss_tot is 0, returns 0
        self.assertEqual(r2, 0)

    def test_moderate_fit(self):
        y_actual = [1, 2, 3, 4, 5]
        y_pred = [1.1, 1.9, 3.2, 3.8, 5.1]
        r2 = r_squared(y_actual, y_pred)
        self.assertGreater(r2, 0.9)


class TestLogistic(unittest.TestCase):
    """Tests for logistic() — logistic function with overflow guards."""

    def test_midpoint(self):
        # At t=t_mid, logistic = L/2
        result = logistic(5.0, L=100, r=1.0, t_mid=5.0)
        self.assertAlmostEqual(result, 50.0, places=3)

    def test_large_positive_overflow(self):
        # r*(t-t_mid) > 50 should return L
        result = logistic(100.0, L=100, r=1.0, t_mid=0.0)
        self.assertEqual(result, 100)

    def test_large_negative_overflow(self):
        # r*(t-t_mid) < -50 should return 0
        result = logistic(-100.0, L=100, r=1.0, t_mid=0.0)
        self.assertEqual(result, 0.0)

    def test_asymptotic_approach(self):
        # Far past midpoint should approach L
        result = logistic(20.0, L=100, r=1.0, t_mid=5.0)
        self.assertGreater(result, 99.0)

    def test_early_phase(self):
        # Well before midpoint should be near 0
        result = logistic(-10.0, L=100, r=1.0, t_mid=5.0)
        self.assertLess(result, 1.0)


class TestLogisticDeriv(unittest.TestCase):
    """Tests for logistic_deriv() — logistic derivative."""

    def test_peak_at_midpoint(self):
        # Derivative is maximum at t_mid
        deriv_mid = logistic_deriv(5.0, L=100, r=1.0, t_mid=5.0)
        deriv_off = logistic_deriv(8.0, L=100, r=1.0, t_mid=5.0)
        self.assertGreater(deriv_mid, deriv_off)

    def test_overflow_returns_zero(self):
        result = logistic_deriv(100.0, L=100, r=1.0, t_mid=0.0)
        self.assertEqual(result, 0.0)

    def test_underflow_returns_zero(self):
        result = logistic_deriv(-100.0, L=100, r=1.0, t_mid=0.0)
        self.assertEqual(result, 0.0)

    def test_positive_derivative(self):
        result = logistic_deriv(5.0, L=100, r=1.0, t_mid=5.0)
        self.assertGreater(result, 0)


class TestFitLogistic(unittest.TestCase):
    """Tests for fit_logistic() — grid search logistic fitting."""

    def test_known_curve(self):
        # Generate data from known logistic
        L, r, tmid = 100, 0.5, 5.0
        t_values = list(range(12))
        y_values = [logistic(t, L, r, tmid) for t in t_values]

        result = fit_logistic(
            t_values, y_values,
            L_range=range(90, 120, 5),
            r_range=range(3, 8),  # r/10 = 0.3 to 0.7
            tmid_range=range(30, 70),  # tmid/10 = 3.0 to 6.9
        )
        self.assertIsNotNone(result)
        r2, fit_L, fit_r, fit_tmid = result
        self.assertGreater(r2, 0.95)

    def test_returns_none_for_empty(self):
        # Empty ranges produce no iterations
        result = fit_logistic([], [], range(0), range(0), range(0))
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
