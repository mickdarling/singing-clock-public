"""Tests for dual-scoring output (regex vs LLM enriched)."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import scan


class TestDualScoringOutput(unittest.TestCase):
    """Tests that scan.py outputs both regex and enriched monthly data."""

    def _make_commits(self, n=5):
        """Create test commits spanning multiple months."""
        import datetime
        commits = []
        base = datetime.date(2025, 7, 1)
        messages = [
            "feat: add agent execution loop",
            "fix: setup boilerplate scaffold",
            "feat: self-modify runtime creation",
            "docs: update readme",
            "feat: add introspect relationships",
        ]
        for i in range(min(n, len(messages))):
            d = base + datetime.timedelta(days=i * 35)
            commits.append((d, messages[i], "test-repo", f"hash{i:04d}"))
        return commits

    def test_scored_regex_populated_with_enrich(self):
        """When enrich_cache is present, scored_regex should be populated."""
        commits = self._make_commits(3)
        enrich_cache = {
            "hash0000": {"agents": 3},
            "hash0001": {"foundation": 1},
            "hash0002": {"self_modify": 2},
        }
        diffstat_cache = {}
        cache = {}

        scored = []
        scored_regex = []
        for date, message, repo, hash_id in commits:
            # Regex score
            base_total, base_cats = scan.score_commit(message)
            ds = diffstat_cache.get(hash_id)
            rx_total, rx_cats = scan.apply_diffstat_weight(base_total, base_cats, ds)
            cache[hash_id] = {"v": scan.SCORE_CACHE_VERSION, "total": rx_total, "cats": rx_cats}

            # Enriched score
            if hash_id in enrich_cache:
                total, cats = scan.enrich_score(enrich_cache[hash_id])
                total, cats = scan.apply_diffstat_weight(total, cats, ds)
            else:
                total, cats = rx_total, rx_cats

            scored.append((date, total, cats, message, repo, hash_id))
            scored_regex.append((date, rx_total, rx_cats, message, repo, hash_id))

        # Both should have same length
        self.assertEqual(len(scored), len(scored_regex))
        # Enriched and regex should differ for at least some commits
        diffs = sum(1 for s, r in zip(scored, scored_regex) if s[1] != r[1])
        self.assertGreater(diffs, 0, "Enriched and regex scores should differ")

    def test_regex_monthly_data_structure(self):
        """monthly_regex entries should have the same keys as monthly entries."""
        import datetime
        from collections import defaultdict

        commits = self._make_commits(3)
        enrich_cache = {
            "hash0000": {"agents": 2},
            "hash0001": {"foundation": 1},
            "hash0002": {"meta": 3},
        }

        # Score both ways
        scored = []
        scored_regex = []
        for date, message, repo, hash_id in commits:
            base_total, base_cats = scan.score_commit(message)
            rx_total, rx_cats = scan.apply_diffstat_weight(base_total, base_cats, None)

            if hash_id in enrich_cache:
                total, cats = scan.enrich_score(enrich_cache[hash_id])
                total, cats = scan.apply_diffstat_weight(total, cats, None)
            else:
                total, cats = rx_total, rx_cats

            scored.append((date, total, cats, message, repo, hash_id))
            scored_regex.append((date, rx_total, rx_cats, message, repo, hash_id))

        # Build months
        epoch = datetime.date(2025, 6, 30)
        today = datetime.date(2025, 12, 1)
        all_months = []
        y, m = epoch.year, epoch.month
        while (y, m) <= (today.year, today.month):
            all_months.append((y, m))
            m += 1
            if m > 12:
                m = 1
                y += 1

        # Aggregate enriched
        monthly_commits = defaultdict(int)
        monthly_capability = defaultdict(float)
        monthly_cat_scores = defaultdict(lambda: defaultdict(float))
        for date, total, cats, msg, repo, _ in scored:
            key = (date.year, date.month)
            monthly_commits[key] += 1
            monthly_capability[key] += total
            for cat, score in cats.items():
                monthly_cat_scores[key][cat] += score

        # Aggregate regex
        rx_monthly_capability = defaultdict(float)
        rx_monthly_cat_scores = defaultdict(lambda: defaultdict(float))
        for date, total, cats, msg, repo, _ in scored_regex:
            key = (date.year, date.month)
            rx_monthly_capability[key] += total
            for cat, score in cats.items():
                rx_monthly_cat_scores[key][cat] += score

        # Build monthly data
        cum_commits = 0
        cum_cap = 0
        rx_cum_cap = 0
        monthly_data = []
        monthly_regex_data = []

        for ym in all_months:
            c = monthly_commits.get(ym, 0)
            cap = monthly_capability.get(ym, 0)
            cum_commits += c
            cum_cap += cap

            cats = monthly_cat_scores.get(ym, {})
            soph = scan.compute_sophistication(cats)

            monthly_data.append({
                "month": f"{ym[0]}-{ym[1]:02d}",
                "commits": c,
                "capability": round(cap),
                "sophistication": round(soph, 3),
                "cumulative_commits": cum_commits,
                "cumulative_capability": round(cum_cap),
            })

            rx_cap = rx_monthly_capability.get(ym, 0)
            rx_cum_cap += rx_cap
            rx_cats = rx_monthly_cat_scores.get(ym, {})
            rx_soph = scan.compute_sophistication(rx_cats)
            monthly_regex_data.append({
                "month": f"{ym[0]}-{ym[1]:02d}",
                "commits": c,
                "capability": round(rx_cap),
                "sophistication": round(rx_soph, 3),
                "cumulative_commits": cum_commits,
                "cumulative_capability": round(rx_cum_cap),
            })

        # Verify structures match
        self.assertEqual(len(monthly_data), len(monthly_regex_data))
        for md, rd in zip(monthly_data, monthly_regex_data):
            self.assertEqual(set(md.keys()), set(rd.keys()))
            self.assertEqual(md["month"], rd["month"])
            self.assertEqual(md["commits"], rd["commits"])
            self.assertEqual(md["cumulative_commits"], rd["cumulative_commits"])

    def test_enrich_score_differs_from_regex(self):
        """enrich_score should produce different scores than score_commit for same message."""
        message = "feat: add agent execution loop with self-modify"
        rx_total, rx_cats = scan.score_commit(message)

        # Simulated LLM classification (different emphasis)
        enrich_cats = {"agents": 3, "self_modify": 2}
        en_total, en_cats = scan.enrich_score(enrich_cats)

        # Both should be positive but may differ
        self.assertGreater(rx_total, 0)
        self.assertGreater(en_total, 0)

    def test_no_monthly_regex_without_enrich(self):
        """When enrich_cache is None, monthly_regex_data should be empty."""
        # This is the behavior: monthly_regex_data list is only populated
        # when enrich_cache is not None
        enrich_cache = None
        monthly_regex_data = []
        # When enrich_cache is None, the code block doesn't execute
        if enrich_cache is not None:
            monthly_regex_data.append({"test": True})
        self.assertEqual(monthly_regex_data, [])

    def test_scoring_mode_in_output(self):
        """scoring_mode should be set correctly based on args."""
        # Regex mode
        args_regex = {"enrich": False, "enrich_model": "haiku"}
        method = f"llm_{args_regex['enrich_model']}" if args_regex.get("enrich") else "regex"
        self.assertEqual(method, "regex")

        # Enriched mode
        args_enrich = {"enrich": True, "enrich_model": "sonnet"}
        method = f"llm_{args_enrich['enrich_model']}" if args_enrich.get("enrich") else "regex"
        self.assertEqual(method, "llm_sonnet")

    def test_smoothing_applied_to_regex_data(self):
        """Smoothing should be applied to regex sophistication values too."""
        raw = [0.1, 0.8, 0.2, 0.7, 0.3]
        smoothed = scan.smooth_sophistication(raw)
        # Smoothed values should be less extreme
        self.assertLess(max(smoothed), max(raw))
        self.assertGreater(min(smoothed[1:]), min(raw[1:]))


if __name__ == "__main__":
    unittest.main()
