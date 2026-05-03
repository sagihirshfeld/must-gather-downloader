from unittest.mock import patch

import pytest
import requests

from must_gather_downloader.download import _download_tarball
from must_gather_downloader.reportportal import (
    _fetch_html_lines,
    _fetch_json,
    _rp_headers,
)

RP_MODULE = "must_gather_downloader.reportportal"
DL_MODULE = "must_gather_downloader.download"


class TestRpHeaders:
    def test_structure(self):
        headers = _rp_headers("my-key")
        assert headers["Accept"] == "application/json"
        assert headers["Authorization"] == "Bearer my-key"


class TestFetchJson:
    @patch(f"{RP_MODULE}.requests.get")
    def test_success(self, mock_get, make_mock_response):
        expected = {"content": [{"id": 1}]}
        mock_get.return_value = make_mock_response(json_data=expected)
        result = _fetch_json("https://rp.example.com/api/v1/ocs/launch", "key")
        assert result == expected
        mock_get.assert_called_once()
        call_kwargs = mock_get.call_args
        assert call_kwargs.kwargs["timeout"] == 30

    @patch(f"{RP_MODULE}.requests.get")
    def test_http_error(self, mock_get, make_mock_response):
        mock_get.return_value = make_mock_response(status_code=404)
        with pytest.raises(requests.HTTPError):
            _fetch_json("https://rp.example.com/api/v1/ocs/launch", "key")

    @patch(f"{RP_MODULE}.requests.get")
    def test_timeout(self, mock_get):
        mock_get.side_effect = requests.Timeout("timed out")
        with pytest.raises(requests.Timeout):
            _fetch_json("https://rp.example.com/api/v1/ocs/launch", "key")


class TestFetchHtmlLines:
    @patch(f"{RP_MODULE}.requests.get")
    def test_with_api_key(self, mock_get, make_mock_response):
        mock_get.return_value = make_mock_response(text="line1\nline2\n")
        result = _fetch_html_lines("https://magna.example.com/dir/", "my-key")
        assert result == ["line1", "line2"]
        call_headers = mock_get.call_args.kwargs.get("headers", mock_get.call_args[1].get("headers", {}))
        assert "Authorization" in call_headers

    @patch(f"{RP_MODULE}.requests.get")
    def test_without_api_key(self, mock_get, make_mock_response):
        mock_get.return_value = make_mock_response(text="line1\n")
        _fetch_html_lines("https://magna.example.com/dir/")
        call_headers = mock_get.call_args.kwargs.get("headers", mock_get.call_args[1].get("headers", {}))
        assert "Authorization" not in call_headers

    @patch(f"{RP_MODULE}.requests.get")
    def test_filters_blank_lines(self, mock_get, make_mock_response):
        mock_get.return_value = make_mock_response(text="line1\n\n  \nline2\n")
        result = _fetch_html_lines("https://magna.example.com/dir/")
        assert result == ["line1", "line2"]


class TestDownloadTarball:
    @patch(f"{DL_MODULE}.requests.get")
    def test_writes_content(self, mock_get, tmp_path, make_mock_response):
        resp = make_mock_response()
        resp.iter_content.return_value = iter([b"chunk1", b"chunk2"])
        mock_get.return_value = resp
        dest = tmp_path / "out.tar.gz"
        _download_tarball("https://magna.example.com/file.tar.gz", dest)
        assert dest.read_bytes() == b"chunk1chunk2"

    @patch(f"{DL_MODULE}.requests.get")
    def test_with_api_key(self, mock_get, tmp_path, make_mock_response):
        mock_get.return_value = make_mock_response()
        dest = tmp_path / "out.tar.gz"
        _download_tarball("https://magna.example.com/file.tar.gz", dest, "my-key")
        call_headers = mock_get.call_args.kwargs.get("headers", mock_get.call_args[1].get("headers", {}))
        assert call_headers.get("Authorization") == "Bearer my-key"

    @patch(f"{DL_MODULE}.requests.get")
    def test_http_error(self, mock_get, tmp_path, make_mock_response):
        mock_get.return_value = make_mock_response(status_code=500)
        dest = tmp_path / "out.tar.gz"
        with pytest.raises(requests.HTTPError):
            _download_tarball("https://magna.example.com/file.tar.gz", dest)
