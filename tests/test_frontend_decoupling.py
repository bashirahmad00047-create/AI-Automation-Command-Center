"""Unit tests for Phase 7: Mobile Responsiveness & Frontend Decoupling (Audit Area 12).

Verifies:
1. JavaScript modular decoupling: auth.js, chat_interface.js, and catalog_manager.js.
2. Efficient defer loading in templates/index.html and templates/dashboard.html.
3. Mobile CSS responsiveness rule for screens < 380px (data tables, modal windows, flex sidebar).
4. Static asset caching and dynamic Gzip compression middleware in app.py.
"""

import os
import unittest


class TestFrontendDecoupling(unittest.TestCase):
    def setUp(self):
        self.base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

    def test_modular_js_files_exist_and_non_empty(self):
        """Verify auth.js, chat_interface.js, and catalog_manager.js exist and contain modules."""
        auth_path = os.path.join(self.base_dir, "static", "js", "auth.js")
        chat_path = os.path.join(self.base_dir, "static", "js", "chat_interface.js")
        cat_path = os.path.join(self.base_dir, "static", "js", "catalog_manager.js")

        self.assertTrue(os.path.exists(auth_path), "auth.js must exist")
        self.assertTrue(os.path.exists(chat_path), "chat_interface.js must exist")
        self.assertTrue(os.path.exists(cat_path), "catalog_manager.js must exist")

        with open(auth_path, "r", encoding="utf-8") as f:
            auth_content = f.read()
        self.assertIn("BashFlowAuth", auth_content)
        self.assertIn("initAuthAndTenancy", auth_content)

        with open(chat_path, "r", encoding="utf-8") as f:
            chat_content = f.read()
        self.assertIn("BashFlowChat", chat_content)
        self.assertIn("initSocket", chat_content)

        with open(cat_path, "r", encoding="utf-8") as f:
            cat_content = f.read()
        self.assertIn("BashFlowCatalog", cat_content)
        self.assertIn("loadProductsCatalog", cat_content)

    def test_scripts_included_with_defer_in_templates(self):
        """Verify index.html and dashboard.html load modular scripts with defer."""
        for tpl_name in ["index.html", "dashboard.html"]:
            path = os.path.join(self.base_dir, "templates", tpl_name)
            self.assertTrue(os.path.exists(path), f"{tpl_name} must exist")
            with open(path, "r", encoding="utf-8") as f:
                html = f.read()

            self.assertIn('defer src="/static/js/auth.js', html)
            self.assertIn('defer src="/static/js/chat_interface.js', html)
            self.assertIn('defer src="/static/js/catalog_manager.js', html)
            self.assertIn('defer src="/static/js/app.js', html)

    def test_ultra_compact_css_media_query_and_overflow_hardening(self):
        """Verify CSS contains max-width: 380px breakpoint and table/modal overflow hardening."""
        css_path = os.path.join(self.base_dir, "static", "css", "style.css")
        with open(css_path, "r", encoding="utf-8") as f:
            css = f.read()

        self.assertIn("@media (max-width: 380px)", css)
        self.assertIn(".wa-mobile-back-btn", css)
        self.assertIn(".table-container", css)
        self.assertIn("overflow-x: auto", css)

    def test_static_caching_and_compression_middleware(self):
        """Verify app.py contains static asset caching and gzip compression headers."""
        app_path = os.path.join(self.base_dir, "app.py")
        with open(app_path, "r", encoding="utf-8") as f:
            app_code = f.read()

        self.assertIn('response.headers["Cache-Control"] = "public, max-age=31536000, immutable"', app_code)
        self.assertIn('response.headers["Content-Encoding"] = "gzip"', app_code)


if __name__ == "__main__":
    unittest.main()
