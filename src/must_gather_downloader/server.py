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
    resp = requests.get(url, headers=_rp_headers(api_key), timeout=30)
    resp.raise_for_status()
    return resp.json()


def _fetch_html_lines(url: str, api_key: str = "") -> list[str]:
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    resp = requests.get(url, headers=headers, timeout=30)
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
    with requests.get(url, headers=headers, stream=True, timeout=300) as resp:
        resp.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)


def _extract_tarball(tarball_path: Path, extract_dir: Path) -> None:
    extract_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tarball_path, "r:*") as tar:
        tar.extractall(path=extract_dir, filter="data")


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


def main():
    mcp.run()


if __name__ == "__main__":
    main()
