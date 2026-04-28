import fcntl
import json
import os
import re
import shutil
import tarfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, unquote

import requests
from fastmcp import FastMCP

mcp = FastMCP("must-gather")

RP_PROJECT = "ocs"


def _ssl_verify() -> bool | str:
    val = os.environ.get("RP_SSL_VERIFY", "true").strip().lower()
    if val == "false":
        return False
    if val == "true":
        return True
    return val


def _get_config():
    api_key = os.environ.get("RP_API_KEY", "")
    base_url = os.environ.get("RP_BASE_URL", "").strip().strip("\"'").rstrip("/")
    cache_dir = Path(
        os.environ.get("MUST_GATHER_CACHE_DIR", "/tmp/must-gather-cache")
    )
    if not api_key or not base_url:
        raise ValueError(
            "RP_API_KEY and RP_BASE_URL environment variables are required. "
            "Configure them in your MCP server settings."
        )
    return api_key, base_url, cache_dir


def _extract_ids(url: str) -> tuple[str, str]:
    if "launches/" not in url or "log" not in url:
        raise ValueError(
            "Invalid ReportPortal URL. Expected a test log page URL "
            "containing '/launches/' and '/log'."
        )
    after_launches = url.split("launches/")[1]
    parts = after_launches.split("/")
    try:
        launch_id = parts[1]
        test_item_id = parts[3]
    except IndexError:
        raise ValueError(
            "Could not extract launch ID and test item ID from URL. "
            "Expected format: .../launches/<type>/<launch_id>/<section>/<test_item_id>/..."
        )
    return launch_id, test_item_id


def _rp_headers(api_key: str) -> dict:
    return {
        "Accept": "application/json",
        "Authorization": f"Bearer {api_key}",
    }


def _fetch_json(url: str, api_key: str) -> dict:
    resp = requests.get(url, headers=_rp_headers(api_key), timeout=30, verify=_ssl_verify())
    resp.raise_for_status()
    return resp.json()


def _fetch_html_lines(url: str, api_key: str = "") -> list[str]:
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    resp = requests.get(url, headers=headers, timeout=30, verify=_ssl_verify())
    resp.raise_for_status()
    return [line for line in resp.text.split("\n") if line.strip()]


def _extract_hrefs(lines: list[str]) -> list[str]:
    hrefs = []
    for line in lines:
        match = re.search(r'href="([^"]+)"', line)
        if match:
            hrefs.append(match.group(1))
    return hrefs


def _safe_test_name(test_name: str) -> str:
    safe = f"{test_name}_ocs_logs"
    return quote(safe, safe="/[]-_.~")


def _resolve_test_log_directory(
    launch_id: str, test_item_id: str, api_key: str, base_url: str
) -> dict:
    rp_api = f"{base_url}/api/v1/{RP_PROJECT}"
    launch_api = f"{rp_api}/launch?filter.eq.id={launch_id}"
    item_api = f"{rp_api}/item/{test_item_id}"

    launch_json = _fetch_json(launch_api, api_key)
    item_json = _fetch_json(item_api, api_key)

    try:
        description = launch_json["content"][0]["description"]
        logs_url_root = description.split("Logs URL:")[1].strip().split()[0]
        cluster_name = logs_url_root.split("openshift-clusters/")[1].split("/")[0]
        test_name = item_json["name"]
    except (KeyError, IndexError) as e:
        raise ValueError(
            "Could not extract Magna logs location from ReportPortal. "
            f"Missing description or name field: {e}"
        )

    lines = _fetch_html_lines(logs_url_root, api_key)
    hrefs = _extract_hrefs(lines)
    failed_dir_suffixes = [h for h in hrefs if "failed_testcase" in h]

    if not failed_dir_suffixes:
        raise ValueError("No failed_testcase directories found on Magna.")

    def _check_suffix(suffix):
        dir_url = f"{logs_url_root.rstrip('/')}/{suffix}"
        dir_lines = _fetch_html_lines(dir_url, api_key)
        if any(test_name in line for line in dir_lines):
            return suffix
        return None

    target_suffix = None
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(_check_suffix, s): s for s in failed_dir_suffixes}
        for future in as_completed(futures):
            result = future.result()
            if result is not None:
                target_suffix = result
                for f in futures:
                    f.cancel()
                break

    if not target_suffix:
        raise ValueError(
            "Test exists in ReportPortal but not found in any "
            "failed_testcase directory on Magna."
        )

    return {
        "logs_url_root": logs_url_root,
        "cluster_name": cluster_name,
        "test_name": test_name,
        "target_suffix": target_suffix,
        "safe_test_name": _safe_test_name(test_name),
        "launch_id": launch_id,
        "test_item_id": test_item_id,
    }


