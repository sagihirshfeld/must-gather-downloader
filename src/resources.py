import json

from .navigate import _count_files, _find_must_gather_root, _find_noobaa_dir
from .noobaa import handle_noobaa_only_resource
from .resource_maps import (
    _ALL_SUPPORTED_TYPES,
    _CEPH_COMMANDS,
    _CLUSTER_SCOPED,
    _DUAL_SUBTREE_TYPES,
    _NAMESPACED,
    _NOOBAA_CLUSTER_SCOPED,
    _NOOBAA_NAMESPACED,
    _NOOBAA_ONLY_TYPES,
    _RESOURCE_ALIASES,
)
from .resource_utils import (
    get_cluster_scoped_resource,
    get_namespaced_resource,
    safe_resolve_path,
    truncate_content,
)
from .text import _strip_managed_fields, _tail_yaml_list

_VALID_SUBTREES = frozenset({"auto", "main", "noobaa"})


def list_must_gather_contents(must_gather_path: str) -> str:
    """Scan a must-gather directory and return a structured inventory.

    Reports namespaces, cluster-scoped resources, ceph commands,
    pod counts per namespace, NooBaa info, and total file count.

    Args:
        must_gather_path: Path to the top-level must-gather extraction.

    Returns:
        JSON string with the full contents inventory.
    """
    root = _find_must_gather_root(must_gather_path)

    namespaces_dir = root / "namespaces"
    namespaces = sorted(d.name for d in namespaces_dir.iterdir() if d.is_dir()) if namespaces_dir.is_dir() else []

    cluster_scoped = {}
    csr_dir = root / "cluster-scoped-resources"
    if csr_dir.is_dir():
        for api_group in sorted(csr_dir.iterdir()):
            if api_group.is_dir():
                resource_types = sorted(d.name for d in api_group.iterdir() if d.is_dir())
                if resource_types:
                    cluster_scoped[api_group.name] = resource_types

    ceph_commands_dir = root / "ceph" / "must_gather_commands"
    ceph_commands = (
        sorted(f.name for f in ceph_commands_dir.iterdir() if f.is_file()) if ceph_commands_dir.is_dir() else []
    )

    ceph_logs_dir = root / "ceph_logs"
    ceph_log_nodes = sorted(d.name for d in ceph_logs_dir.iterdir() if d.is_dir()) if ceph_logs_dir.is_dir() else []

    pod_counts = {}
    for ns in namespaces:
        pods_dir = namespaces_dir / ns / "pods"
        if not pods_dir.is_dir():
            pods_dir = namespaces_dir / ns / "core" / "pods"
        if pods_dir.is_dir():
            pod_counts[ns] = sum(1 for d in pods_dir.iterdir() if d.is_dir())

    top_level_dirs = sorted(d.name for d in root.iterdir() if d.is_dir())

    host_logs_dir = root / "host_service_logs"

    noobaa_dir = root / "noobaa"
    has_noobaa = noobaa_dir.is_dir()
    noobaa_info = {}
    if has_noobaa:
        raw_output = noobaa_dir / "raw_output"
        noobaa_info["has_status"] = (raw_output / "status").is_file() if raw_output.is_dir() else False
        noobaa_info["has_db_list"] = (raw_output / "db_list.txt").is_file() if raw_output.is_dir() else False
        diag_tarballs = list(raw_output.glob("noobaa_diagnostics_*.tar.gz")) if raw_output.is_dir() else []
        noobaa_info["has_diagnostics"] = len(diag_tarballs) > 0
        noobaa_logs = noobaa_dir / "logs" / "openshift-storage"
        noobaa_info["log_files"] = (
            sorted(f.name for f in noobaa_logs.iterdir() if f.is_file()) if noobaa_logs.is_dir() else []
        )
        cnpg_dir = noobaa_dir / "cnpg_info"
        noobaa_info["cnpg_files"] = (
            sorted(f.name for f in cnpg_dir.iterdir() if f.is_file()) if cnpg_dir.is_dir() else []
        )

    return json.dumps(
        {
            "must_gather_root": str(root),
            "namespaces": namespaces,
            "cluster_scoped_resources": cluster_scoped,
            "has_ceph_data": len(ceph_commands) > 0,
            "ceph_commands": ceph_commands,
            "ceph_log_nodes": ceph_log_nodes,
            "pod_counts": pod_counts,
            "top_level_dirs": top_level_dirs,
            "host_service_logs": host_logs_dir.is_dir(),
            "has_noobaa": has_noobaa,
            "noobaa": noobaa_info if has_noobaa else {},
            "total_files": _count_files(root),
        }
    )


