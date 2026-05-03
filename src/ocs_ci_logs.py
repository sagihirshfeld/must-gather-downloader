"""OCS-CI test log retrieval from deploy logs on Magna."""

import json
import re

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

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_DEPLOY_LOG_PREFIX = "deploy-ocs-cluster-build"


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def _is_test_header(line: str, next_line: str) -> bool:
    """Check if line + next_line form a pytest test header."""
    clean = _strip_ansi(line)
    clean_next = _strip_ansi(next_line)
    return "] tests/" in clean and ".py::" in clean and "live log setup" in clean_next


def _find_deploy_log_url(logs_url_root: str, api_key: str) -> tuple[str, str]:
    """Find the deploy log file URL from the Magna logs root directory.

    Scans ``logs_url_root`` directly for files starting with
    ``deploy-ocs-cluster-build`` and ending in ``.log``.  If multiple
    exist, picks the largest by parsing sizes from the Apache directory
    listing HTML.

    Args:
        logs_url_root: Magna logs root URL (deploy logs live here
            alongside ``failed_testcase`` directories).
        api_key: Bearer token for Magna.

    Returns:
        Tuple of (log_file_url, log_filename).

    Raises:
        ValueError: If no deploy log file is found.
    """
    logs_page = f"{logs_url_root.rstrip('/')}/"
    lines = _fetch_html_lines(logs_page, api_key)
    hrefs = _extract_hrefs(lines)

    candidates = [h for h in hrefs if h.startswith(_DEPLOY_LOG_PREFIX) and h.endswith(".log")]

    if not candidates:
        available = [h for h in hrefs if h.endswith(".log")]
        raise ValueError(
            f"No deploy log file (starting with '{_DEPLOY_LOG_PREFIX}') found. Available .log files: {available}"
        )

    if len(candidates) == 1:
        filename = candidates[0]
    else:
        size_map: dict[str, float] = {}
        for line in lines:
            for c in candidates:
                if c in line:
                    m = re.search(r"<td[^>]*>\s*([\d.]+)([KMG])\s*</td>", line)
                    if m:
                        val = float(m.group(1))
                        unit = m.group(2)
                        if unit == "K":
                            val *= 1024
                        elif unit == "M":
                            val *= 1024 * 1024
                        elif unit == "G":
                            val *= 1024 * 1024 * 1024
                        size_map[c] = val
        if size_map:
            filename = max(size_map, key=size_map.get)
        else:
            filename = candidates[0]

    return f"{logs_page}{filename}", filename


def _extract_test_section(lines: list[str], test_name: str) -> list[str]:
    """Extract lines belonging to a specific test from the full deploy log.

    Finds all sections where ``test_name`` appears in a pytest test header
    (a line containing the test nodeid followed by a "live log setup" line).
    Each section runs from the header line up to (but not including) the
    next test header.

    Args:
        lines: All lines from the deploy log.
        test_name: Test name to search for (substring match against nodeid).

    Returns:
        Extracted lines for the test (may include multiple sections separated
        by a marker line).

    Raises:
        ValueError: If the test is not found in the log.
    """
    sections: list[tuple[int, int]] = []

    for i in range(len(lines) - 1):
        clean = _strip_ansi(lines[i])
        if test_name not in clean:
            continue
        if not _is_test_header(lines[i], lines[i + 1]):
            continue

        start = i
        end = len(lines)
        for j in range(i + 2, len(lines) - 1):
            if _is_test_header(lines[j], lines[j + 1]):
                end = j
                break
        sections.append((start, end))

    if not sections:
        raise ValueError(
            f"Test '{test_name}' not found in the deploy log. "
            "Make sure the test name matches (substring of the pytest nodeid)."
        )

    result: list[str] = []
    for idx, (start, end) in enumerate(sections):
        if idx > 0:
            result.append(f"{'=' * 60} section {idx + 1} {'=' * 60}")
        result.extend(_strip_ansi(line) for line in lines[start:end])

    return result


def _fetch_and_extract_test(
    log_url: str,
    api_key: str,
    test_name: str,
    tail: int = 0,
    head: int = 0,
) -> tuple[str, dict]:
    """Fetch the deploy log and extract a specific test's section.

    Args:
        log_url: URL to the deploy log file.
        api_key: Bearer token for Magna.
        test_name: Test name to extract (substring match).
        tail: Keep only the last N lines (0 = all).
        head: Keep only the first N lines (0 = all).

    Returns:
        Tuple of (filtered_content, metadata_dict).

    Raises:
        ValueError: If both head and tail are non-zero, or test not found.
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

    extracted = _extract_test_section(raw_lines, test_name)
    total_lines_extracted = len(extracted)

    if head > 0:
        extracted = extracted[:head]
    elif tail > 0:
        extracted = extracted[-tail:]

    content = "\n".join(extracted)
    if extracted:
        content += "\n"

    content, truncated = truncate_log_from_tail(content, max_size=MAX_LOG_SIZE)

    meta = {
        "total_lines_deploy_log": total_lines_raw,
        "total_lines_extracted": total_lines_extracted,
        "lines_returned": len(content.splitlines()),
        "truncated": truncated,
    }
    return content, meta


def get_ocs_ci_test_log(
    reportportal_url: str,
    test_name: str,
    tail: int = 0,
    head: int = 0,
) -> str:
    """Retrieve OCS-CI test log from a ReportPortal launch.

    Given a ReportPortal URL and test name, resolves the Magna logs
    directory, finds the deploy log file, downloads it, and extracts
    the section for the requested test.

    The deploy log contains the full pytest output for all tests in the
    run. This function finds the test by matching ``test_name`` as a
    substring of the pytest nodeid in the log, then extracts everything
    from the test header through to the next test header (or end of file).

    Args:
        reportportal_url: Full ReportPortal URL to a test log page
            (must contain '/launches/' and '/log').
        test_name: Test function name, e.g.
            ``'test_bucket_notifications[default-logs-pvc]'``.
            Matched as a substring against pytest nodeids in the log.
        tail: Return only the last N lines after extraction (0 = all).
        head: Return only the first N lines after extraction (0 = all).

    Returns:
        JSON string with test log content and metadata.
    """
    try:
        api_key, base_url, _cache_dir = _get_config()
        launch_id, test_item_id = _extract_ids(reportportal_url)

        meta = _resolve_magna_metadata(launch_id, test_item_id, api_key, base_url)

        log_url, deploy_log = _find_deploy_log_url(meta["logs_url_root"], api_key)

        content, log_meta = _fetch_and_extract_test(log_url, api_key, test_name, tail, head)

        return json.dumps(
            {
                "test_name": test_name,
                "log_url": log_url,
                "deploy_log": deploy_log,
                "total_lines_deploy_log": log_meta["total_lines_deploy_log"],
                "total_lines_extracted": log_meta["total_lines_extracted"],
                "lines_returned": log_meta["lines_returned"],
                "truncated": log_meta["truncated"],
                "content": content,
            }
        )
    except (ValueError, requests.HTTPError) as e:
        return json.dumps({"error": str(e)})
