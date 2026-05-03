"""OCS-CI per-test log retrieval from Magna directory listings."""

import json
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from .config import _get_config, _ssl_verify
from .reportportal import (
    _extract_hrefs,
    _extract_ids,
    _fetch_html_lines,
    _resolve_magna_metadata,
)
from .resource_utils import truncate_log_from_tail
from .text import MAX_LOG_SIZE


def _normalize_test_name(test_name: str) -> str:
    """Normalize a test name for directory matching.

    OCS-CI replaces brackets with dashes in directory names:
    ``test_foo[bar-baz]`` becomes ``test_foo-bar-baz``.

    Args:
        test_name: Raw test name, possibly with bracket parameters.

    Returns:
        Normalized name suitable for directory path matching.
    """
    return test_name.replace("[", "-").replace("]", "")


def _recursive_search(base_url: str, target: str, api_key: str) -> list[str]:
    """Recursively search Apache directory listings for a directory name.

    Walks the directory tree starting from *base_url* and returns URLs of
    directories whose name contains *target* as a substring.

    Args:
        base_url: URL of the directory to start searching from.
        target: Normalized test name to search for (substring match).
        api_key: Bearer token for Magna.

    Returns:
        List of full URLs to directories matching the target.
    """
    lines = _fetch_html_lines(base_url, api_key)
    hrefs = _extract_hrefs(lines)

    subdirs = [h for h in hrefs if h.endswith("/") and not h.startswith("?") and not h.startswith("/")]

    matches: list[str] = []
    for subdir in subdirs:
        clean = subdir.rstrip("/")
        if target in clean:
            matches.append(f"{base_url.rstrip('/')}/{subdir}")
        else:
            matches.extend(_recursive_search(f"{base_url.rstrip('/')}/{subdir}", target, api_key))
    return matches


def _find_test_log_url(
    logs_url_root: str,
    test_name: str,
    api_key: str,
) -> tuple[str, str]:
    """Find the OCS-CI per-test log file URL by searching ocs-ci-logs-* directories.

    Args:
        logs_url_root: Magna base URL for the launch (contains ``logs/``).
        test_name: Raw test name (will be normalized internally).
        api_key: Bearer token for Magna.

    Returns:
        Tuple of (log_file_url, ocs_ci_dir_name).

    Raises:
        ValueError: If no ``ocs-ci-logs`` directories exist, the test is
            not found, or multiple tests match ambiguously.
    """
    normalized = _normalize_test_name(test_name)
    logs_page = f"{logs_url_root.rstrip('/')}/logs/"

    lines = _fetch_html_lines(logs_page, api_key)
    hrefs = _extract_hrefs(lines)
    ocs_ci_dirs = [h for h in hrefs if h.startswith("ocs-ci-logs")]

    if not ocs_ci_dirs:
        available = [h for h in hrefs if h.endswith("/") and not h.startswith("?") and not h.startswith("/")]
        raise ValueError(f"No ocs-ci-logs directories found in the Magna logs page. Available entries: {available}")

    all_matches: list[tuple[str, str]] = []

    def _search_dir(ocs_ci_dir: str) -> list[tuple[str, str]]:
        tests_url = f"{logs_page}{ocs_ci_dir}tests/"
        try:
            found = _recursive_search(tests_url, normalized, api_key)
        except requests.HTTPError:
            return []
        results = []
        for match_url in found:
            log_url = f"{match_url.rstrip('/')}/logs"
            results.append((log_url, ocs_ci_dir.rstrip("/")))
        return results

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(_search_dir, d): d for d in ocs_ci_dirs}
        for future in as_completed(futures):
            all_matches.extend(future.result())

    if not all_matches:
        raise ValueError(
            f"Test '{test_name}' (normalized: '{normalized}') not found in any "
            f"ocs-ci-logs directory. Searched: {[d.rstrip('/') for d in ocs_ci_dirs]}"
        )

    if len(all_matches) > 1:
        paths = [m[0] for m in all_matches]
        raise ValueError(f"Multiple matches found for '{test_name}'. Please be more specific.\nMatches: {paths}")

    return all_matches[0]