def _resolve_noobaa_dir(root):
    """Try to find the noobaa directory, returning None if missing."""
    try:
        return _find_noobaa_dir(root)
    except ValueError:
        return None


def _resolve_cluster_scoped_base(root, rt, subtree):
    """Resolve the base directory for a cluster-scoped resource lookup.

    Returns (base_dir, context_label, scoped_map) or a JSON error string.
    """
    if subtree == "main":
        return root, "must-gather", _CLUSTER_SCOPED
    if subtree == "noobaa":
        if rt not in _NOOBAA_CLUSTER_SCOPED:
            return json.dumps({"error": f"'{rt}' is not available in the noobaa subtree"}), None, None
        noobaa_dir = _resolve_noobaa_dir(root)
        if noobaa_dir is None:
            return json.dumps({"error": "No noobaa/ directory found in must-gather"}), None, None
        return noobaa_dir, "noobaa subtree", _NOOBAA_CLUSTER_SCOPED
    # auto: prefer noobaa for dual-subtree types
    if rt in _DUAL_SUBTREE_TYPES and rt in _NOOBAA_CLUSTER_SCOPED:
        noobaa_dir = _resolve_noobaa_dir(root)
        if noobaa_dir is not None:
            rel_path = _NOOBAA_CLUSTER_SCOPED[rt]
            if (noobaa_dir / rel_path).is_dir():
                return noobaa_dir, "noobaa subtree", _NOOBAA_CLUSTER_SCOPED
    return root, "must-gather", _CLUSTER_SCOPED


def _resolve_namespaced_base(root, rt, subtree):
    """Resolve the base namespaces directory for a namespaced resource lookup.

    Returns (namespaces_dir, context_label, namespaced_map) or a JSON error string.
    """
    if subtree == "main":
        return root / "namespaces", "must-gather", _NAMESPACED
    if subtree == "noobaa":
        if rt not in _NOOBAA_NAMESPACED:
            return json.dumps({"error": f"'{rt}' is not available in the noobaa subtree"}), None, None
        noobaa_dir = _resolve_noobaa_dir(root)
        if noobaa_dir is None:
            return json.dumps({"error": "No noobaa/ directory found in must-gather"}), None, None
        return noobaa_dir / "namespaces", "noobaa subtree", _NOOBAA_NAMESPACED
    # auto: prefer noobaa for dual-subtree types
    if rt in _DUAL_SUBTREE_TYPES and rt in _NOOBAA_NAMESPACED:
        noobaa_dir = _resolve_noobaa_dir(root)
        if noobaa_dir is not None and (noobaa_dir / "namespaces").is_dir():
            return noobaa_dir / "namespaces", "noobaa subtree", _NOOBAA_NAMESPACED
    return root / "namespaces", "must-gather", _NAMESPACED


