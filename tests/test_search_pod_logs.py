import json

import pytest
from must_gather_downloader.pod_logs import search_pod_logs


@pytest.fixture
def search_tree(tmp_path):
    """Create a must-gather tree with log content tailored for search tests."""
    root = tmp_path / "extracted" / "must-gather-search"

    ns = "openshift-storage"
    pods_dir = root / "namespaces" / ns / "pods"

    # Pod 1: noobaa-endpoint with two containers
    ep_main = pods_dir / "noobaa-endpoint-7f8b9c6d5-x2k4m" / "endpoint" / "endpoint" / "logs"
    ep_main.mkdir(parents=True)
    (ep_main / "current.log").write_text(
        "2025-01-15T03:37:00.000Z INFO starting endpoint\n"
        "2025-01-15T03:38:00.000Z DEBUG connection pool initialized\n"
        "2025-01-15T03:38:30.000Z ERROR connect ECONNREFUSED 10.0.0.1:443\n"
        "2025-01-15T03:38:31.000Z ERROR retry 1 failed ECONNREFUSED\n"
        "2025-01-15T03:38:32.000Z INFO retrying connection\n"
        "2025-01-15T03:39:00.000Z ERROR connect ECONNREFUSED 10.0.0.2:443\n"
        "2025-01-15T03:39:30.000Z WARN connection unstable\n"
        "2025-01-15T03:40:00.000Z INFO endpoint recovered\n"
    )
    (ep_main / "previous.log").write_text(
        "2025-01-14T23:00:00.000Z INFO old endpoint starting\n"
        "2025-01-14T23:01:00.000Z ERROR old ECONNREFUSED error\n"
        "2025-01-14T23:02:00.000Z INFO old endpoint stopped\n"
    )

    ep_sidecar = pods_dir / "noobaa-endpoint-7f8b9c6d5-x2k4m" / "sidecar" / "sidecar" / "logs"
    ep_sidecar.mkdir(parents=True)
    (ep_sidecar / "current.log").write_text(
        "2025-01-15T03:37:00.000Z INFO sidecar started\n"
        "2025-01-15T03:38:35.000Z WARN sidecar ECONNREFUSED from proxy\n"
        "2025-01-15T03:39:00.000Z INFO sidecar healthy\n"
    )

    # Pod 2: another noobaa-endpoint replica
    ep2_main = pods_dir / "noobaa-endpoint-7f8b9c6d5-y3l5n" / "endpoint" / "endpoint" / "logs"
    ep2_main.mkdir(parents=True)
    (ep2_main / "current.log").write_text(
        "2025-01-15T03:37:00.000Z INFO starting endpoint replica 2\n"
        "2025-01-15T03:39:15.000Z ERROR ECONNREFUSED on replica 2\n"
        "2025-01-15T03:40:00.000Z INFO replica 2 recovered\n"
    )

    # Pod 3: unrelated pod
    core_pod = pods_dir / "noobaa-core-0" / "noobaa-core" / "noobaa-core" / "logs"
    core_pod.mkdir(parents=True)
    (core_pod / "current.log").write_text(
        "2025-01-15T03:38:00.000Z INFO core processing\n2025-01-15T03:39:00.000Z DEBUG core heartbeat\n"
    )

    return {"extracted": tmp_path / "extracted", "root": root, "namespace": ns}


class TestBasicSearch:
    def test_pattern_match_with_context(self, search_tree):
        result = json.loads(
            search_pod_logs(
                str(search_tree["extracted"]),
                search_tree["namespace"],
                "noobaa-endpoint-7f8b9c6d5-x2k4m",
                "ECONNREFUSED",
                container="endpoint",
            )
        )
        assert result["total_matches"] == 3
        assert not result["truncated"]

        m = result["matches"][0]
        assert m["line_number"] == 3
        assert "ECONNREFUSED" in m["line"]
        assert len(m["context_before"]) == 2
        assert len(m["context_after"]) == 3

    def test_no_matches_returns_empty_list(self, search_tree):
        result = json.loads(
            search_pod_logs(
                str(search_tree["extracted"]),
                search_tree["namespace"],
                "noobaa-endpoint-7f8b9c6d5-x2k4m",
                "NONEXISTENT_PATTERN",
                container="endpoint",
            )
        )
        assert result["total_matches"] == 0
        assert result["matches"] == []
        assert not result["truncated"]

    def test_empty_pattern_returns_error(self, search_tree):
        result = json.loads(
            search_pod_logs(
                str(search_tree["extracted"]),
                search_tree["namespace"],
                "noobaa-endpoint",
                "",
            )
        )
        assert "error" in result


