import fcntl
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from must_gather_downloader.download import extract_local_must_gather

MODULE = "must_gather_downloader.download"


@pytest.fixture
def local_mocks(tmp_path):
    cache_dir = tmp_path / "cache"
    patches = {
        "cache_dir": patch(f"{MODULE}._get_cache_dir", return_value=cache_dir),
        "cache_check": patch(f"{MODULE}._cache_check", return_value=None),
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


class TestExtractLocalCacheHit:
    def test_cache_hit_before_lock(self, local_mocks, sample_tarball):
        mocks, cache_dir = local_mocks
        cached_meta = {"source_tarball": str(sample_tarball), "files_count": 10}
        mocks["cache_check"].return_value = cached_meta

        source = Path(sample_tarball).resolve()
        cache_key = "local-" + hashlib.sha256(str(source).encode()).hexdigest()[:16]
        (cache_dir / cache_key / "extracted").mkdir(parents=True)

        result = json.loads(extract_local_must_gather(str(sample_tarball)))
        assert result["cached"] is True
        assert result["source_tarball"] == str(sample_tarball)
        mocks["extract"].assert_not_called()
        mocks["flock"].assert_not_called()

    def test_cache_hit_after_lock(self, local_mocks, sample_tarball):
        mocks, cache_dir = local_mocks
        cached_meta = {"source_tarball": str(sample_tarball), "files_count": 10}
        mocks["cache_check"].side_effect = [None, cached_meta]

        source = Path(sample_tarball).resolve()
        cache_key = "local-" + hashlib.sha256(str(source).encode()).hexdigest()[:16]
        (cache_dir / cache_key / "extracted").mkdir(parents=True)

        result = json.loads(extract_local_must_gather(str(sample_tarball)))
        assert result["cached"] is True
        mocks["extract"].assert_not_called()


class TestExtractLocalFullPipeline:
    def test_full_extraction(self, local_mocks, sample_tarball):
        mocks, _ = local_mocks
        result = json.loads(extract_local_must_gather(str(sample_tarball)))
        assert result["cached"] is False
        assert result["files_count"] == 42
        assert result["path"].endswith("/extracted")
        mocks["extract"].assert_called_once()

    def test_metadata_written(self, local_mocks, sample_tarball):
        mocks, cache_dir = local_mocks
        extract_local_must_gather(str(sample_tarball))

        entries = list(cache_dir.iterdir())
        assert len(entries) == 1
        meta_path = entries[0] / "metadata.json"
        assert meta_path.exists()
        meta = json.loads(meta_path.read_text())
        assert meta["source_tarball"] == str(sample_tarball.resolve())
        assert "extracted_at" in meta
        assert meta["files_count"] == 42
        assert meta["size_bytes"] == 1024

    def test_return_json_structure(self, local_mocks, sample_tarball):
        mocks, _ = local_mocks
        result = json.loads(extract_local_must_gather(str(sample_tarball)))
        assert set(result.keys()) == {"path", "source_tarball", "cached", "files_count"}


class TestExtractLocalForceReExtract:
    def test_force_re_extract(self, local_mocks, sample_tarball):
        mocks, cache_dir = local_mocks

        # First extraction
        extract_local_must_gather(str(sample_tarball))

        # Second with force — cache_check still returns None (mocked)
        result = json.loads(extract_local_must_gather(str(sample_tarball), force_re_extract=True))
        assert result["cached"] is False
        assert mocks["extract"].call_count == 2


class TestExtractLocalErrors:
    def test_tarball_not_found(self, local_mocks):
        with pytest.raises(ValueError, match="does not exist"):
            extract_local_must_gather("/nonexistent/path/must-gather.tar.gz")

    def test_path_is_directory(self, local_mocks, tmp_path):
        with pytest.raises(ValueError, match="not a file"):
            extract_local_must_gather(str(tmp_path))

    def test_invalid_tarball(self, local_mocks, tmp_path):
        mocks, _ = local_mocks
        import tarfile

        mocks["extract"].side_effect = tarfile.TarError("bad tar")
        bad_file = tmp_path / "bad.tar.gz"
        bad_file.write_bytes(b"not a tarball")

        with pytest.raises(ValueError, match="not a valid tar archive"):
            extract_local_must_gather(str(bad_file))

    def test_lock_released_on_error(self, local_mocks, tmp_path):
        mocks, _ = local_mocks
        import tarfile

        mocks["extract"].side_effect = tarfile.TarError("bad tar")
        bad_file = tmp_path / "bad.tar.gz"
        bad_file.write_bytes(b"not a tarball")

        with pytest.raises(ValueError):
            extract_local_must_gather(str(bad_file))
        flock_calls = mocks["flock"].call_args_list
        lock_flags = [c.args[1] for c in flock_calls]
        assert fcntl.LOCK_EX in lock_flags
        assert fcntl.LOCK_UN in lock_flags


class TestExtractLocalCacheKey:
    def test_same_path_same_cache_key(self, local_mocks, sample_tarball):
        mocks, cache_dir = local_mocks
        extract_local_must_gather(str(sample_tarball))
        extract_local_must_gather(str(sample_tarball))

        # Only one cache entry directory should exist
        entries = [d for d in cache_dir.iterdir() if d.is_dir()]
        assert len(entries) == 1

    def test_different_path_different_cache_key(self, local_mocks, tmp_path):
        mocks, cache_dir = local_mocks

        tarball1 = tmp_path / "a.tar.gz"
        tarball1.write_bytes(b"content1")
        tarball2 = tmp_path / "b.tar.gz"
        tarball2.write_bytes(b"content2")

        extract_local_must_gather(str(tarball1))
        extract_local_must_gather(str(tarball2))

        entries = [d for d in cache_dir.iterdir() if d.is_dir()]
        assert len(entries) == 2
