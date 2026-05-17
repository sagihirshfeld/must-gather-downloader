import json
import re
from dataclasses import dataclass
from pathlib import Path

from .navigate import _find_must_gather_root
from .resource_utils import truncate_log_from_tail
from .search import _MAX_LINE_LENGTH
from .text import _extract_time_str, _filter_log_by_time, _normalize_time


@dataclass
class _PodLogFile:
    """Metadata for a discovered pod log file."""

    pod: str
    container: str
    log_file: str
    path: Path


def _find_pods_dir(must_gather_path: str, namespace: str) -> tuple[Path | None, str | None, list[str]]:
    """Locate the pods directory for a namespace.

    Returns:
        Tuple of (pods_dir or None, error message or None, available namespaces).
    """
    root = _find_must_gather_root(must_gather_path)
    pods_dir = root / "namespaces" / namespace / "pods"
    if not pods_dir.exists():
        pods_dir = root / "namespaces" / namespace / "core" / "pods"

    if not pods_dir.exists():
        namespaces_dir = root / "namespaces"
        available_ns = sorted(d.name for d in namespaces_dir.iterdir() if d.is_dir()) if namespaces_dir.exists() else []
        return None, f"Namespace '{namespace}' not found or has no pods directory", available_ns

    return pods_dir, None, []


def _find_pod_log_files(
    pods_dir: Path,
    pod_name: str,
    container: str = "",
    previous: bool = False,
) -> list[_PodLogFile]:
    """Find log file paths for pods matching the given name substring.

    Args:
        pods_dir: Path to the namespace pods directory.
        pod_name: Substring to match against pod directory names.
        container: Container name filter. Empty includes all.
        previous: If True, look for ``previous.log`` instead of ``current.log``.

    Returns:
        List of ``_PodLogFile`` entries for each matched log file.
    """
    all_pods = sorted(d.name for d in pods_dir.iterdir() if d.is_dir())
    matched_pods = [p for p in all_pods if pod_name in p]
    log_filename = "previous.log" if previous else "current.log"

    results: list[_PodLogFile] = []
    for pod in matched_pods:
        pod_dir = pods_dir / pod
        for log_path in sorted(pod_dir.rglob(log_filename)):
            container_name = log_path.relative_to(pod_dir).parts[0]
            if container and container != container_name:
                continue
            results.append(
                _PodLogFile(
                    pod=pod,
                    container=container_name,
                    log_file=log_filename,
                    path=log_path,
                )
            )
    return results


def _search_in_pod_logs(
    log_files: list[_PodLogFile],
    pattern: str,
    namespace: str,
    pod_name: str,
    context_lines: int,
    max_results: int,
    case_sensitive: bool,
    time_from: str,
    time_to: str,
) -> str:
    """Search within discovered pod log files for a pattern."""
    flags = 0 if case_sensitive else re.IGNORECASE
    try:
        compiled = re.compile(pattern, flags)
    except re.error:
        compiled = re.compile(re.escape(pattern), flags)

    use_time_filter = bool(time_from or time_to)
    t_from = _normalize_time(time_from) if time_from else None
    t_to = _normalize_time(time_to) if time_to else None

    all_matches: list[dict] = []
    truncated = False

    for lf in log_files:
        content = lf.path.read_text(encoding="utf-8", errors="replace")
        lines = content.splitlines()
        total_lines = len(lines)

        in_range = t_from is None
        searchable: list[tuple[int, str]] = []

        for idx, line in enumerate(lines):
            if use_time_filter:
                ts = _extract_time_str(line)
                if ts is not None:
                    if t_from and t_to:
                        in_range = t_from <= ts <= t_to
                    elif t_from:
                        in_range = ts >= t_from
                    elif t_to:
                        in_range = ts <= t_to
                if not in_range:
                    continue
            searchable.append((idx, line))

        for orig_idx, line in searchable:
            if compiled.search(line[:_MAX_LINE_LENGTH]):
                ctx_before = []
                for i in range(max(0, orig_idx - context_lines), orig_idx):
                    ctx_before.append(lines[i][:_MAX_LINE_LENGTH])
                ctx_after = []
                for i in range(orig_idx + 1, min(total_lines, orig_idx + 1 + context_lines)):
                    ctx_after.append(lines[i][:_MAX_LINE_LENGTH])

                all_matches.append(
                    {
                        "pod": lf.pod,
                        "container": lf.container,
                        "log_file": lf.log_file,
                        "line_number": orig_idx + 1,
                        "line": line.strip()[:_MAX_LINE_LENGTH],
                        "context_before": ctx_before,
                        "context_after": ctx_after,
                    }
                )

                if len(all_matches) >= max_results:
                    truncated = True
                    break

        if truncated:
            break

    return json.dumps(
        {
            "pattern": pattern,
            "namespace": namespace,
            "pod_name": pod_name,
            "matches": all_matches,
            "total_matches": len(all_matches),
            "truncated": truncated,
        }
    )


