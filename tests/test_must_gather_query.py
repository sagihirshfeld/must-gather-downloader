import json

import pytest

from must_gather_downloader.server import (
    _find_must_gather_root,
    get_must_gather_resource,
    get_must_gather_pod_logs,
    list_must_gather_contents,
    search_must_gather,
)


class TestFindMustGatherRoot:
    def test_finds_dir_with_namespaces(self, tmp_path):
        root = tmp_path / "tarball" / "plugin-dir"
        (root / "namespaces" / "default").mkdir(parents=True)
        assert _find_must_gather_root(str(tmp_path)) == root

    def test_nested_plugin_directory(self, tmp_path):
        plugin = tmp_path / "ocs_must_gather" / "ocs-qe-proxy-sha256-abc"
        (plugin / "namespaces" / "openshift-storage").mkdir(parents=True)
        (plugin / "cluster-scoped-resources" / "core").mkdir(parents=True)
        assert _find_must_gather_root(str(tmp_path)) == plugin

    def test_prefers_shallowest_namespaces(self, tmp_path):
        shallow = tmp_path / "root"
        (shallow / "namespaces" / "ns1").mkdir(parents=True)
        (shallow / "ceph" / "namespaces" / "ns2").mkdir(parents=True)
        assert _find_must_gather_root(str(tmp_path)) == shallow

    def test_fallback_single_subdir(self, tmp_path):
        only_dir = tmp_path / "single-root"
        only_dir.mkdir()
        assert _find_must_gather_root(str(tmp_path)) == only_dir

    def test_fallback_prefers_must_gather_prefix(self, multi_root_must_gather):
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


class TestListMustGatherContents:
    def test_full_structure(self, must_gather_tree):
        result = json.loads(list_must_gather_contents(str(must_gather_tree["extracted"])))
        assert result["must_gather_root"] == str(must_gather_tree["root"])
        assert "openshift-storage" in result["namespaces"]
        assert "default" in result["namespaces"]
        assert result["has_ceph_data"] is True
        assert len(result["ceph_commands"]) > 0
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

    def test_ceph_commands_listed(self, must_gather_tree):
        result = json.loads(list_must_gather_contents(str(must_gather_tree["extracted"])))
        assert result["has_ceph_data"] is True
        assert "ceph_health_detail" in result["ceph_commands"]
        assert "ceph_status" in result["ceph_commands"]
        assert "ceph_osd_tree" in result["ceph_commands"]

    def test_ceph_log_nodes(self, must_gather_tree):
        result = json.loads(list_must_gather_contents(str(must_gather_tree["extracted"])))
        assert "ceph_daemon_log_master-0" in result["ceph_log_nodes"]
        assert "ceph_daemon_log_worker-0" in result["ceph_log_nodes"]

    def test_pod_counts(self, must_gather_tree):
        result = json.loads(list_must_gather_contents(str(must_gather_tree["extracted"])))
        assert result["pod_counts"]["openshift-storage"] == 3

    def test_no_ceph_data(self, tmp_path):
        root = tmp_path / "extracted" / "must-gather-noceph"
        (root / "namespaces" / "default").mkdir(parents=True)
        result = json.loads(list_must_gather_contents(str(tmp_path / "extracted")))
        assert result["has_ceph_data"] is False
        assert result["ceph_commands"] == []

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

    def test_ceph_status_not_fs_status(self, must_gather_tree):
        result = json.loads(
            get_must_gather_resource(str(must_gather_tree["extracted"]), "cephstatus")
        )
        assert result["resource_type"] == "cephstatus"
        assert "cluster status OK" in result["content"]
        assert "cephfs" not in result["content"].lower()

    def test_osd_tree(self, must_gather_tree):
        result = json.loads(
            get_must_gather_resource(str(must_gather_tree["extracted"]), "osdtree")
        )
        assert result["resource_type"] == "osdtree"
        assert "osd tree data" in result["content"]

    def test_osd_dump(self, must_gather_tree):
        result = json.loads(
            get_must_gather_resource(str(must_gather_tree["extracted"]), "osddump")
        )
        assert result["resource_type"] == "osddump"
        assert "osd dump data" in result["content"]

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