def _find_tarball_url(info: dict, api_key: str) -> str:
    cluster_dir = "/".join([
        info["logs_url_root"].rstrip("/"),
        info["target_suffix"].rstrip("/"),
        info["safe_test_name"],
        info["cluster_name"],
    ])

    lines = _fetch_html_lines(cluster_dir, api_key)
    hrefs = _extract_hrefs(lines)
    tarball_hrefs = [
        h for h in hrefs
        if h.endswith(".tar.gz") or h.endswith(".tgz") or h.endswith(".tar")
    ]

    if not tarball_hrefs:
        raise ValueError(
            "No must-gather tarball found in the expected location on Magna."
        )

    preferred = next(
        (h for h in tarball_hrefs if "must_gather" in h or "must-gather" in h),
        None,
    )
    tarball_suffix = preferred or tarball_hrefs[0]

    return f"{cluster_dir.rstrip('/')}/{tarball_suffix.lstrip('/')}"


def _download_tarball(url: str, dest: Path, api_key: str = "") -> None:
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    with requests.get(url, headers=headers, stream=True, timeout=300, verify=_ssl_verify()) as resp:
        resp.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)


def _extract_tarball(tarball_path: Path, extract_dir: Path) -> None:
    extract_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tarball_path, "r:*") as tar:
        tar.extractall(path=extract_dir, filter="data")


def _find_must_gather_root(must_gather_path: str) -> Path:
    path = Path(must_gather_path)
    if not path.exists():
        raise ValueError(f"Path does not exist: {must_gather_path}")
    if not path.is_dir():
        raise ValueError(f"Path is not a directory: {must_gather_path}")

    for candidate in sorted(path.rglob("namespaces"), key=lambda p: len(p.parts)):
        if candidate.is_dir():
            return candidate.parent

    subdirs = sorted(d for d in path.iterdir() if d.is_dir())
    if not subdirs:
        raise ValueError(f"No subdirectories found in: {must_gather_path}")
    if len(subdirs) == 1:
        return subdirs[0]
    preferred = [d for d in subdirs if d.name.startswith("must-gather")]
    if preferred:
        return preferred[0]
    return subdirs[0]


def _count_files(directory: Path) -> int:
    return sum(1 for _ in directory.rglob("*") if _.is_file())


def _cache_check(cache_entry: Path) -> dict | None:
    metadata_path = cache_entry / "metadata.json"
    extracted_dir = cache_entry / "extracted"
    if metadata_path.exists() and extracted_dir.exists():
        try:
            with open(metadata_path) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return None
    return None


