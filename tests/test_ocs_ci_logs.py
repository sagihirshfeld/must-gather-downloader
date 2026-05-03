import json
from unittest.mock import MagicMock, patch

import pytest
import requests
from must_gather_downloader.ocs_ci_logs import (
    _fetch_and_filter_log,
    _find_test_log_url,
    _normalize_test_name,
    get_ocs_ci_test_log,
)

MODULE = "must_gather_downloader.ocs_ci_logs"
RP_MODULE = "must_gather_downloader.reportportal"


class TestNormalizeTestName:
    def test_simple_name(self):
        assert _normalize_test_name("test_foo") == "test_foo"

    def test_single_param(self):
        assert _normalize_test_name("test_foo[bar]") == "test_foo-bar"

    def test_multi_param(self):
        assert _normalize_test_name("test_foo[bar-baz]") == "test_foo-bar-baz"

    def test_no_brackets(self):
        assert _normalize_test_name("test_bucket_notifications") == "test_bucket_notifications"

    def test_complex_params(self):
        assert _normalize_test_name("test_foo[a][b]") == "test_foo-a-b"


LOGS_PAGE_HTML = [
    '<a href="ocs-ci-logs-111/">ocs-ci-logs-111/</a>',
    '<a href="ocs-ci-logs-222/">ocs-ci-logs-222/</a>',
    '<a href="deploy-log.log">deploy-log.log</a>',
]

TESTS_DIR_HTML = [
    '<a href="functional/">functional/</a>',
]

FUNCTIONAL_DIR_HTML = [
    '<a href="object/">object/</a>',
]

OBJECT_DIR_HTML = [
    '<a href="mcg/">mcg/</a>',
]

MCG_DIR_HTML = [
    '<a href="test_bucket_notifications.py/">test_bucket_notifications.py/</a>',
    '<a href="test_other.py/">test_other.py/</a>',
]

CLASS_DIR_HTML = [
    '<a href="TestBucketNotifications/">TestBucketNotifications/</a>',
]

TEST_DIR_HTML = [
    '<a href="test_bucket_notifications-default-logs-pvc/">test_bucket_notifications-default-logs-pvc/</a>',
]


class TestFindTestLogUrl:
    @patch(f"{MODULE}._fetch_html_lines")
    def test_found_in_first_dir(self, mock_fetch):
        mock_fetch.side_effect = [
            LOGS_PAGE_HTML,
            TESTS_DIR_HTML,
            FUNCTIONAL_DIR_HTML,
            OBJECT_DIR_HTML,
            MCG_DIR_HTML,
            CLASS_DIR_HTML,
            TEST_DIR_HTML,
            [],
            # Second ocs-ci-logs dir: empty tests
            ['<a href="functional/">functional/</a>'],
            [],
        ]

        log_url, ocs_dir = _find_test_log_url(
            "https://magna.example.com/cluster/", "test_bucket_notifications[default-logs-pvc]", "key"
        )
        assert "test_bucket_notifications-default-logs-pvc/logs" in log_url
        assert ocs_dir == "ocs-ci-logs-111"

    @patch(f"{MODULE}._fetch_html_lines")
    def test_not_found_raises(self, mock_fetch):
        mock_fetch.side_effect = [
            LOGS_PAGE_HTML,
            # Dir 1: no matching test
            ['<a href="functional/">functional/</a>'],
            [],
            # Dir 2: no matching test
            ['<a href="functional/">functional/</a>'],
            [],
        ]

        with pytest.raises(ValueError, match="not found"):
            _find_test_log_url("https://magna.example.com/cluster/", "test_nonexistent", "key")

    @patch(f"{MODULE}._fetch_html_lines")
    def test_no_ocs_ci_dirs(self, mock_fetch):
        mock_fetch.return_value = [
            '<a href="deploy-log.log">deploy-log.log</a>',
            '<a href="some-other-dir/">some-other-dir/</a>',
        ]

        with pytest.raises(ValueError, match="No ocs-ci-logs"):
            _find_test_log_url("https://magna.example.com/cluster/", "test_foo", "key")

    @patch(f"{MODULE}._fetch_html_lines")
    def test_partial_match(self, mock_fetch):
        mock_fetch.side_effect = [
            ['<a href="ocs-ci-logs-111/">ocs-ci-logs-111/</a>'],
            ['<a href="test_bucket_notifications-default-logs-pvc/">test_bucket_notifications-default-logs-pvc/</a>'],
            [],
        ]

        log_url, _ = _find_test_log_url("https://magna.example.com/cluster/", "test_bucket_notifications", "key")
        assert "test_bucket_notifications-default-logs-pvc/logs" in log_url

    @patch(f"{MODULE}._fetch_html_lines")
    def test_multiple_matches_raises(self, mock_fetch):
        mock_fetch.side_effect = [
            ['<a href="ocs-ci-logs-111/">ocs-ci-logs-111/</a>'],
            [
                '<a href="test_bucket_notifications-default-logs-pvc/">match1/</a>',
                '<a href="test_bucket_notifications-provided-logs-pvc/">match2/</a>',
            ],
            [],
            [],
        ]

        with pytest.raises(ValueError, match="Multiple matches"):
            _find_test_log_url("https://magna.example.com/cluster/", "test_bucket_notifications", "key")

    @patch(f"{MODULE}._fetch_html_lines")
    def test_http_error_skips_dir(self, mock_fetch):
        def side_effect(url, api_key=""):
            if "ocs-ci-logs-111" in url:
                raise requests.HTTPError("404")
            if "ocs-ci-logs-222" in url and "tests" in url:
                return ['<a href="test_foo/">test_foo/</a>']
            if "test_foo" in url:
                return []
            return [
                '<a href="ocs-ci-logs-111/">ocs-ci-logs-111/</a>',
                '<a href="ocs-ci-logs-222/">ocs-ci-logs-222/</a>',
            ]

        mock_fetch.side_effect = side_effect

        log_url, ocs_dir = _find_test_log_url("https://magna.example.com/cluster/", "test_foo", "key")
        assert ocs_dir == "ocs-ci-logs-222"