class TestSearchMustGather:
    def test_search_finds_matches(self, must_gather_tree):
        result = json.loads(search_must_gather(str(must_gather_tree["extracted"]), "CrashLoopBackOff"))
        assert result["total_matches"] >= 1
        assert any("CrashLoopBackOff" in m["line"] for m in result["matches"])

    def test_case_insensitive_default(self, must_gather_tree):
        result = json.loads(search_must_gather(str(must_gather_tree["extracted"]), "crashloopbackoff"))
        assert result["total_matches"] >= 1

    def test_case_sensitive(self, must_gather_tree):
        result = json.loads(search_must_gather(
            str(must_gather_tree["extracted"]), "crashloopbackoff", case_sensitive=True
        ))
        assert result["total_matches"] == 0

    def test_file_pattern_filter(self, must_gather_tree):
        result = json.loads(search_must_gather(
            str(must_gather_tree["extracted"]), "log", file_pattern="*.log"
        ))
        assert result["total_matches"] >= 1
        for m in result["matches"]:
            assert m["file"].endswith(".log")

    def test_max_results_truncation(self, must_gather_tree):
        result = json.loads(search_must_gather(
            str(must_gather_tree["extracted"]), "name", max_results=2
        ))
        assert result["truncated"] is True
        assert len(result["matches"]) == 2

    def test_no_matches(self, must_gather_tree):
        result = json.loads(search_must_gather(
            str(must_gather_tree["extracted"]), "zzz_nonexistent_string_zzz"
        ))
        assert result["total_matches"] == 0
        assert result["matches"] == []
        assert result["truncated"] is False

    def test_regex_pattern(self, must_gather_tree):
        result = json.loads(search_must_gather(str(must_gather_tree["extracted"]), r"kind: \w+"))
        assert result["total_matches"] >= 2

    def test_invalid_regex_fallback(self, must_gather_tree):
        result = json.loads(search_must_gather(str(must_gather_tree["extracted"]), "[invalid"))
        assert "error" not in result
        assert isinstance(result["matches"], list)

    def test_empty_pattern_error(self, must_gather_tree):
        result = json.loads(search_must_gather(str(must_gather_tree["extracted"]), ""))
        assert "error" in result

    def test_binary_file_skipped(self, must_gather_tree):
        binary_file = must_gather_tree["root"] / "namespaces" / "openshift-storage" / "binary.dat"
        binary_file.write_bytes(b"\x00\x01\x02FINDME\x03\x04")
        result = json.loads(search_must_gather(str(must_gather_tree["extracted"]), "FINDME"))
        assert result["total_matches"] == 0

    def test_files_searched_count(self, must_gather_tree):
        result = json.loads(search_must_gather(str(must_gather_tree["extracted"]), "anything"))
        assert result["files_searched"] > 0

    def test_match_structure(self, must_gather_tree):
        result = json.loads(search_must_gather(str(must_gather_tree["extracted"]), "CrashLoopBackOff"))
        assert result["total_matches"] >= 1
        match = result["matches"][0]
        assert "file" in match
        assert "line_number" in match
        assert "line" in match

    def test_relative_paths(self, must_gather_tree):
        result = json.loads(search_must_gather(str(must_gather_tree["extracted"]), "CrashLoopBackOff"))
        for m in result["matches"]:
            assert not m["file"].startswith("/")


