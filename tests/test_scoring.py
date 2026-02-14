"""Tests for commit scoring functions."""

import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scan import score_commit, enrich_score, CATEGORIES


class TestScoreCommit(unittest.TestCase):
    """Tests for score_commit() — regex-based commit scoring."""

    def test_foundation_commit(self):
        total, cats = score_commit("initial commit: scaffold project")
        self.assertIn("foundation", cats)
        self.assertGreater(total, 0)

    def test_agent_commit(self):
        total, cats = score_commit("feat: add autonomous agent execution loop")
        self.assertIn("agents", cats)
        # agents weight is 3, should produce meaningful score
        self.assertGreaterEqual(cats["agents"], 3)

    def test_self_modify_commit(self):
        total, cats = score_commit("feat: implement self-modification and runtime creation")
        self.assertIn("self_modify", cats)
        # self_modify weight is 5
        self.assertGreaterEqual(cats["self_modify"], 5)

    def test_meta_commit(self):
        total, cats = score_commit("feat: add introspection and ensemble orchestration")
        self.assertIn("meta", cats)

    def test_safety_commit(self):
        total, cats = score_commit("fix: add input validation and trust tier checks")
        self.assertIn("safety", cats)

    def test_ecosystem_commit(self):
        total, cats = score_commit("feat: implement collection browse and portfolio sync")
        self.assertIn("ecosystem", cats)

    def test_integration_commit(self):
        total, cats = score_commit("feat: add REST API endpoint with OAuth bridge")
        self.assertIn("integration", cats)

    def test_aql_commit(self):
        total, cats = score_commit("feat: implement AQL query language resolver")
        self.assertIn("aql", cats)

    def test_multi_category_commit(self):
        total, cats = score_commit(
            "feat: add agent execution with safety validation and introspection"
        )
        # Should hit agents, safety, and meta
        self.assertGreaterEqual(len(cats), 2)

    def test_merge_pr_bonus(self):
        total_merge, _ = score_commit(
            "Merge pull request #42 from feature/add-agent-feat"
        )
        total_normal, _ = score_commit("feat: add agent")
        # Merge PR with feat keyword should get 1.5x bonus
        self.assertGreater(total_merge, total_normal)

    def test_zero_match_floor(self):
        total, cats = score_commit("Update changelog for v1.2.3")
        # No category matches -> floor score of 0.5
        self.assertEqual(total, 0.5)
        self.assertEqual(len(cats), 0)

    def test_case_insensitive(self):
        total1, cats1 = score_commit("INITIAL COMMIT setup scaffold")
        total2, cats2 = score_commit("initial commit setup scaffold")
        self.assertEqual(total1, total2)
        self.assertEqual(cats1, cats2)

    def test_hit_count_capped_at_3(self):
        # foundation has many patterns; stuff them all in one message
        msg = "initial commit setup scaffold boilerplate package.json tsconfig eslint prettier basic structure foundation directory structure"
        total, cats = score_commit(msg)
        # weight is 1, max hits 3, so max foundation score = 3
        if "foundation" in cats:
            self.assertLessEqual(cats["foundation"], 3)

    def test_elements_commit(self):
        total, cats = score_commit("feat: create element manager for persona CRUD")
        self.assertIn("elements", cats)


class TestEnrichScore(unittest.TestCase):
    """Tests for enrich_score() — LLM classification scoring."""

    def test_valid_single_category(self):
        total, cats = enrich_score({"agents": 2})
        # agents weight=3, hits=2 -> score=6
        self.assertEqual(cats["agents"], 6)
        self.assertEqual(total, 6)

    def test_valid_multi_category(self):
        total, cats = enrich_score({"agents": 2, "safety": 1})
        self.assertEqual(cats["agents"], 6)  # 3 * 2
        self.assertEqual(cats["safety"], 2)  # 2 * 1
        self.assertEqual(total, 8)

    def test_empty_dict_floor(self):
        total, cats = enrich_score({})
        self.assertEqual(total, 0.5)
        self.assertEqual(len(cats), 0)

    def test_unknown_categories_ignored(self):
        total, cats = enrich_score({"nonexistent": 3, "agents": 1})
        self.assertNotIn("nonexistent", cats)
        self.assertIn("agents", cats)

    def test_hit_count_clamped_min(self):
        total, cats = enrich_score({"agents": 0})
        # min clamp to 1: 3 * 1 = 3
        self.assertEqual(cats["agents"], 3)

    def test_hit_count_clamped_max(self):
        total, cats = enrich_score({"agents": 10})
        # max clamp to 3: 3 * 3 = 9
        self.assertEqual(cats["agents"], 9)

    def test_all_categories_valid(self):
        raw = {cat: 2 for cat in CATEGORIES}
        total, cats = enrich_score(raw)
        self.assertEqual(len(cats), len(CATEGORIES))
        expected = sum(CATEGORIES[c]["weight"] * 2 for c in CATEGORIES)
        self.assertEqual(total, expected)


if __name__ == "__main__":
    unittest.main()
