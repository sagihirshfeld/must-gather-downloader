import json
from pathlib import Path

from .config import _get_config


def _cache_check(cache_entry: Path) -> dict | None:
    """Validate a cache entry and return its metadata if valid.

    A cache entry is valid when both ``metadata.json`` and the
    ``extracted/`` directory exist and the metadata file is parseable.

    Args:
        cache_entry: Path to a cache entry directory (keyed by test item ID).

    Returns:
        Parsed metadata dict, or None if the entry is missing or corrupt.
    """
    metadata_path = cache_entry / "metadata.json"
    extracted_dir = cache_entry / "extracted"
    if metadata_path.exists() and extracted_dir.exists():
        try:
            with open(metadata_path) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return None
    return None


def list_must_gather_cache() -> str:
    """List all cached must-gather extractions with metadata and sizes.

    Returns:
        JSON string with ``entries`` list and ``cache_dir`` path.
        Each entry includes test_item_id, test_name, cluster_name,
        path, downloaded_at, and size_mb.
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
            size_bytes = (
                sum(f.stat().st_size for f in extracted_dir.rglob("*") if f.is_file()) if extracted_dir.exists() else 0
            )

        entries.append(
            {
                "test_item_id": child.name,
                "test_name": meta.get("test_name", "unknown"),
                "cluster_name": meta.get("cluster_name", "unknown"),
                "path": str(extracted_dir),
                "downloaded_at": meta.get("downloaded_at", "unknown"),
                "size_mb": round(size_bytes / (1024 * 1024), 1),
            }
        )

    return json.dumps({"entries": entries, "cache_dir": str(cache_dir)})
