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


class ImportTests(unittest.TestCase):
    def test_main_callable(self) -> None:
        self.assertTrue(callable(gofile_cli.main))


if __name__ == "__main__":
    unittest.main()
