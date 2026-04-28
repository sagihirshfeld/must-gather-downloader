import json
from pathlib import Path
from unittest.mock import patch

from must_gather_downloader.server import (
    _cache_check,
    _count_files,
    _extract_tarball,
    list_must_gather_cache,
)

MODULE = "must_gather_downloader.server"


class TestCacheCheck:
    def test_valid(self, populated_cache_entry):
        result = _cache_check(populated_cache_entry["entry"])
        assert result is not None
        assert result["test_name"] == "test_my_feature"

    def test_missing_metadata(self, tmp_path):
        entry = tmp_path / "entry"
        (entry / "extracted").mkdir(parents=True)
        assert _cache_check(entry) is None

    def test_missing_extracted(self, tmp_path):
        entry = tmp_path / "entry"
        entry.mkdir()
        (entry / "metadata.json").write_text('{"test_name": "t"}')
        assert _cache_check(entry) is None

    def test_corrupt_json(self, tmp_path):
        entry = tmp_path / "entry"
        (entry / "extracted").mkdir(parents=True)
        (entry / "metadata.json").write_text("not valid json{{{")
        assert _cache_check(entry) is None


class TestCountFiles:
    def test_nested(self, tmp_path):
        (tmp_path / "a.txt").write_text("a")
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "b.txt").write_text("b")
        (sub / "c.txt").write_text("c")
        assert _count_files(tmp_path) == 3

    def test_empty_dir(self, tmp_path):
        assert _count_files(tmp_path) == 0


class TestExtractTarball:
    def test_extraction(self, sample_tarball, tmp_path):
        extract_dir = tmp_path / "extracted"
        _extract_tarball(sample_tarball, extract_dir)
        assert (extract_dir / "must-gather" / "must-gather-log.txt").exists()
        assert (
            extract_dir / "must-gather" / "must-gather-log.txt"
        ).read_text() == "sample log data"
        assert (extract_dir / "must-gather" / "subdir" / "nested.yaml").exists()

    def test_creates_dir(self, sample_tarball, tmp_path):
        extract_dir = tmp_path / "deep" / "nested" / "path"
        _extract_tarball(sample_tarball, extract_dir)
        assert extract_dir.exists()


class TestListMustGatherCache:
    def test_empty_cache(self, env_config):
        result = json.loads(list_must_gather_cache())
        assert result["entries"] == []
        assert result["cache_dir"] == env_config["cache_dir"]

    def test_with_entries(self, populated_cache_entry, monkeypatch):
        monkeypatch.setenv("RP_API_KEY", "key")
        monkeypatch.setenv("RP_BASE_URL", "https://rp.example.com")
        monkeypatch.setenv(
            "MUST_GATHER_CACHE_DIR", str(populated_cache_entry["cache_dir"])
        )
        result = json.loads(list_must_gather_cache())
        assert len(result["entries"]) == 1
        entry = result["entries"][0]
        assert entry["test_item_id"] == "67890"
        assert entry["test_name"] == "test_my_feature"
        assert entry["cluster_name"] == "test-cluster-1"
        assert "size_mb" in entry

    def test_skips_corrupt_entries(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RP_API_KEY", "key")
        monkeypatch.setenv("RP_BASE_URL", "https://rp.example.com")
        cache_dir = tmp_path / "cache"

        good = cache_dir / "good"
        (good / "extracted").mkdir(parents=True)
        (good / "metadata.json").write_text(
            json.dumps({
                "test_name": "t",
                "cluster_name": "c",
                "tarball_url": "u",
                "downloaded_at": "2025-01-01",
                "size_bytes": 100,
            })
        )

        bad = cache_dir / "bad"
        (bad / "extracted").mkdir(parents=True)
        (bad / "metadata.json").write_text("corrupt{{{")

        monkeypatch.setenv("MUST_GATHER_CACHE_DIR", str(cache_dir))
        result = json.loads(list_must_gather_cache())
        assert len(result["entries"]) == 1
        assert result["entries"][0]["test_item_id"] == "good"

    def test_size_fallback(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RP_API_KEY", "key")
        monkeypatch.setenv("RP_BASE_URL", "https://rp.example.com")
        cache_dir = tmp_path / "cache"
        entry = cache_dir / "item1"
        extracted = entry / "extracted"
        extracted.mkdir(parents=True)
        (extracted / "file.txt").write_text("hello")
        (entry / "metadata.json").write_text(
            json.dumps({
                "test_name": "t",
                "cluster_name": "c",
                "tarball_url": "u",
                "downloaded_at": "2025-01-01",
            })
        )
        monkeypatch.setenv("MUST_GATHER_CACHE_DIR", str(cache_dir))
        result = json.loads(list_must_gather_cache())
        assert len(result["entries"]) == 1
        assert result["entries"][0]["size_mb"] >= 0
