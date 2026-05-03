import json
from unittest.mock import MagicMock, patch

import pytest
import requests
from must_gather_downloader.ocs_ci_logs import (
    _extract_test_section,
    _fetch_and_extract_test,
    _find_deploy_log_url,
    _strip_ansi,
    get_ocs_ci_test_log,
)

MODULE = "must_gather_downloader.ocs_ci_logs"
RP_MODULE = "must_gather_downloader.reportportal"


class TestStripAnsi:
    def test_removes_codes(self):
        assert _strip_ansi("\x1b[32mINFO\x1b[0m") == "INFO"

    def test_no_codes(self):
        assert _strip_ansi("plain text") == "plain text"

    def test_bold_and_color(self):
        assert _strip_ansi("\x1b[1m--- live log ---\x1b[0m") == "--- live log ---"


LOGS_PAGE_HTML = [
    '<tr><td><a href="deploy-ocs-cluster-build-12345.log">deploy-ocs-cluster-build-12345.log</a></td>'
    '<td align="right">2026-04-30 19:59</td><td align="right">8.7M</td></tr>',
    '<tr><td><a href="destroy-ocs-cluster-build-99999.log">destroy-ocs-cluster-build-99999.log</a></td>'
    '<td align="right">2026-04-30 20:13</td><td align="right">  0 </td></tr>',
    '<tr><td><a href="ocs-ci-logs-111/">ocs-ci-logs-111/</a></td></tr>',
]


class TestFindDeployLogUrl:
    @patch(f"{MODULE}._fetch_html_lines")
    def test_single_deploy_log(self, mock_fetch):
        mock_fetch.return_value = LOGS_PAGE_HTML
        url, name = _find_deploy_log_url("https://magna.example.com/cluster/", "key")
        assert name == "deploy-ocs-cluster-build-12345.log"
        assert url.endswith("deploy-ocs-cluster-build-12345.log")

    @patch(f"{MODULE}._fetch_html_lines")
    def test_multiple_deploy_logs_picks_largest(self, mock_fetch):
        mock_fetch.return_value = [
            '<tr><td><a href="deploy-ocs-cluster-build-111.log">f1</a></td>'
            '<td align="right">2026</td><td align="right">1.2M</td></tr>',
            '<tr><td><a href="deploy-ocs-cluster-build-222.log">f2</a></td>'
            '<td align="right">2026</td><td align="right">8.7M</td></tr>',
        ]
        url, name = _find_deploy_log_url("https://magna.example.com/cluster/", "key")
        assert name == "deploy-ocs-cluster-build-222.log"

    @patch(f"{MODULE}._fetch_html_lines")
    def test_no_deploy_log_raises(self, mock_fetch):
        mock_fetch.return_value = [
            '<tr><td><a href="other-file.log">other-file.log</a></td></tr>',
        ]
        with pytest.raises(ValueError, match="No deploy log file"):
            _find_deploy_log_url("https://magna.example.com/cluster/", "key")

    @patch(f"{MODULE}._fetch_html_lines")
    def test_no_size_info_picks_first(self, mock_fetch):
        mock_fetch.return_value = [
            '<a href="deploy-ocs-cluster-build-111.log">f1</a>',
            '<a href="deploy-ocs-cluster-build-222.log">f2</a>',
        ]
        _, name = _find_deploy_log_url("https://magna.example.com/cluster/", "key")
        assert name == "deploy-ocs-cluster-build-111.log"


_TS = "[2026-04-30T08:00:00.000Z]"
_SETUP = f"{_TS} \x1b[1m------------ live log setup ------------\x1b[0m"
DEPLOY_LOG = (
    f"{_TS} collected 10 items\n"
    f"{_TS} \n"
    f"{_TS} tests/functional/test_foo.py::TestFoo::test_alpha[param1] \n"
    f"{_SETUP}\n"
    f"{_TS} 04:00:01 - MainThread - INFO - setup alpha\n"
    f"{_TS} 04:00:02 - MainThread - INFO - running alpha\n"
    f"{_TS} duration reported by test_alpha[param1] after exec: 2.0\n"
    f"{_TS} \x1b[32mPASSED\x1b[0m\n"
    f"{_TS} memory stats line\n"
    f"{_TS} \n"
    f"{_TS} tests/functional/test_foo.py::TestFoo::test_beta \n"
    f"{_SETUP}\n"
    f"{_TS} 04:00:06 - MainThread - INFO - setup beta\n"
    f"{_TS} 04:00:07 - MainThread - INFO - running beta\n"
    f"{_TS} duration reported by test_beta after exec: 3.0\n"
    f"{_TS} \x1b[31mFAILED\x1b[0m\n"
    f"{_TS} teardown stats\n"
)


