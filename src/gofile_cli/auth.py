"""Where the API token comes from."""

from __future__ import annotations

import os
from pathlib import Path

DOTENV_KEYS = ("GOFILE_API_TOKEN", "GOFILE_TOKEN", "GOFILER_API_TOKEN")


def _dotenv_value(raw: str) -> str:
    """Unquote a dotenv value and drop an unquoted trailing comment.

    The closing quote is the first matching quote after which only whitespace
    or a # comment remains, so inner quotes stay and `"tok" # note` drops the
    note. An unterminated quote is returned unchanged.
    """
    value = raw.strip()
    if len(value) >= 2 and value[0] in "\"'":
        quote = value[0]
        for index in range(1, len(value)):
            if value[index] != quote:
                continue
            rest = value[index + 1 :].strip()
            if rest == "" or rest.startswith("#"):
                return value[1:index]
        return value
    for marker in (" #", "\t#"):
        index = value.find(marker)
        if index != -1:
            return value[:index].rstrip()
    return value


def _dotenv_token() -> str | None:
    """Read a token from the first .env that defines one.

    Precedence is: cwd, $HOME/.config/gofile/.env, $HOME/.gofile/.env.
    Writing `export GOFILE_API_TOKEN=...` also works. A trailing `# ...`
    comment is ignored on an unquoted value and after a closing quote, and
    kept when it sits inside the quotes.
    """
    candidates = (
        Path.cwd() / ".env",
        Path.home() / ".config" / "gofile" / ".env",
        Path.home() / ".gofile" / ".env",
    )
    for dotenv in candidates:
        try:
            text = dotenv.read_text(encoding="utf-8")
        except OSError:
            continue
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if line.startswith("export "):
                line = line[len("export ") :].lstrip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            if key not in DOTENV_KEYS:
                continue
            value = _dotenv_value(value)
            if value:
                return value
    return None


def resolve_token(cli_token: str | None = None) -> str | None:
    candidates = (
        cli_token,
        os.environ.get("GOFILE_API_TOKEN"),
        os.environ.get("GOFILE_TOKEN"),
        _dotenv_token(),
    )
    for candidate in candidates:
        if candidate:
            return candidate
    return None
