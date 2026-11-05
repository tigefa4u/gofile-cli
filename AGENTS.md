# gofile-cli

## Commands
- If `mise` is available, run `mise upgrade --bump` to update `uv` in `mise.toml`.
- Install deps: `uv sync`
- Run CLI: `uv run gofile-cli ...` (entrypoint `gofile_cli:main`)
- Tests: `uv run python -m unittest discover -s tests -v`
- Regenerate usage spec: `uv run gofile-cli --usage-spec > gofile.usage.kdl`
- Lint spec: `usage lint gofile.usage.kdl --warnings-as-errors`

## Structure
- Source: `src/gofile_cli/` (`client.py` API client, `cli.py` Typer app).
- `--usage-spec` is handled in `main()` before Typer parsing.
- Default upload shortcut: a first arg that is an existing file/folder and not a known subcommand is rewritten to `upload`.

## Auth
- Token resolution: `--token` → `$GOFILE_API_TOKEN`/`$GOFILE_TOKEN` → `.env`.
- `.env` is gitignored; template is `.env.example`.

## Docs
- Use the `chrome-devtools` MCP server to read live API docs at https://gofile.io/api (e.g. `list_pages` then `take_snapshot`).

## Remotes
- `origin` → `git@gitlab.com:tigefa/gofile-cli.git` (primary; GitLab CI runs here).
- `github` → `git@github.com:tigefa4u/gofile-cli.git` (public mirror, branch `main`).
- Both repos are public. Never commit `.env` or a token — a force-add would be world-readable.
- Pushing to one remote does not update the other: push to both, i.e. `git push origin main && git push github main`.

## Gotchas
- `contents get`/`search`/`copy`/`move`/`import`/direct links are Premium-only and return `error-notPremium` for standard accounts.
- `usage lint` must pass after any CLI flag changes; keep `gofile.usage.kdl` in sync.
- `uv version <x>` bumps `pyproject.toml` and `uv.lock`; commit both, then tag `v<x>` to publish.