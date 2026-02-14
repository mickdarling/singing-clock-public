"""Tests for file classification and rename resolution."""

import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scan import _resolve_rename, classify_file


class TestResolveRename(unittest.TestCase):
    """Tests for _resolve_rename() — git rename syntax resolution."""

    def test_passthrough_no_rename(self):
        self.assertEqual(_resolve_rename("src/main.py"), "src/main.py")

    def test_passthrough_empty(self):
        self.assertEqual(_resolve_rename(""), "")

    def test_arrow_form(self):
        self.assertEqual(_resolve_rename("old.py => new.py"), "new.py")

    def test_arrow_form_with_paths(self):
        self.assertEqual(_resolve_rename("src/old.py => src/new.py"), "src/new.py")

    def test_brace_form_filename(self):
        self.assertEqual(_resolve_rename("src/{old.py => new.py}"), "src/new.py")

    def test_brace_form_directory(self):
        self.assertEqual(_resolve_rename("{old => new}/file.py"), "new/file.py")

    def test_brace_form_middle(self):
        self.assertEqual(
            _resolve_rename("src/{v1 => v2}/utils.py"), "src/v2/utils.py"
        )

    def test_multiple_braces(self):
        result = _resolve_rename("{a => b}/{c => d}/file.py")
        self.assertEqual(result, "b/d/file.py")

    def test_brace_with_spaces(self):
        self.assertEqual(
            _resolve_rename("src/{ old.py => new.py }"), "src/new.py"
        )


class TestClassifyFile(unittest.TestCase):
    """Tests for classify_file() — file type classification."""

    # Source extensions
    def test_source_py(self):
        self.assertEqual(classify_file("src/main.py"), "source")

    def test_source_ts(self):
        self.assertEqual(classify_file("src/index.ts"), "source")

    def test_source_js(self):
        self.assertEqual(classify_file("lib/utils.js"), "source")

    def test_source_tsx(self):
        self.assertEqual(classify_file("components/App.tsx"), "source")

    def test_source_go(self):
        self.assertEqual(classify_file("cmd/server.go"), "source")

    def test_source_rs(self):
        self.assertEqual(classify_file("src/lib.rs"), "source")

    def test_source_sh(self):
        self.assertEqual(classify_file("scripts/deploy.sh"), "source")

    def test_source_mjs(self):
        self.assertEqual(classify_file("lib/module.mjs"), "source")

    # Test patterns take priority over source
    def test_test_dot_test(self):
        self.assertEqual(classify_file("src/utils.test.ts"), "test")

    def test_test_dot_spec(self):
        self.assertEqual(classify_file("src/utils.spec.js"), "test")

    def test_test_underscore_prefix(self):
        self.assertEqual(classify_file("tests/test_main.py"), "test")

    def test_test_underscore_suffix(self):
        self.assertEqual(classify_file("tests/main_test.go"), "test")

    def test_test_directory(self):
        self.assertEqual(classify_file("__tests__/utils.js"), "test")

    # Config extensions
    def test_config_json(self):
        self.assertEqual(classify_file("package.json"), "config")

    def test_config_yaml(self):
        self.assertEqual(classify_file("config.yaml"), "config")

    def test_config_yml(self):
        self.assertEqual(classify_file("docker-compose.yml"), "config")

    def test_config_toml(self):
        self.assertEqual(classify_file("pyproject.toml"), "config")

    def test_config_env_dotfile(self):
        # .env is a dotfile with no extension per Python's Path
        # Path(".env").suffix == "" so it classifies as "other"
        self.assertEqual(classify_file(".env"), "other")

    def test_config_env_with_name(self):
        self.assertEqual(classify_file("app.env"), "config")

    # Doc extensions
    def test_doc_md(self):
        self.assertEqual(classify_file("README.md"), "doc")

    def test_doc_txt(self):
        self.assertEqual(classify_file("notes.txt"), "doc")

    def test_doc_rst(self):
        self.assertEqual(classify_file("docs/index.rst"), "doc")

    # Other
    def test_other_image(self):
        self.assertEqual(classify_file("logo.png"), "other")

    def test_other_binary(self):
        self.assertEqual(classify_file("app.exe"), "other")

    # Rename syntax integration
    def test_renamed_source(self):
        self.assertEqual(classify_file("old.py => new.py"), "source")

    def test_renamed_test(self):
        self.assertEqual(classify_file("{old_test.py => new_test.py}"), "test")

    def test_brace_rename_source(self):
        self.assertEqual(classify_file("src/{old.ts => new.ts}"), "source")


if __name__ == "__main__":
    unittest.main()