@mcp.tool
def download_must_gather(
    reportportal_url: str, force_redownload: bool = False
) -> str:
    """Download and extract must-gather logs from a ReportPortal test failure.

    Given a ReportPortal test log page URL, this tool:
    1. Resolves the corresponding Magna logs directory
    2. Finds and downloads the must-gather tarball
    3. Extracts it locally for analysis

    Results are cached by test item ID. Repeat calls return the cached path
    instantly unless force_redownload is True.

    Args:
        reportportal_url: Full ReportPortal URL to a test log page
            (must contain '/launches/' and '/log')
        force_redownload: If True, bypass cache and re-download the tarball

    Returns:
        JSON string with path, test_name, cluster_name, tarball_url,
        cached (bool), and files_count
    """
    api_key, base_url, cache_dir = _get_config()
    launch_id, test_item_id = _extract_ids(reportportal_url)

    cache_entry = cache_dir / test_item_id
    cache_entry.mkdir(parents=True, exist_ok=True)

    if not force_redownload:
        metadata = _cache_check(cache_entry)
        if metadata:
            extracted = cache_entry / "extracted"
            return json.dumps({
                "path": str(extracted),
                "test_name": metadata["test_name"],
                "cluster_name": metadata["cluster_name"],
                "tarball_url": metadata["tarball_url"],
                "cached": True,
                "files_count": metadata.get("files_count") or _count_files(extracted),
            })

    lock_path = cache_entry / ".lock"
    lock_fd = open(lock_path, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)

        if not force_redownload:
            metadata = _cache_check(cache_entry)
            if metadata:
                extracted = cache_entry / "extracted"
                return json.dumps({
                    "path": str(extracted),
                    "test_name": metadata["test_name"],
                    "cluster_name": metadata["cluster_name"],
                    "tarball_url": metadata["tarball_url"],
                    "cached": True,
                    "files_count": metadata.get("files_count") or _count_files(extracted),
                })

        extracted_dir = cache_entry / "extracted"
        if force_redownload and extracted_dir.exists():
            shutil.rmtree(extracted_dir)

        info = _resolve_test_log_directory(launch_id, test_item_id, api_key, base_url)
        tarball_url = _find_tarball_url(info, api_key)

        tarball_filename = Path(unquote(tarball_url.rsplit("/", 1)[-1])).name
        tarball_path = cache_entry / tarball_filename
        _download_tarball(tarball_url, tarball_path, api_key)
        _extract_tarball(tarball_path, extracted_dir)

        files_count = _count_files(extracted_dir)
        size_bytes = sum(f.stat().st_size for f in extracted_dir.rglob("*") if f.is_file())

        metadata = {
            "test_name": info["test_name"],
            "cluster_name": info["cluster_name"],
            "tarball_url": tarball_url,
            "launch_id": info["launch_id"],
            "test_item_id": info["test_item_id"],
            "downloaded_at": datetime.now(timezone.utc).isoformat(),
            "files_count": files_count,
            "size_bytes": size_bytes,
        }
        with open(cache_entry / "metadata.json", "w") as f:
            json.dump(metadata, f, indent=2)

        return json.dumps({
            "path": str(extracted_dir),
            "test_name": info["test_name"],
            "cluster_name": info["cluster_name"],
            "tarball_url": tarball_url,
            "cached": False,
            "files_count": files_count,
        })
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


@mcp.tool
def list_must_gather_cache() -> str:
    """List all cached must-gather extractions.

    Shows what has already been downloaded and is available for analysis,
    including the local path, test name, cluster, and download timestamp.

    Returns:
        JSON string with a list of cached entries, each containing
        test_item_id, test_name, cluster_name, path, downloaded_at,
        and size_mb
    """
    _, _, cache_dir = _get_config()

    entries = []
    if not cache_dir.exists():
        return json.dumps({"entries": [], "cache_dir": str(cache_dir)})

    for child in sorted(cache_dir.iterdir()):
        if not child.is_dir():
            continue
        metadata_path = child / "metadata.json"
        extracted_dir = child / "extracted"
        if not metadata_path.exists():
            continue
        try:
            with open(metadata_path) as f:
                meta = json.load(f)
        except (json.JSONDecodeError, IOError):
            continue

        size_bytes = meta.get("size_bytes")
        if size_bytes is None:
            size_bytes = sum(
                f.stat().st_size for f in extracted_dir.rglob("*") if f.is_file()
            ) if extracted_dir.exists() else 0

        entries.append({
            "test_item_id": child.name,
            "test_name": meta.get("test_name", "unknown"),
            "cluster_name": meta.get("cluster_name", "unknown"),
            "path": str(extracted_dir),
            "downloaded_at": meta.get("downloaded_at", "unknown"),
            "size_mb": round(size_bytes / (1024 * 1024), 1),
        })

    return json.dumps({"entries": entries, "cache_dir": str(cache_dir)})


