"""AI analysis report retrieval from Magna."""

import json
import re
from html import unescape
from html.parser import HTMLParser

import requests

from .config import _get_config, _ssl_verify
from .reportportal import (
    _extract_hrefs,
    _extract_ids,
    _fetch_html_lines,
    _resolve_magna_metadata,
)

_AI_REPORT_PREFIX = "ai_analysis_report_"

_DT_KEY_MAP = {
    "file": "file",
    "function": "function",
    "description": "description",
    "code": "code",
    "diff": "diff",
    "fixed on master": "fixed_on_master",
    "platform": "platform",
    "ocp deployment": "ocp_deployment",
    "odf deployment": "odf_deployment",
    "versions": "versions",
    "impacts work": "impacts_work",
    "workaround": "workaround",
    "reproducible": "reproducible",
    "reproducible (ui)": "reproducible_ui",
    "regression": "regression",
    "steps to reproduce": "steps_to_reproduce",
    "actual results": "actual_results",
    "expected results": "expected_results",
    "additional info": "additional_info",
}


def _find_report_url(logs_url_root: str, api_key: str) -> tuple[str, str]:
    """Find the AI analysis report HTML file from the Magna logs directory.

    Args:
        logs_url_root: Magna logs root URL.
        api_key: Bearer token for Magna.

    Returns:
        Tuple of (report_url, filename).

    Raises:
        ValueError: If no report file is found.
    """
    logs_page = f"{logs_url_root.rstrip('/')}/"
    lines = _fetch_html_lines(logs_page, api_key)
    hrefs = _extract_hrefs(lines)

    candidates = [h for h in hrefs if h.startswith(_AI_REPORT_PREFIX) and h.endswith(".html")]

    if not candidates:
        available = [h for h in hrefs if h.endswith(".html")]
        raise ValueError(
            f"No AI analysis report (starting with '{_AI_REPORT_PREFIX}') found. Available .html files: {available}"
        )

    filename = candidates[0]
    return f"{logs_page}{filename}", filename


def _split_cards(html: str) -> list[str]:
    """Split full HTML into individual failure card chunks."""
    pattern = re.compile(r'<div\s+class="failure-card"\s+id="failure-\d+">')
    starts = [m.start() for m in pattern.finditer(html)]
    if not starts:
        return []
    chunks = []
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(html)
        chunks.append(html[start:end])
    return chunks


def _get_class(attrs: list[tuple[str, str | None]]) -> str:
    """Extract the CSS class from tag attributes."""
    for name, value in attrs:
        if name == "class" and value:
            return value
    return ""


def _get_attr(attrs: list[tuple[str, str | None]], key: str) -> str:
    """Extract a specific attribute value."""
    for name, value in attrs:
        if name == key and value is not None:
            return value
    return ""


