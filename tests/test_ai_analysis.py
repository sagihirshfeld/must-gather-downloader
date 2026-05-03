import json
from unittest.mock import MagicMock, patch

import pytest
import requests
from must_gather_downloader.ai_analysis import (
    _fetch_and_parse_report,
    _find_report_url,
    _match_test_failures,
    _parse_failure_cards,
    _split_cards,
    get_ai_analysis_report,
)

MODULE = "must_gather_downloader.ai_analysis"
RP_MODULE = "must_gather_downloader.reportportal"

LOGS_PAGE_HTML = [
    '<tr><td><a href="ai_analysis_report_upgrade_123.html">ai_analysis_report_upgrade_123.html</a></td>'
    '<td align="right">2026-04-30 21:50</td><td align="right">687K</td></tr>',
    '<tr><td><a href="deploy-ocs-cluster-build-12345.log">deploy-ocs-cluster-build-12345.log</a></td>'
    '<td align="right">2026-04-30 19:59</td><td align="right">8.7M</td></tr>',
    '<tr><td><a href="ai_analysis_upgrade_123.log">ai_analysis_upgrade_123.log</a></td>'
    '<td align="right">2026-04-30 21:50</td><td align="right">74K</td></tr>',
]

# Minimal but realistic HTML with three failure cards covering all features:
# - Card 1: test_alpha — has traceback, suggested fix, no jira
# - Card 2: test_beta — has traceback, bug details, linked jira issues
# - Card 3: test_alpha[param] — same base name, no extras
REPORT_HTML = """<!DOCTYPE html>
<html><head><title>Report</title></head><body>
<div class="container">
<div class="card"><h2>Failure Analysis (3)</h2>

<div class="failure-card" id="failure-1">
  <div class="failure-header" onclick="this.parentElement.classList.toggle('open')">
    <div class="failure-num">1</div>
    <div class="failure-name" title="test_alpha">test_alpha</div>
    <span class="badge badge-test_bug">test bug</span>
    <span class="confidence">90%</span>
    <span class="chevron">&#9654;</span>
  </div>
  <div class="failure-body">
    <div class="failure-meta">
      <div class="meta-item">
        <span class="meta-label">Class</span>
        <span class="meta-value">tests.test_alpha.TestAlpha</span>
      </div>
    </div>

    <div class="section-label">Root Cause</div>
    <div class="root-cause">The test fails because it doesn&#39;t handle the edge case.</div>

    <div class="section-label">Recommended Action</div>
    <div class="action-box">Fix the test by adding a &amp; proper check.</div>

    <div class="section-label">Evidence</div>
    <ul class="evidence-list">
      <li>First evidence &mdash; details here</li>
      <li>Second evidence with &#34;quotes&#34;</li>
    </ul>

    <button class="traceback-toggle" onclick="toggle(this)">Show Traceback</button>
    <div class="traceback-content">
      <pre>self = &lt;TestAlpha object&gt;

    def test_alpha(self):
&gt;       assert False
E       AssertionError

tests/test_alpha.py:10: AssertionError</pre>
    </div>

    <button class="traceback-toggle" style="margin-left:8px" onclick="toggle(this)">Show Suggested Fix</button>
    <div class="traceback-content">
      <div style="background:#fefce8">
        <div style="font-size:15px">Suggested Fix</div>
        <dl>
          <dt>File</dt>
          <dd>tests/test_alpha.py:10</dd>
          <dt>Function</dt>
          <dd>test_alpha</dd>
          <dt>Description</dt>
          <dd>Add proper edge case handling</dd>
          <dt>Code</dt>
          <dd><pre style="background:#1e293b">        assert x == expected</pre></dd>
          <dt>Diff</dt>
          <dd><pre style="background:#1e293b"> def test_alpha(self):
+    assert x == expected
-    assert False</pre></dd>
          <dt>Fixed on master</dt>
          <dd>No</dd>
        </dl>
      </div>
    </div>
  </div>
</div>

<div class="failure-card" id="failure-2">
  <div class="failure-header" onclick="this.parentElement.classList.toggle('open')">
    <div class="failure-num">2</div>
    <div class="failure-name" title="test_beta">test_beta</div>
    <span class="badge badge-product_bug">product bug</span>
    <span class="confidence">85%</span>
    <span class="chevron">&#9654;</span>
  </div>
  <div class="failure-body">
    <div class="failure-meta">
      <div class="meta-item">
        <span class="meta-label">Status</span>
        <span class="meta-value">failed</span>
      </div>
    </div>

    <div class="section-label">Linked Jira Issues</div>
    <ul class="jira-list">
      <li><a href="https://jira.example.com/browse/BUG-123">BUG-123</a> &mdash; First bug (Open)</li>
      <li><a href="https://jira.example.com/browse/BUG-456">BUG-456</a> &mdash; Second bug (Closed)</li>
    </ul>

    <div class="section-label">Root Cause</div>
    <div class="root-cause">A product bug in the widget component.</div>

    <div class="section-label">Recommended Action</div>
    <div class="action-box">File a bug against the widget team.</div>

    <div class="section-label">Evidence</div>
    <ul class="evidence-list">
      <li>Widget crashed with error code 42</li>
    </ul>

    <button class="traceback-toggle" onclick="toggle(this)">Show Traceback</button>
    <div class="traceback-content">
      <pre>widget.error: crash code 42</pre>
    </div>

    <button class="traceback-toggle" style="margin-left:8px" onclick="toggle(this)">Show Bug Details</button>
    <div class="traceback-content">
      <div style="background:#fef2f2">
        <div style="font-size:16px">Widget crash during upgrade</div>
        <dl>
          <dt>Description</dt>
          <dd>The widget component crashes during upgrade</dd>
          <dt>Platform</dt>
          <dd>AWS</dd>
          <dt>Workaround</dt>
          <dd>Restart the widget pod</dd>
        </dl>
      </div>
    </div>
  </div>
</div>

<div class="failure-card" id="failure-3">
  <div class="failure-header" onclick="this.parentElement.classList.toggle('open')">
    <div class="failure-num">3</div>
    <div class="failure-name" title="test_alpha[param1]">test_alpha[param1]</div>
    <span class="badge badge-infra_issue">infra issue</span>
    <span class="confidence">70%</span>
    <span class="chevron">&#9654;</span>
  </div>
  <div class="failure-body">
    <div class="section-label">Root Cause</div>
    <div class="root-cause">Infrastructure timeout.</div>

    <div class="section-label">Recommended Action</div>
    <div class="action-box">Retry the test.</div>

    <div class="section-label">Evidence</div>
    <ul class="evidence-list">
      <li>Timeout after 300s</li>
    </ul>

    <button class="traceback-toggle" onclick="toggle(this)">Show Traceback</button>
    <div class="traceback-content">
      <pre>TimeoutError: 300s elapsed</pre>
    </div>
  </div>
</div>

</div>
</div>
</body></html>"""


