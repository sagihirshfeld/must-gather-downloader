from fastmcp import FastMCP

from .cache import list_must_gather_cache as _list_cache_impl
from .download import download_must_gather as _download_impl
from .noobaa import get_noobaa_resource as _get_noobaa_impl
from .pod_logs import get_must_gather_pod_logs as _pod_logs_impl
from .resources import get_must_gather_resource as _get_resource_impl
from .resources import list_must_gather_contents as _list_contents_impl
from .search import search_must_gather as _search_impl

mcp = FastMCP("must-gather")


@mcp.tool
def download_must_gather(reportportal_url: str, force_redownload: bool = False) -> str:
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
    return _download_impl(reportportal_url, force_redownload)


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
    return _list_cache_impl()


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
        top_level_dirs, host_service_logs, has_noobaa, noobaa, and total_files
    """
    return _list_contents_impl(must_gather_path)


@mcp.tool
def get_must_gather_resource(
    must_gather_path: str,
    resource_type: str,
    name: str = "",
    namespace: str = "",
    tail: int = 0,
) -> str:
    """Retrieve a specific resource from a must-gather extraction.

    Maps logical resource names to their file paths within the must-gather
    directory structure and returns their content. Kubernetes YAML resources
    are automatically cleaned (managedFields stripped) for readability.

    Args:
        must_gather_path: Path to the extracted must-gather directory
        resource_type: Type of resource. Cluster-scoped: node, pv, sc,
            objectbucket/ob. Namespaced: events, pod, configmap, secret,
            deployment, objectbucketclaim/obc, backingstore/bs,
            namespacestore/ns_store, bucketclass/bc, noobaa.
            Ceph: ceph (generic, specify name), cephhealth, cephstatus,
            osdtree, osddump
        name: Name of the specific resource (optional — omit to list available names)
        namespace: Namespace for namespaced resources (required for events, pod, etc.)
        tail: For events, return only the last N events (0 = all, default 0)

    Returns:
        JSON string with resource content or available names listing
    """
    return _get_resource_impl(must_gather_path, resource_type, name, namespace, tail)


@mcp.tool
def get_noobaa_resource(
    must_gather_path: str,
    resource_type: str,
    name: str = "",
    namespace: str = "",
    tail: int = 0,
) -> str:
    """Retrieve a resource from the NooBaa subtree of a must-gather extraction.

    Accesses NooBaa-specific data that lives under the noobaa/ directory,
    including CLI status output, diagnostics tarballs, NooBaa-specific logs,
    CNPG database info, and NooBaa CRD resources.

    Args:
        must_gather_path: Path to the extracted must-gather directory
        resource_type: Type of NooBaa resource. Options:
            status — NooBaa CLI status output
            db_list — NooBaa database table listing
            diagnostics — extracted diagnostics tarball (name="" to list, name="<file>" to read)
            logs — NooBaa log files (name="" to list, name="<file>" to read)
            cnpg — CNPG database info files (name="" to list, name="<file>" to read)
            objectbucketclaim/obc, objectbucket/ob, backingstore/bs,
            namespacestore/ns_store, bucketclass/bc, noobaa — NooBaa CRD YAMLs
        name: Specific resource or file name (optional — omit to list available)
        namespace: Namespace for namespaced CRD resources
        tail: For logs, return only the last N lines (0 = all)

    Returns:
        JSON string with resource content or available items listing
    """
    return _get_noobaa_impl(must_gather_path, resource_type, name, namespace, tail)


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
    return _search_impl(must_gather_path, pattern, file_pattern, max_results, case_sensitive)


@mcp.tool
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

    Navigates the must-gather directory structure to find and return pod logs.
    Can list available pods in a namespace, or retrieve logs for a specific
    pod with optional container, tail, and time-range filtering.

    Args:
        must_gather_path: Path to the extracted must-gather directory
        namespace: Kubernetes namespace to look in
        pod_name: Pod name or substring to match (empty = list available pods)
        container: Container name filter (empty = all containers)
        previous: If True, return previous.log instead of current.log
        tail: Number of lines from the end to return (0 = all lines)
        time_from: Start time filter, e.g. "03:38:00" or "2025-01-15T03:38:00"
        time_to: End time filter, e.g. "03:41:00" or "2025-01-15T03:41:00"

    Returns:
        JSON string with available pods list, or pod log contents
    """
    return _pod_logs_impl(
        must_gather_path,
        namespace,
        pod_name,
        container,
        previous,
        tail,
        time_from,
        time_to,
    )


def main():
    """Run the MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
