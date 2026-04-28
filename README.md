# must-gather-downloader

An MCP server for Claude Code that downloads and extracts must-gather logs from ReportPortal test failures.

Given a ReportPortal test log URL, it resolves the corresponding Magna logs directory, finds the must-gather tarball, downloads and extracts it locally, and returns the path so Claude can analyze the logs.

## Features

- **Single tool call**: paste a ReportPortal URL, get extracted must-gather logs
- **Smart caching**: repeat calls return instantly; no double downloads
- **Parallel safe**: multiple downloads run concurrently without conflicts (file-based locking prevents races on the same test)
- **Auto-starts**: installs once, available in every Claude Code session

## Prerequisites

- Python 3.10+
- ReportPortal API access (API key + base URL)
- Network access to Magna logs server

## Setup

### 1. Register with Claude Code

```bash
claude mcp add --scope user --transport stdio must-gather \
  -- uvx --from "git+https://github.com/sagihirshfeld/must-gather-downloader" \
  must-gather-downloader
```

### 2. Configure environment variables

Edit `~/.claude.json` and add env vars to the server entry:

```json
{
  "mcpServers": {
    "must-gather": {
      "command": "uvx",
      "args": [
        "--from", "git+https://github.com/sagihirshfeld/must-gather-downloader",
        "must-gather-downloader"
      ],
      "env": {
        "RP_API_KEY": "<your-reportportal-api-key>",
        "RP_BASE_URL": "<your-reportportal-base-url>"
      }
    }
  }
}
```

### 3. Restart Claude Code

The server starts automatically on session launch. No manual steps needed after initial setup.

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `RP_API_KEY` | Yes | ReportPortal Bearer token (Profile > API Keys) |
| `RP_BASE_URL` | Yes | ReportPortal instance URL, no trailing slash |
| `MUST_GATHER_CACHE_DIR` | No | Override cache directory (default: `/tmp/must-gather-cache`) |

## Tools

### `download_must_gather`

Download and extract must-gather logs from a ReportPortal test failure.

**Parameters:**
- `reportportal_url` (required) — full ReportPortal URL to a test log page
- `force_redownload` (optional, default `false`) — bypass cache and re-download

**Returns:** JSON with `path`, `test_name`, `cluster_name`, `tarball_url`, `cached`, `files_count`

### `list_must_gather_cache`

List all cached must-gather extractions with test names, paths, timestamps, and sizes.

## Cache Structure

```
/tmp/must-gather-cache/
├── {test_item_id}/
│   ├── .lock              # prevents parallel double-downloads
│   ├── metadata.json      # test name, cluster, tarball URL, timestamp
│   ├── *.tar.gz           # original tarball (kept for re-use)
│   └── extracted/         # extracted must-gather contents
```

Cache lives under `/tmp` and is cleared on reboot. Override with `MUST_GATHER_CACHE_DIR`.

## Local Development

```bash
git clone https://github.com/sagihirshfeld/must-gather-downloader.git
cd must-gather-downloader
pip install -e .

# Set env vars
export RP_API_KEY="your-key"
export RP_BASE_URL="https://reportportal.example.com"

# Run the server
must-gather-downloader
```
