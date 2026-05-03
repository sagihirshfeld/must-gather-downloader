import json

from .navigate import (
    _ensure_noobaa_diagnostics_extracted,
    _find_must_gather_root,
    _find_noobaa_dir,
)
from .resource_maps import (
    _ALL_NOOBAA_TYPES,
    _MAX_RESOURCE_SIZE,
    _NOOBAA_CLUSTER_SCOPED,
    _NOOBAA_NAMESPACED,
    _NOOBAA_RESOURCE_ALIASES,
)
from .resource_utils import (
    get_cluster_scoped_resource,
    get_namespaced_resource,
    safe_resolve_path,
    truncate_content,
    truncate_log_from_tail,
)


def _read_raw_file(noobaa_dir, relative_path: str, resource_type: str, error_msg: str) -> str:
    """Read a single file from the noobaa subtree with truncation."""
    target = noobaa_dir / relative_path
    if not target.is_file():
        return json.dumps({"error": error_msg})
    content = target.read_text(encoding="utf-8", errors="replace")
    result: dict = {"resource_type": resource_type, "path": str(target)}
    truncate_content(result, content, target)
    return json.dumps(result)


def _list_or_read_from_dir(
    dir_path,
    name: str,
    resource_type: str,
    list_key: str,
    hint: str,
    dir_label: str,
    not_found_msg: str,
    max_size: int = _MAX_RESOURCE_SIZE,
) -> str:
    """Handle the list-files-or-read-one-file pattern for a directory."""
    available = sorted(f.name for f in dir_path.iterdir() if f.is_file())
    if not name:
        return json.dumps(
            {
                "resource_type": resource_type,
                list_key: available,
                "hint": hint,
            }
        )
    target, err = safe_resolve_path(dir_path, name, dir_label)
    if err:
        return err
    if not target.is_file():
        return json.dumps(
            {
                "error": f"{not_found_msg}: '{name}'",
                list_key: available,
            }
        )
    content = target.read_text(encoding="utf-8", errors="replace")
    result: dict = {"resource_type": resource_type, "name": name, "path": str(target)}
    truncate_content(result, content, target, max_size)
    return json.dumps(result)


def get_noobaa_resource(
    must_gather_path: str,
    resource_type: str,
    name: str = "",
    namespace: str = "",
    tail: int = 0,
) -> str:
    """Retrieve a NooBaa-specific resource from the must-gather.

    Handles status, db_list, diagnostics, logs, CNPG info, and
    NooBaa CRD resources (both cluster-scoped and namespaced).
    Path traversal is prevented for all file-based lookups.

    Args:
        must_gather_path: Path to the must-gather extraction.
        resource_type: NooBaa resource type or alias (e.g. "status",
            "diagnostics", "logs", "cnpg", "obc", "bs").
        name: Specific file or resource name. Omit to list available.
        namespace: Required for namespaced CRD resources.
        tail: For logs, keep only the last N lines (0 = all).

    Returns:
        JSON string with resource content, or a listing of available
        items if *name* is omitted.
    """
    root = _find_must_gather_root(must_gather_path)
    try:
        noobaa_dir = _find_noobaa_dir(root)
    except ValueError as e:
        return json.dumps({"error": str(e)})

    rt = resource_type.lower()
    rt = _NOOBAA_RESOURCE_ALIASES.get(rt, rt)

    if rt == "status":
        return _read_raw_file(noobaa_dir, "raw_output/status", "status", "No noobaa/raw_output/status file found")

    if rt == "db_list":
        return _read_raw_file(
            noobaa_dir, "raw_output/db_list.txt", "db_list", "No noobaa/raw_output/db_list.txt file found"
        )

    if rt == "diagnostics":
        extract_dir = _ensure_noobaa_diagnostics_extracted(noobaa_dir)
        if extract_dir is None:
            return json.dumps({"error": "No noobaa_diagnostics tarball found in noobaa/raw_output/"})
        available = sorted(str(f.relative_to(extract_dir)) for f in extract_dir.rglob("*") if f.is_file())
        if not name:
            return json.dumps(
                {
                    "resource_type": "diagnostics",
                    "available_files": available,
                    "hint": "Specify name parameter to read a specific file",
                }
            )
        target, err = safe_resolve_path(extract_dir, name, "diagnostics directory")
        if err:
            return err
        if not target.is_file():
            return json.dumps(
                {
                    "error": f"File not found in diagnostics: '{name}'",
                    "available_files": available,
                }
            )
        content = target.read_text(encoding="utf-8", errors="replace")
        content, truncated = truncate_log_from_tail(content, tail, _MAX_RESOURCE_SIZE)
        result: dict = {
            "resource_type": "diagnostics",
            "name": name,
            "path": str(target),
            "lines": len(content.splitlines()),
            "content": content,
            "truncated": truncated,
        }
        return json.dumps(result)

    if rt == "logs":
        logs_dir = noobaa_dir / "logs" / "openshift-storage"
        if not logs_dir.is_dir():
            return json.dumps({"error": "No noobaa/logs/openshift-storage/ directory found"})
        available = sorted(f.name for f in logs_dir.iterdir() if f.is_file())
        if not name:
            return json.dumps(
                {
                    "resource_type": "logs",
                    "available_logs": available,
                    "hint": "Specify name parameter to read a specific log file",
                }
            )
        target, err = safe_resolve_path(logs_dir, name, "logs directory")
        if err:
            return err
        if not target.is_file():
            return json.dumps(
                {
                    "error": f"Log file not found: '{name}'",
                    "available_logs": available,
                }
            )
        content = target.read_text(encoding="utf-8", errors="replace")
        content, truncated = truncate_log_from_tail(content, tail, _MAX_RESOURCE_SIZE)
        result = {
            "resource_type": "logs",
            "name": name,
            "path": str(target),
            "lines": len(content.splitlines()),
            "content": content,
            "truncated": truncated,
        }
        return json.dumps(result)

    if rt == "cnpg":
        cnpg_dir = noobaa_dir / "cnpg_info"
        if not cnpg_dir.is_dir():
            return json.dumps({"error": "No noobaa/cnpg_info/ directory found"})
        return _list_or_read_from_dir(
            cnpg_dir,
            name,
            resource_type="cnpg",
            list_key="available_files",
            hint="Specify name parameter to read a specific CNPG info file",
            dir_label="cnpg directory",
            not_found_msg="CNPG info file not found",
        )

    if rt in _NOOBAA_CLUSTER_SCOPED:
        return get_cluster_scoped_resource(noobaa_dir, rt, name, _NOOBAA_CLUSTER_SCOPED, context_label="noobaa subtree")

    if rt in _NOOBAA_NAMESPACED:
        return get_namespaced_resource(
            noobaa_dir / "namespaces", rt, name, namespace, _NOOBAA_NAMESPACED, context_label="noobaa subtree"
        )

    return json.dumps(
        {
            "error": f"Unknown noobaa resource_type '{resource_type}'",
            "supported_types": _ALL_NOOBAA_TYPES,
        }
    )