class TestCaseSensitivity:
    def test_case_insensitive_default(self, search_tree):
        result = json.loads(
            search_pod_logs(
                str(search_tree["extracted"]),
                search_tree["namespace"],
                "noobaa-endpoint-7f8b9c6d5-x2k4m",
                "econnrefused",
                container="endpoint",
            )
        )
        assert result["total_matches"] == 3

    def test_case_sensitive(self, search_tree):
        result = json.loads(
            search_pod_logs(
                str(search_tree["extracted"]),
                search_tree["namespace"],
                "noobaa-endpoint-7f8b9c6d5-x2k4m",
                "econnrefused",
                container="endpoint",
                case_sensitive=True,
            )
        )
        assert result["total_matches"] == 0

    def test_case_sensitive_exact_match(self, search_tree):
        result = json.loads(
            search_pod_logs(
                str(search_tree["extracted"]),
                search_tree["namespace"],
                "noobaa-endpoint-7f8b9c6d5-x2k4m",
                "ECONNREFUSED",
                container="endpoint",
                case_sensitive=True,
            )
        )
        assert result["total_matches"] == 3


class TestTimeFiltering:
    def test_time_from_filter(self, search_tree):
        result = json.loads(
            search_pod_logs(
                str(search_tree["extracted"]),
                search_tree["namespace"],
                "noobaa-endpoint-7f8b9c6d5-x2k4m",
                "ECONNREFUSED",
                container="endpoint",
                time_from="03:39:00",
            )
        )
        assert result["total_matches"] == 1
        assert "10.0.0.2" in result["matches"][0]["line"]

    def test_time_to_filter(self, search_tree):
        result = json.loads(
            search_pod_logs(
                str(search_tree["extracted"]),
                search_tree["namespace"],
                "noobaa-endpoint-7f8b9c6d5-x2k4m",
                "ECONNREFUSED",
                container="endpoint",
                time_to="03:38:31",
            )
        )
        assert result["total_matches"] == 2

    def test_time_range_filter(self, search_tree):
        result = json.loads(
            search_pod_logs(
                str(search_tree["extracted"]),
                search_tree["namespace"],
                "noobaa-endpoint-7f8b9c6d5-x2k4m",
                "ECONNREFUSED",
                container="endpoint",
                time_from="03:38:30",
                time_to="03:38:31",
            )
        )
        assert result["total_matches"] == 2


class TestPodMatching:
    def test_substring_matches_multiple_pods(self, search_tree):
        result = json.loads(
            search_pod_logs(
                str(search_tree["extracted"]),
                search_tree["namespace"],
                "noobaa-endpoint",
                "ECONNREFUSED",
            )
        )
        pods_with_matches = {m["pod"] for m in result["matches"]}
        assert len(pods_with_matches) == 2
        assert "noobaa-endpoint-7f8b9c6d5-x2k4m" in pods_with_matches
        assert "noobaa-endpoint-7f8b9c6d5-y3l5n" in pods_with_matches

    def test_no_matching_pod_returns_error(self, search_tree):
        result = json.loads(
            search_pod_logs(
                str(search_tree["extracted"]),
                search_tree["namespace"],
                "nonexistent-pod",
                "ECONNREFUSED",
            )
        )
        assert "error" in result
        assert "available_pods" in result

    def test_invalid_namespace_returns_error(self, search_tree):
        result = json.loads(
            search_pod_logs(
                str(search_tree["extracted"]),
                "nonexistent-namespace",
                "noobaa-endpoint",
                "ECONNREFUSED",
            )
        )
        assert "error" in result


