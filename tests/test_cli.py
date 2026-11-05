"""Offline smoke tests for gofile-cli."""

from __future__ import annotations

import unittest

import gofile_cli
from gofile_cli.cli import usage_spec


class UsageSpecTests(unittest.TestCase):
    def test_usage_spec_generates(self) -> None:
        spec = usage_spec()
        self.assertIn("name gofile-cli", spec)
        self.assertIn("bin gofile-cli", spec)

    def test_usage_spec_carries_package_version(self) -> None:
        spec = usage_spec()
        version_lines = [ln for ln in spec.splitlines() if ln.startswith("version ")]
        self.assertEqual(version_lines, [f'version "{gofile_cli.__version__}"'])

    def test_usage_spec_documents_private_negations(self) -> None:
        # typer_usage cannot express --public/--private; usage_spec() patches
        # negate=--private onto both flags (mkdir and contents create-folder).
        spec = usage_spec()
        self.assertEqual(spec.count("negate=--private"), 2)


class ImportTests(unittest.TestCase):
    def test_main_callable(self) -> None:
        self.assertTrue(callable(gofile_cli.main))


if __name__ == "__main__":
    unittest.main()
