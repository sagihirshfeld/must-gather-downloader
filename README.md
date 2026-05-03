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

- Python 3.12+
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

#### `list_must_gather_cache`

List all cached must-gather extractions with test names, paths, timestamps, and sizes.

#### `list_must_gather_contents`

List the structure of a downloaded must-gather — namespaces, resource types, ceph data, NooBaa sections, and pod counts.

| Parameter | Required | Description |
|---|---|---|
| `must_gather_path` | Yes | The `extracted/` directory path from `download_must_gather` |

### Resource Retrieval

#### `get_must_gather_resource`

Retrieve Kubernetes resources or Ceph command output from a must-gather. Supports cluster-scoped resources (node, pv, sc, objectbucket), namespaced resources (events, pod, configmap, secret, deployment, obc, backingstore, namespacestore, bucketclass, noobaa), and Ceph data (cephhealth, cephstatus, osdtree, osddump). YAML resources are automatically cleaned (managedFields stripped).

| Parameter | Required | Description |
|---|---|---|
| `must_gather_path` | Yes | Path to the extracted must-gather directory |
| `resource_type` | Yes | Resource type (see above) |
| `name` | No | Specific resource name (omit to list available) |
| `namespace` | No | Namespace (required for namespaced resources) |
| `tail` | No | For events, return only the last N (default: all) |

#### `get_noobaa_resource`

Retrieve NooBaa-specific resources: CLI status, diagnostics tarballs, operator logs, CNPG database info, and NooBaa CRD YAMLs (backingstores, namespacestores, bucketclasses, OBCs).

| Parameter | Required | Description |
|---|---|---|
| `must_gather_path` | Yes | Path to the extracted must-gather directory |
| `resource_type` | Yes | `status`, `db_list`, `diagnostics`, `logs`, `cnpg`, or CRD types (`obc`, `bs`, `ns_store`, `bc`, `noobaa`) |
| `name` | No | Specific resource or file name (omit to list available) |
| `namespace` | No | Namespace for CRD resources |
| `tail` | No | For logs, return only the last N lines (default: all) |

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

#### `search_pod_logs`

Targeted search within pod logs — returns matching lines with surrounding context. Combines pod-log file discovery with pattern matching.

| Parameter | Required | Description |
|---|---|---|
| `must_gather_path` | Yes | Path to the extracted must-gather directory |
| `namespace` | Yes | Kubernetes namespace |
| `pod_name` | Yes | Pod name or substring to match |
| `pattern` | Yes | Regex or literal string to search for |
| `container` | No | Container name filter |
| `previous` | No | Search `previous.log` instead (default: `false`) |
| `context_lines` | No | Lines of context around each match (default: 3) |
| `max_results` | No | Maximum matches (default: 50) |
| `case_sensitive` | No | Case-sensitive search (default: `false`) |
| `time_from` | No | Start time filter (e.g. `03:38:00`) |
| `time_to` | No | End time filter (e.g. `03:41:00`) |

### Pod Logs

#### `get_must_gather_pod_logs`

Retrieve full pod log content. Can list available pods (omit `pod_name`) or retrieve logs with container, tail, and time-range filtering.

| Parameter | Required | Description |
|---|---|---|
| `must_gather_path` | Yes | Path to the extracted must-gather directory |
| `namespace` | Yes | Kubernetes namespace |
| `pod_name` | No | Pod name or substring (omit to list available pods) |
| `container` | No | Container name filter |
| `previous` | No | Return `previous.log` (default: `false`) |
| `tail` | No | Lines from end to return (default: all) |
| `time_from` | No | Start time filter (e.g. `03:38:00`) |
| `time_to` | No | End time filter (e.g. `03:41:00`) |

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