@mcp.tool
def list_must_gather_contents(must_gather_path: str) -> str:
    """List the contents and structure of a downloaded must-gather.

    Scans the must-gather directory and reports what namespaces, resource types,
    ceph data, and other sections are available. Use this to get a quick inventory
    before drilling into specific resources.

    Args:
        must_gather_path: The extracted/ directory path from download_must_gather

    Returns:
        JSON string with must_gather_root, namespaces, cluster_scoped_resources,
        has_ceph_data, ceph_commands, ceph_log_nodes, pod_counts,
        top_level_dirs, host_service_logs, and total_files
    """
    root = _find_must_gather_root(must_gather_path)

    namespaces_dir = root / "namespaces"
    namespaces = sorted(
        d.name for d in namespaces_dir.iterdir() if d.is_dir()
    ) if namespaces_dir.is_dir() else []

    cluster_scoped = {}
    csr_dir = root / "cluster-scoped-resources"
    if csr_dir.is_dir():
        for api_group in sorted(csr_dir.iterdir()):
            if api_group.is_dir():
                resource_types = sorted(
                    d.name for d in api_group.iterdir() if d.is_dir()
                )
                if resource_types:
                    cluster_scoped[api_group.name] = resource_types

    ceph_commands_dir = root / "ceph" / "must_gather_commands"
    ceph_commands = sorted(
        f.name for f in ceph_commands_dir.iterdir() if f.is_file()
    ) if ceph_commands_dir.is_dir() else []

    ceph_logs_dir = root / "ceph_logs"
    ceph_log_nodes = sorted(
        d.name for d in ceph_logs_dir.iterdir() if d.is_dir()
    ) if ceph_logs_dir.is_dir() else []

    pod_counts = {}
    for ns in namespaces:
        pods_dir = namespaces_dir / ns / "pods"
        if not pods_dir.is_dir():
            pods_dir = namespaces_dir / ns / "core" / "pods"
        if pods_dir.is_dir():
            pod_counts[ns] = sum(1 for d in pods_dir.iterdir() if d.is_dir())

    top_level_dirs = sorted(d.name for d in root.iterdir() if d.is_dir())

    host_logs_dir = root / "host_service_logs"

    return json.dumps({
        "must_gather_root": str(root),
        "namespaces": namespaces,
        "cluster_scoped_resources": cluster_scoped,
        "has_ceph_data": len(ceph_commands) > 0,
        "ceph_commands": ceph_commands,
        "ceph_log_nodes": ceph_log_nodes,
        "pod_counts": pod_counts,
        "top_level_dirs": top_level_dirs,
        "host_service_logs": host_logs_dir.is_dir(),
        "total_files": _count_files(root),
    })



_RESOURCE_ALIASES = {
    "pv": "persistentvolume",
    "sc": "storageclass",
}

_CLUSTER_SCOPED = {
    "node": "cluster-scoped-resources/core/nodes",
    "persistentvolume": "cluster-scoped-resources/core/persistentvolumes",
    "storageclass": "cluster-scoped-resources/storage.k8s.io/storageclasses",
}

_NAMESPACED = {
    "events": ("core", "events.yaml"),
    "pod": ("core", "pods"),
    "configmap": ("core", "configmaps"),
    "secret": ("core", "secrets"),
    "deployment": ("apps", "deployments.apps"),
}

_CEPH_COMMANDS = {
    "cephhealth": "ceph_health_detail",
    "cephstatus": "ceph_status",
    "osdtree": "ceph_osd_tree",
    "osddump": "ceph_osd_dump",
}

_MAX_RESOURCE_SIZE = 100 * 1024

