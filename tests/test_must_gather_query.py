import json

import pytest

from must_gather_downloader.server import (
    _find_must_gather_root,
    get_must_gather_resource,
    list_must_gather_contents,
)


class TestFindMustGatherRoot:
    def test_single_root_dir(self, tmp_path):
        only_dir = tmp_path / "single-root"
        only_dir.mkdir()
        assert _find_must_gather_root(str(tmp_path)) == only_dir

    def test_prefers_must_gather_prefix(self, multi_root_must_gather):
        result = _find_must_gather_root(str(multi_root_must_gather["extracted"]))
        assert result == multi_root_must_gather["preferred"]

    def test_fallback_to_first_sorted(self, tmp_path):
        (tmp_path / "bravo").mkdir()
        (tmp_path / "alpha").mkdir()
        assert _find_must_gather_root(str(tmp_path)).name == "alpha"

    def test_nonexistent_path(self):
        with pytest.raises(ValueError, match="does not exist"):
            _find_must_gather_root("/nonexistent/path/xyz")

    def test_not_a_directory(self, tmp_path):
        file_path = tmp_path / "afile.txt"
        file_path.write_text("hi")
        with pytest.raises(ValueError, match="not a directory"):
            _find_must_gather_root(str(file_path))

    def test_empty_extracted(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        with pytest.raises(ValueError, match="No subdirectories"):
            _find_must_gather_root(str(empty))

    def test_ignores_files_in_root(self, tmp_path):
        (tmp_path / "readme.txt").write_text("ignore me")
        only_dir = tmp_path / "the-dir"
        only_dir.mkdir()
        assert _find_must_gather_root(str(tmp_path)) == only_dir


class TestListMustGatherContents:
    def test_full_structure(self, must_gather_tree):
        result = json.loads(list_must_gather_contents(str(must_gather_tree["extracted"])))
        assert result["must_gather_root"] == str(must_gather_tree["root"])
        assert "openshift-storage" in result["namespaces"]
        assert "default" in result["namespaces"]
        assert result["has_ceph_data"] is True
        assert len(result["ceph_data_paths"]) > 0
        assert "ceph" in result["top_level_dirs"]
        assert "namespaces" in result["top_level_dirs"]
        assert result["host_service_logs"] is True
        assert result["total_files"] > 0

    def test_namespaces_listed(self, must_gather_tree):
        result = json.loads(list_must_gather_contents(str(must_gather_tree["extracted"])))
        assert sorted(result["namespaces"]) == ["default", "openshift-storage"]

    def test_cluster_scoped_resources_structure(self, must_gather_tree):
        result = json.loads(list_must_gather_contents(str(must_gather_tree["extracted"])))
        csr = result["cluster_scoped_resources"]
        assert "core" in csr
        assert "nodes" in csr["core"]
        assert "persistentvolumes" in csr["core"]
        assert "storage.k8s.io" in csr
        assert "storageclasses" in csr["storage.k8s.io"]

    def test_ceph_data_detected(self, must_gather_tree):
        result = json.loads(list_must_gather_contents(str(must_gather_tree["extracted"])))
        assert result["has_ceph_data"] is True
        assert any("ceph_health_detail" in p for p in result["ceph_data_paths"])
        assert any("ceph_status" in p for p in result["ceph_data_paths"])

    def test_no_ceph_data(self, tmp_path):
        root = tmp_path / "extracted" / "must-gather-noceph"
        (root / "namespaces" / "default").mkdir(parents=True)
        result = json.loads(list_must_gather_contents(str(tmp_path / "extracted")))
        assert result["has_ceph_data"] is False
        assert result["ceph_data_paths"] == []

    def test_empty_must_gather(self, empty_must_gather):
        result = json.loads(list_must_gather_contents(str(empty_must_gather["extracted"])))
        assert result["namespaces"] == []
        assert result["cluster_scoped_resources"] == {}
        assert result["has_ceph_data"] is False
        assert result["host_service_logs"] is False
        assert result["total_files"] == 0

    def test_invalid_path(self):
        with pytest.raises(ValueError):
            list_must_gather_contents("/nonexistent/path/xyz")


class TestGetMustGatherResource:
    def test_get_specific_node(self, must_gather_tree):
        result = json.loads(
            get_must_gather_resource(
                str(must_gather_tree["extracted"]), "node", name="master-0"
            )
        )
        assert result["resource_type"] == "node"
        assert result["name"] == "master-0"
        assert "kind: Node" in result["content"]
        assert "path" in result

    def test_list_nodes(self, must_gather_tree):
        result = json.loads(
            get_must_gather_resource(str(must_gather_tree["extracted"]), "node")
        )
        assert result["resource_type"] == "node"
        assert sorted(result["available_names"]) == ["master-0", "worker-0"]
        assert "hint" in result

    def test_get_pv(self, must_gather_tree):
        result = json.loads(
            get_must_gather_resource(
                str(must_gather_tree["extracted"]), "pv", name="pv-001"
            )
        )
        assert result["resource_type"] == "persistentvolume"
        assert result["name"] == "pv-001"
        assert "PersistentVolume" in result["content"]

    def test_get_storageclass(self, must_gather_tree):
        result = json.loads(
            get_must_gather_resource(
                str(must_gather_tree["extracted"]),
                "sc",
                name="ocs-storagecluster-ceph-rbd",
            )
        )
        assert result["resource_type"] == "storageclass"
        assert "StorageClass" in result["content"]

    def test_get_events(self, must_gather_tree):
        result = json.loads(
            get_must_gather_resource(
                str(must_gather_tree["extracted"]),
                "events",
                namespace="openshift-storage",
            )
        )
        assert result["resource_type"] == "events"
        assert "CrashLoopBackOff" in result["content"]

    def test_namespaced_resource_no_namespace(self, must_gather_tree):
        result = json.loads(
            get_must_gather_resource(str(must_gather_tree["extracted"]), "events")
        )
        assert "error" in result
        assert "namespace is required" in result["error"]
        assert "openshift-storage" in result["available_namespaces"]
        assert "default" in result["available_namespaces"]

    def test_resource_not_found(self, must_gather_tree):
        result = json.loads(
            get_must_gather_resource(
                str(must_gather_tree["extracted"]), "node", name="nonexistent"
            )
        )
        assert "error" in result
        assert "nonexistent" in result["error"]

    def test_unknown_resource_type(self, must_gather_tree):
        result = json.loads(
            get_must_gather_resource(str(must_gather_tree["extracted"]), "foobar")
        )
        assert "error" in result
        assert "Unknown resource_type" in result["error"]
        assert "supported_types" in result
        assert "node" in result["supported_types"]

    def test_ceph_health(self, must_gather_tree):
        result = json.loads(
            get_must_gather_resource(str(must_gather_tree["extracted"]), "cephhealth")
        )
        assert result["resource_type"] == "cephhealth"
        assert "HEALTH_WARN" in result["content"]

    def test_large_file_truncation(self, must_gather_tree):
        large_node = (
            must_gather_tree["root"]
            / "cluster-scoped-resources"
            / "core"
            / "nodes"
            / "large-node.yaml"
        )
        large_node.write_text("x" * 200_000)

        result = json.loads(
            get_must_gather_resource(
                str(must_gather_tree["extracted"]), "node", name="large-node"
            )
        )
        assert result["truncated"] is True
        assert result["total_size_bytes"] == 200_000
        assert len(result["content"]) <= 100 * 1024

    def test_deployment_resource(self, must_gather_tree):
        result = json.loads(
            get_must_gather_resource(
                str(must_gather_tree["extracted"]),
                "deployment",
                name="noobaa-operator",
                namespace="openshift-storage",
            )
        )
        assert result["resource_type"] == "deployment"
        assert result["name"] == "noobaa-operator"
        assert "Deployment" in result["content"]

    def test_case_insensitive_resource_type(self, must_gather_tree):
        result = json.loads(
            get_must_gather_resource(
                str(must_gather_tree["extracted"]), "Node", name="master-0"
            )
        )
        assert result["resource_type"] == "node"
        assert "kind: Node" in result["content"]

    def test_invalid_path(self):
        with pytest.raises(ValueError, match="does not exist"):
            get_must_gather_resource("/nonexistent/path", "node")
