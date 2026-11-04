# gofile-cli

[![pipeline status](https://gitlab.com/tigefa/gofile-cli/badges/main/pipeline.svg)](https://gitlab.com/tigefa/gofile-cli/-/commits/main)

A command-line client for the [Gofile](https://gofile.io) API: upload files and folders, and manage files, folders, accounts and direct links.

## Usage

```bash
gofile-cli file.txt               # upload a file
gofile-cli folder/                # upload every file in a folder
gofile-cli folder/ --recursive    # include subfolders
gofile-cli upload file.txt --folder-id <uuid>
```

Uploaded files print their JSON metadata (including `downloadPage`). Status and errors go to stderr.

## Common commands

```bash
gofile-cli whoami                                    # show current account
gofile-cli mkdir <parent-folder-uuid> --name mydir     # create folder
gofile-cli account getid                              # resolve token -> account
gofile-cli contents delete <uuid> --yes                # delete content
gofile-cli contents update <uuid> --name newname       # rename
gofile-cli --usage-spec                               # print usage spec
```

## Authentication

Token resolution order:
1. `--token`
2. `$GOFILE_API_TOKEN` / `$GOFILE_TOKEN`
3. `.env` in current dir or `~/.config/gofile/.env`

```ini
# .env
GOFILE_API_TOKEN=your-api-token-here
```

Keep `.env` out of version control.

## Development

```bash
uv sync
uv run gofile-cli --help
uv run gofile-cli --usage-spec > gofile.usage.kdl
```

## License

MIT
EOF
echo done