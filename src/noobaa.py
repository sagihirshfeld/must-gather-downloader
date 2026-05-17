import json

from .navigate import (
    _ensure_noobaa_diagnostics_extracted,
    _find_noobaa_dir,
)
from .resource_maps import _MAX_RESOURCE_SIZE
from .resource_utils import (
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


def handle_noobaa_only_resource(root, rt: str, name: str, tail: int) -> str:
    """Handle NooBaa-only resource types (status, db_list, diagnostics, logs, cnpg).

    These types only exist in the noobaa subtree and have no main-subtree equivalent.

    Args:
        root: Must-gather root path (resolved via _find_must_gather_root).
        rt: Resolved resource type (already lowered and alias-resolved).
        name: Specific file or resource name. Omit to list available.
        tail: For logs/diagnostics, keep only the last N lines (0 = all).

    Returns:
        JSON string with resource content or listing.
    """
    try:
        noobaa_dir = _find_noobaa_dir(root)
    except ValueError as e:
        return json.dumps({"error": str(e)})

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

    return json.dumps({"error": f"Unknown noobaa-only resource type: '{rt}'"})
