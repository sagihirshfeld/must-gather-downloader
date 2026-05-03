import json

from .navigate import (
    _ensure_noobaa_diagnostics_extracted,
    _find_must_gather_root,
    _find_noobaa_dir,
)
from .noobaa_resource_maps import (
    _ALL_NOOBAA_TYPES,
    _NOOBAA_CLUSTER_SCOPED,
    _NOOBAA_NAMESPACED,
    _NOOBAA_RESOURCE_ALIASES,
)
from .resource_maps import _MAX_RESOURCE_SIZE
from .text import _strip_managed_fields


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
        status_file = noobaa_dir / "raw_output" / "status"
        if not status_file.is_file():
            return json.dumps({"error": "No noobaa/raw_output/status file found"})
        content = status_file.read_text(encoding="utf-8", errors="replace")
        result = {"resource_type": "status", "path": str(status_file), "content": content}
        if len(content.encode("utf-8")) > _MAX_RESOURCE_SIZE:
            result["content"] = content[:_MAX_RESOURCE_SIZE]
            result["truncated"] = True
            result["total_size_bytes"] = status_file.stat().st_size
        return json.dumps(result)

    if rt == "db_list":
        db_file = noobaa_dir / "raw_output" / "db_list.txt"
        if not db_file.is_file():
            return json.dumps({"error": "No noobaa/raw_output/db_list.txt file found"})
        content = db_file.read_text(encoding="utf-8", errors="replace")
        result = {"resource_type": "db_list", "path": str(db_file), "content": content}
        if len(content.encode("utf-8")) > _MAX_RESOURCE_SIZE:
            result["content"] = content[:_MAX_RESOURCE_SIZE]
            result["truncated"] = True
            result["total_size_bytes"] = db_file.stat().st_size
        return json.dumps(result)

    if rt == "diagnostics":
        extract_dir = _ensure_noobaa_diagnostics_extracted(noobaa_dir)
        if extract_dir is None:
            return json.dumps({"error": "No noobaa_diagnostics tarball found in noobaa/raw_output/"})
        available = sorted(
            str(f.relative_to(extract_dir))
            for f in extract_dir.rglob("*") if f.is_file()
        )
        if not name:
            return json.dumps({
                "resource_type": "diagnostics",
                "available_files": available,
                "hint": "Specify name parameter to read a specific file",
            })
        target = (extract_dir / name).resolve()
        if not target.is_relative_to(extract_dir.resolve()):
            return json.dumps({"error": "Invalid path: escapes diagnostics directory"})
        if not target.is_file():
            return json.dumps({
                "error": f"File not found in diagnostics: '{name}'",
                "available_files": available,
            })
        content = target.read_text(encoding="utf-8", errors="replace")
        result = {
            "resource_type": "diagnostics",
            "name": name,
            "path": str(target),
            "content": content,
        }
        if len(content.encode("utf-8")) > _MAX_RESOURCE_SIZE:
            result["content"] = content[:_MAX_RESOURCE_SIZE]
            result["truncated"] = True
            result["total_size_bytes"] = target.stat().st_size
        return json.dumps(result)

    if rt == "logs":
        logs_dir = noobaa_dir / "logs" / "openshift-storage"
        if not logs_dir.is_dir():
            return json.dumps({"error": "No noobaa/logs/openshift-storage/ directory found"})
        available = sorted(f.name for f in logs_dir.iterdir() if f.is_file())
        if not name:
            return json.dumps({
                "resource_type": "logs",
                "available_logs": available,
                "hint": "Specify name parameter to read a specific log file",
            })
        target = (logs_dir / name).resolve()
        if not target.is_relative_to(logs_dir.resolve()):
            return json.dumps({"error": "Invalid path: escapes logs directory"})
        if not target.is_file():
            return json.dumps({
                "error": f"Log file not found: '{name}'",
                "available_logs": available,
            })
        content = target.read_text(encoding="utf-8", errors="replace")
        truncated = False
        if tail > 0:
            lines = content.splitlines()
            content = "\n".join(lines[-tail:])
            if lines[-tail:]:
                content += "\n"
        elif len(content.encode("utf-8")) > _MAX_RESOURCE_SIZE:
            lines = content.splitlines()
            kept = []
            size = 0
            for line in reversed(lines):
                line_size = len(line.encode("utf-8", errors="replace")) + 1
                if size + line_size > _MAX_RESOURCE_SIZE:
                    break
                kept.append(line)
                size += line_size
            kept.reverse()
            content = "\n".join(kept) + "\n"
            truncated = True
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
        available = sorted(f.name for f in cnpg_dir.iterdir() if f.is_file())
        if not name:
            return json.dumps({
                "resource_type": "cnpg",
                "available_files": available,
                "hint": "Specify name parameter to read a specific CNPG info file",
            })
        target = (cnpg_dir / name).resolve()
        if not target.is_relative_to(cnpg_dir.resolve()):
            return json.dumps({"error": "Invalid path: escapes cnpg directory"})
        if not target.is_file():
            return json.dumps({
                "error": f"CNPG info file not found: '{name}'",
                "available_files": available,
            })
        content = target.read_text(encoding="utf-8", errors="replace")
        result = {
            "resource_type": "cnpg",
            "name": name,
            "path": str(target),
            "content": content,
        }
        if len(content.encode("utf-8")) > _MAX_RESOURCE_SIZE:
            result["content"] = content[:_MAX_RESOURCE_SIZE]
            result["truncated"] = True
            result["total_size_bytes"] = target.stat().st_size
        return json.dumps(result)

    if rt in _NOOBAA_CLUSTER_SCOPED:
        resource_dir = noobaa_dir / _NOOBAA_CLUSTER_SCOPED[rt]
        if not resource_dir.is_dir():
            return json.dumps({"error": f"No {rt} directory found in noobaa subtree"})
        if name:
            resource_file = resource_dir / f"{name}.yaml"
            if not resource_file.is_file():
                return json.dumps({"error": f"Resource not found: {rt} '{name}'"})
            content = resource_file.read_text(encoding="utf-8", errors="replace")
            content = _strip_managed_fields(content)
            result = {
                "resource_type": rt,
                "name": name,
                "path": str(resource_file),
                "content": content,
            }
            if len(content.encode("utf-8")) > _MAX_RESOURCE_SIZE:
                result["content"] = content[:_MAX_RESOURCE_SIZE]
                result["truncated"] = True
                result["total_size_bytes"] = resource_file.stat().st_size
            return json.dumps(result)
        available = sorted(f.stem for f in resource_dir.iterdir() if f.suffix == ".yaml")
        return json.dumps({
            "resource_type": rt,
            "available_names": available,
            "hint": f"Specify a name parameter to retrieve a specific {rt}",
        })

    if rt in _NOOBAA_NAMESPACED:
        namespaces_dir = noobaa_dir / "namespaces"
        if not namespace:
            available_ns = sorted(
                d.name for d in namespaces_dir.iterdir() if d.is_dir()
            ) if namespaces_dir.is_dir() else []
            return json.dumps({
                "error": f"namespace is required for resource_type '{rt}'",
                "available_namespaces": available_ns,
            })
        api_group, resource_path = _NOOBAA_NAMESPACED[rt]
        resource_dir = namespaces_dir / namespace / api_group / resource_path
        if not resource_dir.is_dir():
            return json.dumps({"error": f"No {rt} directory found in noobaa subtree for namespace '{namespace}'"})
        if name:
            resource_file = resource_dir / f"{name}.yaml"
            if not resource_file.is_file():
                return json.dumps({"error": f"Resource not found: {rt} '{name}' in namespace '{namespace}'"})
            content = resource_file.read_text(encoding="utf-8", errors="replace")
            content = _strip_managed_fields(content)
            result = {
                "resource_type": rt,
                "name": name,
                "namespace": namespace,
                "path": str(resource_file),
                "content": content,
            }
            if len(content.encode("utf-8")) > _MAX_RESOURCE_SIZE:
                result["content"] = content[:_MAX_RESOURCE_SIZE]
                result["truncated"] = True
                result["total_size_bytes"] = resource_file.stat().st_size
            return json.dumps(result)
        available = sorted(f.stem for f in resource_dir.iterdir() if f.suffix == ".yaml")
        return json.dumps({
            "resource_type": rt,
            "namespace": namespace,
            "available_names": available,
            "hint": f"Specify a name parameter to retrieve a specific {rt}",
        })

    return json.dumps({
        "error": f"Unknown noobaa resource_type '{resource_type}'",
        "supported_types": _ALL_NOOBAA_TYPES,
    })