class TestFindReportUrl:
    @patch(f"{MODULE}._fetch_html_lines")
    def test_single_report(self, mock_fetch):
        mock_fetch.return_value = LOGS_PAGE_HTML
        url, name = _find_report_url("https://magna.example.com/cluster/logs/", "key")
        assert name == "ai_analysis_report_upgrade_123.html"
        assert url.endswith("ai_analysis_report_upgrade_123.html")

    @patch(f"{MODULE}._fetch_html_lines")
    def test_multiple_reports_picks_first(self, mock_fetch):
        mock_fetch.return_value = [
            '<a href="ai_analysis_report_a.html">a</a>',
            '<a href="ai_analysis_report_b.html">b</a>',
        ]
        _, name = _find_report_url("https://magna.example.com/cluster/logs/", "key")
        assert name == "ai_analysis_report_a.html"

    @patch(f"{MODULE}._fetch_html_lines")
    def test_no_report_raises(self, mock_fetch):
        mock_fetch.return_value = [
            '<a href="other-page.html">other</a>',
        ]
        with pytest.raises(ValueError, match="No AI analysis report"):
            _find_report_url("https://magna.example.com/cluster/logs/", "key")

    @patch(f"{MODULE}._fetch_html_lines")
    def test_error_lists_available_html(self, mock_fetch):
        mock_fetch.return_value = [
            '<a href="index.html">index</a>',
        ]
        with pytest.raises(ValueError, match="index.html"):
            _find_report_url("https://magna.example.com/cluster/logs/", "key")


class TestSplitCards:
    def test_splits_multiple_cards(self):
        chunks = _split_cards(REPORT_HTML)
        assert len(chunks) == 3

    def test_empty_html(self):
        assert _split_cards("<html></html>") == []

    def test_single_card(self):
        html = '<div class="failure-card" id="failure-1"><p>content</p></div>'
        chunks = _split_cards(html)
        assert len(chunks) == 1


