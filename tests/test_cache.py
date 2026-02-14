"""Tests for cache load/save and versioning."""

import json
import os
import tempfile
import unittest
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import scan


class TestScoreCacheIO(unittest.TestCase):
    """Tests for load_score_cache() and save_score_cache()."""

    def test_load_missing_file(self):
        with mock.patch.object(scan, "SCORE_CACHE_FILE", Path("/nonexistent/path")):
            result = scan.load_score_cache()
            self.assertEqual(result, {})

    def test_load_valid_cache(self):
        data = {"_v": 3, "abc123": {"agents": 6}}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            f.flush()
            try:
                with mock.patch.object(scan, "SCORE_CACHE_FILE", Path(f.name)):
                    result = scan.load_score_cache()
                    self.assertIn("abc123", result)
            finally:
                os.unlink(f.name)

    def test_load_corrupted_cache(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("{invalid json")
            f.flush()
            try:
                with mock.patch.object(scan, "SCORE_CACHE_FILE", Path(f.name)):
                    result = scan.load_score_cache()
                    self.assertEqual(result, {})
            finally:
                os.unlink(f.name)

    def test_save_and_reload(self):
        data = {"abc123": {"agents": 6}, "def456": {"safety": 2}}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            tmp_path = Path(f.name)
            try:
                with mock.patch.object(scan, "SCORE_CACHE_FILE", tmp_path):
                    scan.save_score_cache(data)
                    reloaded = json.loads(tmp_path.read_text())
                    self.assertIn("abc123", reloaded)
            finally:
                os.unlink(f.name)


class TestDiffstatCacheIO(unittest.TestCase):
    """Tests for load_diffstat_cache() and save_diffstat_cache()."""

    def test_load_missing_file(self):
        with mock.patch.object(scan, "DIFFSTAT_CACHE_FILE", Path("/nonexistent/path")):
            result = scan.load_diffstat_cache()
            self.assertEqual(result, {})

    def test_load_valid_cache(self):
        data = {"_v": scan.DIFFSTAT_CACHE_VERSION, "abc123": {"a": 10, "d": 5}}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            f.flush()
            try:
                with mock.patch.object(scan, "DIFFSTAT_CACHE_FILE", Path(f.name)):
                    result = scan.load_diffstat_cache()
                    self.assertIn("abc123", result)
            finally:
                os.unlink(f.name)

    def test_load_version_mismatch(self):
        data = {"_v": 999, "abc123": {"a": 10}}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            f.flush()
            try:
                with mock.patch.object(scan, "DIFFSTAT_CACHE_FILE", Path(f.name)):
                    result = scan.load_diffstat_cache()
                    # Version mismatch -> fresh cache with version key
                    self.assertEqual(result.get("_v"), scan.DIFFSTAT_CACHE_VERSION)
                    self.assertNotIn("abc123", result)
            finally:
                os.unlink(f.name)

    def test_save_and_reload(self):
        cache = {"abc123": {"a": 10, "d": 5, "f": 3, "s": 8, "t": 0, "c": 2, "n": 1}}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            tmp_path = Path(f.name)
            try:
                with mock.patch.object(scan, "DIFFSTAT_CACHE_FILE", tmp_path):
                    scan.save_diffstat_cache(cache)
                    reloaded = json.loads(tmp_path.read_text())
                    self.assertEqual(reloaded["_v"], scan.DIFFSTAT_CACHE_VERSION)
                    self.assertIn("abc123", reloaded)
            finally:
                os.unlink(f.name)


class TestEnrichCacheIO(unittest.TestCase):
    """Tests for load_enrich_cache() and save_enrich_cache()."""

    def test_load_missing_file(self):
        with mock.patch.object(scan, "ENRICH_CACHE_FILE", Path("/nonexistent/path")):
            result = scan.load_enrich_cache()
            self.assertEqual(result, {"_v": scan.ENRICH_CACHE_VERSION})

    def test_load_valid_cache(self):
        data = {"_v": scan.ENRICH_CACHE_VERSION, "abc123": {"agents": 2}}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            f.flush()
            try:
                with mock.patch.object(scan, "ENRICH_CACHE_FILE", Path(f.name)):
                    result = scan.load_enrich_cache()
                    self.assertIn("abc123", result)
            finally:
                os.unlink(f.name)

    def test_load_version_mismatch(self):
        data = {"_v": 999, "abc123": {"agents": 2}}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            f.flush()
            try:
                with mock.patch.object(scan, "ENRICH_CACHE_FILE", Path(f.name)):
                    result = scan.load_enrich_cache()
                    self.assertEqual(result, {"_v": scan.ENRICH_CACHE_VERSION})
            finally:
                os.unlink(f.name)

    def test_load_corrupted(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("not valid json!!!")
            f.flush()
            try:
                with mock.patch.object(scan, "ENRICH_CACHE_FILE", Path(f.name)):
                    result = scan.load_enrich_cache()
                    self.assertEqual(result, {"_v": scan.ENRICH_CACHE_VERSION})
            finally:
                os.unlink(f.name)


if __name__ == "__main__":
    unittest.main()
