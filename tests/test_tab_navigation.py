import unittest
import os
import re

class TestTabNavigation(unittest.TestCase):
    def setUp(self):
        self.repo_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def test_index_html_early_switch_tab(self):
        index_path = os.path.join(self.repo_dir, "templates", "index.html")
        with open(index_path, "r", encoding="utf-8") as f:
            html = f.read()

        self.assertIn("function earlySwitchTab", html)
        self.assertIn("window.switchTab = earlySwitchTab", html)
        self.assertIn("window.switchTab(hashTab || 'whatsapp')", html)

    def test_app_js_switch_tab_global(self):
        app_js_path = os.path.join(self.repo_dir, "static", "js", "app.js")
        with open(app_js_path, "r", encoding="utf-8") as f:
            code = f.read()

        self.assertIn("window.switchTab = switchTab;", code)
        self.assertIn("window.initNavigationListeners = initNavigationListeners;", code)
        # Check safe DOMContentLoaded order
        pos_nav = code.find("initNavigationListeners();")
        pos_refresh = code.find("refreshAllData();")
        self.assertTrue(pos_nav > 0 and pos_nav < pos_refresh, "initNavigationListeners must run before refreshAllData")

if __name__ == "__main__":
    unittest.main()
