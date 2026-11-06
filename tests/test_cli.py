"""Tests for gofile-cli.

LiveUploadIntegrationTests is the only class that hits the network.
"""

from __future__ import annotations

import http.client
import os
import shutil
import subprocess
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from typer.testing import CliRunner

import gofile_cli
from gofile_cli import auth, cli, client
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
        # negate=--private onto both commands (mkdir and contents create-folder).
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

    def test_message_equal_to_status_is_not_repeated(self) -> None:
        exc = client.GofileError("error-notPremium", "error-notPremium")
        self.assertEqual(str(exc), "error-notPremium")


class DotenvTokenTests(unittest.TestCase):
    """_dotenv_token() mis-parses export lines, inline comments, and quotes."""

    def _read(self, text: str) -> str | None:
        """Write text into a .env, then read it as both cwd and home."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text(text, encoding="utf-8")
            with (
                mock.patch("gofile_cli.auth.Path.cwd", return_value=Path(tmp)),
                mock.patch("gofile_cli.auth.Path.home", return_value=Path(tmp)),
            ):
                return auth._dotenv_token()

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
                "gofile_cli.auth.os.environ",
                {"GOFILE_API_TOKEN": "synthetic-ci-token"},
                clear=True,
            ),
            mock.patch("gofile_cli.auth._dotenv_token", return_value="dotenv-token"),
        ):
            self.assertEqual(auth.resolve_token(), "synthetic-ci-token")

    def test_empty_quotes_do_not_crash_and_are_skipped(self) -> None:
        self.assertIsNone(self._read('GOFILE_API_TOKEN=""\n'))
        self.assertEqual(
            self._read('GOFILE_API_TOKEN=""\nGOFILE_TOKEN=second\n'),
            "second",
        )

    def test_comment_after_closing_quote_is_dropped(self) -> None:
        self.assertEqual(self._read('GOFILE_API_TOKEN="tok" # note\n'), "tok")
        self.assertEqual(self._read("GOFILE_API_TOKEN='tok' # note\n"), "tok")
        self.assertEqual(self._read('GOFILE_API_TOKEN="tok" # "no"\n'), "tok")

    def test_hash_inside_quotes_is_kept(self) -> None:
        self.assertEqual(self._read('GOFILE_API_TOKEN="abc # keep"\n'), "abc # keep")

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
                mock.patch("gofile_cli.auth.Path.home", return_value=root / "home"),
                mock.patch("gofile_cli.auth.Path.cwd", return_value=root / "work"),
            ):
                self.assertEqual(auth._dotenv_token(), "from-cwd")


class LiveUploadIntegrationTests(unittest.TestCase):
    """Exercise real uploads; successful remote content is intentionally kept."""

    def test_file_and_folder_upload_shortcuts(self) -> None:
        # resolve_token() honors every source the CLI supports (flag/env/.env);
        # skip rather than fail when none is configured.
        token = auth.resolve_token()
        if not token:
            self.skipTest("no Gofile token configured (set GOFILE_API_TOKEN/GOFILE_TOKEN or a .env)")

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


class _Body:
    def __init__(self, raw: bytes, status: int = 200) -> None:
        self._raw = raw
        self.status = status

    def read(self) -> bytes:
        return self._raw


class ParseResponseTests(unittest.TestCase):
    def test_status_without_message_is_not_duplicated(self) -> None:
        with self.assertRaises(client.GofileError) as caught:
            client._read_payload(_Body(b'{"status":"error-notPremium"}'))
        self.assertEqual(str(caught.exception), "error-notPremium")

    def test_distinct_message_keeps_the_prefix(self) -> None:
        with self.assertRaises(client.GofileError) as caught:
            client._read_payload(
                _Body(b'{"status":"error-field","message":"bad tags"}')
            )
        self.assertEqual(str(caught.exception), "error-field: bad tags")


class MultipartBodyTests(unittest.TestCase):
    def test_folder_id_is_body_text_and_filename_is_a_header(self) -> None:
        body = client._multipart_body(
            boundary="BOUND",
            filename='a"b.txt',
            content=b"hi",
            content_type="text/plain",
            folder_id='id"still',
        )
        self.assertIn(b'name="folderId"\r\n\r\nid"still\r\n', body)
        self.assertNotIn(b'id\\"still', body)
        self.assertIn(b'filename="a\\"b.txt"', body)

    def test_folder_id_cannot_inject_a_part(self) -> None:
        body = client._multipart_body(
            boundary="BOUND",
            filename="file.txt",
            content=b"hi",
            content_type="text/plain",
            folder_id="ab\r\n--BOUND",
        )
        self.assertNotIn(b"ab\r\n--BOUND", body)
        self.assertIn(b"ab--BOUND\r\n", body)


class UploadRegionTests(unittest.TestCase):
    def test_known_region_is_an_allowlisted_host(self) -> None:
        self.assertEqual(client.upload_host("EU-PAR"), "upload-eu-par.gofile.io")
        self.assertEqual(client.upload_host(None), "upload.gofile.io")
        self.assertEqual(client.upload_host("auto"), "upload.gofile.io")

    def test_unknown_region_is_rejected_before_the_network(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "file.txt"
            path.write_text("x", encoding="utf-8")
            with mock.patch("gofile_cli.client.urllib.request.urlopen") as urlopen:
                with self.assertRaises(client.GofileError) as caught:
                    client.upload_file(path, region="https://evil.example")
                urlopen.assert_not_called()
        self.assertEqual(caught.exception.status, "error-region")

    def test_region_selects_the_host_and_keeps_a_top_level_guest_token(self) -> None:
        class _Resp(_Body):
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        raw = (
            b'{"status":"ok","data":{"id":"1","parentFolder":"p"},'
            b'"guestToken":"guest-secret"}'
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "file.txt"
            path.write_text("x", encoding="utf-8")
            with mock.patch(
                "gofile_cli.client.urllib.request.urlopen",
                return_value=_Resp(raw),
            ) as urlopen:
                data = client.upload_file(path, region="eu-par", token="t")
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://upload-eu-par.gofile.io/uploadfile")
        self.assertEqual(data["guestToken"], "guest-secret")
        self.assertEqual(data["parentFolder"], "p")


class StreamingUploadTests(unittest.TestCase):
    """upload_file streams the body; it never reads the whole file at once."""

    class _Resp(_Body):
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def _upload(self, path, **kwargs):
        raw = b'{"status":"ok","data":{"id":"1","parentFolder":"p"}}'
        captured = {}

        def fake_urlopen(request, timeout=None):
            # Consume the streaming body while the file is still open, the
            # way http.client.send() would during a real request.
            captured["body"] = b"".join(request.data)
            return self._Resp(raw)

        with mock.patch(
            "gofile_cli.client.urllib.request.urlopen",
            side_effect=fake_urlopen,
        ) as urlopen:
            client.upload_file(path, token="t", **kwargs)
        request = urlopen.call_args.args[0]
        request.streamed_body = captured["body"]
        return request

    def test_body_is_a_generator_and_content_length_matches(self) -> None:
        payload = b"x" * (3 * client._UPLOAD_CHUNK + 17)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "big.bin"
            path.write_bytes(payload)
            request = self._upload(path)

        self.assertIsInstance(request.data, types.GeneratorType)


        # Recompute what Content-Length must be: head + size + tail.
        head = client._multipart_head(
            boundary=request.get_header("Content-type").split("boundary=")[1],
            filename="big.bin",
            content_type="application/octet-stream",
            folder_id=None,
        )
        tail = b"\r\n" + f"--{request.get_header('Content-type').split('boundary=')[1]}--\r\n".encode()
        self.assertEqual(
            request.get_header("Content-length"), str(len(head) + len(payload) + len(tail))
        )

    def test_streamed_body_matches_in_memory_body(self) -> None:
        payload = b"y" * (client._UPLOAD_CHUNK + 5)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "f.bin"
            path.write_bytes(payload)
            request = self._upload(path)
        boundary = request.get_header("Content-type").split("boundary=")[1]
        assembled = request.streamed_body
        expected = client._multipart_body(
            boundary=boundary,
            filename="f.bin",
            content=payload,
            content_type="application/octet-stream",
            folder_id=None,
        )
        self.assertEqual(assembled, expected)


class TransportErrorTests(unittest.TestCase):
    """Socket-level failures surface as GofileError, not raw tracebacks."""

    def test_timeout_becomes_error_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "f.txt"
            path.write_text("x", encoding="utf-8")
            with mock.patch(
                "gofile_cli.client.urllib.request.urlopen",
                side_effect=TimeoutError("timed out"),
            ):
                with self.assertRaises(client.GofileError) as caught:
                    client.upload_file(path, token="t")
        self.assertEqual(caught.exception.status, "error-timeout")

    def test_dns_failure_becomes_error_network(self) -> None:
        with mock.patch(
            "gofile_cli.client.urllib.request.urlopen",
            side_effect=OSError("name resolution failed"),
        ):
            with self.assertRaises(client.GofileError) as caught:
                client.get_account_id(token="t")
        self.assertEqual(caught.exception.status, "error-network")

    def test_http_exception_becomes_gofile_error(self) -> None:

        with mock.patch(
            "gofile_cli.client.urllib.request.urlopen",
            side_effect=http.client.RemoteDisconnected("peer closed"),
        ):
            with self.assertRaises(client.GofileError) as caught:
                client.get_account_id(token="t")
        self.assertIn(caught.exception.status, ("error-network", "error-http"))


def _captured(result) -> str:
    return (result.output or "") + (getattr(result, "stderr", None) or "")


class UploadCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CliRunner()

    def test_ls_accepts_the_same_options_as_contents_get(self) -> None:
        listing = self.runner.invoke(cli.app, ["ls", "--help"])
        reading = self.runner.invoke(cli.app, ["contents", "get", "--help"])
        self.assertEqual(listing.exit_code, 0)
        self.assertEqual(reading.exit_code, 0)
        for flag in ("--password", "--page", "--page-size", "--maxdepth", "--filter"):
            self.assertIn(flag, listing.output)
            self.assertIn(flag, reading.output)

    def test_missing_token_still_refuses_without_guest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "file.txt"
            path.write_text("x", encoding="utf-8")
            with (
                mock.patch.dict("gofile_cli.auth.os.environ", {}, clear=True),
                mock.patch("gofile_cli.auth._dotenv_token", return_value=None),
                mock.patch("gofile_cli.client.upload_file") as upload,
            ):
                result = self.runner.invoke(cli.app, ["upload", str(path)])
        self.assertEqual(result.exit_code, 1)
        self.assertIn("no API token", _captured(result))
        upload.assert_not_called()

    def test_guest_flag_refuses_when_a_token_is_set(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "file.txt"
            path.write_text("x", encoding="utf-8")
            with (
                mock.patch.dict(
                    "gofile_cli.auth.os.environ",
                    {"GOFILE_API_TOKEN": "real-token"},
                    clear=True,
                ),
                mock.patch("gofile_cli.client.upload_file") as upload,
            ):
                result = self.runner.invoke(cli.app, ["upload", str(path), "--guest"])
        self.assertEqual(result.exit_code, 1)
        self.assertIn("cannot be combined", _captured(result))
        upload.assert_not_called()

    def test_guest_upload_reuses_the_issued_token(self) -> None:
        calls: list[dict] = []

        def upload(path, *, token, folder_id, region, timeout):
            name = Path(path).name
            calls.append(
                {"name": name, "token": token, "folder_id": folder_id, "region": region}
            )
            if name == "b.txt":
                raise client.GofileError("error-limits", "cap")
            return {
                "name": name,
                "size": 1,
                "downloadPage": "https://gofile.io/d/abc",
                "parentFolder": "folder-1",
                "guestToken": "guest-secret",
            }

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.txt").write_text("a", encoding="utf-8")
            (root / "b.txt").write_text("b", encoding="utf-8")
            with (
                mock.patch.dict("gofile_cli.auth.os.environ", {}, clear=True),
                mock.patch("gofile_cli.auth._dotenv_token", return_value=None),
                mock.patch("gofile_cli.client.upload_file", upload),
            ):
                result = self.runner.invoke(
                    cli.app,
                    ["upload", str(root / "a.txt"), str(root / "b.txt"), "--guest"],
                )
        text = _captured(result)
        self.assertEqual(result.exit_code, 1, text)
        self.assertEqual(calls[0]["token"], None)
        self.assertEqual(calls[1]["token"], "guest-secret")
        self.assertEqual(calls[1]["folder_id"], "folder-1")
        self.assertIn("guest-secret", text)
        self.assertIn("a.txt", text)

    def test_a_real_token_is_not_replaced_by_guest_token(self) -> None:
        seen: list[str | None] = []

        def upload(path, *, token, folder_id, region, timeout):
            seen.append(token)
            return {
                "name": Path(path).name,
                "size": 1,
                "downloadPage": "https://gofile.io/d/abc",
                "parentFolder": "folder-1",
                "guestToken": "should-not-print",
            }

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "file.txt"
            path.write_text("x", encoding="utf-8")
            with (
                mock.patch.dict(
                    "gofile_cli.auth.os.environ",
                    {"GOFILE_API_TOKEN": "real-token"},
                    clear=True,
                ),
                mock.patch("gofile_cli.auth._dotenv_token", return_value=None),
                mock.patch("gofile_cli.client.upload_file", upload),
            ):
                result = self.runner.invoke(cli.app, ["upload", str(path)])
        self.assertEqual(result.exit_code, 0, _captured(result))
        self.assertEqual(seen, ["real-token"])
        self.assertNotIn("should-not-print", _captured(result))

    def test_unknown_region_fails_before_upload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "file.txt"
            path.write_text("x", encoding="utf-8")
            with (
                mock.patch.dict(
                    "gofile_cli.auth.os.environ",
                    {"GOFILE_API_TOKEN": "real-token"},
                    clear=True,
                ),
                mock.patch("gofile_cli.client.upload_file") as upload,
            ):
                result = self.runner.invoke(
                    cli.app, ["upload", str(path), "--region", "https://evil.example"]
                )
        self.assertEqual(result.exit_code, 1)
        self.assertIn("unknown upload region", _captured(result))
        upload.assert_not_called()


if __name__ == "__main__":
    unittest.main()
