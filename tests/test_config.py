import logging
from pathlib import Path

import pytest

from must_gather_downloader.config import _get_config, _ssl_verify


class TestGetConfig:
    def test_all_vars_set(self, env_config):
        api_key, base_url, cache_dir = _get_config()
        assert api_key == env_config["api_key"]
        assert base_url == env_config["base_url"]
        assert isinstance(cache_dir, Path)
        assert str(cache_dir) == env_config["cache_dir"]

    def test_default_cache_dir(self, monkeypatch):
        monkeypatch.setenv("RP_API_KEY", "key")
        monkeypatch.setenv("RP_BASE_URL", "https://rp.example.com")
        monkeypatch.delenv("MUST_GATHER_CACHE_DIR", raising=False)
        _, _, cache_dir = _get_config()
        assert cache_dir == Path("/tmp/must-gather-cache")

    def test_missing_api_key(self, monkeypatch):
        monkeypatch.delenv("RP_API_KEY", raising=False)
        monkeypatch.setenv("RP_BASE_URL", "https://rp.example.com")
        with pytest.raises(ValueError, match="RP_API_KEY"):
            _get_config()

    def test_missing_base_url(self, monkeypatch):
        monkeypatch.setenv("RP_API_KEY", "key")
        monkeypatch.delenv("RP_BASE_URL", raising=False)
        with pytest.raises(ValueError, match="RP_API_KEY"):
            _get_config()

    def test_strips_quotes_and_slashes(self, monkeypatch):
        monkeypatch.setenv("RP_API_KEY", "key")
        monkeypatch.setenv("RP_BASE_URL", '"https://rp.example.com/"')
        monkeypatch.delenv("MUST_GATHER_CACHE_DIR", raising=False)
        _, base_url, _ = _get_config()
        assert base_url == "https://rp.example.com"


class TestSslVerify:
    def test_default_is_true(self, monkeypatch):
        monkeypatch.delenv("RP_SSL_VERIFY", raising=False)
        assert _ssl_verify() is True

    def test_explicit_true(self, monkeypatch):
        monkeypatch.setenv("RP_SSL_VERIFY", "true")
        assert _ssl_verify() is True

    def test_false(self, monkeypatch):
        monkeypatch.setenv("RP_SSL_VERIFY", "false")
        assert _ssl_verify() is False

    def test_ca_bundle_path(self, monkeypatch):
        monkeypatch.setenv("RP_SSL_VERIFY", "/etc/pki/tls/certs/ca-bundle.crt")
        assert _ssl_verify() == "/etc/pki/tls/certs/ca-bundle.crt"

    def test_ssl_false_logs_warning(self, monkeypatch, caplog):
        monkeypatch.setenv("RP_SSL_VERIFY", "false")
        with caplog.at_level(logging.WARNING, logger="must_gather_downloader.config"):
            _ssl_verify()
        assert "SSL verification is disabled" in caplog.text
