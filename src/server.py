from fastmcp import FastMCP

from .cache import list_must_gather_cache as _list_cache_impl
from .download import download_must_gather as _download_impl
from .noobaa import get_noobaa_resource as _get_noobaa_impl
from .ocs_ci_logs import get_ocs_ci_test_log as _ocs_ci_log_impl
from .pod_logs import get_must_gather_pod_logs as _pod_logs_impl
from .pod_logs import search_pod_logs as _search_pod_logs_impl
from .resources import get_must_gather_resource as _get_resource_impl
from .resources import list_must_gather_contents as _list_contents_impl
from .search import search_must_gather as _search_impl

mcp = FastMCP("must-gather")


@mcp.tool
def download_must_gather(reportportal_url: str, force_redownload: bool = False) -> str:
    """Download and extract must-gather logs from a ReportPortal test failure.

    Use this when ReportPortal logs alone don't explain the failure and you
    need cluster state -- pod logs, Kubernetes resources, Ceph status, or
    NooBaa data. Must-gather is a cluster snapshot, not the test execution
    trace (use get_ocs_ci_test_log for that).

    Given a ReportPortal test log page URL, this tool resolves the
    corresponding Magna logs directory, finds and downloads the must-gather
    tarball, and extracts it locally. Results are cached by test item ID;
    repeat calls return the cached path instantly unless force_redownload
    is True.

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
    """Retrieve a Kubernetes resource or Ceph command output from a must-gather.

    Use this for cluster-scoped resources (nodes, PVs, StorageClasses),
    namespaced resources (pods, events, configmaps, deployments), and Ceph
    data (ceph status, OSD tree). For NooBaa-specific resources (diagnostics,
    NooBaa logs, CNPG info, NooBaa CLI status), use get_noobaa_resource
    instead. For pod logs, use get_must_gather_pod_logs or search_pod_logs.

    YAML resources are automatically cleaned (managedFields stripped).

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

    Use when the failure involves object storage, buckets, backingstores,
    or namespacestores. Accesses NooBaa-specific data: CLI status output,
    diagnostics tarballs, NooBaa operator logs, CNPG database info, and
    NooBaa CRD resources (backingstores, namespacestores, bucketclasses,
    OBCs). For general Kubernetes resources or Ceph data, use
    get_must_gather_resource instead.

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
    """Search through all must-gather files for a pattern (grep-like).

    Use for broad searches across the entire must-gather -- YAML resources,
    Ceph outputs, config files, and logs alike. To search only within pod
    logs (with pod/container scoping and context lines), use search_pod_logs
    instead.

    Searches text files for lines matching a regex or literal pattern.
    Binary files are automatically skipped.

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
    """Retrieve full pod log content from a must-gather extraction.

    Use when you need to read complete pod logs or list available pods in a
    namespace. If you already know what pattern to look for, use
    search_pod_logs instead -- it returns only matching lines with context,
    which uses fewer tokens.

    Can list available pods (omit pod_name), or retrieve logs for a specific
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


@mcp.tool
def search_pod_logs(
    must_gather_path: str,
    namespace: str,
    pod_name: str,
    pattern: str,
    container: str = "",
    previous: bool = False,
    context_lines: int = 3,
    max_results: int = 50,
    case_sensitive: bool = False,
    time_from: str = "",
    time_to: str = "",
) -> str:
    """Search within pod log files and return matching lines with context.

    Targeted search that combines pod-log file discovery with pattern matching.
    Returns only matching lines with surrounding context instead of full log
    content. Fills the gap between get_must_gather_pod_logs (full log) and
    search_must_gather (all files).

    Args:
        must_gather_path: Path to the extracted must-gather directory
        namespace: Kubernetes namespace to look in
        pod_name: Pod name or substring to match
        pattern: Regex or literal string to search for
        container: Container name filter (empty = all containers)
        previous: If True, search previous.log instead of current.log
        context_lines: Lines of context before and after each match (default 3)
        max_results: Maximum matches to return (default 50)
        case_sensitive: If False (default), search is case-insensitive
        time_from: Start time filter, e.g. "03:38:00" or "2025-01-15T03:38:00"
        time_to: End time filter, e.g. "03:41:00" or "2025-01-15T03:41:00"

    Returns:
        JSON string with matches list, each containing line_number, line,
        context_before, context_after, pod, container, and log_file
    """
    return _search_pod_logs_impl(
        must_gather_path,
        namespace,
        pod_name,
        pattern,
        container,
        previous,
        context_lines,
        max_results,
        case_sensitive,
        time_from,
        time_to,
    )


@mcp.tool
def get_ocs_ci_test_log(
    reportportal_url: str,
    test_name: str,
    tail: int = 0,
    head: int = 0,
) -> str:
    """Retrieve OCS-CI test log from a ReportPortal launch.

    Use this to see the test execution trace -- what the test framework did
    step by step, including setup, teardown, assertions, and oc commands.
    This is different from must-gather tools (which show cluster state at
    failure time) and ReportPortal logs (which show the failure summary).
    Does not require downloading a must-gather first; fetches directly
    from Magna.

    Extracts the test's section from the full deploy log by finding the
    pytest test header and collecting everything up to the next test.
    ANSI escape codes are stripped from the output.

    Args:
        reportportal_url: Full ReportPortal URL to a test log page
            (must contain '/launches/' and '/log')
        test_name: Test function name, e.g.
            'test_bucket_notifications[default-logs-pvc]'.
            Matched as a substring against pytest nodeids in the log.
        tail: Return only the last N lines after extraction (0 = all)
        head: Return only the first N lines after extraction (0 = all)

    Returns:
        JSON string with test log content and metadata including
        line counts and truncation info
    """
    return _ocs_ci_log_impl(reportportal_url, test_name, tail, head)


def main():
    """Run the MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
