import re
from urllib.parse import quote

import requests

from .config import _ssl_verify


def _extract_ids(url: str) -> tuple[str, str]:
    """Parse a ReportPortal test log URL to extract launch and test item IDs.

    Args:
        url: Full ReportPortal URL pointing to a test log page.

    Returns:
        Tuple of (launch_id, test_item_id).

    Raises:
        ValueError: If the URL format is invalid or IDs cannot be extracted.
    """
    if "launches/" not in url or "log" not in url:
        raise ValueError("Invalid ReportPortal URL. Expected a test log page URL containing '/launches/' and '/log'.")
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
    """Build HTTP headers for authenticated ReportPortal API requests."""
    return {
        "Accept": "application/json",
        "Authorization": f"Bearer {api_key}",
    }


def _fetch_json(url: str, api_key: str) -> dict:
    """Make an authenticated GET request and return the parsed JSON response.

    Args:
        url: ReportPortal API endpoint URL.
        api_key: Bearer token for authentication.

    Returns:
        Parsed JSON response as a dict.
    """
    resp = requests.get(url, headers=_rp_headers(api_key), timeout=30, verify=_ssl_verify())
    resp.raise_for_status()
    return resp.json()


def _fetch_html_lines(url: str, api_key: str = "") -> list[str]:
    """Fetch an HTML page and return its non-empty lines.

    Used for scraping Apache-style directory listings on Magna.

    Args:
        url: URL to fetch.
        api_key: Optional Bearer token. Omit for unauthenticated requests.

    Returns:
        List of non-empty lines from the HTML response body.
    """
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    resp = requests.get(url, headers=headers, timeout=30, verify=_ssl_verify())
    resp.raise_for_status()
    return [line for line in resp.text.split("\n") if line.strip()]


def _extract_hrefs(lines: list[str]) -> list[str]:
    """Extract href attribute values from HTML lines."""
    hrefs = []
    for line in lines:
        match = re.search(r'href="([^"]+)"', line)
        if match:
            hrefs.append(match.group(1))
    return hrefs


def _resolve_magna_metadata(launch_id: str, test_item_id: str, api_key: str, base_url: str) -> dict:
    """Resolve Magna base URL and test name from ReportPortal IDs.

    Queries the RP API concurrently for launch description and test item
    name, then extracts the Magna logs URL root and cluster name from the
    launch description.

    Args:
        launch_id: ReportPortal launch ID.
        test_item_id: ReportPortal test item ID.
        api_key: Bearer token for RP API.
        base_url: ReportPortal base URL (without trailing slash).

    Returns:
        Dict with keys: logs_url_root, cluster_name, test_name,
        launch_id, test_item_id.

    Raises:
        ValueError: If description or name fields are missing or the
            Magna URL cannot be parsed.
    """
    from concurrent.futures import ThreadPoolExecutor

    from .config import RP_PROJECT

    rp_api = f"{base_url}/api/v1/{RP_PROJECT}"
    launch_api = f"{rp_api}/launch?filter.eq.id={launch_id}"
    item_api = f"{rp_api}/item/{test_item_id}"

    with ThreadPoolExecutor(max_workers=2) as pool:
        launch_future = pool.submit(_fetch_json, launch_api, api_key)
        item_future = pool.submit(_fetch_json, item_api, api_key)
        launch_json = launch_future.result()
        item_json = item_future.result()

    try:
        description = launch_json["content"][0]["description"]
        logs_url_root = description.split("Logs URL:")[1].strip().split()[0]
        cluster_name = logs_url_root.split("openshift-clusters/")[1].split("/")[0]
        test_name = item_json["name"]
    except (KeyError, IndexError) as e:
        raise ValueError(
            f"Could not extract Magna logs location from ReportPortal. Missing description or name field: {e}"
        )

    return {
        "logs_url_root": logs_url_root,
        "cluster_name": cluster_name,
        "test_name": test_name,
        "launch_id": launch_id,
        "test_item_id": test_item_id,
    }


def _safe_test_name(test_name: str) -> str:
    """URL-encode a test name for use in Magna directory paths."""
    safe = f"{test_name}_ocs_logs"
    return quote(safe, safe="/[]-_.~")
