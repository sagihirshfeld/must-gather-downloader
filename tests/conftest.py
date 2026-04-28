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
def must_gather_tree(tmp_path):
    root = tmp_path / "extracted" / "must-gather-20250115"

    nodes = root / "cluster-scoped-resources" / "core" / "nodes"
    nodes.mkdir(parents=True)
    (nodes / "master-0.yaml").write_text(
        "apiVersion: v1\nkind: Node\nmetadata:\n  name: master-0\n"
        "status:\n  conditions:\n    - type: Ready\n      status: 'True'\n"
    )
    (nodes / "worker-0.yaml").write_text(
        "apiVersion: v1\nkind: Node\nmetadata:\n  name: worker-0\n"
        "status:\n  conditions:\n    - type: Ready\n      status: 'True'\n"
    )

    pvs = root / "cluster-scoped-resources" / "core" / "persistentvolumes"
    pvs.mkdir(parents=True)
    (pvs / "pv-001.yaml").write_text(
        "apiVersion: v1\nkind: PersistentVolume\nmetadata:\n  name: pv-001\n"
    )

    scs = root / "cluster-scoped-resources" / "storage.k8s.io" / "storageclasses"
    scs.mkdir(parents=True)
    (scs / "ocs-storagecluster-ceph-rbd.yaml").write_text(
        "apiVersion: storage.k8s.io/v1\nkind: StorageClass\n"
        "metadata:\n  name: ocs-storagecluster-ceph-rbd\n"
    )

    os_ns = root / "namespaces" / "openshift-storage"
    (os_ns / "core").mkdir(parents=True)
    (os_ns / "core" / "events.yaml").write_text(
        "apiVersion: v1\nkind: EventList\nitems:\n"
        "  - reason: CrashLoopBackOff\n    message: back-off restarting\n"
    )

    pods_yaml_dir = os_ns / "core" / "pods"
    pods_yaml_dir.mkdir(parents=True)
    (pods_yaml_dir / "rook-ceph-mon-a-abc123.yaml").write_text(
        "apiVersion: v1\nkind: Pod\nmetadata:\n  name: rook-ceph-mon-a-abc123\n"
    )

    pods_dir = os_ns / "pods"

    mon_pod = pods_dir / "rook-ceph-mon-a-abc123" / "mon" / "mon" / "logs"
    mon_pod.mkdir(parents=True)
    (mon_pod / "current.log").write_text("mon current log\n")
    (mon_pod / "previous.log").write_text("mon previous log\n")

    osd_pod = pods_dir / "rook-ceph-osd-0-def456" / "osd" / "osd" / "logs"
    osd_pod.mkdir(parents=True)
    (osd_pod / "current.log").write_text("osd current log\n")

    noobaa_pod = pods_dir / "noobaa-core-0"
    noobaa_core = noobaa_pod / "noobaa-core" / "noobaa-core" / "logs"
    noobaa_core.mkdir(parents=True)
    (noobaa_core / "current.log").write_text("noobaa-core log\n")
    noobaa_init = noobaa_pod / "init-container" / "init-container" / "logs"
    noobaa_init.mkdir(parents=True)
    (noobaa_init / "current.log").write_text("init-container log\n")

    deployments = os_ns / "apps" / "deployments.apps"
    deployments.mkdir(parents=True)
    (deployments / "noobaa-operator.yaml").write_text(
        "apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: noobaa-operator\n"
    )

    # configmaps and secrets dirs for namespaced resource tests
    cms = os_ns / "core" / "configmaps"
    cms.mkdir(parents=True)
    (cms / "rook-ceph-mon-endpoints.yaml").write_text(
        "apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: rook-ceph-mon-endpoints\n"
    )

    secrets = os_ns / "core" / "secrets"
    secrets.mkdir(parents=True)
    (secrets / "rook-ceph-admin.yaml").write_text(
        "apiVersion: v1\nkind: Secret\nmetadata:\n  name: rook-ceph-admin\n"
    )

    default_ns = root / "namespaces" / "default" / "core"
    default_ns.mkdir(parents=True)
    (default_ns / "events.yaml").write_text(
        "apiVersion: v1\nkind: EventList\nitems: []\n"
    )

    ceph_cmds = root / "ceph" / "must_gather_commands"
    ceph_cmds.mkdir(parents=True)
    (ceph_cmds / "ceph_health_detail").write_text("HEALTH_WARN\n")
    (ceph_cmds / "ceph_status").write_text("cluster status OK\n")
    (ceph_cmds / "ceph_fs_status").write_text("cephfs status data\n")
    (ceph_cmds / "ceph_osd_dump").write_text("osd dump data\n")
    (ceph_cmds / "ceph_osd_tree").write_text("osd tree data\n")

    ceph_logs = root / "ceph_logs"
    (ceph_logs / "ceph_daemon_log_master-0").mkdir(parents=True)
    (ceph_logs / "ceph_daemon_log_worker-0").mkdir(parents=True)

    host_logs = root / "host_service_logs" / "master-0"
    host_logs.mkdir(parents=True)
    (host_logs / "kubelet.log").write_text("kubelet log line\n")

    return {"extracted": tmp_path / "extracted", "root": root}


@pytest.fixture
def empty_must_gather(tmp_path):
    extracted = tmp_path / "extracted"
    root = extracted / "must-gather-empty"
    root.mkdir(parents=True)
    return {"extracted": extracted, "root": root}


@pytest.fixture
def multi_root_must_gather(tmp_path):
    extracted = tmp_path / "extracted"
    (extracted / "other-dir").mkdir(parents=True)
    preferred = extracted / "must-gather-20250115"
    preferred.mkdir(parents=True)
    return {"extracted": extracted, "preferred": preferred}


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
