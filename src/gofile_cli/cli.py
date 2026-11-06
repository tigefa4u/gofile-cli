"""Command-line interface for gofile-cli."""

from __future__ import annotations

import importlib.metadata
import json
import re
import sys
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table
from typer_usage import generate

from . import client
from .auth import resolve_token

BIN_NAME = "gofile-cli"

try:
    __version__ = importlib.metadata.version("gofile-cli")
except importlib.metadata.PackageNotFoundError:  # pragma: no cover - not installed
    __version__ = "0.0.0"

_RICH_MARKUP = re.compile(r"\[(?:/?[a-z][a-z ]*|/?)\]")

app = typer.Typer(
    no_args_is_help=True,
    help="Manage files and folders on [blue]Gofile[/blue] from the command line.",
    add_completion=True,
)

account_app = typer.Typer(help="Manage Gofile accounts.")
contents_app = typer.Typer(help="Manage files and folders.")
directlinks_app = typer.Typer(help="Manage direct links (Premium).")
app.add_typer(account_app, name="account")
app.add_typer(contents_app, name="contents")
app.add_typer(directlinks_app, name="directlinks")


_REGION_HELP = (
    "Upload region ("
    + ", ".join(["auto", *client.UPLOAD_REGIONS])
    + "). Default is the closest region."
)


def _require_token(ctx: typer.Context) -> str:
    token = (ctx.obj or {}).get("token")
    if not token:
        typer.echo(
            "Error: no API token. Set --token, $GOFILE_API_TOKEN, or a .env file.",
            err=True,
        )
        raise typer.Exit(code=1)
    return token


def _fail(exc: Exception) -> typer.Exit:
    msg = str(exc)
    typer.echo(f"Error: {msg}", err=True)
    return typer.Exit(code=1)


def _print(data: Any) -> None:
    typer.echo(json.dumps(data, indent=2, default=str))


# ---------------- upload helpers ----------------


def _collect_files(path: Path, recursive: bool) -> list[Path]:
    if path.is_file():
        return [path]
    if path.is_dir():
        if recursive:
            return sorted(p for p in path.rglob("*") if p.is_file())
        return sorted(p for p in path.iterdir() if p.is_file())
    raise client.GofileError("error-file", f"not a file or folder: {path}")


def _print_uploads(
    console: Console, results: list[tuple[Path, dict[str, Any]]]
) -> None:
    table = Table(title="Uploaded files")
    table.add_column("File", style="cyan")
    table.add_column("Size", justify="right")
    table.add_column("Download page", style="green")
    table.add_column("Parent folder", style="dim")
    for f, data in results:
        table.add_row(
            f.name,
            str(data.get("size", "")),
            str(data.get("downloadPage", "")),
            str(data.get("parentFolder", "")),
        )
    console.print(table)


def _guest_token_from(data: Any) -> str | None:
    if not isinstance(data, dict):
        return None
    issued = data.get("guestToken")
    if isinstance(issued, str) and issued:
        return issued
    return None


def _print_guest_token(guest_token: str | None) -> None:
    if not guest_token:
        return
    typer.echo(
        "Guest token (save it; this account has no email):\n" + guest_token,
        err=True,
    )


