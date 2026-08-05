from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from prickly_imax_helper.browser import _ensure_browser_tab


class EnsureBrowserTabTests(unittest.TestCase):
    def test_keeps_existing_matching_tab(self) -> None:
        with patch(
            "prickly_imax_helper.browser._json_url",
            return_value=[{"url": "https://cgv.co.kr/cnm/movieBook"}],
        ), patch("prickly_imax_helper.browser.urllib.request.urlopen") as open_url:
            _ensure_browser_tab(9222, "https://cgv.co.kr/cnm/movieBook", wait_seconds=0)
        open_url.assert_not_called()

    def test_creates_missing_startup_tab(self) -> None:
        response = Mock()
        response.close.return_value = None
        with patch("prickly_imax_helper.browser._json_url", return_value=[]), patch(
            "prickly_imax_helper.browser.urllib.request.urlopen", return_value=response
        ) as open_url:
            _ensure_browser_tab(9222, "https://cgv.co.kr/cnm/movieBook", wait_seconds=0)
        request = open_url.call_args.args[0]
        self.assertEqual(request.get_method(), "PUT")
        self.assertIn("/json/new?https%3A%2F%2Fcgv.co.kr%2Fcnm%2FmovieBook", request.full_url)


if __name__ == "__main__":
    unittest.main()
