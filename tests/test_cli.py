"""Offline tests for gofile-cli. No tests hit the network."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import gofile_cli
from gofile_cli import cli, client
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


class GofileErrorTests(unittest.TestCase):
    """The CLI doubles a status when message falls back to status."""

    def test_message_defaults_to_status_without_duplicating_it(self) -> None:
        exc = client.GofileError("error-notPremium")
        self.assertEqual(str(exc), "error-notPremium")

    def test_explicit_message_keeps_prefix(self) -> None:
        exc = client.GofileError("error-http", "boom", 500)
        self.assertEqual(str(exc), "error-http: boom")


class DotenvTokenTests(unittest.TestCase):
    """_dotenv_token() mis-parses export lines, inline comments, and quotes."""

    def _read(self, text: str) -> str | None:
        """Write text into a .env, then read it as both cwd and home."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text(text, encoding="utf-8")
            with (
                mock.patch("gofile_cli.cli.Path.cwd", return_value=Path(tmp)),
                mock.patch("gofile_cli.cli.Path.home", return_value=Path(tmp)),
            ):
                return cli._dotenv_token()

    def test_export_prefix_is_not_part_of_the_token(self) -> None:
        self.assertEqual(
            self._read("export GOFILE_API_TOKEN=test-token-value\n"),
            "test-token-value",
        )

    def test_inline_comment_is_not_part_of_the_token(self) -> None:
        self.assertEqual(self._read("GOFILE_API_TOKEN=abc123 # my note\n"), "abc123")

    def test_quoted_value_has_only_outer_quotes_stripped(self) -> None:
        self.assertEqual(self._read('GOFILE_API_TOKEN="tok"\n'), "tok")

    def test_interior_quotes_are_preserved(self) -> None:
        # Old code: .strip('"').strip("'") turned `"""tok"""` into `tok`.
        self.assertEqual(self._read('GOFILE_API_TOKEN="""tok"""\n'), '""tok""')

    def test_environment_token_is_used_before_dotenv(self) -> None:
        with (
            mock.patch.dict(
                "gofile_cli.cli.os.environ",
                {"GOFILE_API_TOKEN": "synthetic-ci-token"},
                clear=True,
            ),
            mock.patch("gofile_cli.cli._dotenv_token", return_value="dotenv-token"),
        ):
            self.assertEqual(cli.resolve_token(), "synthetic-ci-token")

    def test_precedence_prefers_cwd_over_home(self) -> None:
        # A cwd .env takes priority over the home fallbacks.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "home").mkdir()
            (root / "work").mkdir()
            (root / "home" / ".env").write_text(
                "GOFILE_API_TOKEN=from-home\n", encoding="utf-8"
            )
            (root / "work" / ".env").write_text(
                "GOFILE_API_TOKEN=from-cwd\n", encoding="utf-8"
            )
            with (
                mock.patch("gofile_cli.cli.Path.home", return_value=root / "home"),
                mock.patch("gofile_cli.cli.Path.cwd", return_value=root / "work"),
            ):
                self.assertEqual(cli._dotenv_token(), "from-cwd")


class LiveUploadIntegrationTests(unittest.TestCase):
    """Exercise real uploads; successful remote content is intentionally kept."""

    def test_file_and_folder_upload_shortcuts(self) -> None:
        token = os.environ.get("GOFILE_API_TOKEN")
        self.assertTrue(token, "GOFILE_API_TOKEN is required for live upload tests")

        executable = shutil.which("gofile-cli")
        self.assertIsNotNone(executable, "gofile-cli executable is required")
        env = os.environ.copy()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "file.txt").write_text("live upload integration test\n")
            folder = root / "folder"
            folder.mkdir()
            for name in ("file1.txt", "file2.txt", "file3.txt"):
                (folder / name).write_text(f"live upload integration test: {name}\n")

            for relative_path, expected_names in (
                ("file.txt", ("file.txt",)),
                ("folder/", ("file1.txt", "file2.txt", "file3.txt")),
            ):
                with self.subTest(path=relative_path):
                    result = subprocess.run(
                        [executable, relative_path],
                        cwd=root,
                        env=env,
                        capture_output=True,
                        text=True,
                        timeout=600,
                        check=False,
                    )
                    self.assertEqual(
                        result.returncode,
                        0,
                        f"Upload command failed for {relative_path}:\n"
                        f"{result.stdout}\n{result.stderr}",
                    )
                    for name in expected_names:
                        self.assertIn(name, result.stdout)


class HeaderEscapingTests(unittest.TestCase):
    """Multipart headers reject quotes and swallow CR/LF."""

    def test_double_quote_is_escaped(self) -> None:
        self.assertEqual(client._escape_header_value('a"bc'), 'a\\"bc')

    def test_backslash_is_escaped_first(self) -> None:
        self.assertEqual(client._escape_header_value("a\\bc"), "a\\\\bc")

    def test_carriage_return_and_newline_are_removed(self) -> None:
        self.assertEqual(client._escape_header_value("a\r\nbc"), "abc")

    def test_plain_value_is_unchanged(self) -> None:
        self.assertEqual(client._escape_header_value("file.txt"), "file.txt")


class KnownCommandsTests(unittest.TestCase):
    """KNOWN_COMMANDS must be derived, not a hand-maintained literal."""

    def test_derived_set_matches_registered_commands(self) -> None:
        expected = {c.name for c in cli.app.registered_commands if c.name}
        expected |= {g.name for g in cli.app.registered_groups}
        self.assertTrue(expected.issubset(cli.KNOWN_COMMANDS))

    def test_bare_path_that_shadows_a_command_is_not_an_upload(self) -> None:
        # A file named like a command must not be rewritten to `upload`.
        self.assertIn("upload", cli.KNOWN_COMMANDS)


if __name__ == "__main__":
    unittest.main()