SAMPLE_LOG = (
    "2026-03-25 07:15:08,069 - MainThread - INFO - ocs_ci.framework - setup started\n"
    "2026-03-25 07:15:08,070 - MainThread - DEBUG - ocs_ci.utility.utils - Command stdout: apiVersion: v1\n"
    "kind: Pod\n"
    "metadata:\n"
    "  name: test-pod\n"
    "2026-03-25 07:15:08,209 - MainThread - DEBUG - ocs_ci.utility.utils - Command return code: 0\n"
    "2026-03-25 07:15:08,210 - MainThread - INFO - ocs_ci.utility.utils - Executing command: oc get pods\n"
    "2026-03-25 07:15:09,000 - MainThread - WARNING - ocs_ci.ocs.resources - Pod not ready\n"
    "2026-03-25 07:15:10,000 - MainThread - ERROR - ocs_ci.ocs.resources - Test failed\n"
    "2026-03-25 07:15:11,000 - MainThread - INFO - ocs_ci.framework - teardown done\n"
)


class TestFetchAndFilterLog:
    @patch(f"{MODULE}.requests.get")
    def test_debug_filtering(self, mock_get):
        resp = MagicMock()
        resp.text = SAMPLE_LOG
        resp.raise_for_status.return_value = None
        mock_get.return_value = resp

        content, meta = _fetch_and_filter_log("https://magna.example.com/logs", "key", exclude_debug=True)
        assert "- DEBUG -" not in content
        assert "- INFO -" in content
        assert "- WARNING -" in content
        assert "- ERROR -" in content
        assert meta["total_lines_raw"] == 10
        assert meta["total_lines_after_filter"] == 8

    @patch(f"{MODULE}.requests.get")
    def test_no_debug_filtering(self, mock_get):
        resp = MagicMock()
        resp.text = SAMPLE_LOG
        resp.raise_for_status.return_value = None
        mock_get.return_value = resp

        content, meta = _fetch_and_filter_log("https://magna.example.com/logs", "key", exclude_debug=False)
        assert "- DEBUG -" in content
        assert meta["total_lines_after_filter"] == 10

    @patch(f"{MODULE}.requests.get")
    def test_tail(self, mock_get):
        resp = MagicMock()
        resp.text = SAMPLE_LOG
        resp.raise_for_status.return_value = None
        mock_get.return_value = resp

        content, meta = _fetch_and_filter_log("https://magna.example.com/logs", "key", exclude_debug=True, tail=2)
        lines = content.strip().splitlines()
        assert len(lines) == 2
        assert "teardown done" in lines[-1]

    @patch(f"{MODULE}.requests.get")
    def test_head(self, mock_get):
        resp = MagicMock()
        resp.text = SAMPLE_LOG
        resp.raise_for_status.return_value = None
        mock_get.return_value = resp

        content, meta = _fetch_and_filter_log("https://magna.example.com/logs", "key", exclude_debug=True, head=2)
        lines = content.strip().splitlines()
        assert len(lines) == 2
        assert "setup started" in lines[0]

    def test_head_and_tail_error(self):
        with pytest.raises(ValueError, match="Cannot specify both"):
            _fetch_and_filter_log("https://magna.example.com/logs", "key", head=10, tail=10)

    @patch(f"{MODULE}.requests.get")
    def test_max_size_truncation(self, mock_get):
        large_log = "\n".join(f"line {i}" for i in range(100000)) + "\n"
        resp = MagicMock()
        resp.text = large_log
        resp.raise_for_status.return_value = None
        mock_get.return_value = resp

        content, meta = _fetch_and_filter_log("https://magna.example.com/logs", "key", exclude_debug=False)
        assert meta["truncated"]
        assert len(content.encode("utf-8")) <= 200 * 1024 + 100

    @patch(f"{MODULE}.requests.get")
    def test_line_counts(self, mock_get):
        resp = MagicMock()
        resp.text = SAMPLE_LOG
        resp.raise_for_status.return_value = None
        mock_get.return_value = resp

        content, meta = _fetch_and_filter_log("https://magna.example.com/logs", "key", exclude_debug=True)
        assert meta["lines_returned"] == meta["total_lines_after_filter"]
        assert meta["total_lines_raw"] > meta["total_lines_after_filter"]

    @patch(f"{MODULE}.requests.get")
    def test_debug_filter_preserves_multiline_context(self, mock_get):
        log = (
            "2026 - MainThread - INFO - start\n"
            "2026 - MainThread - DEBUG - Command stdout: apiVersion: v1\n"
            "kind: Pod\n"
            "2026 - MainThread - INFO - end\n"
        )
        resp = MagicMock()
        resp.text = log
        resp.raise_for_status.return_value = None
        mock_get.return_value = resp

        content, meta = _fetch_and_filter_log("https://magna.example.com/logs", "key", exclude_debug=True)
        lines = content.strip().splitlines()
        assert len(lines) == 3
        assert "start" in lines[0]
        assert "kind: Pod" in lines[1]
        assert "end" in lines[2]