class TestContainerFiltering:
    def test_filter_specific_container(self, search_tree):
        result = json.loads(
            search_pod_logs(
                str(search_tree["extracted"]),
                search_tree["namespace"],
                "noobaa-endpoint-7f8b9c6d5-x2k4m",
                "ECONNREFUSED",
                container="sidecar",
            )
        )
        assert result["total_matches"] == 1
        assert result["matches"][0]["container"] == "sidecar"

    def test_no_container_searches_all(self, search_tree):
        result = json.loads(
            search_pod_logs(
                str(search_tree["extracted"]),
                search_tree["namespace"],
                "noobaa-endpoint-7f8b9c6d5-x2k4m",
                "ECONNREFUSED",
            )
        )
        containers = {m["container"] for m in result["matches"]}
        assert "endpoint" in containers
        assert "sidecar" in containers


class TestMaxResults:
    def test_truncation(self, search_tree):
        result = json.loads(
            search_pod_logs(
                str(search_tree["extracted"]),
                search_tree["namespace"],
                "noobaa-endpoint-7f8b9c6d5-x2k4m",
                "ECONNREFUSED",
                container="endpoint",
                max_results=2,
            )
        )
        assert result["total_matches"] == 2
        assert result["truncated"] is True

    def test_no_truncation_when_under_limit(self, search_tree):
        result = json.loads(
            search_pod_logs(
                str(search_tree["extracted"]),
                search_tree["namespace"],
                "noobaa-endpoint-7f8b9c6d5-x2k4m",
                "ECONNREFUSED",
                container="endpoint",
                max_results=100,
            )
        )
        assert result["truncated"] is False


class TestPreviousLog:
    def test_searches_previous_log(self, search_tree):
        result = json.loads(
            search_pod_logs(
                str(search_tree["extracted"]),
                search_tree["namespace"],
                "noobaa-endpoint-7f8b9c6d5-x2k4m",
                "ECONNREFUSED",
                container="endpoint",
                previous=True,
            )
        )
        assert result["total_matches"] == 1
        assert "old" in result["matches"][0]["line"]


class TestRegex:
    def test_regex_pattern(self, search_tree):
        result = json.loads(
            search_pod_logs(
                str(search_tree["extracted"]),
                search_tree["namespace"],
                "noobaa-endpoint-7f8b9c6d5-x2k4m",
                r"ECONNREFUSED.*443",
                container="endpoint",
            )
        )
        assert result["total_matches"] == 2

    def test_invalid_regex_falls_back_to_literal(self, search_tree):
        result = json.loads(
            search_pod_logs(
                str(search_tree["extracted"]),
                search_tree["namespace"],
                "noobaa-endpoint-7f8b9c6d5-x2k4m",
                "[invalid regex",
                container="endpoint",
            )
        )
        assert result["total_matches"] == 0
        assert not result["truncated"]


class TestContextLines:
    def test_zero_context_lines(self, search_tree):
        result = json.loads(
            search_pod_logs(
                str(search_tree["extracted"]),
                search_tree["namespace"],
                "noobaa-endpoint-7f8b9c6d5-x2k4m",
                "ECONNREFUSED",
                container="endpoint",
                context_lines=0,
            )
        )
        for m in result["matches"]:
            assert m["context_before"] == []
            assert m["context_after"] == []

    def test_context_at_file_boundaries(self, search_tree):
        result = json.loads(
            search_pod_logs(
                str(search_tree["extracted"]),
                search_tree["namespace"],
                "noobaa-endpoint-7f8b9c6d5-x2k4m",
                "starting endpoint$",
                container="endpoint",
                context_lines=5,
            )
        )
        assert result["total_matches"] == 1
        assert result["matches"][0]["context_before"] == []
        assert len(result["matches"][0]["context_after"]) == 5
