import re
from urllib.parse import quote

import requests

from .config import _ssl_verify


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