LAUNCH_JSON = {
    "content": [{"description": "Build #42\nLogs URL: https://magna.example.com/openshift-clusters/test-cluster/"}]
}
ITEM_JSON = {"name": "test_my_feature[param1]"}


class TestGetOcsCiTestLog:
    @patch(f"{MODULE}._find_test_log_url")
    @patch(f"{RP_MODULE}._fetch_json")
    @patch(f"{MODULE}._fetch_and_filter_log")
    def test_success(self, mock_filter, mock_json, mock_find, env_config):
        mock_json.side_effect = [LAUNCH_JSON, ITEM_JSON]
        mock_find.return_value = ("https://magna.example.com/logs/file", "ocs-ci-logs-111")
        mock_filter.return_value = (
            "log content\n",
            {
                "total_lines_raw": 100,
                "total_lines_after_filter": 50,
                "lines_returned": 50,
                "truncated": False,
            },
        )

        result = json.loads(
            get_ocs_ci_test_log(
                "https://rp.example.com/ui/#ocs/launches/all/12345/item/67890/log",
                "test_my_feature[param1]",
            )
        )
        assert result["test_name"] == "test_my_feature[param1]"
        assert result["ocs_ci_dir"] == "ocs-ci-logs-111"
        assert result["content"] == "log content\n"
        assert result["exclude_debug"] is True

    @patch(f"{RP_MODULE}._fetch_json")
    def test_rp_error(self, mock_json, env_config):
        mock_json.side_effect = requests.HTTPError("500 Server Error")

        result = json.loads(
            get_ocs_ci_test_log(
                "https://rp.example.com/ui/#ocs/launches/all/12345/item/67890/log",
                "test_foo",
            )
        )
        assert "error" in result

    def test_invalid_url(self, env_config):
        result = json.loads(get_ocs_ci_test_log("https://not-a-valid-url.com", "test_foo"))
        assert "error" in result

    @patch(f"{MODULE}._find_test_log_url")
    @patch(f"{RP_MODULE}._fetch_json")
    def test_test_not_found(self, mock_json, mock_find, env_config):
        mock_json.side_effect = [LAUNCH_JSON, ITEM_JSON]
        mock_find.side_effect = ValueError("Test 'test_foo' not found")

        result = json.loads(
            get_ocs_ci_test_log(
                "https://rp.example.com/ui/#ocs/launches/all/12345/item/67890/log",
                "test_foo",
            )
        )
        assert "error" in result
        assert "not found" in result["error"]

    @patch(f"{MODULE}._find_test_log_url")
    @patch(f"{RP_MODULE}._fetch_json")
    @patch(f"{MODULE}._fetch_and_filter_log")
    def test_head_tail_conflict(self, mock_filter, mock_json, mock_find, env_config):
        mock_json.side_effect = [LAUNCH_JSON, ITEM_JSON]
        mock_find.return_value = ("https://magna.example.com/logs/file", "ocs-ci-logs-111")
        mock_filter.side_effect = ValueError("Cannot specify both head and tail")

        result = json.loads(
            get_ocs_ci_test_log(
                "https://rp.example.com/ui/#ocs/launches/all/12345/item/67890/log",
                "test_foo",
                head=10,
                tail=10,
            )
        )
        assert "error" in result
        assert "Cannot specify both" in result["error"]

    def test_config_error(self, monkeypatch):
        monkeypatch.delenv("RP_API_KEY", raising=False)
        monkeypatch.delenv("RP_BASE_URL", raising=False)

        result = json.loads(
            get_ocs_ci_test_log(
                "https://rp.example.com/ui/#ocs/launches/all/12345/item/67890/log",
                "test_foo",
            )
        )
        assert "error" in result
