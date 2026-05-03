import pytest
from must_gather_downloader.reportportal import _extract_hrefs, _extract_ids, _safe_test_name


class TestExtractIds:
    def test_valid_url(self, sample_rp_url):
        launch_id, test_item_id = _extract_ids(sample_rp_url)
        assert launch_id == "12345"
        assert test_item_id == "67890"

    def test_missing_launches(self):
        with pytest.raises(ValueError, match="Invalid ReportPortal URL"):
            _extract_ids("https://rp.example.com/ui/#ocs/dashboard")

    def test_missing_log(self):
        with pytest.raises(ValueError, match="Invalid ReportPortal URL"):
            _extract_ids("https://rp.example.com/ui/#ocs/launches/all/12345/item/67890")

    def test_truncated_path(self):
        with pytest.raises(ValueError, match="Could not extract launch ID"):
            _extract_ids("https://rp.example.com/ui/#ocs/launches/all/log")

    def test_url_with_query_params(self):
        url = "https://rp.example.com/ui/#ocs/launches/all/12345/item/67890/log?page=1"
        launch_id, test_item_id = _extract_ids(url)
        assert launch_id == "12345"
        assert test_item_id == "67890"


class TestExtractHrefs:
    def test_basic(self):
        lines = [
            '<a href="dir1/">dir1</a>',
            '<a href="dir2/">dir2</a>',
        ]
        assert _extract_hrefs(lines) == ["dir1/", "dir2/"]

    def test_no_matches(self):
        lines = ["<p>no links</p>", "plain text"]
        assert _extract_hrefs(lines) == []

    def test_mixed(self):
        lines = [
            '<a href="link1/">link1</a>',
            "<p>no link here</p>",
            '<a href="link2.tar.gz">link2</a>',
        ]
        assert _extract_hrefs(lines) == ["link1/", "link2.tar.gz"]


class TestSafeTestName:
    def test_simple(self):
        result = _safe_test_name("test_my_feature")
        assert result == "test_my_feature_ocs_logs"

    def test_special_chars(self):
        result = _safe_test_name("test with spaces")
        assert "_ocs_logs" in result
        assert "test%20with%20spaces" in result
