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


@pytest.fixture
def must_gather_tree(tmp_path):
    extracted = tmp_path / "extracted"
    root = extracted / "must-gather-20250115"
    root.mkdir(parents=True)

    # cluster-scoped-resources
    nodes = root / "cluster-scoped-resources" / "core" / "nodes"
    nodes.mkdir(parents=True)
    (nodes / "master-0.yaml").write_text(
        "metadata:\n  name: master-0\nstatus:\n  conditions:\n  - type: Ready\n    status: 'True'\n"
    )
    (nodes / "worker-0.yaml").write_text(
        "metadata:\n  name: worker-0\nstatus:\n  conditions:\n  - type: Ready\n    status: 'True'\n"
    )

    pvs = root / "cluster-scoped-resources" / "core" / "persistentvolumes"
    pvs.mkdir(parents=True)
    (pvs / "pv-001.yaml").write_text("metadata:\n  name: pv-001\n")

    scs = root / "cluster-scoped-resources" / "storage.k8s.io" / "storageclasses"
    scs.mkdir(parents=True)
    (scs / "ocs-storagecluster-ceph-rbd.yaml").write_text(
        "metadata:\n  name: ocs-storagecluster-ceph-rbd\n"
    )

    # namespaces/openshift-storage
    ns_os = root / "namespaces" / "openshift-storage"
    (ns_os / "core").mkdir(parents=True)
    (ns_os / "core" / "events.yaml").write_text(
        "items:\n- reason: CrashLoopBackOff\n  message: Back-off restarting\n"
    )

    mon_logs = ns_os / "core" / "pods" / "rook-ceph-mon-a-abc123" / "mon" / "mon"
    mon_logs.mkdir(parents=True)
    (mon_logs / "current.log").write_text("mon current log\n")
    (mon_logs / "previous.log").write_text("mon previous log\n")

    osd_logs = ns_os / "core" / "pods" / "rook-ceph-osd-0-def456" / "osd" / "osd"
    osd_logs.mkdir(parents=True)
    (osd_logs / "current.log").write_text("osd current log\n")

    noobaa_core = ns_os / "core" / "pods" / "noobaa-core-0" / "noobaa-core" / "noobaa-core"
    noobaa_core.mkdir(parents=True)
    (noobaa_core / "current.log").write_text("noobaa-core log\n")

    noobaa_init = ns_os / "core" / "pods" / "noobaa-core-0" / "init-container" / "init-container"
    noobaa_init.mkdir(parents=True)
    (noobaa_init / "current.log").write_text("init container log\n")

    deployments = ns_os / "apps"
    deployments.mkdir(parents=True)
    (deployments / "deployments.apps").mkdir()
    (deployments / "deployments.apps" / "noobaa-operator.yaml").write_text(
        "metadata:\n  name: noobaa-operator\n"
    )

    # namespaces/default
    ns_default = root / "namespaces" / "default" / "core"
    ns_default.mkdir(parents=True)
    (ns_default / "events.yaml").write_text("items: []\n")

    # ceph data
    ceph = root / "ceph"
    ceph.mkdir()
    (ceph / "ceph_health_detail").write_text("HEALTH_OK\n")
    (ceph / "ceph_status").write_text("cluster status ok\n")
    (ceph / "ceph_osd_dump").write_text("osd dump\n")

    # host_service_logs
    host_logs = root / "host_service_logs" / "master-0"
    host_logs.mkdir(parents=True)
    (host_logs / "kubelet.log").write_text("kubelet log\n")

    return {"extracted": extracted, "root": root}


@pytest.fixture
def empty_must_gather(tmp_path):
    root = tmp_path / "empty-extracted" / "must-gather-empty"
    root.mkdir(parents=True)
    return {"extracted": root.parent, "root": root}


@pytest.fixture
def multi_root_must_gather(tmp_path):
    extracted = tmp_path / "multi-extracted"
    (extracted / "other-dir").mkdir(parents=True)
    (extracted / "must-gather-abc").mkdir(parents=True)
    return {"extracted": extracted, "preferred": extracted / "must-gather-abc"}