_ALL_SUPPORTED_TYPES = sorted(
    list(_CLUSTER_SCOPED.keys())
    + list(_NAMESPACED.keys())
    + list(_CEPH_COMMANDS.keys())
    + list(_RESOURCE_ALIASES.keys())
)


@mcp.tool
def get_must_gather_resource(
    must_gather_path: str,
    resource_type: str,
    name: str = "",
    namespace: str = "",
) -> str:
    """Retrieve a specific resource from a must-gather extraction.

    Maps logical resource names to their file paths within the must-gather
    directory structure and returns their content.

    Args:
        must_gather_path: Path to the extracted must-gather directory
        resource_type: Type of resource (node, pv, sc, events, pod,
            configmap, secret, deployment, cephhealth, cephstatus,
            osdtree, osddump)
        name: Name of the specific resource (optional — omit to list available names)
        namespace: Namespace for namespaced resources (required for events, pod, etc.)

    Returns:
        JSON string with resource content or available names listing
    """
    root = _find_must_gather_root(must_gather_path)
    rt = resource_type.lower()
    rt = _RESOURCE_ALIASES.get(rt, rt)

    if rt in _CEPH_COMMANDS:
        exact_name = _CEPH_COMMANDS[rt]
        matches = [
            f for f in root.rglob(exact_name)
            if f.is_file() and f.name == exact_name
        ]
        if not matches:
            return json.dumps({"error": f"No {rt} data found in must-gather"})
        target = matches[0]
        content = target.read_text(encoding="utf-8", errors="replace")
        result = {
            "resource_type": rt,
            "path": str(target),
            "content": content,
        }
        if len(content.encode("utf-8")) > _MAX_RESOURCE_SIZE:
            result["content"] = content[:_MAX_RESOURCE_SIZE]
            result["truncated"] = True
            result["total_size_bytes"] = target.stat().st_size
        return json.dumps(result)

    if rt in _CLUSTER_SCOPED:
        resource_dir = root / _CLUSTER_SCOPED[rt]
        if not resource_dir.is_dir():
            return json.dumps({"error": f"No {rt} directory found in must-gather"})
        if name:
            resource_file = resource_dir / f"{name}.yaml"
            if not resource_file.is_file():
                return json.dumps({"error": f"Resource not found: {rt} '{name}'"})
            content = resource_file.read_text(encoding="utf-8", errors="replace")
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
        available = sorted(
            f.stem for f in resource_dir.iterdir() if f.suffix == ".yaml"
        )
        return json.dumps({
            "resource_type": rt,
            "available_names": available,
            "hint": f"Specify a name parameter to retrieve a specific {rt}",
        })

    if rt in _NAMESPACED:
        namespaces_dir = root / "namespaces"
        if not namespace:
            available_ns = sorted(
                d.name for d in namespaces_dir.iterdir() if d.is_dir()
            ) if namespaces_dir.is_dir() else []
            return json.dumps({
                "error": f"namespace is required for resource_type '{rt}'",
                "available_namespaces": available_ns,
            })

        api_group, resource_path = _NAMESPACED[rt]

        if rt == "events":
            events_file = namespaces_dir / namespace / api_group / resource_path
            if not events_file.is_file():
                return json.dumps({"error": f"Resource not found: {rt} in namespace '{namespace}'"})
            content = events_file.read_text(encoding="utf-8", errors="replace")
            result = {
                "resource_type": rt,
                "namespace": namespace,
                "path": str(events_file),
                "content": content,
            }
            if len(content.encode("utf-8")) > _MAX_RESOURCE_SIZE:
                result["content"] = content[:_MAX_RESOURCE_SIZE]
                result["truncated"] = True
                result["total_size_bytes"] = events_file.stat().st_size
            return json.dumps(result)

        resource_dir = namespaces_dir / namespace / api_group / resource_path
        if not resource_dir.is_dir():
            return json.dumps({"error": f"No {rt} directory found in namespace '{namespace}'"})
        if name:
            resource_file = resource_dir / f"{name}.yaml"
            if not resource_file.is_file():
                return json.dumps({"error": f"Resource not found: {rt} '{name}' in namespace '{namespace}'"})
            content = resource_file.read_text(encoding="utf-8", errors="replace")
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
        available = sorted(
            f.stem for f in resource_dir.iterdir() if f.suffix == ".yaml"
        )
        return json.dumps({
            "resource_type": rt,
            "namespace": namespace,
            "available_names": available,
            "hint": f"Specify a name parameter to retrieve a specific {rt}",
        })

    return json.dumps({
        "error": f"Unknown resource_type '{resource_type}'",
        "supported_types": _ALL_SUPPORTED_TYPES,
    })


