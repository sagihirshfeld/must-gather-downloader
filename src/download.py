import fcntl
import json
import shutil
import tarfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote

import requests

from .cache import _cache_check
from .config import _get_config, _ssl_verify
from .navigate import _count_files, _count_files_and_size
from .reportportal import (
    _extract_hrefs,
    _extract_ids,
    _fetch_html_lines,
    _resolve_magna_metadata,
    _safe_test_name,
)


def _resolve_test_log_directory(launch_id: str, test_item_id: str, api_key: str, base_url: str) -> dict:
    """Resolve the Magna logs directory for a ReportPortal test failure.

    Calls the RP API to get the launch description (Magna logs URL) and
    test name, then crawls Magna directory listings to locate the
    ``failed_testcase`` directory that contains this test.

    Args:
        launch_id: ReportPortal launch ID.
        test_item_id: ReportPortal test item ID.
        api_key: Bearer token for RP and Magna.
        base_url: ReportPortal base URL (without trailing slash).

    Returns:
        Dict with keys: logs_url_root, cluster_name, test_name,
        target_suffix, safe_test_name, launch_id, test_item_id.

    Raises:
        ValueError: If metadata cannot be extracted or the test is not
            found in any failed_testcase directory.
    """
    meta = _resolve_magna_metadata(launch_id, test_item_id, api_key, base_url)
    logs_url_root = meta["logs_url_root"]
    cluster_name = meta["cluster_name"]
    test_name = meta["test_name"]

    lines = _fetch_html_lines(logs_url_root, api_key)
    hrefs = _extract_hrefs(lines)
    failed_dir_suffixes = [h for h in hrefs if "failed_testcase" in h]

    if not failed_dir_suffixes:
        raise ValueError("No failed_testcase directories found on Magna.")

    def _check_suffix(suffix):
        """Check if the test name appears in the given failed_testcase directory."""
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
        raise ValueError("Test exists in ReportPortal but not found in any failed_testcase directory on Magna.")

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
    """Locate the must-gather tarball URL on Magna.

    Navigates into the test's cluster subdirectory and selects the
    tarball, preferring files with "must_gather" or "must-gather"
    in the name.

    Args:
        info: Resolution dict from ``_resolve_test_log_directory``.
        api_key: Bearer token for Magna.

    Returns:
        Full URL to the must-gather tarball.

    Raises:
        ValueError: If no tarball is found in the expected directory.
    """
    cluster_dir = "/".join(
        [
            info["logs_url_root"].rstrip("/"),
            info["target_suffix"].rstrip("/"),
            info["safe_test_name"],
            info["cluster_name"],
        ]
    )

    lines = _fetch_html_lines(cluster_dir, api_key)
    hrefs = _extract_hrefs(lines)
    tarball_hrefs = [h for h in hrefs if h.endswith(".tar.gz") or h.endswith(".tgz") or h.endswith(".tar")]

    if not tarball_hrefs:
        raise ValueError("No must-gather tarball found in the expected location on Magna.")

    preferred = next(
        (h for h in tarball_hrefs if "must_gather" in h or "must-gather" in h),
        None,
    )
    tarball_suffix = preferred or tarball_hrefs[0]

    return f"{cluster_dir.rstrip('/')}/{tarball_suffix.lstrip('/')}"


def _download_tarball(url: str, dest: Path, api_key: str = "") -> None:
    """Stream-download a tarball from a URL to a local file."""
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    with requests.get(url, headers=headers, stream=True, timeout=300, verify=_ssl_verify()) as resp:
        resp.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)


def _extract_tarball(tarball_path: Path, extract_dir: Path) -> None:
    """Extract a tarball to the given directory using safe data-only filtering."""
    extract_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tarball_path, "r:*") as tar:
        tar.extractall(path=extract_dir, filter="data")


def download_must_gather(reportportal_url: str, force_redownload: bool = False) -> str:
    """Download, cache, and extract a must-gather tarball from ReportPortal.

    Orchestrates the full pipeline: URL parsing, cache lookup (with file
    locking for concurrent safety), resolution via RP API and Magna,
    download, extraction, and metadata persistence.

    Args:
        reportportal_url: Full ReportPortal test log page URL.
        force_redownload: If True, bypass cache and re-download.

    Returns:
        JSON string with path, test_name, cluster_name, tarball_url,
        cached flag, and files_count.
    """
    api_key, base_url, cache_dir = _get_config()
    launch_id, test_item_id = _extract_ids(reportportal_url)

    cache_entry = cache_dir / test_item_id
    cache_entry.mkdir(parents=True, exist_ok=True)

    if not force_redownload:
        metadata = _cache_check(cache_entry)
        if metadata:
            extracted = cache_entry / "extracted"
            return json.dumps(
                {
                    "path": str(extracted),
                    "test_name": metadata["test_name"],
                    "cluster_name": metadata["cluster_name"],
                    "tarball_url": metadata["tarball_url"],
                    "cached": True,
                    "files_count": metadata.get("files_count") or _count_files(extracted),
                }
            )

    lock_path = cache_entry / ".lock"
    with open(lock_path, "w") as lock_fd:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        try:
            if not force_redownload:
                metadata = _cache_check(cache_entry)
                if metadata:
                    extracted = cache_entry / "extracted"
                    return json.dumps(
                        {
                            "path": str(extracted),
                            "test_name": metadata["test_name"],
                            "cluster_name": metadata["cluster_name"],
                            "tarball_url": metadata["tarball_url"],
                            "cached": True,
                            "files_count": metadata.get("files_count") or _count_files(extracted),
                        }
                    )

            extracted_dir = cache_entry / "extracted"
            if force_redownload and extracted_dir.exists():
                shutil.rmtree(extracted_dir)

            info = _resolve_test_log_directory(launch_id, test_item_id, api_key, base_url)
            tarball_url = _find_tarball_url(info, api_key)

            tarball_filename = Path(unquote(tarball_url.rsplit("/", 1)[-1])).name
            tarball_path = cache_entry / tarball_filename
            _download_tarball(tarball_url, tarball_path, api_key)
            _extract_tarball(tarball_path, extracted_dir)
            tarball_path.unlink(missing_ok=True)

            files_count, size_bytes = _count_files_and_size(extracted_dir)

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

            return json.dumps(
                {
                    "path": str(extracted_dir),
                    "test_name": info["test_name"],
                    "cluster_name": info["cluster_name"],
                    "tarball_url": tarball_url,
                    "cached": False,
                    "files_count": files_count,
                }
            )
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
