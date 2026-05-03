# Task 4: Implement `search_pod_logs` MCP Tool

## Goal

Add a new MCP tool `search_pod_logs` that searches within a specific pod's log files and returns only matching lines with surrounding context. This fills the gap between `get_must_gather_pod_logs` (reads entire log — expensive) and `search_must_gather` (searches all files — noisy).

## Motivation

When investigating failures, agents currently either:
1. Call `get_must_gather_pod_logs` with no tail/time limits, pulling thousands of lines into context, or
2. Use `search_must_gather` across all files, getting matches from irrelevant files.

A targeted pod-log search lets an agent say "search the noobaa-endpoint pod logs for ECONNREFUSED" and get back just the 20 relevant lines instead of 5,000.

## Existing Code to Build On

- **`src/must_gather_downloader/pod_logs.py`** — `get_must_gather_pod_logs()` already has all the logic for locating pod log files (namespace → pods dir → pod matching → container dirs → `current.log`/`previous.log`). Reuse this file-location logic.
- **`src/must_gather_downloader/search.py`** — `search_must_gather()` has the pattern-matching logic (regex compilation, binary detection, line-length capping at `_MAX_LINE_LENGTH`). Reference this for consistency.
- **`src/must_gather_downloader/text.py`** — Has `_filter_log_by_time()` and `MAX_LOG_SIZE` constants.
- **`src/must_gather_downloader/navigate.py`** — `_find_must_gather_root()` resolves the root path.
- **`src/must_gather_downloader/server.py`** — Where tools are registered on the `mcp` FastMCP instance.

## Interface

```python
def search_pod_logs(
    must_gather_path: str,
    namespace: str,
    pod_name: str,
    pattern: str,
    container: str = "",
    previous: bool = False,
    context_lines: int = 3,
    max_results: int = 50,
    case_sensitive: bool = False,
    time_from: str = "",
    time_to: str = "",
) -> str:
```

### Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `must_gather_path` | Yes | Path to the must-gather extraction |
| `namespace` | Yes | Kubernetes namespace |
| `pod_name` | Yes | Pod name or substring to match |
| `pattern` | Yes | Regex or literal string to search for |
| `container` | No | Container name filter (empty = all containers) |
| `previous` | No | Search `previous.log` instead of `current.log` |
| `context_lines` | No | Lines of context before and after each match (default 3) |
| `max_results` | No | Maximum matches to return (default 50) |
| `case_sensitive` | No | Case-sensitive search (default False) |
| `time_from` | No | Only search lines after this time |
| `time_to` | No | Only search lines before this time |

### Return Value

JSON string with structure:

```json
{
    "pattern": "ECONNREFUSED",
    "pod": "noobaa-endpoint-7f8b9c6d5-x2k4m",
    "namespace": "openshift-storage",
    "container": "endpoint",
    "log_file": "current.log",
    "matches": [
        {
            "line_number": 1523,
            "line": "2025-01-15T03:39:12 ERROR ... ECONNREFUSED ...",
            "context_before": ["line 1520...", "line 1521...", "line 1522..."],
            "context_after": ["line 1524...", "line 1525...", "line 1526..."]
        }
    ],
    "total_matches": 5,
    "total_lines": 8420,
    "truncated": false
}
```

If multiple pods match `pod_name`, search all of them and include matches from each (with the `pod` field distinguishing them). Or alternatively, return an error asking the user to be more specific — use your judgment on which is more useful (searching all matches is probably better).

If multiple containers exist for a pod and `container` is empty, search all containers' logs.

## Implementation Plan

1. **Create the function** in `src/must_gather_downloader/pod_logs.py` (colocated with the existing pod log logic) or in a new file if `pod_logs.py` gets too large.

2. **Reuse pod-log file discovery** from `get_must_gather_pod_logs` — factor out the shared logic for finding the log file paths into a helper if it isn't already factored out.

3. **Search logic**:
   - Compile the pattern (with fallback to `re.escape` for invalid regex, like `search.py` does).
   - Optionally apply time filtering first (reuse `_filter_log_by_time` from `text.py`, or filter in-stream).
   - Scan lines, collect matches with `context_lines` of surrounding context.
   - Cap line length at `_MAX_LINE_LENGTH` (from `search.py`).
   - Stop after `max_results`.

4. **Register the tool** in `server.py` following the same pattern as existing tools: import the implementation, wrap it in an `@mcp.tool` decorated function with a full docstring.

5. **Write tests** in `tests/` — create `tests/test_search_pod_logs.py`. Test at minimum:
   - Basic pattern match with context lines
   - Case-insensitive search (default)
   - Case-sensitive search
   - Time filtering combined with search
   - Pod name substring matching
   - Container filtering
   - `max_results` truncation
   - Invalid/no matches returns empty list
   - Invalid regex falls back to literal match
   - Multiple pods matching (if you implement multi-pod search)

6. **Run the full test suite**: `.venv/bin/pytest tests/ -v` — all existing tests must still pass.

## Files You'll Touch

- `src/must_gather_downloader/pod_logs.py` — add `search_pod_logs()` (and possibly refactor shared helpers)
- `src/must_gather_downloader/server.py` — register the new tool
- `tests/test_search_pod_logs.py` — new test file
- Possibly `tests/conftest.py` — if you need new shared fixtures

## Commit

Create a single commit with a descriptive message.
