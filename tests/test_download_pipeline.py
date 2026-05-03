import fcntl
import json
from unittest.mock import patch

import pytest

from must_gather_downloader.download import download_must_gather

MODULE = "must_gather_downloader.download"


@pytest.fixture
def pipeline_mocks(tmp_path, sample_info_dict):
    cache_dir = tmp_path / "cache"
    config = ("test-key", "https://rp.example.com", cache_dir)
    tarball_url = "https://magna.example.com/path/must-gather.tar.gz"

    patches = {
        "get_config": patch(f"{MODULE}._get_config", return_value=config),
        "extract_ids": patch(f"{MODULE}._extract_ids", return_value=("12345", "67890")),
        "cache_check": patch(f"{MODULE}._cache_check", return_value=None),
        "resolve": patch(f"{MODULE}._resolve_test_log_directory", return_value=sample_info_dict),
        "find_tarball": patch(f"{MODULE}._find_tarball_url", return_value=tarball_url),
        "download": patch(f"{MODULE}._download_tarball"),
        "extract": patch(f"{MODULE}._extract_tarball"),
        "count": patch(f"{MODULE}._count_files_and_size", return_value=(42, 1024)),
        "flock": patch(f"{MODULE}.fcntl.flock"),
    }

    mocks = {}
    for key, p in patches.items():
        mocks[key] = p.start()

    yield mocks, cache_dir

    for p in patches.values():
        p.stop()


class TestDownloadCacheHit:
    def test_cache_hit_before_lock(self, pipeline_mocks):
        mocks, cache_dir = pipeline_mocks
        cached_meta = {
            "test_name": "test_my_feature",
            "cluster_name": "test-cluster-1",
            "tarball_url": "https://magna.example.com/path/must-gather.tar.gz",
            "files_count": 10,
        }
        mocks["cache_check"].return_value = cached_meta

        # Need to create the extracted dir since it's referenced in the return
        entry = cache_dir / "67890"
        (entry / "extracted").mkdir(parents=True)

        result = json.loads(download_must_gather("https://rp.example.com/launches/all/12345/item/67890/log"))
        assert result["cached"] is True
        mocks["resolve"].assert_not_called()
        mocks["flock"].assert_not_called()

    def test_cache_hit_after_lock(self, pipeline_mocks):
        mocks, cache_dir = pipeline_mocks
        cached_meta = {
            "test_name": "test_my_feature",
            "cluster_name": "test-cluster-1",
            "tarball_url": "https://magna.example.com/path/must-gather.tar.gz",
            "files_count": 10,
        }
        mocks["cache_check"].side_effect = [None, cached_meta]

        entry = cache_dir / "67890"
        (entry / "extracted").mkdir(parents=True)

        result = json.loads(download_must_gather("https://rp.example.com/launches/all/12345/item/67890/log"))
        assert result["cached"] is True
        mocks["resolve"].assert_not_called()


class TestDownloadFullPipeline:
    def test_full_download(self, pipeline_mocks, sample_info_dict):
        mocks, cache_dir = pipeline_mocks

        result = json.loads(download_must_gather("https://rp.example.com/launches/all/12345/item/67890/log"))
        assert result["cached"] is False
        assert result["files_count"] == 42
        assert result["test_name"] == "test_my_feature"
        assert result["path"].endswith("/extracted")
        mocks["resolve"].assert_called_once()
        mocks["download"].assert_called_once()
        mocks["extract"].assert_called_once()

    def test_metadata_written(self, pipeline_mocks):
        mocks, cache_dir = pipeline_mocks
        download_must_gather("https://rp.example.com/launches/all/12345/item/67890/log")
        metadata_path = cache_dir / "67890" / "metadata.json"
        assert metadata_path.exists()
        meta = json.loads(metadata_path.read_text())
        assert meta["test_name"] == "test_my_feature"
        assert meta["cluster_name"] == "test-cluster-1"
        assert "downloaded_at" in meta
        assert "files_count" in meta
        assert "size_bytes" in meta

    def test_return_json_structure(self, pipeline_mocks):
        mocks, cache_dir = pipeline_mocks
        result = json.loads(download_must_gather("https://rp.example.com/launches/all/12345/item/67890/log"))
        expected_keys = {"path", "test_name", "cluster_name", "tarball_url", "cached", "files_count"}
        assert set(result.keys()) == expected_keys


class TestDownloadForceRedownload:
    def test_force_redownload(self, pipeline_mocks):
        mocks, cache_dir = pipeline_mocks

        entry = cache_dir / "67890"
        extracted = entry / "extracted"
        extracted.mkdir(parents=True)
        (extracted / "old-file.txt").write_text("old")

        result = json.loads(
            download_must_gather(
                "https://rp.example.com/launches/all/12345/item/67890/log",
                force_redownload=True,
            )
        )
        assert result["cached"] is False
        mocks["resolve"].assert_called_once()
        assert not (extracted / "old-file.txt").exists()


class TestDownloadErrors:
    def test_config_error(self, pipeline_mocks):
        mocks, _ = pipeline_mocks
        mocks["get_config"].side_effect = ValueError("missing env")
        with pytest.raises(ValueError, match="missing env"):
            download_must_gather("https://rp.example.com/launches/all/12345/item/67890/log")

    def test_invalid_url(self, pipeline_mocks):
        mocks, _ = pipeline_mocks
        mocks["extract_ids"].side_effect = ValueError("bad url")
        with pytest.raises(ValueError, match="bad url"):
            download_must_gather("bad-url")

    def test_resolve_error(self, pipeline_mocks):
        mocks, _ = pipeline_mocks
        mocks["resolve"].side_effect = ValueError("not found")
        with pytest.raises(ValueError, match="not found"):
            download_must_gather("https://rp.example.com/launches/all/12345/item/67890/log")

    def test_lock_released_on_error(self, pipeline_mocks):
        mocks, _ = pipeline_mocks
        mocks["resolve"].side_effect = ValueError("not found")
        with pytest.raises(ValueError):
            download_must_gather("https://rp.example.com/launches/all/12345/item/67890/log")
        flock_calls = mocks["flock"].call_args_list
        lock_flags = [c.args[1] for c in flock_calls]
        assert fcntl.LOCK_EX in lock_flags
        assert fcntl.LOCK_UN in lock_flags
