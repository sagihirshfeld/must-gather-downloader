import json

import pytest
from must_gather_downloader.navigate import _count_files_and_size, _find_must_gather_root
from must_gather_downloader.noobaa import get_noobaa_resource
from must_gather_downloader.pod_logs import get_must_gather_pod_logs
from must_gather_downloader.resources import get_must_gather_resource, list_must_gather_contents
from must_gather_downloader.search import search_must_gather
from must_gather_downloader.text import (
    _filter_log_by_time,
    _strip_managed_fields,
    _strip_yaml_keys,
    _tail_yaml_list,
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


class TestStripManagedFields:
    def test_strips_managed_fields_block(self):
        content = (
            "apiVersion: v1\n"
            "metadata:\n"
            "  name: test\n"
            "  managedFields:\n"
            "  - apiVersion: v1\n"
            "    fieldsType: FieldsV1\n"
            "    fieldsV1:\n"
            "      f:data: {}\n"
            "    manager: kubectl\n"
            "  namespace: default\n"
            "spec:\n"
            "  key: value\n"
        )
        result = _strip_managed_fields(content)
        assert "managedFields" not in result
        assert "fieldsV1" not in result
        assert "manager: kubectl" not in result
        assert "namespace: default" in result
        assert "spec:" in result

    def test_preserves_content_without_managed_fields(self):
        content = "apiVersion: v1\nkind: Pod\nmetadata:\n  name: test\n"
        assert _strip_managed_fields(content) == content

    def test_handles_multiple_managed_fields(self):
        content = (
            "items:\n"
            "- metadata:\n"
            "    managedFields:\n"
            "    - manager: a\n"
            "    name: first\n"
            "- metadata:\n"
            "    managedFields:\n"
            "    - manager: b\n"
            "    name: second\n"
        )
        result = _strip_managed_fields(content)
        assert "managedFields" not in result
        assert "name: first" in result
        assert "name: second" in result


class TestStripYamlKeys:
    def test_strips_multiple_keys(self):
        content = (
            "metadata:\n"
            "  name: node-1\n"
            "  managedFields:\n"
            "  - manager: kubelet\n"
            "status:\n"
            "  conditions:\n"
            "  - type: Ready\n"
            "  images:\n"
            "  - names:\n"
            "    - quay.io/image@sha256:abc\n"
            "    sizeBytes: 123456\n"
            "  - names:\n"
            "    - quay.io/image@sha256:def\n"
            "    sizeBytes: 789012\n"
            "  nodeInfo:\n"
            "    kubeletVersion: v1.28.0\n"
        )
        result = _strip_yaml_keys(content, ["managedFields", "images"])
        assert "managedFields" not in result
        assert "images" not in result
        assert "sha256" not in result
        assert "sizeBytes" not in result
        assert "name: node-1" in result
        assert "type: Ready" in result
        assert "kubeletVersion" in result


class TestTailYamlList:
    def test_tails_items(self):
        content = (
            "apiVersion: v1\nitems:\n- name: event1\n  data: a\n- name: event2\n  data: b\n- name: event3\n  data: c\n"
        )
        result, total = _tail_yaml_list(content, 2)
        assert total == 3
        assert "event1" not in result
        assert "event2" in result
        assert "event3" in result
        assert "apiVersion: v1" in result

    def test_count_zero_returns_all(self):
        content = "header:\n- item1\n- item2\n"
        result, total = _tail_yaml_list(content, 0)
        assert total == 2
        assert "item1" in result
        assert "item2" in result

    def test_count_exceeds_items(self):
        content = "header:\n- item1\n- item2\n"
        result, total = _tail_yaml_list(content, 100)
        assert total == 2
        assert "item1" in result
        assert "item2" in result


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

    def test_noobaa_inventory(self, must_gather_tree):
        result = json.loads(list_must_gather_contents(str(must_gather_tree["extracted"])))
        assert result["has_noobaa"] is True
        noobaa = result["noobaa"]
        assert noobaa["has_status"] is True
        assert noobaa["has_db_list"] is True
        assert noobaa["has_diagnostics"] is True
        assert "noobaa_endpoint.log" in noobaa["log_files"]
        assert "pg_stat_statements" in noobaa["cnpg_files"]

    def test_no_noobaa_inventory(self, empty_must_gather):
        result = json.loads(list_must_gather_contents(str(empty_must_gather["extracted"])))
        assert result["has_noobaa"] is False
        assert result["noobaa"] == {}

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
        result = json.loads(get_must_gather_resource(str(must_gather_tree["extracted"]), "node", name="master-0"))
        assert result["resource_type"] == "node"
        assert result["name"] == "master-0"
        assert "kind: Node" in result["content"]
        assert "path" in result

    def test_list_nodes(self, must_gather_tree):
        result = json.loads(get_must_gather_resource(str(must_gather_tree["extracted"]), "node"))
        assert result["resource_type"] == "node"
        assert sorted(result["available_names"]) == ["master-0", "worker-0"]
        assert "hint" in result

    def test_get_pv(self, must_gather_tree):
        result = json.loads(get_must_gather_resource(str(must_gather_tree["extracted"]), "pv", name="pv-001"))
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

    def test_events_managed_fields_stripped(self, must_gather_tree):
        result = json.loads(
            get_must_gather_resource(
                str(must_gather_tree["extracted"]),
                "events",
                namespace="openshift-storage",
            )
        )
        assert "managedFields" not in result["content"]
        assert "manager: kubelet" not in result["content"]
        assert "CrashLoopBackOff" in result["content"]

    def test_events_tail(self, must_gather_tree):
        result = json.loads(
            get_must_gather_resource(
                str(must_gather_tree["extracted"]),
                "events",
                namespace="openshift-storage",
                tail=2,
            )
        )
        assert result["total_events"] == 3
        assert result["showing_last"] == 2
        assert "Created" not in result["content"]
        assert "CrashLoopBackOff" in result["content"]
        assert "Scheduled" in result["content"]

    def test_node_managed_fields_and_images_stripped(self, must_gather_tree):
        node_file = must_gather_tree["root"] / "cluster-scoped-resources" / "core" / "nodes" / "master-0.yaml"
        content = node_file.read_text()
        content += (
            "  managedFields:\n  - manager: test\n    apiVersion: v1\n"
            "  images:\n  - names:\n    - quay.io/img@sha256:abc\n    sizeBytes: 999\n"
        )
        node_file.write_text(content)
        result = json.loads(get_must_gather_resource(str(must_gather_tree["extracted"]), "node", name="master-0"))
        assert "managedFields" not in result["content"]
        assert "images" not in result["content"]
        assert "sha256" not in result["content"]
        assert "kind: Node" in result["content"]

    def test_namespaced_resource_no_namespace(self, must_gather_tree):
        result = json.loads(get_must_gather_resource(str(must_gather_tree["extracted"]), "events"))
        assert "error" in result
        assert "namespace is required" in result["error"]
        assert "openshift-storage" in result["available_namespaces"]
        assert "default" in result["available_namespaces"]

    def test_resource_not_found(self, must_gather_tree):
        result = json.loads(get_must_gather_resource(str(must_gather_tree["extracted"]), "node", name="nonexistent"))
        assert "error" in result
        assert "nonexistent" in result["error"]

    def test_unknown_resource_type(self, must_gather_tree):
        result = json.loads(get_must_gather_resource(str(must_gather_tree["extracted"]), "foobar"))
        assert "error" in result
        assert "Unknown resource_type" in result["error"]
        assert "supported_types" in result
        assert "node" in result["supported_types"]

    def test_ceph_health(self, must_gather_tree):
        result = json.loads(get_must_gather_resource(str(must_gather_tree["extracted"]), "cephhealth"))
        assert result["resource_type"] == "cephhealth"
        assert "HEALTH_WARN" in result["content"]

    def test_ceph_status_not_fs_status(self, must_gather_tree):
        result = json.loads(get_must_gather_resource(str(must_gather_tree["extracted"]), "cephstatus"))
        assert result["resource_type"] == "cephstatus"
        assert "cluster status OK" in result["content"]
        assert "cephfs" not in result["content"].lower()

    def test_osd_tree(self, must_gather_tree):
        result = json.loads(get_must_gather_resource(str(must_gather_tree["extracted"]), "osdtree"))
        assert result["resource_type"] == "osdtree"
        assert "osd tree data" in result["content"]

    def test_osd_dump(self, must_gather_tree):
        result = json.loads(get_must_gather_resource(str(must_gather_tree["extracted"]), "osddump"))
        assert result["resource_type"] == "osddump"
        assert "osd dump data" in result["content"]

    def test_generic_ceph_list_commands(self, must_gather_tree):
        result = json.loads(get_must_gather_resource(str(must_gather_tree["extracted"]), "ceph"))
        assert result["resource_type"] == "ceph"
        assert "ceph_health_detail" in result["available_commands"]
        assert "ceph_status" in result["available_commands"]
        assert "ceph_fs_status" in result["available_commands"]
        assert "ceph_osd_dump" in result["available_commands"]

    def test_generic_ceph_read_by_name(self, must_gather_tree):
        result = json.loads(get_must_gather_resource(str(must_gather_tree["extracted"]), "ceph", name="ceph_fs_status"))
        assert result["resource_type"] == "ceph"
        assert result["name"] == "ceph_fs_status"
        assert "cephfs status data" in result["content"]

    def test_generic_ceph_not_found_with_suggestions(self, must_gather_tree):
        result = json.loads(get_must_gather_resource(str(must_gather_tree["extracted"]), "ceph", name="osd"))
        assert "error" in result
        assert "ceph_osd_dump" in result["similar"]
        assert "ceph_osd_tree" in result["similar"]
        assert "available_commands" in result

    def test_generic_ceph_exact_not_found_no_similar(self, must_gather_tree):
        result = json.loads(
            get_must_gather_resource(str(must_gather_tree["extracted"]), "ceph", name="nonexistent_xyz")
        )
        assert "error" in result
        assert result["similar"] == []

    def test_existing_ceph_aliases_still_work(self, must_gather_tree):
        for alias, expected in [
            ("cephhealth", "HEALTH_WARN"),
            ("cephstatus", "cluster status OK"),
            ("osdtree", "osd tree data"),
            ("osddump", "osd dump data"),
        ]:
            result = json.loads(get_must_gather_resource(str(must_gather_tree["extracted"]), alias))
            assert expected in result["content"]

    def test_get_objectbucketclaim(self, must_gather_tree):
        result = json.loads(
            get_must_gather_resource(
                str(must_gather_tree["extracted"]),
                "objectbucketclaim",
                name="my-obc",
                namespace="openshift-storage",
            )
        )
        assert result["resource_type"] == "objectbucketclaim"
        assert "ObjectBucketClaim" in result["content"]

    def test_obc_alias(self, must_gather_tree):
        result = json.loads(
            get_must_gather_resource(
                str(must_gather_tree["extracted"]),
                "obc",
                name="my-obc",
                namespace="openshift-storage",
            )
        )
        assert result["resource_type"] == "objectbucketclaim"

    def test_list_objectbucketclaims(self, must_gather_tree):
        result = json.loads(
            get_must_gather_resource(
                str(must_gather_tree["extracted"]),
                "obc",
                namespace="openshift-storage",
            )
        )
        assert "my-obc" in result["available_names"]

    def test_get_objectbucket_cluster_scoped(self, must_gather_tree):
        result = json.loads(
            get_must_gather_resource(
                str(must_gather_tree["extracted"]),
                "ob",
                name="obc-ns-my-obc",
            )
        )
        assert result["resource_type"] == "objectbucket"
        assert "ObjectBucket" in result["content"]

    def test_get_backingstore(self, must_gather_tree):
        result = json.loads(
            get_must_gather_resource(
                str(must_gather_tree["extracted"]),
                "bs",
                name="noobaa-default-backing-store",
                namespace="openshift-storage",
            )
        )
        assert result["resource_type"] == "backingstore"
        assert "BackingStore" in result["content"]

    def test_get_namespacestore(self, must_gather_tree):
        result = json.loads(
            get_must_gather_resource(
                str(must_gather_tree["extracted"]),
                "ns_store",
                name="my-ns-store",
                namespace="openshift-storage",
            )
        )
        assert result["resource_type"] == "namespacestore"
        assert "NamespaceStore" in result["content"]

    def test_get_bucketclass(self, must_gather_tree):
        result = json.loads(
            get_must_gather_resource(
                str(must_gather_tree["extracted"]),
                "bc",
                name="noobaa-default-bucket-class",
                namespace="openshift-storage",
            )
        )
        assert result["resource_type"] == "bucketclass"
        assert "BucketClass" in result["content"]

    def test_get_noobaa_cr(self, must_gather_tree):
        result = json.loads(
            get_must_gather_resource(
                str(must_gather_tree["extracted"]),
                "noobaa",
                name="noobaa",
                namespace="openshift-storage",
            )
        )
        assert result["resource_type"] == "noobaa"
        assert "NooBaa" in result["content"]

    def test_large_file_truncation(self, must_gather_tree):
        large_node = must_gather_tree["root"] / "cluster-scoped-resources" / "core" / "nodes" / "large-node.yaml"
        large_node.write_text("x" * 200_000)

        result = json.loads(get_must_gather_resource(str(must_gather_tree["extracted"]), "node", name="large-node"))
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
        result = json.loads(get_must_gather_resource(str(must_gather_tree["extracted"]), "Node", name="master-0"))
        assert result["resource_type"] == "node"
        assert "kind: Node" in result["content"]

    def test_invalid_path(self):
        with pytest.raises(ValueError, match="does not exist"):
            get_must_gather_resource("/nonexistent/path", "node")


class TestGetNoobaaResource:
    def test_noobaa_status(self, must_gather_tree):
        result = json.loads(get_noobaa_resource(str(must_gather_tree["extracted"]), "status"))
        assert result["resource_type"] == "status"
        assert "system-address" in result["content"]
        assert "backing-stores" in result["content"]

    def test_noobaa_db_list(self, must_gather_tree):
        result = json.loads(get_noobaa_resource(str(must_gather_tree["extracted"]), "db_list"))
        assert result["resource_type"] == "db_list"
        assert "nbcore" in result["content"]

    def test_noobaa_logs_list(self, must_gather_tree):
        result = json.loads(get_noobaa_resource(str(must_gather_tree["extracted"]), "logs"))
        assert result["resource_type"] == "logs"
        assert "noobaa_endpoint.log" in result["available_logs"]
        assert "noobaa_operator.log" in result["available_logs"]

    def test_noobaa_logs_read(self, must_gather_tree):
        result = json.loads(get_noobaa_resource(str(must_gather_tree["extracted"]), "logs", name="noobaa_endpoint.log"))
        assert result["resource_type"] == "logs"
        assert "endpoint started" in result["content"]
        assert result["lines"] == 3

    def test_noobaa_logs_tail(self, must_gather_tree):
        result = json.loads(
            get_noobaa_resource(
                str(must_gather_tree["extracted"]),
                "logs",
                name="noobaa_endpoint.log",
                tail=1,
            )
        )
        assert result["lines"] == 1
        assert "endpoint stopped" in result["content"]

    def test_noobaa_logs_not_found(self, must_gather_tree):
        result = json.loads(get_noobaa_resource(str(must_gather_tree["extracted"]), "logs", name="nonexistent.log"))
        assert "error" in result
        assert "available_logs" in result

    def test_noobaa_cnpg_list(self, must_gather_tree):
        result = json.loads(get_noobaa_resource(str(must_gather_tree["extracted"]), "cnpg"))
        assert result["resource_type"] == "cnpg"
        assert "pg_stat_statements" in result["available_files"]
        assert "cnpg_cluster_status" in result["available_files"]

    def test_noobaa_cnpg_read(self, must_gather_tree):
        result = json.loads(get_noobaa_resource(str(must_gather_tree["extracted"]), "cnpg", name="pg_stat_statements"))
        assert result["resource_type"] == "cnpg"
        assert "SELECT 1" in result["content"]

    def test_noobaa_diagnostics_list(self, must_gather_tree):
        result = json.loads(get_noobaa_resource(str(must_gather_tree["extracted"]), "diagnostics"))
        assert result["resource_type"] == "diagnostics"
        assert "noobaa_core_describe.txt" in result["available_files"]
        assert "noobaa_db_dump.json" in result["available_files"]

    def test_noobaa_diagnostics_read(self, must_gather_tree):
        result = json.loads(
            get_noobaa_resource(
                str(must_gather_tree["extracted"]),
                "diagnostics",
                name="noobaa_core_describe.txt",
            )
        )
        assert result["resource_type"] == "diagnostics"
        assert "pod describe output" in result["content"]

    def test_noobaa_diagnostics_cached(self, must_gather_tree):
        get_noobaa_resource(str(must_gather_tree["extracted"]), "diagnostics")
        extract_dir = must_gather_tree["root"] / "noobaa" / "raw_output" / ".diagnostics_extracted"
        assert extract_dir.is_dir()
        mtime_before = extract_dir.stat().st_mtime
        get_noobaa_resource(str(must_gather_tree["extracted"]), "diagnostics")
        assert extract_dir.stat().st_mtime == mtime_before

    def test_noobaa_diagnostics_file_not_found(self, must_gather_tree):
        result = json.loads(get_noobaa_resource(str(must_gather_tree["extracted"]), "diagnostics", name="nonexistent"))
        assert "error" in result
        assert "available_files" in result

    def test_noobaa_backingstore(self, must_gather_tree):
        result = json.loads(
            get_noobaa_resource(
                str(must_gather_tree["extracted"]),
                "bs",
                name="noobaa-default-backing-store",
                namespace="openshift-storage",
            )
        )
        assert result["resource_type"] == "backingstore"
        assert "BackingStore" in result["content"]

    def test_noobaa_objectbucketclaim(self, must_gather_tree):
        result = json.loads(
            get_noobaa_resource(
                str(must_gather_tree["extracted"]),
                "obc",
                name="my-obc",
                namespace="openshift-storage",
            )
        )
        assert result["resource_type"] == "objectbucketclaim"
        assert "ObjectBucketClaim" in result["content"]

    def test_noobaa_objectbucket_cluster_scoped(self, must_gather_tree):
        result = json.loads(
            get_noobaa_resource(
                str(must_gather_tree["extracted"]),
                "ob",
                name="obc-ns-my-obc",
            )
        )
        assert result["resource_type"] == "objectbucket"
        assert "ObjectBucket" in result["content"]

    def test_noobaa_namespaced_requires_namespace(self, must_gather_tree):
        result = json.loads(
            get_noobaa_resource(
                str(must_gather_tree["extracted"]),
                "backingstore",
            )
        )
        assert "error" in result
        assert "namespace is required" in result["error"]

    def test_noobaa_dir_missing(self, tmp_path):
        root = tmp_path / "extracted" / "must-gather"
        ns = root / "namespaces" / "default"
        ns.mkdir(parents=True)
        result = json.loads(get_noobaa_resource(str(tmp_path / "extracted"), "status"))
        assert "error" in result
        assert "noobaa" in result["error"].lower()

    def test_noobaa_namespacestore(self, must_gather_tree):
        result = json.loads(
            get_noobaa_resource(
                str(must_gather_tree["extracted"]),
                "ns_store",
                name="my-ns-store",
                namespace="openshift-storage",
            )
        )
        assert result["resource_type"] == "namespacestore"
        assert "NamespaceStore" in result["content"]

    def test_noobaa_bucketclass(self, must_gather_tree):
        result = json.loads(
            get_noobaa_resource(
                str(must_gather_tree["extracted"]),
                "bc",
                name="noobaa-default-bucket-class",
                namespace="openshift-storage",
            )
        )
        assert result["resource_type"] == "bucketclass"
        assert "BucketClass" in result["content"]

    def test_noobaa_cr(self, must_gather_tree):
        result = json.loads(
            get_noobaa_resource(
                str(must_gather_tree["extracted"]),
                "noobaa",
                name="noobaa",
                namespace="openshift-storage",
            )
        )
        assert result["resource_type"] == "noobaa"
        assert "NooBaa" in result["content"]

    def test_unknown_noobaa_resource_type(self, must_gather_tree):
        result = json.loads(get_noobaa_resource(str(must_gather_tree["extracted"]), "nonexistent"))
        assert "error" in result
        assert "supported_types" in result

    def test_noobaa_large_file_truncation(self, must_gather_tree):
        status_file = must_gather_tree["root"] / "noobaa" / "raw_output" / "status"
        status_file.write_text("x" * 200_000)
        result = json.loads(get_noobaa_resource(str(must_gather_tree["extracted"]), "status"))
        assert result["truncated"] is True
        assert result["total_size_bytes"] == 200_000


class TestSearchMustGather:
    def test_search_finds_matches(self, must_gather_tree):
        result = json.loads(search_must_gather(str(must_gather_tree["extracted"]), "CrashLoopBackOff"))
        assert result["total_matches"] >= 1
        assert any("CrashLoopBackOff" in m["line"] for m in result["matches"])

    def test_case_insensitive_default(self, must_gather_tree):
        result = json.loads(search_must_gather(str(must_gather_tree["extracted"]), "crashloopbackoff"))
        assert result["total_matches"] >= 1

    def test_case_sensitive(self, must_gather_tree):
        result = json.loads(
            search_must_gather(str(must_gather_tree["extracted"]), "crashloopbackoff", case_sensitive=True)
        )
        assert result["total_matches"] == 0

    def test_file_pattern_filter(self, must_gather_tree):
        result = json.loads(search_must_gather(str(must_gather_tree["extracted"]), "log", file_pattern="*.log"))
        assert result["total_matches"] >= 1
        for m in result["matches"]:
            assert m["file"].endswith(".log")

    def test_max_results_truncation(self, must_gather_tree):
        result = json.loads(search_must_gather(str(must_gather_tree["extracted"]), "name", max_results=2))
        assert result["truncated"] is True
        assert len(result["matches"]) == 2

    def test_no_matches(self, must_gather_tree):
        result = json.loads(search_must_gather(str(must_gather_tree["extracted"]), "zzz_nonexistent_string_zzz"))
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
        result = json.loads(get_must_gather_pod_logs(str(must_gather_tree["extracted"]), "openshift-storage"))
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
        assert "normal line before window" in log["content"]

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
            must_gather_tree["root"]
            / "namespaces"
            / "openshift-storage"
            / "pods"
            / "rook-ceph-mon-a-abc123"
            / "mon"
            / "mon"
            / "logs"
            / "current.log"
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
        result = json.loads(get_must_gather_pod_logs(str(must_gather_tree["extracted"]), "nonexistent"))
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
            must_gather_tree["root"]
            / "namespaces"
            / "openshift-storage"
            / "pods"
            / "rook-ceph-mon-a-abc123"
            / "mon"
            / "mon"
            / "logs"
            / "current.log"
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


class TestFilterLogByTime:
    def test_basic_range(self):
        content = (
            "2025-01-15T03:37:00.000Z before\n"
            "2025-01-15T03:38:30.000Z inside1\n"
            "2025-01-15T03:39:00.000Z inside2\n"
            "2025-01-15T03:41:30.000Z after\n"
        )
        result, total, matched = _filter_log_by_time(content, "03:38:00", "03:41:00")
        assert "inside1" in result
        assert "inside2" in result
        assert "before" not in result
        assert "after" not in result
        assert total == 4
        assert matched == 2

    def test_continuation_lines(self):
        content = (
            "2025-01-15T03:38:30.000Z error occurred\n"
            "  stack trace line 1\n"
            "  stack trace line 2\n"
            "2025-01-15T03:42:00.000Z after\n"
        )
        result, _, matched = _filter_log_by_time(content, "03:38:00", "03:41:00")
        assert "error occurred" in result
        assert "stack trace line 1" in result
        assert "stack trace line 2" in result
        assert "after" not in result
        assert matched == 3

    def test_from_only(self):
        content = "2025-01-15T03:37:00.000Z before\n2025-01-15T03:39:00.000Z target\n2025-01-15T03:42:00.000Z after\n"
        result, _, matched = _filter_log_by_time(content, time_from="03:39:00")
        assert "before" not in result
        assert "target" in result
        assert "after" in result
        assert matched == 2

    def test_to_only(self):
        content = "2025-01-15T03:37:00.000Z before\n2025-01-15T03:39:00.000Z target\n2025-01-15T03:42:00.000Z after\n"
        result, _, matched = _filter_log_by_time(content, time_to="03:39:00")
        assert "before" in result
        assert "target" in result
        assert "after" not in result
        assert matched == 2

    def test_no_matches(self):
        content = "2025-01-15T03:37:00.000Z line1\n2025-01-15T03:38:00.000Z line2\n"
        result, total, matched = _filter_log_by_time(content, "01:00:00", "02:00:00")
        assert matched == 0
        assert total == 2

    def test_klog_format(self):
        content = (
            "I0115 03:37:00.123456 msg before\nI0115 03:39:00.123456 msg inside\nI0115 03:42:00.123456 msg after\n"
        )
        result, _, matched = _filter_log_by_time(content, "03:38:00", "03:41:00")
        assert "msg inside" in result
        assert "msg before" not in result
        assert matched == 1

    def test_hhmm_input(self):
        content = "2025-01-15T03:37:00.000Z before\n2025-01-15T03:39:00.000Z inside\n"
        result, _, matched = _filter_log_by_time(content, "03:38", "03:40")
        assert "inside" in result
        assert "before" not in result


class TestTimeFilteredPodLogs:
    def test_time_filter_on_pod_logs(self, must_gather_tree):
        result = json.loads(
            get_must_gather_pod_logs(
                str(must_gather_tree["extracted"]),
                "openshift-storage",
                pod_name="rook-ceph-mon-a-abc123",
                time_from="03:38:00",
                time_to="03:41:00",
            )
        )
        log = result["logs"][0]
        assert "line inside window" in log["content"]
        assert "stack trace continuation" in log["content"]
        assert "another inside window" in log["content"]
        assert "normal line before window" not in log["content"]
        assert "line after window" not in log["content"]
        assert result["time_from"] == "03:38:00"
        assert result["time_to"] == "03:41:00"

    def test_time_filter_combined_with_tail(self, must_gather_tree):
        result = json.loads(
            get_must_gather_pod_logs(
                str(must_gather_tree["extracted"]),
                "openshift-storage",
                pod_name="rook-ceph-mon-a-abc123",
                time_from="03:38:00",
                time_to="03:41:00",
                tail=1,
            )
        )
        log = result["logs"][0]
        assert log["lines"] == 1
        assert "another inside window" in log["content"]

    def test_no_time_filter_metadata_when_not_used(self, must_gather_tree):
        result = json.loads(
            get_must_gather_pod_logs(
                str(must_gather_tree["extracted"]),
                "openshift-storage",
                pod_name="rook-ceph-mon-a-abc123",
            )
        )
        assert "time_from" not in result
        assert "time_to" not in result


class TestPathTraversalGuards:
    def test_ceph_path_traversal(self, must_gather_tree):
        result = json.loads(
            get_must_gather_resource(str(must_gather_tree["extracted"]), "ceph", name="../../etc/passwd")
        )
        assert "error" in result
        assert "escapes" in result["error"]

    def test_ceph_path_traversal_dot_segments(self, must_gather_tree):
        result = json.loads(
            get_must_gather_resource(
                str(must_gather_tree["extracted"]),
                "ceph",
                name="subdir/../../../etc/shadow",
            )
        )
        assert "error" in result
        assert "escapes" in result["error"]

    def test_noobaa_diagnostics_path_traversal(self, must_gather_tree):
        # Trigger diagnostics extraction first
        get_noobaa_resource(str(must_gather_tree["extracted"]), "diagnostics")
        result = json.loads(
            get_noobaa_resource(
                str(must_gather_tree["extracted"]),
                "diagnostics",
                name="../../etc/passwd",
            )
        )
        assert "error" in result
        assert "escapes" in result["error"]

    def test_noobaa_diagnostics_absolute_path(self, must_gather_tree):
        get_noobaa_resource(str(must_gather_tree["extracted"]), "diagnostics")
        result = json.loads(
            get_noobaa_resource(
                str(must_gather_tree["extracted"]),
                "diagnostics",
                name="/etc/passwd",
            )
        )
        assert "error" in result

    def test_noobaa_logs_path_traversal(self, must_gather_tree):
        result = json.loads(
            get_noobaa_resource(
                str(must_gather_tree["extracted"]),
                "logs",
                name="../../../etc/passwd",
            )
        )
        assert "error" in result
        assert "escapes" in result["error"]

    def test_noobaa_cnpg_path_traversal(self, must_gather_tree):
        result = json.loads(
            get_noobaa_resource(
                str(must_gather_tree["extracted"]),
                "cnpg",
                name="../../etc/passwd",
            )
        )
        assert "error" in result
        assert "escapes" in result["error"]


class TestLineLengthCapping:
    def test_long_lines_capped_for_matching(self, tmp_path):
        root = tmp_path / "mg"
        (root / "namespaces" / "default").mkdir(parents=True)
        f = root / "namespaces" / "default" / "long.txt"
        f.write_text("x" * 20_000 + "needle\n")

        result = json.loads(search_must_gather(str(tmp_path), "needle"))
        assert result["total_matches"] == 0

    def test_match_within_cap(self, tmp_path):
        root = tmp_path / "mg"
        (root / "namespaces" / "default").mkdir(parents=True)
        f = root / "namespaces" / "default" / "ok.txt"
        f.write_text("x" * 100 + "needle\n")

        result = json.loads(search_must_gather(str(tmp_path), "needle"))
        assert result["total_matches"] == 1

    def test_works_from_non_main_thread(self, tmp_path):
        """Search must work from non-main threads (MCP handlers run in worker threads)."""
        root = tmp_path / "mg"
        (root / "namespaces" / "default").mkdir(parents=True)
        f = root / "namespaces" / "default" / "data.txt"
        f.write_text("findme here\n")

        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(search_must_gather, str(tmp_path), "findme")
            result = json.loads(future.result(timeout=10))

        assert result["total_matches"] == 1


class TestCountFilesAndSize:
    def test_counts_files_and_sums_size(self, tmp_path):
        (tmp_path / "a.txt").write_text("hello")
        (tmp_path / "b.txt").write_text("world!")
        (tmp_path / "c.txt").write_text("!")
        count, size = _count_files_and_size(tmp_path)
        assert count == 3
        assert size == 5 + 6 + 1

    def test_empty_directory(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        count, size = _count_files_and_size(empty)
        assert count == 0
        assert size == 0

    def test_nested_files(self, tmp_path):
        sub = tmp_path / "a" / "b" / "c"
        sub.mkdir(parents=True)
        (sub / "deep.txt").write_text("data")
        (tmp_path / "top.txt").write_text("hi")
        count, size = _count_files_and_size(tmp_path)
        assert count == 2
        assert size == 4 + 2


class TestFindMustGatherRootCaching:
    def setup_method(self):
        _find_must_gather_root.cache_clear()

    def teardown_method(self):
        _find_must_gather_root.cache_clear()

    def test_lru_cache_returns_same_object(self, tmp_path):
        root = tmp_path / "mg"
        (root / "namespaces" / "default").mkdir(parents=True)
        result1 = _find_must_gather_root(str(tmp_path))
        result2 = _find_must_gather_root(str(tmp_path))
        assert result1 is result2

    def test_lru_cache_different_paths(self, tmp_path):
        path_a = tmp_path / "a"
        (path_a / "namespaces" / "ns1").mkdir(parents=True)
        path_b = tmp_path / "b"
        (path_b / "namespaces" / "ns2").mkdir(parents=True)
        result_a = _find_must_gather_root(str(path_a))
        result_b = _find_must_gather_root(str(path_b))
        assert result_a == path_a
        assert result_b == path_b
        assert result_a != result_b

    def test_direct_namespaces_path(self, tmp_path):
        (tmp_path / "namespaces" / "default").mkdir(parents=True)
        result = _find_must_gather_root(str(tmp_path))
        assert result == tmp_path

    def test_one_level_deep_fast_path(self, tmp_path):
        child = tmp_path / "must-gather-root"
        (child / "namespaces" / "default").mkdir(parents=True)
        result = _find_must_gather_root(str(tmp_path))
        assert result == child


class TestEdgeCases:
    def test_noobaa_logs_large_file_auto_truncation(self, must_gather_tree):
        log_file = must_gather_tree["root"] / "noobaa" / "logs" / "openshift-storage" / "noobaa_endpoint.log"
        log_file.write_text("\n".join(f"line {i} " + "x" * 200 for i in range(2000)) + "\n")
        result = json.loads(
            get_noobaa_resource(
                str(must_gather_tree["extracted"]),
                "logs",
                name="noobaa_endpoint.log",
            )
        )
        assert result["truncated"] is True

    def test_events_large_file_with_tail_hint(self, must_gather_tree):
        events_file = must_gather_tree["root"] / "namespaces" / "openshift-storage" / "core" / "events.yaml"
        events_file.write_text(
            "apiVersion: v1\nkind: EventList\nitems:\n"
            + "".join(f"- reason: Event{i}\n  message: {'x' * 500}\n" for i in range(500))
        )
        result = json.loads(
            get_must_gather_resource(
                str(must_gather_tree["extracted"]),
                "events",
                namespace="openshift-storage",
            )
        )
        assert result["truncated"] is True
        assert "hint" in result
        assert "tail" in result["hint"]

    def test_configmap_list(self, must_gather_tree):
        result = json.loads(
            get_must_gather_resource(
                str(must_gather_tree["extracted"]),
                "configmap",
                namespace="openshift-storage",
            )
        )
        assert "rook-ceph-mon-endpoints" in result["available_names"]

    def test_secret_resource(self, must_gather_tree):
        result = json.loads(
            get_must_gather_resource(
                str(must_gather_tree["extracted"]),
                "secret",
                name="rook-ceph-admin",
                namespace="openshift-storage",
            )
        )
        assert result["resource_type"] == "secret"
        assert "Secret" in result["content"]

    def test_namespaced_resource_dir_missing(self, must_gather_tree):
        result = json.loads(
            get_must_gather_resource(
                str(must_gather_tree["extracted"]),
                "deployment",
                namespace="default",
            )
        )
        assert "error" in result
        assert "default" in result["error"]
