import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

RP_PROJECT = "ocs"


def _ssl_verify() -> bool | str:
    """Return the SSL verification setting from the RP_SSL_VERIFY env var.

    Returns:
        False if verification is disabled, True for default verification,
        or a file path string pointing to a custom CA bundle.
    """
    val = os.environ.get("RP_SSL_VERIFY", "true").strip().lower()
    if val == "false":
        logger.warning(
            "SSL verification is disabled (RP_SSL_VERIFY=false). Connections are vulnerable to MITM attacks."
        )
        return False
    if val == "true":
        return True
    return val


def _get_cache_dir() -> Path:
    """Return the must-gather cache directory from environment.

    Defaults to ``/tmp/must-gather-cache`` when ``MUST_GATHER_CACHE_DIR``
    is not set.
    """
    return Path(os.environ.get("MUST_GATHER_CACHE_DIR", "/tmp/must-gather-cache"))


def _get_config():
    """Read configuration from environment variables.

    Returns:
        Tuple of (api_key, base_url, cache_dir) where cache_dir is a Path.

    Raises:
        ValueError: If RP_API_KEY or RP_BASE_URL are not set.
    """
    api_key = os.environ.get("RP_API_KEY", "")
    base_url = os.environ.get("RP_BASE_URL", "").strip().strip("\"'").rstrip("/")
    cache_dir = _get_cache_dir()
    if not api_key or not base_url:
        raise ValueError(
            "RP_API_KEY and RP_BASE_URL environment variables are required. Configure them in your MCP server settings."
        )
    return api_key, base_url, cache_dir