class _FailureCardParser(HTMLParser):
    """Parse a single failure card HTML chunk into a structured dict.

    Uses a stack-based approach to track div nesting depth for content
    areas that contain nested divs (traceback-content, root-cause, etc.).
    """

    def __init__(self):
        super().__init__()
        self.result: dict = {}

        self._buf: list[str] = []
        self._evidence: list[str] = []
        self._jira_issues: list[str] = []

        self._in_evidence_li = False
        self._in_jira_li = False
        self._in_evidence_ul = False
        self._in_jira_ul = False
        self._in_pre = False
        self._in_confidence = False

        # Tracked div regions: when we enter a div we care about,
        # push its type onto the stack. Nested divs push None.
        # On </div>, pop. When the typed entry pops, we know we left it.
        self._div_stack: list[str | None] = []

        self._next_content_type: str | None = None
        self._extras_title: str | None = None
        self._dl_data: dict[str, str] = {}
        self._current_dt: str | None = None
        self._in_dt = False
        self._in_dd = False
        self._dd_buf: list[str] = []

    def _in_div(self, div_type: str) -> bool:
        return div_type in self._div_stack

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]):
        cls = _get_class(attrs)

        if tag == "div":
            div_type = None
            if "failure-name" in cls:
                title = _get_attr(attrs, "title")
                if title:
                    self.result["test_name"] = unescape(title)
            elif cls == "root-cause":
                div_type = "root_cause"
                self._buf = []
            elif cls == "action-box":
                div_type = "action"
                self._buf = []
            elif cls == "traceback-content":
                if self._next_content_type == "traceback":
                    div_type = "traceback"
                elif self._next_content_type in ("suggested_fix", "bug_details"):
                    div_type = "extras"
                    self._extras_title = None
                    self._dl_data = {}
                self._next_content_type = None
            self._div_stack.append(div_type)
            return

        if tag == "span":
            if "badge" in cls and "badge-" in cls:
                for c in cls.split():
                    if c.startswith("badge-") and c != "badge":
                        self.result["category"] = c.replace("badge-", "")
            elif cls == "confidence":
                self._in_confidence = True
                self._buf = []
            return

        if tag == "ul":
            if cls == "evidence-list":
                self._in_evidence_ul = True
            elif cls == "jira-list":
                self._in_jira_ul = True
            return

        if tag == "li":
            if self._in_evidence_ul:
                self._in_evidence_li = True
                self._buf = []
            elif self._in_jira_ul:
                self._in_jira_li = True
                self._buf = []
            return

        if tag == "button" and "traceback-toggle" in cls:
            self._buf = []
            self._div_stack.append("button_text")
            return

        if tag == "pre":
            if self._in_div("traceback") or self._in_div("extras"):
                self._in_pre = True
                self._buf = []
            return

        if tag == "dl" and self._in_div("extras"):
            self._dl_data = {}
            return

        if tag == "dt" and self._in_div("extras"):
            self._in_dt = True
            self._buf = []
            return

        if tag == "dd" and self._in_div("extras"):
            self._in_dd = True
            self._dd_buf = []
            return

    def handle_endtag(self, tag: str):
        if tag == "div":
            if not self._div_stack:
                return
            div_type = self._div_stack.pop()
            if div_type == "root_cause":
                self.result["root_cause"] = unescape("".join(self._buf).strip())
            elif div_type == "action":
                self.result["recommended_action"] = unescape("".join(self._buf).strip())
            elif div_type == "traceback":
                pass
            elif div_type == "extras":
                if self._extras_title:
                    self._dl_data["title"] = unescape(self._extras_title)
                if "file" in self._dl_data or "function" in self._dl_data:
                    self.result["suggested_fix"] = dict(self._dl_data)
                elif self._dl_data:
                    self.result["bug_details"] = dict(self._dl_data)
            return

        if tag == "span" and self._in_confidence:
            self.result["confidence"] = "".join(self._buf).strip()
            self._in_confidence = False
            return

        if tag == "ul":
            if self._in_evidence_ul:
                self._in_evidence_ul = False
            elif self._in_jira_ul:
                self._in_jira_ul = False
            return

        if tag == "li":
            if self._in_evidence_li:
                self._in_evidence_li = False
                text = unescape("".join(self._buf).strip())
                if text:
                    self._evidence.append(text)
            elif self._in_jira_li:
                self._in_jira_li = False
                text = unescape("".join(self._buf).strip())
                if text:
                    self._jira_issues.append(text)
            return

        if tag == "button" and self._div_stack and self._div_stack[-1] == "button_text":
            self._div_stack.pop()
            btn_text = "".join(self._buf).strip().lower()
            if "traceback" in btn_text:
                self._next_content_type = "traceback"
            elif "suggested fix" in btn_text:
                self._next_content_type = "suggested_fix"
            elif "bug details" in btn_text:
                self._next_content_type = "bug_details"
            return

        if tag == "pre" and self._in_pre:
            text = unescape("".join(self._buf))
            if self._in_div("traceback"):
                self.result["traceback"] = text
            elif self._in_dd:
                self._dd_buf.append(text)
            self._in_pre = False
            return

        if tag == "dt" and self._in_dt:
            self._in_dt = False
            self._current_dt = "".join(self._buf).strip()
            return

        if tag == "dd" and self._in_dd:
            self._in_dd = False
            if self._current_dt is not None:
                key = _DT_KEY_MAP.get(self._current_dt.lower(), self._current_dt.lower().replace(" ", "_"))
                value = unescape("".join(self._dd_buf).strip())
                self._dl_data[key] = value
            self._current_dt = None
            self._dd_buf = []
            return

    def handle_data(self, data: str):
        if self._in_pre:
            self._buf.append(data)
            return

        if self._in_dd:
            self._dd_buf.append(data)
            return

        if self._in_dt:
            self._buf.append(data)
            return

        if self._in_evidence_li or self._in_jira_li:
            self._buf.append(data)
            return

        if self._in_confidence:
            self._buf.append(data)
            return

        if self._div_stack and self._div_stack[-1] == "button_text":
            self._buf.append(data)
            return

        if self._in_div("root_cause") or self._in_div("action"):
            self._buf.append(data)
            return

        if self._in_div("extras") and not self._in_dt and not self._in_dd:
            stripped = data.strip()
            if stripped and self._extras_title is None and not self._dl_data:
                self._extras_title = stripped

    def _handle_char(self, text: str):
        if self._in_pre:
            self._buf.append(text)
        elif self._in_dd:
            self._dd_buf.append(text)
        elif self._in_dt:
            self._buf.append(text)
        elif self._in_evidence_li or self._in_jira_li:
            self._buf.append(text)
        elif self._in_div("root_cause") or self._in_div("action"):
            self._buf.append(text)

    def handle_entityref(self, name: str):
        self._handle_char(unescape(f"&{name};"))

    def handle_charref(self, name: str):
        self._handle_char(unescape(f"&#{name};"))

    def get_result(self) -> dict:
        result = dict(self.result)
        if self._evidence:
            result["evidence"] = list(self._evidence)
        if self._jira_issues:
            result["linked_jira_issues"] = list(self._jira_issues)
        return result


