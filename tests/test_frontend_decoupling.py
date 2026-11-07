"""Unit tests for Phase 7: Mobile Responsiveness & Frontend Decoupling (Audit Area 12).

Verifies:
1. JavaScript modular decoupling: auth.js and chat_interface.js exist and are valid.
2. Script inclusion in templates/index.html.
3. Mobile CSS responsiveness rule for screens < 380px.
"""

import os
import unittest


class TestFrontendDecoupling(unittest.TestCase):
    def setUp(self):
        self.base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

    def test_modular_js_files_exist_and_non_empty(self):
        """Verify auth.js and chat_interface.js are created and contain module definitions."""
        auth_path = os.path.join(self.base_dir, "static", "js", "auth.js")
        chat_path = os.path.join(self.base_dir, "static", "js", "chat_interface.js")

        self.assertTrue(os.path.exists(auth_path), "auth.js must exist")
        self.assertTrue(os.path.exists(chat_path), "chat_interface.js must exist")

        with open(auth_path, "r", encoding="utf-8") as f:
            auth_content = f.read()
        self.assertIn("BashFlowAuth", auth_content)
        self.assertIn("initAuthAndTenancy", auth_content)

        with open(chat_path, "r", encoding="utf-8") as f:
            chat_content = f.read()
        self.assertIn("BashFlowChat", chat_content)
        self.assertIn("initSocket", chat_content)

    def test_scripts_included_in_index_html(self):
        """Verify index.html loads auth.js and chat_interface.js."""
        index_path = os.path.join(self.base_dir, "templates", "index.html")
        with open(index_path, "r", encoding="utf-8") as f:
            html = f.read()

        self.assertIn("/static/js/auth.js", html)
        self.assertIn("/static/js/chat_interface.js", html)

    def test_ultra_compact_css_media_query_present(self):
        """Verify CSS contains max-width: 380px breakpoint for compact mobile screens."""
        css_path = os.path.join(self.base_dir, "static", "css", "style.css")
        with open(css_path, "r", encoding="utf-8") as f:
            css = f.read()

        self.assertIn("@media (max-width: 380px)", css)
        self.assertIn(".wa-mobile-back-btn", css)


if __name__ == "__main__":
    unittest.main()