def _do_upload(
    ctx: typer.Context,
    paths,
    folder_id,
    recursive,
    timeout,
    *,
    region: str | None,
    guest: bool,
) -> None:
    token = (ctx.obj or {}).get("token")
    if guest:
        if token:
            typer.echo("Error: --guest cannot be combined with a token.", err=True)
            raise typer.Exit(code=1)
        token = None
    elif not token:
        typer.echo(
            "Error: no API token. Set --token, $GOFILE_API_TOKEN, or a .env file, "
            "or pass --guest.",
            err=True,
        )
        raise typer.Exit(code=1)
    try:
        client.upload_host(region)
    except client.GofileError as exc:
        raise _fail(exc)
    files: list[Path] = []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            collected = _collect_files(p, recursive)
            if not collected:
                typer.echo(f"Error: no files found in folder: {p}", err=True)
                raise typer.Exit(code=1)
            files.extend(collected)
        elif p.is_file():
            files.append(p)
        else:
            typer.echo(f"Error: path does not exist: {p}", err=True)
            raise typer.Exit(code=1)
    if not files:
        typer.echo("Error: no files to upload.", err=True)
        raise typer.Exit(code=1)
    current_folder = folder_id
    console = Console()
    results: list[tuple[Path, dict[str, Any]]] = []
    guest_token: str | None = None
    missing_guest_token = False
    with Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}[/bold blue]"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("Uploading to Gofile", total=len(files))
        for f in files:
            progress.update(task, description=f"Uploading {f.name}")
            try:
                data = client.upload_file(
                    f,
                    token=token,
                    folder_id=current_folder,
                    region=region,
                    timeout=timeout,
                )
            except client.GofileError as exc:
                # Report what did land before failing on the file that broke:
                # without this, a mid-run drop silently loses uploads the
                # user may not be able to find again. The guest token has to
                # be printed here too, or a mid-batch failure orphans it.
                if results:
                    typer.echo(
                        f"Error: {exc} after {len(results)} of {len(files)} file(s);",
                        err=True,
                    )
                    _print_uploads(console, results)
                _print_guest_token(guest_token)
                raise _fail(exc)
            if guest and guest_token is None and not missing_guest_token:
                issued = _guest_token_from(data)
                if issued:
                    token = issued
                    guest_token = issued
                else:
                    missing_guest_token = True
                    if len(files) > 1:
                        typer.echo(
                            "Warning: upload response had no guestToken; "
                            "later files may land in a different guest account.",
                            err=True,
                        )
            if not isinstance(data, dict):
                data = {"result": data}
            results.append((f, data))
            if current_folder is None:
                current_folder = data.get("parentFolder")
            progress.advance(task)

    _print_guest_token(guest_token)
    _print_uploads(console, results)


# ---------------- callback ----------------


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"{BIN_NAME} {__version__}")
        raise typer.Exit()


@app.callback()
def _callback(
    ctx: typer.Context,
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            "-V",
            callback=_version_callback,
            is_eager=True,
            help="Print the version and exit.",
        ),
    ] = False,
    token: Annotated[
        str | None,
        typer.Option(
            "--token",
            "-t",
            help="Gofile account token. Also $GOFILE_API_TOKEN or .env.",
        ),
    ] = None,
):
    ctx.ensure_object(dict)
    ctx.obj = {"token": resolve_token(token)}


# ---------------- top-level: upload ----------------


@app.command()
def upload(
    ctx: typer.Context,
    paths: Annotated[
        list[Path], typer.Argument(help="File(s) or folder(s) to upload.")
    ],
    folder_id: Annotated[
        str | None,
        typer.Option(
            "--folder-id",
            "-f",
            help="Destination folder UUID. Omit to create a new public folder at account root.",
        ),
    ] = None,
    recursive: Annotated[
        bool,
        typer.Option("--recursive", "-r", help="Upload files in subfolders too."),
    ] = False,
    region: Annotated[
        str | None,
        typer.Option("--region", help=_REGION_HELP),
    ] = None,
    guest: Annotated[
        bool,
        typer.Option(
            "--guest",
            help=(
                "Upload without an account. Prints the new guest token and "
                "reuses it for every file in the batch. Refuses when a token is set."
            ),
        ),
    ] = False,
    timeout: Annotated[
        float, typer.Option("--timeout", help="Request timeout in seconds.")
    ] = 120.0,
):
    """Upload one or more files or folders to Gofile."""
    _do_upload(
        ctx,
        paths,
        folder_id,
        recursive,
        timeout,
        region=region,
        guest=guest,
    )


# ---------------- account ----------------


@account_app.command("create")
def account_create(
    ctx: typer.Context,
    email: Annotated[
        str | None,
        typer.Option(
            "--email",
            "-e",
            help="Email for a standard, recoverable account. Omit for a guest account.",
        ),
    ] = None,
):
    """Create a Gofile account (guest if no email)."""
    token = (ctx.obj or {}).get("token")
    try:
        data = client.create_account(email=email, token=token)
    except client.GofileError as exc:
        raise _fail(exc)
    _print(data)


@account_app.command("getid")
def account_getid(ctx: typer.Context):
    """Resolve the account behind the current token."""
    token = _require_token(ctx)
    try:
        data = client.get_account_id(token=token)
    except client.GofileError as exc:
        raise _fail(exc)
    _print(data)