def _fetch_and_filter_log(
    log_url: str,
    api_key: str,
    exclude_debug: bool = True,
    tail: int = 0,
    head: int = 0,
) -> tuple[str, dict]:
    """Fetch a log file from Magna and apply filtering.

    Args:
        log_url: URL to the per-test logs file.
        api_key: Bearer token for Magna.
        exclude_debug: If True, filter out DEBUG-level lines.
        tail: Keep only the last N lines (0 = all).
        head: Keep only the first N lines (0 = all).

    Returns:
        Tuple of (filtered_content, metadata_dict).

    Raises:
        ValueError: If both head and tail are non-zero.
    """
    if head > 0 and tail > 0:
        raise ValueError(
            "Cannot specify both head and tail. Use head to see the beginning of the log, or tail to see the end."
        )

    headers = {"Accept": "text/plain"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    resp = requests.get(log_url, headers=headers, timeout=300, verify=_ssl_verify())
    resp.raise_for_status()

    raw_lines = resp.text.splitlines()
    total_lines_raw = len(raw_lines)

    if exclude_debug:
        filtered_lines = [line for line in raw_lines if "- DEBUG -" not in line]
    else:
        filtered_lines = raw_lines
    total_lines_after_filter = len(filtered_lines)

    if head > 0:
        filtered_lines = filtered_lines[:head]
    elif tail > 0:
        filtered_lines = filtered_lines[-tail:]

    content = "\n".join(filtered_lines)
    if filtered_lines:
        content += "\n"

    content, truncated = truncate_log_from_tail(content, max_size=MAX_LOG_SIZE)

    meta = {
        "total_lines_raw": total_lines_raw,
        "total_lines_after_filter": total_lines_after_filter,
        "lines_returned": len(content.splitlines()),
        "truncated": truncated,
    }
    return content, meta


def get_ocs_ci_test_log(
    reportportal_url: str,
    test_name: str,
    exclude_debug: bool = True,
    tail: int = 0,
    head: int = 0,
) -> str:
    """Retrieve the OCS-CI per-test log from a ReportPortal launch.

    Given a ReportPortal URL and test name, resolves the Magna logs
    directory, finds the ``ocs-ci-logs`` per-test log file, downloads it,
    and returns its content with optional filtering.

    The per-test log contains DEBUG-level output including full YAML dumps
    from ``oc`` commands. By default, DEBUG lines are filtered out to save
    tokens. Set ``exclude_debug=False`` when you need to examine:

    - Full ``oc get`` command output (Pod specs, StorageCluster YAML, PVC
      details)
    - Resource configuration verification (what was actually applied vs
      expected)
    - Command return codes and raw stdout/stderr content
    - Ceph internal status dumps and OSD diagnostics

    DEBUG logs are large (often 60+ MB) because they include full YAML
    dumps from every ``oc`` command. With filtering on (default), only
    INFO, WARNING, ERROR, and custom OCS-CI levels (TEST_STEP, ASSERTION)
    are returned.

    Args:
        reportportal_url: Full ReportPortal URL to a test log page
            (must contain '/launches/' and '/log').
        test_name: Test function name, e.g.
            ``'test_bucket_notifications[default-logs-pvc]'``.
            Supports partial/substring matching against directory names.
        exclude_debug: Filter out DEBUG-level log lines (default True).
        tail: Return only the last N lines after filtering (0 = all).
        head: Return only the first N lines after filtering (0 = all).

    Returns:
        JSON string with test log content and metadata.
    """
    try:
        api_key, base_url, _cache_dir = _get_config()
        launch_id, test_item_id = _extract_ids(reportportal_url)

        meta = _resolve_magna_metadata(launch_id, test_item_id, api_key, base_url)

        log_url, ocs_ci_dir = _find_test_log_url(meta["logs_url_root"], test_name, api_key)

        content, log_meta = _fetch_and_filter_log(log_url, api_key, exclude_debug, tail, head)

        return json.dumps(
            {
                "test_name": test_name,
                "log_url": log_url,
                "ocs_ci_dir": ocs_ci_dir,
                "exclude_debug": exclude_debug,
                "total_lines_raw": log_meta["total_lines_raw"],
                "total_lines_after_filter": log_meta["total_lines_after_filter"],
                "lines_returned": log_meta["lines_returned"],
                "truncated": log_meta["truncated"],
                "content": content,
            }
        )
    except (ValueError, requests.HTTPError) as e:
        return json.dumps({"error": str(e)})