class TestExtractTestSection:
    def test_extract_first_test(self):
        lines = DEPLOY_LOG.splitlines()
        result = _extract_test_section(lines, "test_alpha[param1]")
        content = "\n".join(result)
        assert "setup alpha" in content
        assert "running alpha" in content
        assert "memory stats line" in content
        assert "setup beta" not in content

    def test_extract_second_test(self):
        lines = DEPLOY_LOG.splitlines()
        result = _extract_test_section(lines, "test_beta")
        content = "\n".join(result)
        assert "setup beta" in content
        assert "running beta" in content
        assert "teardown stats" in content
        assert "setup alpha" not in content

    def test_last_test_includes_to_end(self):
        lines = DEPLOY_LOG.splitlines()
        result = _extract_test_section(lines, "test_beta")
        assert result[-1].strip() != ""
        content = "\n".join(result)
        assert "teardown stats" in content

    def test_not_found_raises(self):
        lines = DEPLOY_LOG.splitlines()
        with pytest.raises(ValueError, match="not found"):
            _extract_test_section(lines, "test_nonexistent")

    def test_ansi_stripped(self):
        lines = DEPLOY_LOG.splitlines()
        result = _extract_test_section(lines, "test_alpha[param1]")
        for line in result:
            assert "\x1b[" not in line

    def test_multiple_sections_concatenated(self):
        log = (
            "[T] tests/test_a.py::test_run \n"
            "[T] \x1b[1m--- live log setup ---\x1b[0m\n"
            "[T] first run\n"
            "[T] tests/test_b.py::test_other \n"
            "[T] \x1b[1m--- live log setup ---\x1b[0m\n"
            "[T] other test\n"
            "[T] tests/test_a.py::test_run \n"
            "[T] \x1b[1m--- live log setup ---\x1b[0m\n"
            "[T] second run\n"
        )
        lines = log.splitlines()
        result = _extract_test_section(lines, "test_run")
        content = "\n".join(result)
        assert "first run" in content
        assert "second run" in content
        assert "section 2" in content.lower()

    def test_substring_match_on_nodeid(self):
        lines = DEPLOY_LOG.splitlines()
        result = _extract_test_section(lines, "test_alpha")
        content = "\n".join(result)
        assert "setup alpha" in content

    def test_parameterized_exact_match(self):
        log = (
            "[T] tests/test.py::Test::test_foo[bar] \n"
            "[T] \x1b[1m--- live log setup ---\x1b[0m\n"
            "[T] bar content\n"
            "[T] tests/test.py::Test::test_foo[baz] \n"
            "[T] \x1b[1m--- live log setup ---\x1b[0m\n"
            "[T] baz content\n"
        )
        lines = log.splitlines()
        result = _extract_test_section(lines, "test_foo[bar]")
        content = "\n".join(result)
        assert "bar content" in content
        assert "baz content" not in content