@account_app.command("show")
def account_show(
    ctx: typer.Context,
    account_id: Annotated[
        str | None, typer.Argument(help="Account UUID. Omit to resolve from token.")
    ] = None,
):
    """Show full account details."""
    token = _require_token(ctx)
    if not account_id:
        try:
            info = client.get_account_id(token=token)
        except client.GofileError as exc:
            raise _fail(exc)
        account_id = info.get("id") if isinstance(info, dict) else None
        if not account_id:
            typer.echo("Error: could not resolve account id.", err=True)
            raise typer.Exit(code=1)
    try:
        data = client.get_account(account_id, token=token)
    except client.GofileError as exc:
        raise _fail(exc)
    _print(data)


@account_app.command("reset-token")
def account_reset_token(
    ctx: typer.Context,
    account_id: Annotated[str, typer.Argument(help="Account UUID.")],
    yes: Annotated[
        bool, typer.Option("--yes", "-y", help="Confirm token reset.")
    ] = False,
):
    """Invalidate the current token and email a new one (never for guests)."""
    if not yes:
        typer.echo(
            "Refusing without --yes: this invalidates the current token immediately.",
            err=True,
        )
        raise typer.Exit(code=1)
    token = _require_token(ctx)
    try:
        data = client.reset_token(account_id, token=token)
    except client.GofileError as exc:
        raise _fail(exc)
    _print(data)


# ---------------- contents ----------------


@contents_app.command("create-folder")
def contents_create_folder(
    ctx: typer.Context,
    parent_folder_id: Annotated[
        str, typer.Argument(help="Parent folder UUID (root folder UUID for top-level).")
    ],
    name: Annotated[
        str | None,
        typer.Option(
            "--name", "-n", help="Folder display name. Omit to auto-generate."
        ),
    ] = None,
    public: Annotated[
        bool | None,
        typer.Option(
            "--public/--private", help="Shareable by link. Omit to inherit parent."
        ),
    ] = None,
):
    """Create a folder inside a parent folder."""
    token = _require_token(ctx)
    try:
        data = client.create_folder(
            parent_folder_id, folder_name=name, public=public, token=token
        )
    except client.GofileError as exc:
        raise _fail(exc)
    _print(data)


@contents_app.command("get")
def contents_get(
    ctx: typer.Context,
    content_id: Annotated[str, typer.Argument(help="Folder/file UUID or share code.")],
    password: Annotated[
        str | None, typer.Option("--password", help="SHA-256 hash of folder password.")
    ] = None,
    page: Annotated[
        int | None, typer.Option("--page", help="Page number (1-based).")
    ] = None,
    page_size: Annotated[
        int | None, typer.Option("--page-size", help="Items per page.")
    ] = None,
    sort_field: Annotated[
        str | None,
        typer.Option("--sort-field", help="createTime|name|size|downloads|mimetype."),
    ] = None,
    sort_direction: Annotated[
        int | None, typer.Option("--sort-direction", help="1 ascending, -1 descending.")
    ] = None,
    content_filter: Annotated[
        str | None,
        typer.Option(
            "--filter", help="Case-insensitive substring filter on child names/tags."
        ),
    ] = None,
    maxdepth: Annotated[
        int | None,
        typer.Option("--maxdepth", help="Nested children depth 1-16 (default 1)."),
    ] = None,
):
    """Read a folder (metadata + children) or a single file's metadata (Premium)."""
    token = _require_token(ctx)
    try:
        data, meta = client.get_content(
            content_id,
            token=token,
            password=password,
            page=page,
            page_size=page_size,
            sort_field=sort_field,
            sort_direction=sort_direction,
            content_filter=content_filter,
            maxdepth=maxdepth,
        )
    except client.GofileError as exc:
        raise _fail(exc)
    out = {"data": data}
    if meta is not None:
        out["metadata"] = meta
    _print(out)