@mcp.tool
def search_must_gather(
    must_gather_path: str,
    pattern: str,
    file_pattern: str = "",
    max_results: int = 50,
    case_sensitive: bool = False,
) -> str:
    """Search through must-gather files for a pattern (grep-like).

    Searches text files in a must-gather extraction for lines matching a
    regex or literal pattern. Binary files are automatically skipped.

    Args:
        must_gather_path: Path to an extracted must-gather directory
        pattern: Regex or literal string to search for
        file_pattern: Optional glob to filter files (e.g. "*.yaml", "*.log")
        max_results: Maximum matches to return (default 50)
        case_sensitive: If False (default), search is case-insensitive

    Returns:
        JSON string with matches, total_matches, files_searched, and truncated flag
    """
    if not pattern:
        return json.dumps({"error": "pattern parameter is required"})

    root = _find_must_gather_root(must_gather_path)

    flags = 0 if case_sensitive else re.IGNORECASE
    try:
        compiled = re.compile(pattern, flags)
    except re.error:
        compiled = re.compile(re.escape(pattern), flags)

    if file_pattern:
        files = [f for f in root.rglob(file_pattern) if f.is_file()]
    else:
        files = [f for f in root.rglob("*") if f.is_file()]

    matches = []
    files_searched = 0
    truncated = False

    for filepath in sorted(files):
        try:
            head = filepath.read_bytes()[:512]
        except OSError:
            continue
        if b"\x00" in head:
            continue

        files_searched += 1
        try:
            with open(filepath, encoding="utf-8", errors="replace") as fh:
                for line_number, line in enumerate(fh, start=1):
                    if compiled.search(line):
                        matches.append({
                            "file": str(filepath.relative_to(root)),
                            "line_number": line_number,
                            "line": line.strip(),
                        })
                        if len(matches) >= max_results:
                            truncated = True
                            break
        except OSError:
            continue
        if truncated:
            break

    return json.dumps({
        "pattern": pattern,
        "file_pattern": file_pattern,
        "case_sensitive": case_sensitive,
        "matches": matches,
        "total_matches": len(matches),
        "files_searched": files_searched,
        "truncated": truncated,
    })


MAX_LOG_SIZE = 200 * 1024


@mcp.tool
def get_must_gather_pod_logs(
    must_gather_path: str,
    namespace: str,
    pod_name: str = "",
    container: str = "",
    previous: bool = False,
    tail: int = 0,
) -> str:
    """Retrieve pod logs from a must-gather extraction.

    Navigates the must-gather directory structure to find and return pod logs.
    Can list available pods in a namespace, or retrieve logs for a specific
    pod with optional container and tail filtering.

    Args:
        must_gather_path: Path to the extracted must-gather directory
        namespace: Kubernetes namespace to look in
        pod_name: Pod name or substring to match (empty = list available pods)
        container: Container name filter (empty = all containers)
        previous: If True, return previous.log instead of current.log
        tail: Number of lines from the end to return (0 = all lines)

    Returns:
        JSON string with available pods list, or pod log contents
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

    return json.dumps({
        "namespace": namespace,
        "pod_name": pod_name,
        "logs": logs,
        "total_logs_found": len(logs),
    })


def main():
    mcp.run()


if __name__ == "__main__":
    main()