class TestFetchAndExtractTest:
    @patch(f"{MODULE}.requests.get")
    def test_basic_extraction(self, mock_get):
        resp = MagicMock()
        resp.text = DEPLOY_LOG
        resp.raise_for_status.return_value = None
        mock_get.return_value = resp

        content, meta = _fetch_and_extract_test("https://magna.example.com/deploy.log", "key", "test_alpha[param1]")
        assert "setup alpha" in content
        assert "setup beta" not in content
        assert meta["total_lines_deploy_log"] == len(DEPLOY_LOG.splitlines())
        assert meta["total_lines_extracted"] > 0

    @patch(f"{MODULE}.requests.get")
    def test_tail(self, mock_get):
        resp = MagicMock()
        resp.text = DEPLOY_LOG
        resp.raise_for_status.return_value = None
        mock_get.return_value = resp

        content, meta = _fetch_and_extract_test(
            "https://magna.example.com/deploy.log", "key", "test_alpha[param1]", tail=2
        )
        lines = content.strip().splitlines()
        assert len(lines) == 2

    @patch(f"{MODULE}.requests.get")
    def test_head(self, mock_get):
        resp = MagicMock()
        resp.text = DEPLOY_LOG
        resp.raise_for_status.return_value = None
        mock_get.return_value = resp

        content, meta = _fetch_and_extract_test(
            "https://magna.example.com/deploy.log", "key", "test_alpha[param1]", head=2
        )
        lines = content.strip().splitlines()
        assert len(lines) == 2

    def test_head_and_tail_error(self):
        with pytest.raises(ValueError, match="Cannot specify both"):
            _fetch_and_extract_test("url", "key", "test", head=10, tail=10)

    @patch(f"{MODULE}.requests.get")
    def test_max_size_truncation(self, mock_get):
        big_log = (
            "[T] tests/test.py::test_big \n"
            "[T] \x1b[1m--- live log setup ---\x1b[0m\n" + "\n".join(f"[T] line {i}" for i in range(100000)) + "\n"
        )
        resp = MagicMock()
        resp.text = big_log
        resp.raise_for_status.return_value = None
        mock_get.return_value = resp

        content, meta = _fetch_and_extract_test("https://magna.example.com/deploy.log", "key", "test_big")
        assert meta["truncated"]
        assert len(content.encode("utf-8")) <= 200 * 1024 + 100

    @patch(f"{MODULE}.requests.get")
    def test_test_not_found(self, mock_get):
        resp = MagicMock()
        resp.text = DEPLOY_LOG
        resp.raise_for_status.return_value = None
        mock_get.return_value = resp

        with pytest.raises(ValueError, match="not found"):
            _fetch_and_extract_test("https://magna.example.com/deploy.log", "key", "test_nonexistent")


LAUNCH_JSON = {
    "content": [{"description": "Build #42\nLogs URL: https://magna.example.com/openshift-clusters/test-cluster/"}]
}
ITEM_JSON = {"name": "test_my_feature[param1]"}


class TestGetOcsCiTestLog:
    @patch(f"{MODULE}._find_deploy_log_url")
    @patch(f"{RP_MODULE}._fetch_json")
    @patch(f"{MODULE}._fetch_and_extract_test")
    def test_success(self, mock_extract, mock_json, mock_find, env_config):
        mock_json.side_effect = [LAUNCH_JSON, ITEM_JSON]
        mock_find.return_value = ("https://magna.example.com/logs/deploy.log", "deploy.log")
        mock_extract.return_value = (
            "log content\n",
            {
                "total_lines_deploy_log": 50000,
                "total_lines_extracted": 100,
                "lines_returned": 100,
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
        assert result["deploy_log"] == "deploy.log"
        assert result["content"] == "log content\n"
        assert "exclude_debug" not in result
        assert "ocs_ci_dir" not in result

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

    @patch(f"{MODULE}._find_deploy_log_url")
    @patch(f"{RP_MODULE}._fetch_json")
    def test_no_deploy_log(self, mock_json, mock_find, env_config):
        mock_json.side_effect = [LAUNCH_JSON, ITEM_JSON]
        mock_find.side_effect = ValueError("No deploy log file found")

        result = json.loads(
            get_ocs_ci_test_log(
                "https://rp.example.com/ui/#ocs/launches/all/12345/item/67890/log",
                "test_foo",
            )
        )
        assert "error" in result
        assert "No deploy log" in result["error"]

    @patch(f"{MODULE}._find_deploy_log_url")
    @patch(f"{RP_MODULE}._fetch_json")
    @patch(f"{MODULE}._fetch_and_extract_test")
    def test_head_tail_conflict(self, mock_extract, mock_json, mock_find, env_config):
        mock_json.side_effect = [LAUNCH_JSON, ITEM_JSON]
        mock_find.return_value = ("https://magna.example.com/logs/deploy.log", "deploy.log")
        mock_extract.side_effect = ValueError("Cannot specify both head and tail")

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