def _parse_failure_cards(html_content: str) -> list[dict]:
    """Parse all failure cards from the AI analysis report HTML.

    Args:
        html_content: Full HTML content of the report.

    Returns:
        List of dicts, one per failure card.
    """
    chunks = _split_cards(html_content)
    cards = []
    for chunk in chunks:
        parser = _FailureCardParser()
        parser.feed(chunk)
        result = parser.get_result()
        if result.get("test_name"):
            cards.append(result)
    return cards


def _match_test_failures(cards: list[dict], test_name: str) -> list[dict]:
    """Filter parsed cards by test name using substring matching.

    Args:
        cards: All parsed failure cards.
        test_name: Test name to match (substring).

    Returns:
        Matching failure cards.

    Raises:
        ValueError: If no matches found.
    """
    matches = [c for c in cards if test_name in c.get("test_name", "")]
    if not matches:
        available = [c.get("test_name", "?") for c in cards]
        raise ValueError(f"Test '{test_name}' not found in the AI analysis report. Available tests: {available}")
    return matches


def _fetch_and_parse_report(
    report_url: str,
    api_key: str,
    test_name: str,
    include_traceback: bool = True,
    include_suggested_fix: bool = True,
) -> list[dict]:
    """Download the AI analysis report and extract matching test failures.

    Args:
        report_url: URL to the HTML report.
        api_key: Bearer token for Magna.
        test_name: Test name to match (substring).
        include_traceback: Include traceback in results.
        include_suggested_fix: Include suggested fix / bug details in results.

    Returns:
        List of matching failure dicts.
    """
    headers = {"Accept": "text/html"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    resp = requests.get(report_url, headers=headers, timeout=120, verify=_ssl_verify())
    resp.raise_for_status()

    cards = _parse_failure_cards(resp.text)
    matches = _match_test_failures(cards, test_name)

    for m in matches:
        if not include_traceback:
            m.pop("traceback", None)
        if not include_suggested_fix:
            m.pop("suggested_fix", None)
            m.pop("bug_details", None)

    return matches


def get_ai_analysis_report(
    reportportal_url: str,
    test_name: str,
    include_traceback: bool = True,
    include_suggested_fix: bool = True,
) -> str:
    """Retrieve AI failure analysis for a test from the AI analysis report.

    Given a ReportPortal URL and test name, resolves the Magna logs
    directory, finds the AI analysis report HTML, downloads it, and
    extracts the failure analysis section(s) for the requested test.

    Args:
        reportportal_url: Full ReportPortal URL to a test log page
            (must contain '/launches/' and '/log').
        test_name: Test function name, e.g.
            ``'test_bucket_notifications[default-logs-pvc]'``.
            Matched as a substring against failure card titles.
        include_traceback: Include the traceback (default True).
        include_suggested_fix: Include the suggested fix or bug details
            (default True).

    Returns:
        JSON string with failure analysis data.
    """
    try:
        api_key, base_url, _cache_dir = _get_config()
        launch_id, test_item_id = _extract_ids(reportportal_url)

        meta = _resolve_magna_metadata(launch_id, test_item_id, api_key, base_url)

        report_url, _filename = _find_report_url(meta["logs_url_root"], api_key)

        matches = _fetch_and_parse_report(
            report_url,
            api_key,
            test_name,
            include_traceback,
            include_suggested_fix,
        )

        return json.dumps(
            {
                "test_name": test_name,
                "report_url": report_url,
                "matches_count": len(matches),
                "failures": matches,
            }
        )
    except (ValueError, requests.HTTPError) as e:
        return json.dumps({"error": str(e)})