class TestParseFailureCards:
    def test_basic_fields(self):
        cards = _parse_failure_cards(REPORT_HTML)
        assert len(cards) == 3
        card1 = cards[0]
        assert card1["test_name"] == "test_alpha"
        assert card1["category"] == "test_bug"
        assert card1["confidence"] == "90%"

    def test_root_cause_with_entity(self):
        cards = _parse_failure_cards(REPORT_HTML)
        assert "doesn't" in cards[0]["root_cause"]

    def test_action_with_entity(self):
        cards = _parse_failure_cards(REPORT_HTML)
        assert "& proper" in cards[0]["recommended_action"]

    def test_evidence_list(self):
        cards = _parse_failure_cards(REPORT_HTML)
        evidence = cards[0]["evidence"]
        assert len(evidence) == 2
        assert "First evidence" in evidence[0]
        assert '"quotes"' in evidence[1]

    def test_evidence_mdash_entity(self):
        cards = _parse_failure_cards(REPORT_HTML)
        assert "—" in cards[0]["evidence"][0]

    def test_traceback(self):
        cards = _parse_failure_cards(REPORT_HTML)
        assert "assert False" in cards[0]["traceback"]
        assert "AssertionError" in cards[0]["traceback"]

    def test_suggested_fix(self):
        cards = _parse_failure_cards(REPORT_HTML)
        sf = cards[0]["suggested_fix"]
        assert sf["file"] == "tests/test_alpha.py:10"
        assert sf["function"] == "test_alpha"
        assert sf["description"] == "Add proper edge case handling"
        assert "assert x == expected" in sf["code"]
        assert sf["fixed_on_master"] == "No"
        assert "diff" in sf

    def test_linked_jira_issues(self):
        cards = _parse_failure_cards(REPORT_HTML)
        card2 = cards[1]
        assert "linked_jira_issues" in card2
        jira = card2["linked_jira_issues"]
        assert len(jira) == 2
        assert "BUG-123" in jira[0]
        assert "BUG-456" in jira[1]

    def test_no_jira_issues_omitted(self):
        cards = _parse_failure_cards(REPORT_HTML)
        assert "linked_jira_issues" not in cards[0]

    def test_bug_details(self):
        cards = _parse_failure_cards(REPORT_HTML)
        bd = cards[1]["bug_details"]
        assert bd["platform"] == "AWS"
        assert "widget component" in bd["description"]
        assert bd["workaround"] == "Restart the widget pod"
        assert "title" in bd

    def test_no_suggested_fix_omitted(self):
        cards = _parse_failure_cards(REPORT_HTML)
        assert "suggested_fix" not in cards[2]
        assert "bug_details" not in cards[2]

    def test_parameterized_test_name(self):
        cards = _parse_failure_cards(REPORT_HTML)
        assert cards[2]["test_name"] == "test_alpha[param1]"
        assert cards[2]["category"] == "infra_issue"
        assert cards[2]["confidence"] == "70%"

    def test_empty_html(self):
        assert _parse_failure_cards("<html></html>") == []

    def test_all_cards_have_test_name(self):
        cards = _parse_failure_cards(REPORT_HTML)
        for card in cards:
            assert "test_name" in card


class TestMatchTestFailures:
    def setup_method(self):
        self.cards = _parse_failure_cards(REPORT_HTML)

    def test_exact_match(self):
        matches = _match_test_failures(self.cards, "test_beta")
        assert len(matches) == 1
        assert matches[0]["test_name"] == "test_beta"

    def test_substring_match(self):
        matches = _match_test_failures(self.cards, "test_alpha")
        assert len(matches) == 2
        names = {m["test_name"] for m in matches}
        assert names == {"test_alpha", "test_alpha[param1]"}

    def test_parameterized_exact(self):
        matches = _match_test_failures(self.cards, "test_alpha[param1]")
        assert len(matches) == 1
        assert matches[0]["test_name"] == "test_alpha[param1]"

    def test_not_found_raises(self):
        with pytest.raises(ValueError, match="not found"):
            _match_test_failures(self.cards, "test_nonexistent")

    def test_not_found_lists_available(self):
        with pytest.raises(ValueError, match="test_alpha"):
            _match_test_failures(self.cards, "test_nonexistent")


