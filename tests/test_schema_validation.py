"""Tests for cache schema validation functions."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import scan


class TestValidateDiffstatEntry(unittest.TestCase):
    def test_valid_entry(self):
        entry = {"a": 10, "d": 5, "f": 3, "n": 1, "s": 8, "t": 2, "c": 0}
        self.assertTrue(scan._validate_diffstat_entry(entry))

    def test_valid_entry_with_floats(self):
        entry = {"a": 10.0, "d": 5.5, "f": 3, "n": 1, "s": 8, "t": 2, "c": 0}
        self.assertTrue(scan._validate_diffstat_entry(entry))

    def test_missing_key(self):
        entry = {"a": 10, "d": 5, "f": 3, "n": 1, "s": 8, "t": 2}
        self.assertFalse(scan._validate_diffstat_entry(entry))

    def test_string_value(self):
        entry = {"a": "bad", "d": 5, "f": 3, "n": 1, "s": 8, "t": 2, "c": 0}
        self.assertFalse(scan._validate_diffstat_entry(entry))

    def test_not_a_dict(self):
        self.assertFalse(scan._validate_diffstat_entry([1, 2, 3]))
        self.assertFalse(scan._validate_diffstat_entry("string"))

    def test_empty_dict(self):
        self.assertFalse(scan._validate_diffstat_entry({}))


class TestValidateScoreEntry(unittest.TestCase):
    def test_valid_entry(self):
        entry = {"v": 3, "total": 12.5, "cats": {"testing": 3}}
        self.assertTrue(scan._validate_score_entry(entry))

    def test_missing_total(self):
        entry = {"v": 3, "cats": {"testing": 3}}
        self.assertFalse(scan._validate_score_entry(entry))

    def test_missing_cats(self):
        entry = {"v": 3, "total": 12.5}
        self.assertFalse(scan._validate_score_entry(entry))

    def test_total_is_string(self):
        entry = {"v": 3, "total": "bad", "cats": {}}
        self.assertFalse(scan._validate_score_entry(entry))

    def test_cats_is_list(self):
        entry = {"v": 3, "total": 5, "cats": [1, 2]}
        self.assertFalse(scan._validate_score_entry(entry))

    def test_not_a_dict(self):
        self.assertFalse(scan._validate_score_entry(42))


class TestValidateEnrichEntry(unittest.TestCase):
    def test_valid_entry(self):
        entry = {"testing": 2, "ci_cd": 1, "deployment": 3}
        self.assertTrue(scan._validate_enrich_entry(entry))

    def test_empty_dict(self):
        self.assertTrue(scan._validate_enrich_entry({}))

    def test_string_value(self):
        entry = {"testing": "high"}
        self.assertFalse(scan._validate_enrich_entry(entry))

    def test_not_a_dict(self):
        self.assertFalse(scan._validate_enrich_entry("bad"))


class TestSpotCheckCache(unittest.TestCase):
    def test_empty_cache(self):
        self.assertTrue(scan._spot_check_cache({}, lambda x: False))

    def test_only_meta_keys(self):
        data = {"_v": 1, "_meta": "info"}
        self.assertTrue(scan._spot_check_cache(data, lambda x: False))

    def test_valid_entries(self):
        data = {
            "_v": 1,
            "abc123": {"a": 1, "d": 2, "f": 1, "n": 0, "s": 1, "t": 0, "c": 0},
            "def456": {"a": 5, "d": 0, "f": 2, "n": 1, "s": 4, "t": 1, "c": 0},
        }
        self.assertTrue(scan._spot_check_cache(data, scan._validate_diffstat_entry))

    def test_one_bad_entry(self):
        data = {
            "_v": 1,
            "abc123": {"a": 1, "d": 2, "f": 1, "n": 0, "s": 1, "t": 0, "c": 0},
            "bad": "not a dict",
        }
        self.assertFalse(scan._spot_check_cache(data, scan._validate_diffstat_entry))

    def test_max_checks_limit(self):
        """Only checks up to max_checks entries."""
        call_count = 0
        def counting_validator(entry):
            nonlocal call_count
            call_count += 1
            return True

        data = {f"hash{i}": {"val": i} for i in range(20)}
        scan._spot_check_cache(data, counting_validator, max_checks=3)
        self.assertEqual(call_count, 3)


class TestLoadDiffstatCacheValidation(unittest.TestCase):
    def test_rejects_malformed_entries(self):
        cache_data = {
            "_v": scan.DIFFSTAT_CACHE_VERSION,
            "abc123": "not a valid entry",
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(cache_data, f)
            tmp_path = Path(f.name)
        try:
            with patch.object(scan, "DIFFSTAT_CACHE_FILE", tmp_path):
                result = scan.load_diffstat_cache()
            self.assertNotIn("abc123", result)
        finally:
            tmp_path.unlink()

    def test_accepts_valid_entries(self):
        cache_data = {
            "_v": scan.DIFFSTAT_CACHE_VERSION,
            "abc123": {"a": 10, "d": 5, "f": 3, "n": 1, "s": 8, "t": 2, "c": 0},
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(cache_data, f)
            tmp_path = Path(f.name)
        try:
            with patch.object(scan, "DIFFSTAT_CACHE_FILE", tmp_path):
                result = scan.load_diffstat_cache()
            self.assertIn("abc123", result)
        finally:
            tmp_path.unlink()


class TestLoadScoreCacheValidation(unittest.TestCase):
    def test_rejects_malformed_entries(self):
        cache_data = {"abc123": {"v": 3, "total": "bad", "cats": {}}}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(cache_data, f)
            tmp_path = Path(f.name)
        try:
            with patch.object(scan, "SCORE_CACHE_FILE", tmp_path):
                result = scan.load_score_cache()
            self.assertEqual(result, {})
        finally:
            tmp_path.unlink()

    def test_accepts_valid_entries(self):
        cache_data = {"abc123": {"v": 3, "total": 12.5, "cats": {"testing": 3}}}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(cache_data, f)
            tmp_path = Path(f.name)
        try:
            with patch.object(scan, "SCORE_CACHE_FILE", tmp_path):
                result = scan.load_score_cache()
            self.assertIn("abc123", result)
        finally:
            tmp_path.unlink()


class TestLoadEnrichCacheValidation(unittest.TestCase):
    def test_rejects_malformed_entries(self):
        cache_data = {
            "_v": scan.ENRICH_CACHE_VERSION,
            "abc123": {"testing": "high"},
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(cache_data, f)
            tmp_path = Path(f.name)
        try:
            with patch.object(scan, "ENRICH_CACHE_FILE", tmp_path):
                result = scan.load_enrich_cache()
            self.assertNotIn("abc123", result)
        finally:
            tmp_path.unlink()

    def test_accepts_valid_entries(self):
        cache_data = {
            "_v": scan.ENRICH_CACHE_VERSION,
            "abc123": {"testing": 2, "ci_cd": 1},
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(cache_data, f)
            tmp_path = Path(f.name)
        try:
            with patch.object(scan, "ENRICH_CACHE_FILE", tmp_path):
                result = scan.load_enrich_cache()
            self.assertIn("abc123", result)
        finally:
            tmp_path.unlink()


if __name__ == "__main__":
    unittest.main()
