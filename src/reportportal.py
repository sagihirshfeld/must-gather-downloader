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


def _safe_test_name(test_name: str) -> str:
    """URL-encode a test name for use in Magna directory paths."""
    safe = f"{test_name}_ocs_logs"
    return quote(safe, safe="/[]-_.~")
