import json
import tarfile
from unittest.mock import MagicMock

import pytest
import requests


@pytest.fixture
def env_config(monkeypatch, tmp_path):
    """Set RP_API_KEY, RP_BASE_URL, and MUST_GATHER_CACHE_DIR env vars for testing."""
    api_key = "test-api-key-12345"
    base_url = "https://reportportal.example.com"
    cache_dir = str(tmp_path / "cache")
    monkeypatch.setenv("RP_API_KEY", api_key)
    monkeypatch.setenv("RP_BASE_URL", base_url)
    monkeypatch.setenv("MUST_GATHER_CACHE_DIR", cache_dir)
    return {"api_key": api_key, "base_url": base_url, "cache_dir": cache_dir}


@pytest.fixture
def sample_rp_url():
    """Return a sample ReportPortal test log URL."""
    return "https://reportportal.example.com/ui/#ocs/launches/all/12345/item/67890/log"


@pytest.fixture
def sample_info_dict():
    """Return a sample resolution info dict as produced by _resolve_test_log_directory."""
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
    """Create a populated cache directory with metadata.json and an extracted file."""
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
    """Create a temporary .tar.gz containing sample must-gather content."""
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
    """Create a full must-gather directory tree with nodes, PVs, pods, ceph, and NooBaa data."""
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
    (pvs / "pv-001.yaml").write_text("apiVersion: v1\nkind: PersistentVolume\nmetadata:\n  name: pv-001\n")

    scs = root / "cluster-scoped-resources" / "storage.k8s.io" / "storageclasses"
    scs.mkdir(parents=True)
    (scs / "ocs-storagecluster-ceph-rbd.yaml").write_text(
        "apiVersion: storage.k8s.io/v1\nkind: StorageClass\nmetadata:\n  name: ocs-storagecluster-ceph-rbd\n"
    )

    os_ns = root / "namespaces" / "openshift-storage"
    (os_ns / "core").mkdir(parents=True)
    (os_ns / "core" / "events.yaml").write_text(
        "apiVersion: v1\nkind: EventList\nitems:\n"
        "- reason: Created\n  message: pod created\n"
        "  metadata:\n    managedFields:\n    - manager: kubelet\n"
        "      apiVersion: v1\n    name: ev-1\n"
        "- reason: Scheduled\n  message: pod scheduled\n"
        "  metadata:\n    managedFields:\n    - manager: scheduler\n"
        "      apiVersion: v1\n    name: ev-2\n"
        "- reason: CrashLoopBackOff\n  message: back-off restarting\n"
        "  metadata:\n    managedFields:\n    - manager: kubelet\n"
        "      apiVersion: v1\n    name: ev-3\n"
    )

    pods_yaml_dir = os_ns / "core" / "pods"
    pods_yaml_dir.mkdir(parents=True)
    (pods_yaml_dir / "rook-ceph-mon-a-abc123.yaml").write_text(
        "apiVersion: v1\nkind: Pod\nmetadata:\n  name: rook-ceph-mon-a-abc123\n"
    )

    pods_dir = os_ns / "pods"

    mon_pod = pods_dir / "rook-ceph-mon-a-abc123" / "mon" / "mon" / "logs"
    mon_pod.mkdir(parents=True)
    (mon_pod / "current.log").write_text(
        "2025-01-15T03:37:00.000Z normal line before window\n"
        "2025-01-15T03:38:30.000Z line inside window\n"
        "  stack trace continuation\n"
        "2025-01-15T03:39:00.000Z another inside window\n"
        "2025-01-15T03:41:30.000Z line after window\n"
        "2025-01-15T03:42:00.000Z final line\n"
    )
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
    (secrets / "rook-ceph-admin.yaml").write_text("apiVersion: v1\nkind: Secret\nmetadata:\n  name: rook-ceph-admin\n")

    # NooBaa CRD resources under main must-gather tree
    obc_dir = os_ns / "objectbucket.io" / "objectbucketclaims"
    obc_dir.mkdir(parents=True)
    (obc_dir / "my-obc.yaml").write_text(
        "apiVersion: objectbucket.io/v1alpha1\nkind: ObjectBucketClaim\n"
        "metadata:\n  name: my-obc\n  namespace: openshift-storage\n"
    )

    ob_dir = root / "cluster-scoped-resources" / "objectbucket.io" / "objectbuckets"
    ob_dir.mkdir(parents=True)
    (ob_dir / "obc-ns-my-obc.yaml").write_text(
        "apiVersion: objectbucket.io/v1alpha1\nkind: ObjectBucket\nmetadata:\n  name: obc-ns-my-obc\n"
    )

    bs_dir = os_ns / "noobaa.io" / "backingstores"
    bs_dir.mkdir(parents=True)
    (bs_dir / "noobaa-default-backing-store.yaml").write_text(
        "apiVersion: noobaa.io/v1alpha1\nkind: BackingStore\nmetadata:\n  name: noobaa-default-backing-store\n"
    )

    ns_store_dir = os_ns / "noobaa.io" / "namespacestores"
    ns_store_dir.mkdir(parents=True)
    (ns_store_dir / "my-ns-store.yaml").write_text(
        "apiVersion: noobaa.io/v1alpha1\nkind: NamespaceStore\nmetadata:\n  name: my-ns-store\n"
    )

    bc_dir = os_ns / "noobaa.io" / "bucketclasses"
    bc_dir.mkdir(parents=True)
    (bc_dir / "noobaa-default-bucket-class.yaml").write_text(
        "apiVersion: noobaa.io/v1alpha1\nkind: BucketClass\nmetadata:\n  name: noobaa-default-bucket-class\n"
    )

    noobaa_cr_dir = os_ns / "noobaa.io" / "noobaas"
    noobaa_cr_dir.mkdir(parents=True)
    (noobaa_cr_dir / "noobaa.yaml").write_text(
        "apiVersion: noobaa.io/v1alpha1\nkind: NooBaa\nmetadata:\n  name: noobaa\n"
    )

    default_ns = root / "namespaces" / "default" / "core"
    default_ns.mkdir(parents=True)
    (default_ns / "events.yaml").write_text("apiVersion: v1\nkind: EventList\nitems: []\n")

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

    # NooBaa subtree (sibling of namespaces/, cluster-scoped-resources/)
    noobaa = root / "noobaa"

    noobaa_raw = noobaa / "raw_output"
    noobaa_raw.mkdir(parents=True)
    (noobaa_raw / "status").write_text(
        "system-address: https://10.0.0.1:443\nbacking-stores:\n  noobaa-default-backing-store: OPTIMAL\n"
    )
    (noobaa_raw / "db_list.txt").write_text(
        "       Name       | Size\n nbcore            | 48 MB\n buckets           | 16 MB\n"
    )

    # Create a small diagnostics tarball
    diag_content_dir = tmp_path / "_diag_content"
    diag_content_dir.mkdir()
    (diag_content_dir / "noobaa_core_describe.txt").write_text("pod describe output\n")
    (diag_content_dir / "noobaa_db_dump.json").write_text('{"buckets": []}\n')
    (diag_content_dir / "noobaa-core-0-core.log").write_text(
        "".join(f"2025-01-15T03:38:{i:02d}.000Z core log line {i}\n" for i in range(10))
    )
    diag_tarball = noobaa_raw / "noobaa_diagnostics_20250115.tar.gz"
    with tarfile.open(diag_tarball, "w:gz") as tar:
        tar.add(diag_content_dir / "noobaa_core_describe.txt", arcname="noobaa_core_describe.txt")
        tar.add(diag_content_dir / "noobaa_db_dump.json", arcname="noobaa_db_dump.json")
        tar.add(diag_content_dir / "noobaa-core-0-core.log", arcname="noobaa-core-0-core.log")

    noobaa_logs = noobaa / "logs" / "openshift-storage"
    noobaa_logs.mkdir(parents=True)
    (noobaa_logs / "noobaa_endpoint.log").write_text(
        "2025-01-15T03:38:00.000Z endpoint started\n"
        "2025-01-15T03:39:00.000Z request handled\n"
        "2025-01-15T03:40:00.000Z endpoint stopped\n"
    )
    (noobaa_logs / "noobaa_operator.log").write_text("operator log\n")

    cnpg_dir = noobaa / "cnpg_info"
    cnpg_dir.mkdir(parents=True)
    (cnpg_dir / "pg_stat_statements").write_text("query | calls | total_time\nSELECT 1 | 100 | 5.2\n")
    (cnpg_dir / "cnpg_cluster_status").write_text("cluster: noobaa-db\nstatus: healthy\n")

    # NooBaa CRD resources under noobaa subtree
    noobaa_ns = noobaa / "namespaces" / "openshift-storage"
    noobaa_obc_dir = noobaa_ns / "objectbucket.io" / "objectbucketclaims"
    noobaa_obc_dir.mkdir(parents=True)
    (noobaa_obc_dir / "my-obc.yaml").write_text(
        "apiVersion: objectbucket.io/v1alpha1\nkind: ObjectBucketClaim\nmetadata:\n  name: my-obc\n"
    )

    noobaa_bs_dir = noobaa_ns / "noobaa.io" / "backingstores"
    noobaa_bs_dir.mkdir(parents=True)
    (noobaa_bs_dir / "noobaa-default-backing-store.yaml").write_text(
        "apiVersion: noobaa.io/v1alpha1\nkind: BackingStore\nmetadata:\n  name: noobaa-default-backing-store\n"
    )

    noobaa_ob_dir = noobaa / "cluster-scoped-resources" / "objectbucket.io" / "objectbuckets"
    noobaa_ob_dir.mkdir(parents=True)
    (noobaa_ob_dir / "obc-ns-my-obc.yaml").write_text(
        "apiVersion: objectbucket.io/v1alpha1\nkind: ObjectBucket\nmetadata:\n  name: obc-ns-my-obc\n"
    )

    noobaa_nsstore_dir = noobaa_ns / "noobaa.io" / "namespacestores"
    noobaa_nsstore_dir.mkdir(parents=True)
    (noobaa_nsstore_dir / "my-ns-store.yaml").write_text(
        "apiVersion: noobaa.io/v1alpha1\nkind: NamespaceStore\nmetadata:\n  name: my-ns-store\n"
    )

    noobaa_bc_dir = noobaa_ns / "noobaa.io" / "bucketclasses"
    noobaa_bc_dir.mkdir(parents=True)
    (noobaa_bc_dir / "noobaa-default-bucket-class.yaml").write_text(
        "apiVersion: noobaa.io/v1alpha1\nkind: BucketClass\nmetadata:\n  name: noobaa-default-bucket-class\n"
    )

    noobaa_cr_dir = noobaa_ns / "noobaa.io" / "noobaas"
    noobaa_cr_dir.mkdir(parents=True)
    (noobaa_cr_dir / "noobaa.yaml").write_text(
        "apiVersion: noobaa.io/v1alpha1\nkind: NooBaa\nmetadata:\n  name: noobaa\n"
    )

    return {"extracted": tmp_path / "extracted", "root": root}


@pytest.fixture
def empty_must_gather(tmp_path):
    """Create an empty must-gather directory with no namespaces/ subdirectory."""
    extracted = tmp_path / "extracted"
    root = extracted / "must-gather-empty"
    root.mkdir(parents=True)
    return {"extracted": extracted, "root": root}


@pytest.fixture
def multi_root_must_gather(tmp_path):
    """Create a must-gather extraction with multiple subdirectories for root detection."""
    extracted = tmp_path / "extracted"
    (extracted / "other-dir").mkdir(parents=True)
    preferred = extracted / "must-gather-20250115"
    preferred.mkdir(parents=True)
    return {"extracted": extracted, "preferred": preferred}


@pytest.fixture
def make_mock_response():
    """Factory fixture returning a helper that builds mock requests.Response objects."""

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
