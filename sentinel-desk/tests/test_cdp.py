from __future__ import annotations

import base64
import unittest
from unittest.mock import patch

from sentineldesk.cdp import (
    CDPError,
    CDPPage,
    capture_screenshot,
    devtools_endpoint,
    parse_cdp_selector,
    parse_cdp_url,
    pick_page,
    screenshot_bytes_from_result,
)


class CdpTests(unittest.TestCase):
    def test_parse_cdp_url_defaults(self) -> None:
        address, port, match_url = parse_cdp_url("cdp://127.0.0.1")
        self.assertEqual(address, "127.0.0.1")
        self.assertEqual(port, 9222)
        self.assertIsNone(match_url)

    def test_parse_cdp_url_with_match_url(self) -> None:
        address, port, match_url = parse_cdp_url("cdp://localhost:9333/current?url=https%3A%2F%2Fexample.com%2Fcase")
        self.assertEqual(address, "localhost")
        self.assertEqual(port, 9333)
        self.assertEqual(match_url, "https://example.com/case")

    def test_parse_cdp_selector_with_title_and_id(self) -> None:
        address, port, selector = parse_cdp_selector("cdp://localhost:9333/current?title=Case%20Portal&id=target-1")
        self.assertEqual(address, "localhost")
        self.assertEqual(port, 9333)
        self.assertEqual(selector.title, "Case Portal")
        self.assertEqual(selector.page_id, "target-1")

    def test_devtools_endpoint(self) -> None:
        self.assertEqual(devtools_endpoint("127.0.0.1", 9222, "/json/list"), "http://127.0.0.1:9222/json/list")

    def test_pick_page_without_selector_allows_single_page(self) -> None:
        page = CDPPage(id="1", title="Case", url="https://example.com/case/123", websocket_url="ws://127.0.0.1/devtools/page/1")
        self.assertEqual(pick_page([page]), page)

    def test_pick_page_without_selector_rejects_multiple_pages(self) -> None:
        pages = [
            CDPPage(id="1", title="Inbox", url="https://mail.example.com", websocket_url="ws://127.0.0.1/devtools/page/1"),
            CDPPage(id="2", title="Case", url="https://example.com/case", websocket_url="ws://127.0.0.1/devtools/page/2"),
        ]
        with self.assertRaisesRegex(CDPError, "Multiple Chrome pages"):
            pick_page(pages)

    def test_pick_page_by_url(self) -> None:
        page = CDPPage(id="1", title="Case", url="https://example.com/case/123", websocket_url="ws://127.0.0.1/devtools/page/1")
        self.assertEqual(pick_page([page], "case/123"), page)

    def test_pick_page_exact_url_beats_partial_url(self) -> None:
        exact = CDPPage(id="1", title="Case", url="https://example.com/case", websocket_url="ws://127.0.0.1/devtools/page/1")
        partial = CDPPage(id="2", title="Nested", url="https://example.com/case/details", websocket_url="ws://127.0.0.1/devtools/page/2")
        self.assertEqual(pick_page([partial, exact], "https://example.com/case"), exact)

    def test_pick_page_by_title(self) -> None:
        page = CDPPage(id="1", title="OPT Case Portal", url="https://example.com/case", websocket_url="ws://127.0.0.1/devtools/page/1")
        other = CDPPage(id="2", title="Inbox", url="https://mail.example.com", websocket_url="ws://127.0.0.1/devtools/page/2")
        self.assertEqual(pick_page([other, page], title="OPT Case"), page)

    def test_pick_page_by_id(self) -> None:
        page = CDPPage(id="target-1", title="Case", url="https://example.com/case", websocket_url="ws://127.0.0.1/devtools/page/target-1")
        other = CDPPage(id="target-2", title="Case", url="https://example.com/case", websocket_url="ws://127.0.0.1/devtools/page/target-2")
        self.assertEqual(pick_page([other, page], page_id="target-1"), page)

    def test_pick_page_combined_selectors_narrow_duplicate_urls(self) -> None:
        page = CDPPage(id="1", title="OPT Case Portal", url="https://example.com/case", websocket_url="ws://127.0.0.1/devtools/page/1")
        other = CDPPage(id="2", title="Appointment Portal", url="https://example.com/case", websocket_url="ws://127.0.0.1/devtools/page/2")
        self.assertEqual(pick_page([other, page], "https://example.com/case", title="OPT"), page)

    def test_pick_page_ambiguous_url_requires_stricter_selector(self) -> None:
        pages = [
            CDPPage(id="1", title="Case A", url="https://example.com/case/1", websocket_url="ws://127.0.0.1/devtools/page/1"),
            CDPPage(id="2", title="Case B", url="https://example.com/case/2", websocket_url="ws://127.0.0.1/devtools/page/2"),
        ]
        with self.assertRaisesRegex(CDPError, "Ambiguous Chrome page selector"):
            pick_page(pages, "example.com/case")

    def test_pick_page_requires_page(self) -> None:
        with self.assertRaises(CDPError):
            pick_page([])

    def test_screenshot_bytes_from_result_decodes_png(self) -> None:
        png = b"\x89PNG\r\n\x1a\nfake"
        result = {"data": base64.b64encode(png).decode("ascii")}
        self.assertEqual(screenshot_bytes_from_result(result), png)

    def test_capture_screenshot_calls_chrome_cdp(self) -> None:
        png = b"\x89PNG\r\n\x1a\nfake"
        with patch("sentineldesk.cdp.cdp_command", return_value={"data": base64.b64encode(png).decode("ascii")}) as command:
            self.assertEqual(capture_screenshot("ws://127.0.0.1/devtools/page/1", timeout=2), png)
        command.assert_called_once_with(
            "ws://127.0.0.1/devtools/page/1",
            "Page.captureScreenshot",
            {"format": "png", "captureBeyondViewport": False, "fromSurface": True},
            timeout=2,
        )


if __name__ == "__main__":
    unittest.main()
