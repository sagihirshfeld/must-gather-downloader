"""Shared utilities for resource retrieval across must-gather modules."""

import json
from pathlib import Path

from .resource_maps import _MAX_RESOURCE_SIZE
from .text import MAX_LOG_SIZE, _strip_managed_fields, _strip_yaml_keys


def truncate_content(
    result: dict,
    content: str,
    file_path: Path,
    max_size: int = _MAX_RESOURCE_SIZE,
) -> None:
    """Set content on result dict, truncating if it exceeds max_size bytes.

    Always sets ``result["content"]``. When content is too large, also sets
    ``result["truncated"]`` and ``result["total_size_bytes"]``.
    """
    if len(content.encode("utf-8")) > max_size:
        result["content"] = content[:max_size]
        result["truncated"] = True
        result["total_size_bytes"] = file_path.stat().st_size
    else:
        result["content"] = content


def truncate_log_from_tail(
    content: str,
    tail: int = 0,
    max_size: int = MAX_LOG_SIZE,
) -> tuple[str, bool]:
    """Apply tail-line limiting or size-based tail truncation to log content.

    Args:
        content: Raw log text.
        tail: Keep only the last N lines. 0 means no line limit.
        max_size: Maximum byte size before auto-truncating from the head.

    Returns:
        Tuple of (processed content, whether truncation occurred).
    """
    if tail > 0:
        lines = content.splitlines()
        content = "\n".join(lines[-tail:])
        if lines[-tail:]:
            content += "\n"
        return content, False

    if len(content.encode("utf-8", errors="replace")) > max_size:
        lines = content.splitlines()
        kept: list[str] = []
        size = 0
        for line in reversed(lines):
            line_size = len(line.encode("utf-8", errors="replace")) + 1
            if size + line_size > max_size:
                break
            kept.append(line)
            size += line_size
        kept.reverse()
        return "\n".join(kept) + "\n", True

    return content, False


def safe_resolve_path(
    base_dir: Path,
    name: str,
    dir_label: str,
) -> tuple[Path, str | None]:
    """Resolve a name under base_dir with path-traversal prevention.

    Args:
        base_dir: Directory to resolve within.
        name: Relative file name to resolve.
        dir_label: Human-readable label for error messages.

    Returns:
        Tuple of (resolved path, error JSON string or None).
    """
    target = (base_dir / name).resolve()
    if not target.is_relative_to(base_dir.resolve()):
        return target, json.dumps({"error": f"Invalid path: escapes {dir_label}"})
    return target, None


def get_cluster_scoped_resource(
    base_dir: Path,
    rt: str,
    name: str,
    scoped_map: dict[str, str],
    extra_strip_keys: dict[str, list[str]] | None = None,
    context_label: str = "must-gather",
) -> str:
    """Retrieve a cluster-scoped YAML resource or list available names.

    Args:
        base_dir: Root directory containing cluster-scoped-resources paths.
        rt: Resolved resource type name (already alias-expanded).
        name: Specific resource name, or empty to list available.
        scoped_map: Mapping of resource type to relative directory path.
        extra_strip_keys: Per-resource-type extra YAML keys to strip
            beyond managedFields (e.g. ``{"node": ["images"]}``).
        context_label: Label for error messages.
    """
    resource_dir = base_dir / scoped_map[rt]
    if not resource_dir.is_dir():
        return json.dumps({"error": f"No {rt} directory found in {context_label}"})
    if name:
        resource_file = resource_dir / f"{name}.yaml"
        if not resource_file.is_file():
            return json.dumps({"error": f"Resource not found: {rt} '{name}'"})
        content = resource_file.read_text(encoding="utf-8", errors="replace")
        strip_keys = ["managedFields"]
        if extra_strip_keys and rt in extra_strip_keys:
            strip_keys.extend(extra_strip_keys[rt])
        content = _strip_yaml_keys(content, strip_keys)
        result: dict = {
            "resource_type": rt,
            "name": name,
            "path": str(resource_file),
        }
        truncate_content(result, content, resource_file)
        return json.dumps(result)
    available = sorted(f.stem for f in resource_dir.iterdir() if f.suffix == ".yaml")
    return json.dumps(
        {
            "resource_type": rt,
            "available_names": available,
            "hint": f"Specify a name parameter to retrieve a specific {rt}",
        }
    )


def get_namespaced_resource(
    namespaces_dir: Path,
    rt: str,
    name: str,
    namespace: str,
    namespaced_map: dict[str, tuple[str, str]],
    context_label: str = "must-gather",
) -> str:
    """Retrieve a namespaced YAML resource or list available names.

    Handles namespace validation, file lookup, managedFields stripping,
    and size truncation. Does NOT handle the events resource type (which
    has special tail-yaml-list logic in resources.py).

    Args:
        namespaces_dir: Path to the ``namespaces/`` directory.
        rt: Resolved resource type name (already alias-expanded).
        name: Specific resource name, or empty to list available.
        namespace: Kubernetes namespace (required).
        namespaced_map: Mapping of resource type to (api_group, resource_path).
        context_label: Label for error messages.
    """
    if not namespace:
        available_ns = sorted(d.name for d in namespaces_dir.iterdir() if d.is_dir()) if namespaces_dir.is_dir() else []
        return json.dumps(
            {
                "error": f"namespace is required for resource_type '{rt}'",
                "available_namespaces": available_ns,
            }
        )
    api_group, resource_path = namespaced_map[rt]
    resource_dir = namespaces_dir / namespace / api_group / resource_path
    if not resource_dir.is_dir():
        return json.dumps({"error": f"No {rt} directory found in {context_label} for namespace '{namespace}'"})
    if name:
        resource_file = resource_dir / f"{name}.yaml"
        if not resource_file.is_file():
            return json.dumps({"error": f"Resource not found: {rt} '{name}' in namespace '{namespace}'"})
        content = resource_file.read_text(encoding="utf-8", errors="replace")
        content = _strip_managed_fields(content)
        result: dict = {
            "resource_type": rt,
            "name": name,
            "namespace": namespace,
            "path": str(resource_file),
        }
        truncate_content(result, content, resource_file)
        return json.dumps(result)
    available = sorted(f.stem for f in resource_dir.iterdir() if f.suffix == ".yaml")
    return json.dumps(
        {
            "resource_type": rt,
            "namespace": namespace,
            "available_names": available,
            "hint": f"Specify a name parameter to retrieve a specific {rt}",
        }
    )
