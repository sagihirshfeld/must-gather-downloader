from fastmcp import FastMCP

from .ai_analysis import get_ai_analysis_report as _ai_analysis_impl
from .download import download_must_gather as _download_impl
from .ocs_ci_logs import get_ocs_ci_test_log as _ocs_ci_log_impl
from .pod_logs import get_must_gather_pod_logs as _pod_logs_impl
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
    subtree: str = "auto",
) -> str:
    """Retrieve a Kubernetes resource or Ceph command output from a must-gather.

    Use this for cluster-scoped resources (nodes, PVs, StorageClasses),
    namespaced resources (pods, events, configmaps, deployments), Ceph
    data (ceph status, OSD tree), and NooBaa resources (status, diagnostics,
    logs, CNPG info, NooBaa CRD YAMLs). For pod logs, use
    get_must_gather_pod_logs.

    YAML resources are automatically cleaned (managedFields stripped).

    Args:
        must_gather_path: Path to the extracted must-gather directory
        resource_type: Type of resource. Cluster-scoped: node, pv, sc,
            objectbucket/ob. Namespaced: events, pod, configmap, secret,
            deployment, objectbucketclaim/obc, backingstore/bs,
            namespacestore/ns_store, bucketclass/bc, noobaa.
            Ceph: ceph (generic, specify name), cephhealth, cephstatus,
            osdtree, osddump.
            NooBaa: status, db_list, diagnostics, logs, cnpg
        name: Name of the specific resource (optional — omit to list available names)
        namespace: Namespace for namespaced resources (required for events, pod, etc.)
        tail: For events, return only the last N events; for NooBaa
            logs/diagnostics, return only the last N lines (0 = all, default 0)
        subtree: Which must-gather subtree to read from. "auto" (default)
            auto-detects: NooBaa-only types always use noobaa subtree,
            main-only types always use main, overlapping CRD types prefer
            noobaa if available. "main" forces the main subtree.
            "noobaa" forces the noobaa subtree.

    Returns:
        JSON string with resource content or available names listing
    """
    return _get_resource_impl(must_gather_path, resource_type, name, namespace, tail, subtree)


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
    logs (with pod/container scoping and context lines), use
    get_must_gather_pod_logs with a pattern instead.

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
    pattern: str = "",
    context_lines: int = 3,
    max_results: int = 50,
    case_sensitive: bool = False,
) -> str:
    """Retrieve full pod log content from a must-gather extraction.

    Use when you need to read complete pod logs or list available pods in a
    namespace. Can also search within pod logs for a pattern -- when pattern
    is provided, returns only matching lines with surrounding context instead
    of the full log content (more token-efficient for targeted lookups).

    Can list available pods (omit pod_name), or retrieve logs for a specific
    pod with optional container, tail, and time-range filtering.

    Args:
        must_gather_path: Path to the extracted must-gather directory
        namespace: Kubernetes namespace to look in
        pod_name: Pod name or substring to match (empty = list available pods)
        container: Container name filter (empty = all containers)
        previous: If True, return previous.log instead of current.log
        tail: Number of lines from the end to return (0 = all lines,
            full-log mode only -- ignored when pattern is provided)
        time_from: Start time filter, e.g. "03:38:00" or "2025-01-15T03:38:00"
        time_to: End time filter, e.g. "03:41:00" or "2025-01-15T03:41:00"
        pattern: Regex or literal string to search for. When provided,
            switches to search mode: returns matching lines with context
            instead of full log content
        context_lines: Lines of context before and after each match
            (default 3, search mode only)
        max_results: Maximum matches to return (default 50, search mode only)
        case_sensitive: If False (default), search is case-insensitive
            (search mode only)

    Returns:
        JSON string with available pods list, pod log contents,
        or search matches with context
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
        pattern,
        context_lines,
        max_results,
        case_sensitive,
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


@mcp.tool
def get_ai_analysis_report(
    reportportal_url: str,
    test_name: str,
    include_traceback: bool = True,
    include_suggested_fix: bool = True,
) -> str:
    """Retrieve AI failure analysis for a test from the AI analysis report.

    Use this to get automated root-cause analysis, recommended actions,
    evidence, and suggested code fixes for test failures. The AI analysis
    report is generated per run and contains structured failure analysis
    for each failed test. This is different from:
    - must-gather tools (raw cluster state at failure time)
    - get_ocs_ci_test_log (step-by-step test execution trace)
    - ReportPortal logs (failure summary and stack traces)

    Given a ReportPortal URL and test name, resolves the Magna logs
    directory, finds the AI analysis report HTML, and extracts the
    failure analysis for the requested test.

    Args:
        reportportal_url: Full ReportPortal URL to a test log page
            (must contain '/launches/' and '/log')
        test_name: Test function name, e.g.
            'test_bucket_notifications[default-logs-pvc]'.
            Matched as a substring against failure card titles.
        include_traceback: Include the traceback in results (default True)
        include_suggested_fix: Include the suggested fix or bug details
            in results (default True)

    Returns:
        JSON string with failure analysis data including root_cause,
        recommended_action, evidence, confidence, and optionally
        traceback and suggested_fix or bug_details
    """
    return _ai_analysis_impl(reportportal_url, test_name, include_traceback, include_suggested_fix)


def main():
    """Run the MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