@contents_app.command("update")
def contents_update(
    ctx: typer.Context,
    content_id: Annotated[
        str, typer.Argument(help="Content UUID (share codes not accepted).")
    ],
    name: Annotated[
        str | None, typer.Option("--name", help="New content name (max 255).")
    ] = None,
    description: Annotated[
        str | None,
        typer.Option(
            "--description",
            help="Folder description (markdown, max 2000). Empty removes.",
        ),
    ] = None,
    tags: Annotated[
        str | None,
        typer.Option("--tags", help="Comma-separated tags. Empty removes all."),
    ] = None,
    public: Annotated[
        bool | None,
        typer.Option("--public/--no-public", help="Make folder public/private."),
    ] = None,
    password: Annotated[
        str | None,
        typer.Option("--password", help="Folder password 4-100 chars; empty removes."),
    ] = None,
    expiry: Annotated[
        int | None,
        typer.Option("--expiry", help="Expiration Unix timestamp; 0 removes."),
    ] = None,
    mod_time: Annotated[
        int | None, typer.Option("--mod-time", help="Modification time Unix timestamp.")
    ] = None,
    delete_after_expiry: Annotated[
        bool | None,
        typer.Option(
            "--delete-after-expiry",
            help="Premium: permanently delete on expiry. Requires --expiry.",
        ),
    ] = None,
):
    """Update one or more attributes of a file or folder (one API call per attribute)."""
    token = _require_token(ctx)
    if delete_after_expiry is not None and expiry is None:
        typer.echo(
            "Warning: --delete-after-expiry is ignored without --expiry; "
            "the API only pairs it with an expiry value.",
            err=True,
        )
    updates: list[tuple[str, Any]] = []
    if name is not None:
        updates.append(("name", name))
    if description is not None:
        updates.append(("description", description))
    if tags is not None:
        updates.append(("tags", tags))
    if public is not None:
        updates.append(("public", public))
    if password is not None:
        updates.append(("password", password))
    if expiry is not None:
        updates.append(("expiry", expiry if expiry != 0 else ""))
    if mod_time is not None:
        updates.append(("modTime", mod_time))
    if not updates:
        typer.echo("Error: no attribute provided.", err=True)
        raise typer.Exit(code=1)
    results = []
    for attr, val in updates:
        try:
            extra = {}
            if attr == "expiry" and delete_after_expiry is not None:
                extra["delete_after_expiry"] = delete_after_expiry
            data = client.update_content(content_id, attr, val, token=token, **extra)
        except client.GofileError as exc:
            raise _fail(exc)
        results.append({"attribute": attr, "data": data})
    _print(results if len(results) > 1 else results[0]["data"])


@contents_app.command("delete")
def contents_delete(
    ctx: typer.Context,
    contents_ids: Annotated[list[str], typer.Argument(help="Content UUIDs to delete.")],
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Confirm deletion.")] = False,
):
    """Delete files and/or folders (recursive for folders)."""
    if not yes:
        typer.echo("Refusing without --yes.", err=True)
        raise typer.Exit(code=1)
    token = _require_token(ctx)
    try:
        data = client.delete_contents(contents_ids, token=token)
    except client.GofileError as exc:
        raise _fail(exc)
    _print(data)


@contents_app.command("copy")
def contents_copy(
    ctx: typer.Context,
    contents_ids: Annotated[list[str], typer.Argument(help="Content UUIDs to copy.")],
    to: Annotated[str, typer.Option("--to", "-t", help="Destination folder UUID.")],
    password: Annotated[
        str | None, typer.Option("--password", help="SHA-256 hash of source password.")
    ] = None,
):
    """Copy files/folders into a destination folder (Premium)."""
    token = _require_token(ctx)
    try:
        data = client.copy_contents(contents_ids, to, password=password, token=token)
    except client.GofileError as exc:
        raise _fail(exc)
    _print(data)


@contents_app.command("move")
def contents_move(
    ctx: typer.Context,
    contents_ids: Annotated[list[str], typer.Argument(help="Content UUIDs to move.")],
    to: Annotated[str, typer.Option("--to", "-t", help="Destination folder UUID.")],
):
    """Move files/folders into another folder (Premium)."""
    token = _require_token(ctx)
    try:
        data = client.move_contents(contents_ids, to, token=token)
    except client.GofileError as exc:
        raise _fail(exc)
    _print(data)


@contents_app.command("import")
def contents_import(
    ctx: typer.Context,
    contents_ids: Annotated[list[str], typer.Argument(help="Content UUIDs to import.")],
    password: Annotated[
        str | None, typer.Option("--password", help="SHA-256 hash of source password.")
    ] = None,
):
    """Import shared content into your account (Premium)."""
    token = _require_token(ctx)
    try:
        data = client.import_contents(contents_ids, password=password, token=token)
    except client.GofileError as exc:
        raise _fail(exc)
    _print(data)


