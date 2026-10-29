from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from package import release_paths


class PackageTests(unittest.TestCase):
    def test_local_state_and_config_filtered_even_when_tracked(self):
        result = release_paths(["README.md", "src/main.m", "config.json", "private/device.json",
                                ".runtime/state.json", "build/app", "dist/file.zip", ".git/config",
                                "scripts/__pycache__/cli.pyc", ".DS_Store"])
        self.assertEqual(result, ["README.md", "src/main.m"])

    def test_archive_path_traversal_rejected(self):
        for name in ("../secret", "/absolute", "docs/../../secret"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                release_paths([name])

    def test_release_selects_project_source_locations(self):
        result = release_paths(["README.md", "docs/architecture.md", "notes.txt", "scratch/device.json"])
        self.assertEqual(result, ["README.md", "docs/architecture.md"])


if __name__ == "__main__":
    unittest.main()