def get_must_gather_resource(
    must_gather_path: str,
    resource_type: str,
    name: str = "",
    namespace: str = "",
    tail: int = 0,
    subtree: str = "auto",
) -> str:
    """Retrieve a specific resource from a must-gather.

    Supports cluster-scoped resources, namespaced resources, ceph command
    outputs, and NooBaa-specific resources. YAML resources are cleaned
    (managedFields stripped) and large results are truncated.

    Args:
        must_gather_path: Path to the must-gather extraction.
        resource_type: Resource type name or alias.
        name: Specific resource name. Omit to list available names.
        namespace: Required for namespaced resources.
        tail: For events, keep only the last N items (0 = all).
            For NooBaa logs/diagnostics, keep only the last N lines.
        subtree: Which subtree to read from: "auto" (default), "main",
            or "noobaa". Auto-detects based on resource type; for types
            that exist in both subtrees, prefers noobaa if available.

    Returns:
        JSON string with resource content, or a listing of available
        names if *name* is omitted.
    """
    if subtree not in _VALID_SUBTREES:
        return json.dumps(
            {
                "error": f"Invalid subtree '{subtree}'",
                "valid_values": sorted(_VALID_SUBTREES),
            }
        )

    root = _find_must_gather_root(must_gather_path)
    rt = resource_type.lower()
    rt = _RESOURCE_ALIASES.get(rt, rt)

    # NooBaa-only types: always route to noobaa handler
    if rt in _NOOBAA_ONLY_TYPES:
        if subtree == "main":
            return json.dumps({"error": f"'{rt}' only exists in the noobaa subtree, not in main"})
        return handle_noobaa_only_resource(root, rt, name, tail)

    # Ceph types: always main
    if rt == "ceph" or rt in _CEPH_COMMANDS:
        if subtree == "noobaa":
            return json.dumps({"error": "Ceph resources are not available in the noobaa subtree"})
        return _handle_ceph(root, rt, name)

    if rt in _CLUSTER_SCOPED:
        resolved = _resolve_cluster_scoped_base(root, rt, subtree)
        if isinstance(resolved[0], str) and resolved[1] is None:
            return resolved[0]
        base_dir, context_label, scoped_map = resolved
        return get_cluster_scoped_resource(
            base_dir, rt, name, scoped_map, extra_strip_keys={"node": ["images"]}, context_label=context_label
        )

    if rt in _NAMESPACED:
        # Events only exist in main
        if rt == "events" and subtree == "noobaa":
            return json.dumps({"error": "Events are not available in the noobaa subtree"})

        if rt == "events":
            return _handle_events(root, rt, namespace, tail)

        resolved = _resolve_namespaced_base(root, rt, subtree)
        if isinstance(resolved[0], str) and resolved[1] is None:
            return resolved[0]
        namespaces_dir, context_label, namespaced_map = resolved
        return get_namespaced_resource(namespaces_dir, rt, name, namespace, namespaced_map, context_label=context_label)

    return json.dumps(
        {
            "error": f"Unknown resource_type '{resource_type}'",
            "supported_types": _ALL_SUPPORTED_TYPES,
        }
    )


def _handle_ceph(root, rt, name):
    """Handle ceph and ceph-command resource types."""
    if rt == "ceph":
        ceph_cmds_dir = root / "ceph" / "must_gather_commands"
        if not ceph_cmds_dir.is_dir():
            return json.dumps({"error": "No ceph/must_gather_commands directory found"})
        available = sorted(f.name for f in ceph_cmds_dir.iterdir() if f.is_file())
        if not name:
            return json.dumps(
                {
                    "resource_type": "ceph",
                    "available_commands": available,
                    "hint": "Specify name parameter to read a specific ceph command output",
                }
            )
        target, err = safe_resolve_path(ceph_cmds_dir, name, "ceph commands directory")
        if err:
            return err
        if not target.is_file():
            similar = [f for f in available if name in f]
            return json.dumps(
                {
                    "error": f"Ceph command output not found: '{name}'",
                    "similar": similar,
                    "available_commands": available,
                }
            )
        content = target.read_text(encoding="utf-8", errors="replace")
        result: dict = {"resource_type": "ceph", "name": name, "path": str(target)}
        truncate_content(result, content, target)
        return json.dumps(result)

    exact_name = _CEPH_COMMANDS[rt]
    target = root / "ceph" / "must_gather_commands" / exact_name
    if not target.is_file():
        return json.dumps({"error": f"No {rt} data found in must-gather"})
    content = target.read_text(encoding="utf-8", errors="replace")
    result = {"resource_type": rt, "path": str(target)}
    truncate_content(result, content, target)
    return json.dumps(result)


def _handle_events(root, rt, namespace, tail):
    """Handle events resource type (always from main subtree)."""
    namespaces_dir = root / "namespaces"
    if not namespace:
        available_ns = sorted(d.name for d in namespaces_dir.iterdir() if d.is_dir()) if namespaces_dir.is_dir() else []
        return json.dumps(
            {
                "error": f"namespace is required for resource_type '{rt}'",
                "available_namespaces": available_ns,
            }
        )
    api_group, resource_path = _NAMESPACED[rt]
    events_file = namespaces_dir / namespace / api_group / resource_path
    if not events_file.is_file():
        return json.dumps({"error": f"Resource not found: {rt} in namespace '{namespace}'"})
    content = events_file.read_text(encoding="utf-8", errors="replace")
    content = _strip_managed_fields(content)
    total_events = None
    if tail > 0:
        content, total_events = _tail_yaml_list(content, tail)
    result = {
        "resource_type": rt,
        "namespace": namespace,
        "path": str(events_file),
    }
    if total_events is not None:
        result["total_events"] = total_events
        result["showing_last"] = min(tail, total_events)
    truncate_content(result, content, events_file)
    if result.get("truncated") and not tail:
        result["hint"] = "Use tail parameter to limit events (e.g. tail=100)"
    return json.dumps(result)