@contents_app.command("search")
def contents_search(
    ctx: typer.Context,
    content_id: Annotated[
        str, typer.Argument(help="Folder UUID or share code to search in.")
    ],
    searched_string: Annotated[
        str, typer.Argument(help="Text to match against names and tags.")
    ],
    password: Annotated[
        str | None, typer.Option("--password", help="SHA-256 hash of folder password.")
    ] = None,
    create_time_from: Annotated[
        int | None,
        typer.Option(
            "--from", help="Only content created at/after this Unix timestamp."
        ),
    ] = None,
    create_time_to: Annotated[
        int | None,
        typer.Option(
            "--to", help="Only content created at/before this Unix timestamp."
        ),
    ] = None,
):
    """Search a folder recursively by name or tags (Premium)."""
    token = _require_token(ctx)
    try:
        data = client.search_contents(
            content_id,
            searched_string,
            password=password,
            create_time_from=create_time_from,
            create_time_to=create_time_to,
            token=token,
        )
    except client.GofileError as exc:
        raise _fail(exc)
    _print(data)


# ---------------- direct links ----------------


@directlinks_app.command("create")
def directlinks_create(
    ctx: typer.Context,
    content_id: Annotated[str, typer.Argument(help="Content UUID.")],
    expire_time: Annotated[
        int | None,
        typer.Option("--expire", help="Expiry Unix timestamp. Omit for never."),
    ] = None,
    ips: Annotated[
        list[str] | None, typer.Option("--ip", help="Allowed IPv4 (repeatable).")
    ] = None,
    domains_allowed: Annotated[
        list[str] | None,
        typer.Option("--domain-allowed", help="Allowed referring domain (repeatable)."),
    ] = None,
    domains_blocked: Annotated[
        list[str] | None,
        typer.Option("--domain-blocked", help="Blocked referring domain (repeatable)."),
    ] = None,
    auth: Annotated[
        list[str] | None,
        typer.Option("--auth", help="HTTP basic auth 'user:pass' (repeatable)."),
    ] = None,
):
    """Create a direct link (Premium)."""
    token = _require_token(ctx)
    try:
        data = client.create_direct_link(
            content_id,
            expire_time=expire_time,
            source_ips_allowed=ips,
            domains_allowed=domains_allowed,
            domains_blocked=domains_blocked,
            auth=auth,
            token=token,
        )
    except client.GofileError as exc:
        raise _fail(exc)
    _print(data)


@directlinks_app.command("update")
def directlinks_update(
    ctx: typer.Context,
    content_id: Annotated[str, typer.Argument(help="Content UUID.")],
    direct_link_id: Annotated[str, typer.Argument(help="Direct link UUID.")],
    expire_time: Annotated[
        int | None,
        typer.Option("--expire", help="New expiry Unix timestamp; 4102444800 = never."),
    ] = None,
    ips: Annotated[
        list[str] | None,
        typer.Option("--ip", help="Replacement IPv4 allowlist (repeatable)."),
    ] = None,
    domains_allowed: Annotated[
        list[str] | None,
        typer.Option(
            "--domain-allowed", help="Replacement allowed domains (repeatable)."
        ),
    ] = None,
    domains_blocked: Annotated[
        list[str] | None,
        typer.Option(
            "--domain-blocked", help="Replacement blocked domains (repeatable)."
        ),
    ] = None,
    auth: Annotated[
        list[str] | None,
        typer.Option("--auth", help="Replacement 'user:pass' pairs (repeatable)."),
    ] = None,
    clear_ips: Annotated[
        bool, typer.Option("--clear-ips", help="Remove IP allowlist.")
    ] = False,
    clear_domains_allowed: Annotated[
        bool, typer.Option("--clear-domains-allowed", help="Remove allowed domains.")
    ] = False,
    clear_domains_blocked: Annotated[
        bool, typer.Option("--clear-domains-blocked", help="Remove blocked domains.")
    ] = False,
    clear_auth: Annotated[
        bool, typer.Option("--clear-auth", help="Remove auth.")
    ] = False,
):
    """Update a direct link (Premium). Omitted fields keep their current value."""
    token = _require_token(ctx)
    kwargs: dict[str, Any] = {}
    if expire_time is not None:
        kwargs["expire_time"] = expire_time
    if ips is not None:
        kwargs["source_ips_allowed"] = ips
    if clear_ips:
        kwargs["source_ips_allowed"] = []
    if domains_allowed is not None:
        kwargs["domains_allowed"] = domains_allowed
    if clear_domains_allowed:
        kwargs["domains_allowed"] = []
    if domains_blocked is not None:
        kwargs["domains_blocked"] = domains_blocked
    if clear_domains_blocked:
        kwargs["domains_blocked"] = []
    if auth is not None:
        kwargs["auth"] = auth
    if clear_auth:
        kwargs["auth"] = []
    try:
        data = client.update_direct_link(
            content_id, direct_link_id, token=token, **kwargs
        )
    except client.GofileError as exc:
        raise _fail(exc)
    _print(data)


