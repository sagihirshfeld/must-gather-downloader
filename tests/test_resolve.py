from unittest.mock import patch

import pytest

from must_gather_downloader.download import _find_tarball_url, _resolve_test_log_directory

MODULE = "must_gather_downloader.download"

LAUNCH_JSON = {
    "content": [{"description": ("Build #42\nLogs URL: https://magna.example.com/openshift-clusters/test-cluster-1/")}]
}
ITEM_JSON = {"name": "test_my_feature"}

ROOT_DIR_HTML_LINES = [
    '<a href="failed_testcase_0/">failed_testcase_0/</a>',
    '<a href="failed_testcase_1/">failed_testcase_1/</a>',
]
MATCH_HTML_LINES = ['<a href="test_my_feature_ocs_logs/">test_my_feature_ocs_logs/</a>']
NO_MATCH_HTML_LINES = ['<a href="other_test_ocs_logs/">other_test_ocs_logs/</a>']


class TestResolveTestLogDirectory:
    @patch(f"{MODULE}._fetch_html_lines")
    @patch(f"{MODULE}._fetch_json")
    def test_success(self, mock_fetch_json, mock_fetch_html):
        mock_fetch_json.side_effect = [LAUNCH_JSON, ITEM_JSON]
        mock_fetch_html.side_effect = [ROOT_DIR_HTML_LINES, MATCH_HTML_LINES]

        result = _resolve_test_log_directory("12345", "67890", "key", "https://rp.example.com")
        assert result["cluster_name"] == "test-cluster-1"
        assert result["test_name"] == "test_my_feature"
        assert result["launch_id"] == "12345"
        assert result["test_item_id"] == "67890"
        assert "target_suffix" in result
        assert "safe_test_name" in result

    @patch(f"{MODULE}._fetch_html_lines")
    @patch(f"{MODULE}._fetch_json")
    def test_no_failed_testcase_dirs(self, mock_fetch_json, mock_fetch_html):
        mock_fetch_json.side_effect = [LAUNCH_JSON, ITEM_JSON]
        mock_fetch_html.return_value = ['<a href="some_other_dir/">other</a>']

        with pytest.raises(ValueError, match="No failed_testcase"):
            _resolve_test_log_directory("12345", "67890", "key", "https://rp.example.com")

    @patch(f"{MODULE}._fetch_html_lines")
    @patch(f"{MODULE}._fetch_json")
    def test_test_not_found_in_any_dir(self, mock_fetch_json, mock_fetch_html):
        mock_fetch_json.side_effect = [LAUNCH_JSON, ITEM_JSON]
        mock_fetch_html.side_effect = [ROOT_DIR_HTML_LINES, NO_MATCH_HTML_LINES, NO_MATCH_HTML_LINES]

        with pytest.raises(ValueError, match="not found in any"):
            _resolve_test_log_directory("12345", "67890", "key", "https://rp.example.com")

    @patch(f"{MODULE}._fetch_html_lines")
    @patch(f"{MODULE}._fetch_json")
    def test_bad_description_format(self, mock_fetch_json, mock_fetch_html):
        bad_launch = {"content": [{"description": "No logs URL here"}]}
        mock_fetch_json.side_effect = [bad_launch, ITEM_JSON]

        with pytest.raises(ValueError, match="Could not extract"):
            _resolve_test_log_directory("12345", "67890", "key", "https://rp.example.com")

    @patch(f"{MODULE}._fetch_html_lines")
    @patch(f"{MODULE}._fetch_json")
    def test_searches_multiple_dirs(self, mock_fetch_json, mock_fetch_html):
        mock_fetch_json.side_effect = [LAUNCH_JSON, ITEM_JSON]
        mock_fetch_html.side_effect = [
            ROOT_DIR_HTML_LINES,
            NO_MATCH_HTML_LINES,
            MATCH_HTML_LINES,
        ]

        result = _resolve_test_log_directory("12345", "67890", "key", "https://rp.example.com")
        assert result["test_name"] == "test_my_feature"


class TestFindTarballUrl:
    @patch(f"{MODULE}._fetch_html_lines")
    def test_prefers_must_gather(self, mock_fetch_html, sample_info_dict):
        mock_fetch_html.return_value = [
            '<a href="other-logs.tar.gz">other</a>',
            '<a href="must-gather-abc.tar.gz">must-gather</a>',
        ]
        result = _find_tarball_url(sample_info_dict, "key")
        assert result.endswith("must-gather-abc.tar.gz")

    @patch(f"{MODULE}._fetch_html_lines")
    def test_falls_back_to_first(self, mock_fetch_html, sample_info_dict):
        mock_fetch_html.return_value = [
            '<a href="logs-archive.tar.gz">logs</a>',
            '<a href="other-archive.tgz">other</a>',
        ]
        result = _find_tarball_url(sample_info_dict, "key")
        assert result.endswith("logs-archive.tar.gz")

    @patch(f"{MODULE}._fetch_html_lines")
    def test_no_tarballs(self, mock_fetch_html, sample_info_dict):
        mock_fetch_html.return_value = [
            '<a href="readme.txt">readme</a>',
        ]
        with pytest.raises(ValueError, match="No must-gather tarball"):
            _find_tarball_url(sample_info_dict, "key")

    @patch(f"{MODULE}._fetch_html_lines")
    def test_url_construction(self, mock_fetch_html, sample_info_dict):
        mock_fetch_html.return_value = [
            '<a href="must-gather.tar.gz">mg</a>',
        ]
        result = _find_tarball_url(sample_info_dict, "key")
        assert "//" not in result.split("://")[1]
        assert result.endswith("must-gather.tar.gz")
        assert "test-cluster-1" in result
