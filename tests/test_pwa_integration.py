import sys
import os
import unittest
import json

from app import create_app

class TestBashFlowPWA(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()

    def tearDown(self):
        self.app_context.pop()

    def test_pwa_manifest_route(self):
        for route in ["/manifest.json", "/manifest.webmanifest", "/static/manifest.json"]:
            resp = self.client.get(route)
            self.assertEqual(resp.status_code, 200, f"Failed for {route}")
            data = json.loads(resp.data.decode("utf-8"))
            self.assertEqual(data["name"], "BashFlow Cloud - AI Automation Command Center")
            self.assertEqual(data["short_name"], "BashFlow")
            self.assertEqual(data["display"], "standalone")
            self.assertEqual(data["start_url"], "/")
            self.assertEqual(data["background_color"], "#0f172a")
            self.assertEqual(data["theme_color"], "#2563eb")
            self.assertTrue(len(data["icons"]) >= 4)
            
            icon_srcs = [icon["src"] for icon in data["icons"]]
            self.assertIn("/static/img/icon-192.png", icon_srcs)
            self.assertIn("/static/img/icon-512.png", icon_srcs)

    def test_pwa_service_worker_routes(self):
        for route in ["/service-worker.js", "/sw.js", "/static/sw.js"]:
            resp = self.client.get(route)
            self.assertEqual(resp.status_code, 200, f"Route {route} failed")
            self.assertIn("application/javascript", resp.content_type)
            if not route.startswith("/static/"):
                self.assertEqual(resp.headers.get("Service-Worker-Allowed"), "/")
            content = resp.data.decode("utf-8")
            self.assertIn("CACHE_NAME", content)
            self.assertIn("self.addEventListener('install'", content)
            self.assertIn("self.addEventListener('fetch'", content)

    def test_pwa_icons_exist_on_disk(self):
        project_root = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
        static_img = os.path.join(project_root, "static", "img")
        required_icons = [
            "icon-192.png",
            "icon-512.png",
            "icon-maskable-192.png",
            "icon-maskable-512.png",
            "icon-180.png",
            "favicon-32.png",
            "opsflow-icon.svg"
        ]
        for icon in required_icons:
            icon_path = os.path.join(static_img, icon)
            self.assertTrue(os.path.exists(icon_path), f"Missing icon: {icon_path}")
            self.assertGreater(os.path.getsize(icon_path), 50, f"Icon {icon} is empty")

    def test_index_html_has_pwa_meta_tags(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode("utf-8")
        self.assertTrue('<link rel="manifest"' in html)
        self.assertIn('name="theme-color" content="#0f172a"', html)
        self.assertIn('name="mobile-web-app-capable" content="yes"', html)
        self.assertIn('name="apple-mobile-web-app-capable" content="yes"', html)
        self.assertIn('name="apple-mobile-web-app-title" content="BashFlow"', html)
        self.assertIn('/static/img/icon-180.png', html)
        self.assertIn('/static/img/icon-192.png', html)
        self.assertIn('id="pwaInstallBtn"', html)

if __name__ == '__main__':
    unittest.main()