def get_must_gather_pod_logs(
    must_gather_path: str,
    namespace: str,
    pod_name: str = "",
    container: str = "",
    previous: bool = False,
    tail: int = 0,
    time_from: str = "",
    time_to: str = "",
    pattern: str = "",
    context_lines: int = 3,
    max_results: int = 50,
    case_sensitive: bool = False,
) -> str:
    """Retrieve pod logs or search within them from a must-gather extraction.

    Lists available pods when *pod_name* is empty. When *pattern* is
    provided, returns matching lines with surrounding context (search
    mode). Otherwise returns full log content with optional tail and
    time-range filtering.

    Args:
        must_gather_path: Path to the must-gather extraction.
        namespace: Kubernetes namespace to look in.
        pod_name: Pod name or substring to match. Empty lists pods.
        container: Container name filter. Empty includes all.
        previous: If True, read ``previous.log`` instead of ``current.log``.
        tail: Lines from the end to return, full-log mode only (0 = all).
        time_from: Inclusive start time filter (e.g. "03:38:00").
        time_to: Inclusive end time filter (e.g. "03:41:00").
        pattern: Regex or literal to search for. Empty means full-log mode.
        context_lines: Context lines around each match, search mode only.
        max_results: Max matches to return, search mode only.
        case_sensitive: Case-sensitive matching, search mode only.

    Returns:
        JSON string with pod list, log contents, or search matches.
    """
    pods_dir, error, available_ns = _find_pods_dir(must_gather_path, namespace)
    if pods_dir is None:
        return json.dumps(
            {
                "error": error,
                "available_namespaces": available_ns,
            }
        )

    all_pods = sorted(d.name for d in pods_dir.iterdir() if d.is_dir())

    if not pod_name:
        return json.dumps(
            {
                "namespace": namespace,
                "available_pods": all_pods,
                "hint": "Specify pod_name to retrieve logs",
            }
        )

    matched_pods = [p for p in all_pods if pod_name in p]
    if not matched_pods:
        return json.dumps(
            {
                "error": f"No pods matching '{pod_name}' found",
                "namespace": namespace,
                "available_pods": all_pods,
            }
        )

    log_files = _find_pod_log_files(pods_dir, pod_name, container, previous)

    if pattern:
        return _search_in_pod_logs(
            log_files,
            pattern,
            namespace,
            pod_name,
            context_lines,
            max_results,
            case_sensitive,
            time_from,
            time_to,
        )

    logs = []

    for lf in log_files:
        content = lf.path.read_text(encoding="utf-8", errors="replace")

        if time_from or time_to:
            content, _total, _matched = _filter_log_by_time(content, time_from, time_to)

        content, truncated = truncate_log_from_tail(content, tail)

        line_count = len(content.splitlines())
        logs.append(
            {
                "pod": lf.pod,
                "container": lf.container,
                "log_file": lf.log_file,
                "lines": line_count,
                "content": content,
                "truncated": truncated,
            }
        )

    result = {
        "namespace": namespace,
        "pod_name": pod_name,
        "logs": logs,
        "total_logs_found": len(logs),
    }
    if time_from:
        result["time_from"] = time_from
    if time_to:
        result["time_to"] = time_to
    return json.dumps(result)