class TestFetchAndParseReport:
    @patch(f"{MODULE}.requests.get")
    def test_basic(self, mock_get):
        resp = MagicMock()
        resp.text = REPORT_HTML
        resp.raise_for_status.return_value = None
        mock_get.return_value = resp

        results = _fetch_and_parse_report("https://magna.example.com/report.html", "key", "test_beta")
        assert len(results) == 1
        assert results[0]["test_name"] == "test_beta"
        assert "traceback" in results[0]
        assert "bug_details" in results[0]

    @patch(f"{MODULE}.requests.get")
    def test_exclude_traceback(self, mock_get):
        resp = MagicMock()
        resp.text = REPORT_HTML
        resp.raise_for_status.return_value = None
        mock_get.return_value = resp

        results = _fetch_and_parse_report(
            "https://magna.example.com/report.html", "key", "test_alpha[param1]", include_traceback=False
        )
        assert "traceback" not in results[0]

    @patch(f"{MODULE}.requests.get")
    def test_exclude_suggested_fix(self, mock_get):
        resp = MagicMock()
        resp.text = REPORT_HTML
        resp.raise_for_status.return_value = None
        mock_get.return_value = resp

        results = _fetch_and_parse_report(
            "https://magna.example.com/report.html", "key", "test_alpha", include_suggested_fix=False
        )
        card1 = [r for r in results if r["test_name"] == "test_alpha"][0]
        assert "suggested_fix" not in card1

    @patch(f"{MODULE}.requests.get")
    def test_exclude_bug_details(self, mock_get):
        resp = MagicMock()
        resp.text = REPORT_HTML
        resp.raise_for_status.return_value = None
        mock_get.return_value = resp

        results = _fetch_and_parse_report(
            "https://magna.example.com/report.html", "key", "test_beta", include_suggested_fix=False
        )
        assert "bug_details" not in results[0]


LAUNCH_JSON = {
    "content": [{"description": "Build #42\nLogs URL: https://magna.example.com/openshift-clusters/test-cluster/logs/"}]
}
ITEM_JSON = {"name": "test_alpha"}


class TestGetAiAnalysisReport:
    @patch(f"{MODULE}._find_report_url")
    @patch(f"{RP_MODULE}._fetch_json")
    @patch(f"{MODULE}._fetch_and_parse_report")
    def test_success(self, mock_parse, mock_json, mock_find, env_config):
        mock_json.side_effect = [LAUNCH_JSON, ITEM_JSON]
        mock_find.return_value = ("https://magna.example.com/report.html", "report.html")
        mock_parse.return_value = [
            {
                "test_name": "test_alpha",
                "category": "test_bug",
                "confidence": "90%",
                "root_cause": "Test issue",
                "recommended_action": "Fix it",
                "evidence": ["evidence 1"],
            }
        ]

        result = json.loads(
            get_ai_analysis_report(
                "https://rp.example.com/ui/#ocs/launches/all/12345/item/67890/log",
                "test_alpha",
            )
        )
        assert result["test_name"] == "test_alpha"
        assert result["report_url"] == "https://magna.example.com/report.html"
        assert result["matches_count"] == 1
        assert len(result["failures"]) == 1
        assert result["failures"][0]["category"] == "test_bug"

    @patch(f"{RP_MODULE}._fetch_json")
    def test_rp_error(self, mock_json, env_config):
        mock_json.side_effect = requests.HTTPError("500 Server Error")

        result = json.loads(
            get_ai_analysis_report(
                "https://rp.example.com/ui/#ocs/launches/all/12345/item/67890/log",
                "test_foo",
            )
        )
        assert "error" in result

    def test_invalid_url(self, env_config):
        result = json.loads(get_ai_analysis_report("https://not-a-valid-url.com", "test_foo"))
        assert "error" in result

    @patch(f"{MODULE}._find_report_url")
    @patch(f"{RP_MODULE}._fetch_json")
    def test_no_report_file(self, mock_json, mock_find, env_config):
        mock_json.side_effect = [LAUNCH_JSON, ITEM_JSON]
        mock_find.side_effect = ValueError("No AI analysis report found")

        result = json.loads(
            get_ai_analysis_report(
                "https://rp.example.com/ui/#ocs/launches/all/12345/item/67890/log",
                "test_foo",
            )
        )
        assert "error" in result
        assert "No AI analysis report" in result["error"]

    def test_config_error(self, monkeypatch):
        monkeypatch.delenv("RP_API_KEY", raising=False)
        monkeypatch.delenv("RP_BASE_URL", raising=False)

        result = json.loads(
            get_ai_analysis_report(
                "https://rp.example.com/ui/#ocs/launches/all/12345/item/67890/log",
                "test_foo",
            )
        )
        assert "error" in result

    @patch(f"{MODULE}._find_report_url")
    @patch(f"{RP_MODULE}._fetch_json")
    @patch(f"{MODULE}._fetch_and_parse_report")
    def test_test_not_found(self, mock_parse, mock_json, mock_find, env_config):
        mock_json.side_effect = [LAUNCH_JSON, ITEM_JSON]
        mock_find.return_value = ("https://magna.example.com/report.html", "report.html")
        mock_parse.side_effect = ValueError("Test 'test_foo' not found")

        result = json.loads(
            get_ai_analysis_report(
                "https://rp.example.com/ui/#ocs/launches/all/12345/item/67890/log",
                "test_foo",
            )
        )
        assert "error" in result
        assert "not found" in result["error"]
