import json
import tarfile
from unittest.mock import MagicMock

import pytest
import requests


@pytest.fixture
def env_config(monkeypatch, tmp_path):
    api_key = "test-api-key-12345"
    base_url = "https://reportportal.example.com"
    cache_dir = str(tmp_path / "cache")
    monkeypatch.setenv("RP_API_KEY", api_key)
    monkeypatch.setenv("RP_BASE_URL", base_url)
    monkeypatch.setenv("MUST_GATHER_CACHE_DIR", cache_dir)
    return {"api_key": api_key, "base_url": base_url, "cache_dir": cache_dir}


@pytest.fixture
def sample_rp_url():
    return "https://reportportal.example.com/ui/#ocs/launches/all/12345/item/67890/log"


@pytest.fixture
def sample_info_dict():
    return {
        "logs_url_root": "https://magna.example.com/openshift-clusters/test-cluster-1/",
        "cluster_name": "test-cluster-1",
        "test_name": "test_my_feature",
        "target_suffix": "failed_testcase_0/",
        "safe_test_name": "test_my_feature_ocs_logs",
        "launch_id": "12345",
        "test_item_id": "67890",
    }


@pytest.fixture
def populated_cache_entry(tmp_path):
    cache_dir = tmp_path / "cache"
    entry = cache_dir / "67890"
    extracted = entry / "extracted"
    extracted.mkdir(parents=True)
    (extracted / "some-log.txt").write_text("log content")
    metadata = {
        "test_name": "test_my_feature",
        "cluster_name": "test-cluster-1",
        "tarball_url": "https://magna.example.com/some/path/must-gather.tar.gz",
        "launch_id": "12345",
        "test_item_id": "67890",
        "downloaded_at": "2025-01-15T10:30:00+00:00",
        "files_count": 1,
        "size_bytes": 11,
    }
    (entry / "metadata.json").write_text(json.dumps(metadata))
    return {"cache_dir": cache_dir, "entry": entry, "metadata": metadata}


@pytest.fixture
def sample_tarball(tmp_path):
    content_dir = tmp_path / "tarball_content"
    content_dir.mkdir()
    (content_dir / "must-gather-log.txt").write_text("sample log data")
    sub = content_dir / "subdir"
    sub.mkdir()
    (sub / "nested.yaml").write_text("key: value")

    tarball_path = tmp_path / "must-gather.tar.gz"
    with tarfile.open(tarball_path, "w:gz") as tar:
        tar.add(content_dir, arcname="must-gather")
    return tarball_path


@pytest.fixture
def make_mock_response():
    def _make(status_code=200, json_data=None, text="", headers=None):
        resp = MagicMock()
        resp.status_code = status_code
        resp.json.return_value = json_data or {}
        resp.text = text
        resp.headers = headers or {}
        if status_code < 400:
            resp.raise_for_status.return_value = None
        else:
            resp.raise_for_status.side_effect = requests.HTTPError(response=resp)
        resp.__enter__ = MagicMock(return_value=resp)
        resp.__exit__ = MagicMock(return_value=False)
        resp.iter_content.return_value = iter([b"fake tarball content"])
        return resp
    return _make
