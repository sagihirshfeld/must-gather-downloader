# must-gather-downloader

An MCP server for Claude Code that downloads and analyzes must-gather logs from ReportPortal test failures.

Given a ReportPortal test log URL, it resolves the corresponding Magna logs directory, finds the must-gather tarball, downloads and extracts it locally, and provides tools to inspect cluster state — Kubernetes resources, pod logs, Ceph status, NooBaa data, and more.

## Features

- **Single tool call**: paste a ReportPortal URL, get extracted must-gather logs
- **Smart caching**: repeat calls return instantly; no double downloads
- **Parallel safe**: multiple downloads run concurrently without conflicts (file-based locking prevents races on the same test)
- **Resource retrieval**: read Kubernetes resources, Ceph outputs, and NooBaa data directly from the must-gather
- **Pod log inspection**: retrieve full pod logs or search within them with time-range and container filtering
- **Grep-like search**: search across all must-gather files for patterns
- **Test log extraction**: pull OCS-CI test execution traces from Magna deploy logs
- **AI analysis**: retrieve automated root-cause analysis for test failures
- **Auto-starts**: installs once, available in every Claude Code session

## Prerequisites

- [uv](https://docs.astral.sh/uv/) (includes `uvx`)
- ReportPortal API access (API key + base URL)
- Network access to Magna logs server

## Setup

### Install

```bash
claude mcp add must-gather \
  -s user \
  -e RP_API_KEY="<YOUR_RP_API_TOKEN>" \
  -e RP_BASE_URL="<YOUR_BASE_URL>" \
  -e RP_SSL_VERIFY="false" \
  -- \
  uvx --from "git+https://github.com/sagihirshfeld/must-gather-downloader" must-gather-downloader
```

Restart Claude Code after running this. The server starts automatically on every session — no manual steps needed.

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `RP_API_KEY` | Yes | ReportPortal Bearer token (Profile > API Keys) |
| `RP_BASE_URL` | Yes | ReportPortal instance URL, no trailing slash |
| `MUST_GATHER_CACHE_DIR` | No | Override cache directory (default: `/tmp/must-gather-cache`) |
| `RP_SSL_VERIFY` | No | SSL verification: `true` (default), `false`, or path to CA bundle |

## Tools

### Core

#### `download_must_gather`

Download and extract must-gather logs from a ReportPortal test failure.

| Parameter | Required | Description |
|---|---|---|
| `reportportal_url` | Yes | Full ReportPortal URL to a test log page |
| `force_redownload` | No | Bypass cache and re-download (default: `false`) |

**Returns:** `path`, `test_name`, `cluster_name`, `tarball_url`, `cached`, `files_count`

#### `list_must_gather_contents`

List the structure of a downloaded must-gather — namespaces, resource types, ceph data, NooBaa sections, and pod counts.

| Parameter | Required | Description |
|---|---|---|
| `must_gather_path` | Yes | The `extracted/` directory path from `download_must_gather` |

### Resource Retrieval

#### `get_must_gather_resource`

Retrieve Kubernetes resources, Ceph command output, or NooBaa resources from a must-gather. Supports cluster-scoped resources (node, pv, sc, objectbucket), namespaced resources (events, pod, configmap, secret, deployment, obc, backingstore, namespacestore, bucketclass, noobaa), Ceph data (cephhealth, cephstatus, osdtree, osddump), and NooBaa-only types (status, db_list, diagnostics, logs, cnpg). YAML resources are automatically cleaned (managedFields stripped).

| Parameter | Required | Description |
|---|---|---|
| `must_gather_path` | Yes | Path to the extracted must-gather directory |
| `resource_type` | Yes | Resource type (see above) |
| `name` | No | Specific resource name (omit to list available) |
| `namespace` | No | Namespace (required for namespaced resources) |
| `tail` | No | For events, last N events; for NooBaa logs/diagnostics, last N lines (default: all) |
| `subtree` | No | `auto` (default), `main`, or `noobaa`. Auto-detects: NooBaa-only types use noobaa, overlapping CRD types prefer noobaa if available, others use main |

### Search

#### `search_must_gather`

Grep-like search across all must-gather files (YAML resources, Ceph outputs, config files, logs). Binary files are automatically skipped.

| Parameter | Required | Description |
|---|---|---|
| `must_gather_path` | Yes | Path to the extracted must-gather directory |
| `pattern` | Yes | Regex or literal string to search for |
| `file_pattern` | No | Glob to filter files (e.g. `*.yaml`, `*.log`) |
| `max_results` | No | Maximum matches to return (default: 50) |
| `case_sensitive` | No | Case-sensitive search (default: `false`) |

### Pod Logs

#### `get_must_gather_pod_logs`

Retrieve full pod log content or search within logs for a pattern. Can list available pods (omit `pod_name`), retrieve full logs with tail/time filtering, or search for matching lines with context (when `pattern` is provided).

| Parameter | Required | Description |
|---|---|---|
| `must_gather_path` | Yes | Path to the extracted must-gather directory |
| `namespace` | Yes | Kubernetes namespace |
| `pod_name` | No | Pod name or substring (omit to list available pods) |
| `container` | No | Container name filter |
| `previous` | No | Return `previous.log` (default: `false`) |
| `tail` | No | Lines from end to return, full-log mode only (default: all) |
| `time_from` | No | Start time filter (e.g. `03:38:00`) |
| `time_to` | No | End time filter (e.g. `03:41:00`) |
| `pattern` | No | Regex or literal to search for (omit for full logs) |
| `context_lines` | No | Lines of context around each match (default: 3, search mode only) |
| `max_results` | No | Maximum matches (default: 50, search mode only) |
| `case_sensitive` | No | Case-sensitive search (default: `false`, search mode only) |

### Test Analysis

#### `get_ocs_ci_test_log`

Retrieve the OCS-CI test execution trace from the deploy log on Magna. Shows step-by-step what the test framework did — setup, teardown, assertions, and oc commands. Does not require downloading a must-gather first.

| Parameter | Required | Description |
|---|---|---|
| `reportportal_url` | Yes | Full ReportPortal URL to a test log page |
| `test_name` | Yes | Test function name (e.g. `test_bucket_notifications[default-logs-pvc]`) |
| `tail` | No | Return only the last N lines (default: all) |
| `head` | No | Return only the first N lines (default: all) |

#### `get_ai_analysis_report`

Retrieve automated AI failure analysis for a test — root cause, recommended actions, evidence, confidence, and suggested fixes.

| Parameter | Required | Description |
|---|---|---|
| `reportportal_url` | Yes | Full ReportPortal URL to a test log page |
| `test_name` | Yes | Test function name |
| `include_traceback` | No | Include traceback in results (default: `true`) |
| `include_suggested_fix` | No | Include suggested fix/bug details (default: `true`) |

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
