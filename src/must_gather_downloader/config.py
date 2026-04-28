import os
from pathlib import Path

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
