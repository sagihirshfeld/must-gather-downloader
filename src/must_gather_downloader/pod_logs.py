import json

from .navigate import _find_must_gather_root
from .text import MAX_LOG_SIZE, _filter_log_by_time


def get_must_gather_pod_logs(
    must_gather_path: str,
    namespace: str,
    pod_name: str = "",
    container: str = "",
    previous: bool = False,
    tail: int = 0,
    time_from: str = "",
    time_to: str = "",
) -> str:
    """Retrieve pod logs from a must-gather extraction.

    Lists available pods when *pod_name* is empty, or returns log
    content with optional container, tail, and time-range filtering.
    Large logs are automatically truncated from the head.

    Args:
        must_gather_path: Path to the must-gather extraction.
        namespace: Kubernetes namespace to look in.
        pod_name: Pod name or substring to match. Empty lists pods.
        container: Container name filter. Empty includes all.
        previous: If True, read ``previous.log`` instead of ``current.log``.
        tail: Number of lines to keep from the end (0 = all).
        time_from: Inclusive start time filter (e.g. "03:38:00").
        time_to: Inclusive end time filter (e.g. "03:41:00").

    Returns:
        JSON string with pod list or log contents and metadata.
    """
    root = _find_must_gather_root(must_gather_path)
    pods_dir = root / "namespaces" / namespace / "pods"
    if not pods_dir.exists():
        pods_dir = root / "namespaces" / namespace / "core" / "pods"

    if not pods_dir.exists():
        namespaces_dir = root / "namespaces"
        available_ns = sorted(d.name for d in namespaces_dir.iterdir() if d.is_dir()) if namespaces_dir.exists() else []
        return json.dumps({
            "error": f"Namespace '{namespace}' not found or has no pods directory",
            "available_namespaces": available_ns,
        })

    all_pods = sorted(d.name for d in pods_dir.iterdir() if d.is_dir())

    if not pod_name:
        return json.dumps({
            "namespace": namespace,
            "available_pods": all_pods,
            "hint": "Specify pod_name to retrieve logs",
        })

    matched_pods = [p for p in all_pods if pod_name in p]
    if not matched_pods:
        return json.dumps({
            "error": f"No pods matching '{pod_name}' found",
            "namespace": namespace,
            "available_pods": all_pods,
        })

    log_filename = "previous.log" if previous else "current.log"
    logs = []

    for pod in matched_pods:
        pod_dir = pods_dir / pod
        for log_path in sorted(pod_dir.rglob(log_filename)):
            container_name = log_path.relative_to(pod_dir).parts[0]
            if container and container != container_name:
                continue

            content = log_path.read_text(encoding="utf-8", errors="replace")
            truncated = False

            if time_from or time_to:
                content, _total, _matched = _filter_log_by_time(
                    content, time_from, time_to
                )

            if tail > 0:
                lines = content.splitlines()
                content = "\n".join(lines[-tail:])
                if lines[-tail:]:
                    content += "\n"
            elif len(content.encode("utf-8", errors="replace")) > MAX_LOG_SIZE:
                lines = content.splitlines()
                kept = []
                size = 0
                for line in reversed(lines):
                    line_size = len(line.encode("utf-8", errors="replace")) + 1
                    if size + line_size > MAX_LOG_SIZE:
                        break
                    kept.append(line)
                    size += line_size
                kept.reverse()
                content = "\n".join(kept) + "\n"
                truncated = True

            line_count = len(content.splitlines())
            logs.append({
                "pod": pod,
                "container": container_name,
                "log_file": log_filename,
                "lines": line_count,
                "content": content,
                "truncated": truncated,
            })

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