@directlinks_app.command("delete")
def directlinks_delete(
    ctx: typer.Context,
    content_id: Annotated[str, typer.Argument(help="Content UUID.")],
    direct_link_id: Annotated[str, typer.Argument(help="Direct link UUID.")],
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Confirm deletion.")] = False,
):
    """Delete a direct link (Premium)."""
    if not yes:
        typer.echo("Refusing without --yes.", err=True)
        raise typer.Exit(code=1)
    token = _require_token(ctx)
    try:
        data = client.delete_direct_link(content_id, direct_link_id, token=token)
    except client.GofileError as exc:
        raise _fail(exc)
    _print(data)


# ---------------- convenience aliases ----------------


@app.command("whoami")
def whoami(ctx: typer.Context):
    """Print the current account's full details."""
    ctx.invoke(account_show, ctx=ctx, account_id=None)


# Same callbacks as the contents commands, so an alias cannot drop a flag.
app.command("mkdir", help="Alias for 'contents create-folder'.")(contents_create_folder)
app.command("rm", help="Alias for 'contents delete'.")(contents_delete)
app.command("ls", help="Alias for 'contents get'.")(contents_get)


# ---------------- usage spec ----------------


def usage_spec() -> str:
    spec = _RICH_MARKUP.sub("", generate(app, BIN_NAME))
    # Patch known typer_usage gaps here so the committed spec stays exactly
    # reproducible via `uv run gofile-cli --usage-spec` (CI diffs this output):
    # 1. It emits the boolean default of the --version option as the spec
    #    version (e.g. `version False`); replace it with the real version.
    spec = re.sub(r"(?m)^version .+$", f'version "{__version__}"', spec, count=1)
    if not re.search(r'(?m)^version "', spec):
        spec = re.sub(
            r"(?m)^(bin \S+)$", rf'\g<1>\nversion "{__version__}"', spec, count=1
        )
    # 2. It only detects negations shaped like "--no-...", so Typer's
    #    --public/--private pairs lose their negative form; add it explicitly.
    #    mkdir and contents create-folder share one callback, so one string.
    spec = spec.replace(
        'flag --public help="Shareable by link. Omit to inherit parent."',
        'flag --public negate=--private help="Shareable by link. Omit to inherit parent."',
    )
    return spec


def _known_commands() -> set[str]:
    """Top-level command names, derived from the Typer app.

    Derived rather than hardcoded so a new command automatically opts out of
    the bare-path-is-an-upload inference in main(); a hand-maintained list
    would silently break new commands that share a name with a local file.
    """
    names: set[str] = set()
    for info in app.registered_commands:
        # Typer derives the command name from the callback when not explicit;
        # fall back to the function name, which is what Typer uses.
        name = getattr(info, "name", None) or getattr(info.callback, "__name__", "")
        if name:
            names.add(name)
    for group in app.registered_groups:
        name = getattr(group, "name", None)
        if name:
            names.add(name)
    return names


KNOWN_COMMANDS = _known_commands()


def main() -> None:
    for argument in sys.argv[1:]:
        if argument == "--":
            break
        if argument == "--usage-spec":
            print(usage_spec())
            raise SystemExit(0)
    args = sys.argv[1:]
    if (
        args
        and not args[0].startswith("-")
        and args[0] not in KNOWN_COMMANDS
        and Path(args[0]).exists()
    ):
        sys.argv = [sys.argv[0], "upload"] + args
    app()


if __name__ == "__main__":
    main()