class TestGetMustGatherPodLogs:
    def test_list_pods(self, must_gather_tree):
        result = json.loads(
            get_must_gather_pod_logs(str(must_gather_tree["extracted"]), "openshift-storage")
        )
        assert result["namespace"] == "openshift-storage"
        assert result["available_pods"] == [
            "noobaa-core-0",
            "rook-ceph-mon-a-abc123",
            "rook-ceph-osd-0-def456",
        ]
        assert result["hint"] == "Specify pod_name to retrieve logs"

    def test_get_specific_pod_logs(self, must_gather_tree):
        result = json.loads(
            get_must_gather_pod_logs(
                str(must_gather_tree["extracted"]),
                "openshift-storage",
                pod_name="rook-ceph-mon-a-abc123",
            )
        )
        assert result["total_logs_found"] == 1
        log = result["logs"][0]
        assert log["pod"] == "rook-ceph-mon-a-abc123"
        assert log["container"] == "mon"
        assert log["log_file"] == "current.log"
        assert "mon current log" in log["content"]

    def test_pod_name_substring_match(self, must_gather_tree):
        result = json.loads(
            get_must_gather_pod_logs(
                str(must_gather_tree["extracted"]),
                "openshift-storage",
                pod_name="rook-ceph-mon",
            )
        )
        assert result["total_logs_found"] == 1
        assert result["logs"][0]["pod"] == "rook-ceph-mon-a-abc123"

    def test_previous_logs(self, must_gather_tree):
        result = json.loads(
            get_must_gather_pod_logs(
                str(must_gather_tree["extracted"]),
                "openshift-storage",
                pod_name="rook-ceph-mon-a-abc123",
                previous=True,
            )
        )
        assert result["total_logs_found"] == 1
        log = result["logs"][0]
        assert log["log_file"] == "previous.log"
        assert "mon previous log" in log["content"]

    def test_previous_log_not_found(self, must_gather_tree):
        result = json.loads(
            get_must_gather_pod_logs(
                str(must_gather_tree["extracted"]),
                "openshift-storage",
                pod_name="rook-ceph-osd-0-def456",
                previous=True,
            )
        )
        assert result["total_logs_found"] == 0
        assert result["logs"] == []

    def test_specific_container(self, must_gather_tree):
        result = json.loads(
            get_must_gather_pod_logs(
                str(must_gather_tree["extracted"]),
                "openshift-storage",
                pod_name="rook-ceph-mon-a-abc123",
                container="mon",
            )
        )
        assert result["total_logs_found"] == 1
        assert result["logs"][0]["container"] == "mon"

    def test_container_not_found(self, must_gather_tree):
        result = json.loads(
            get_must_gather_pod_logs(
                str(must_gather_tree["extracted"]),
                "openshift-storage",
                pod_name="rook-ceph-mon-a-abc123",
                container="nonexistent",
            )
        )
        assert result["total_logs_found"] == 0
        assert result["logs"] == []

    def test_multi_container_pod(self, must_gather_tree):
        result = json.loads(
            get_must_gather_pod_logs(
                str(must_gather_tree["extracted"]),
                "openshift-storage",
                pod_name="noobaa-core-0",
            )
        )
        assert result["total_logs_found"] == 2
        containers = sorted(log["container"] for log in result["logs"])
        assert containers == ["init-container", "noobaa-core"]

    def test_tail_lines(self, must_gather_tree):
        log_path = (
            must_gather_tree["root"] / "namespaces" / "openshift-storage" / "pods"
            / "rook-ceph-mon-a-abc123" / "mon" / "mon" / "logs" / "current.log"
        )
        log_path.write_text("\n".join(f"mon log line {i}" for i in range(50)) + "\n")
        result = json.loads(
            get_must_gather_pod_logs(
                str(must_gather_tree["extracted"]),
                "openshift-storage",
                pod_name="rook-ceph-mon-a-abc123",
                tail=10,
            )
        )
        log = result["logs"][0]
        assert log["lines"] == 10
        assert "mon log line 49" in log["content"]
        assert "mon log line 39" not in log["content"]

    def test_namespace_not_found(self, must_gather_tree):
        result = json.loads(
            get_must_gather_pod_logs(
                str(must_gather_tree["extracted"]), "nonexistent"
            )
        )
        assert "error" in result
        assert "available_namespaces" in result
        assert "openshift-storage" in result["available_namespaces"]

    def test_pod_not_found(self, must_gather_tree):
        result = json.loads(
            get_must_gather_pod_logs(
                str(must_gather_tree["extracted"]),
                "openshift-storage",
                pod_name="nonexistent",
            )
        )
        assert "error" in result
        assert "available_pods" in result
        assert "rook-ceph-mon-a-abc123" in result["available_pods"]

    def test_large_log_truncation(self, must_gather_tree):
        log_path = (
            must_gather_tree["root"] / "namespaces" / "openshift-storage" / "pods"
            / "rook-ceph-mon-a-abc123" / "mon" / "mon" / "logs" / "current.log"
        )
        large_content = "\n".join(f"line {i} " + "x" * 200 for i in range(2000)) + "\n"
        log_path.write_text(large_content)
        result = json.loads(
            get_must_gather_pod_logs(
                str(must_gather_tree["extracted"]),
                "openshift-storage",
                pod_name="rook-ceph-mon-a-abc123",
            )
        )
        log = result["logs"][0]
        assert log["truncated"] is True
        assert len(log["content"].encode("utf-8")) <= 200 * 1024 + 1024

    def test_log_structure(self, must_gather_tree):
        result = json.loads(
            get_must_gather_pod_logs(
                str(must_gather_tree["extracted"]),
                "openshift-storage",
                pod_name="rook-ceph-osd-0-def456",
            )
        )
        log = result["logs"][0]
        assert set(log.keys()) == {"pod", "container", "log_file", "lines", "content", "truncated"}

    def test_multiple_pods_matching(self, must_gather_tree):
        result = json.loads(
            get_must_gather_pod_logs(
                str(must_gather_tree["extracted"]),
                "openshift-storage",
                pod_name="rook-ceph",
            )
        )
        assert result["total_logs_found"] == 2
        pods = sorted(log["pod"] for log in result["logs"])
        assert pods == ["rook-ceph-mon-a-abc123", "rook-ceph-osd-0-def456"]
