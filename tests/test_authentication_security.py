import unittest
from app import app


class AuthenticationSecurityTestCase(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_unauthenticated_access_redirects_to_login(self):
        """Unauthenticated visits to root or dashboard must redirect to /login."""
        r_root = self.client.get("/")
        self.assertEqual(r_root.status_code, 302)
        self.assertIn("/login", r_root.headers.get("Location", ""))

        r_dash = self.client.get("/dashboard")
        self.assertEqual(r_dash.status_code, 302)
        self.assertIn("/login", r_dash.headers.get("Location", ""))

    def test_login_page_renders_cleanly(self):
        """GET /login must serve the standalone security login interface."""
        r = self.client.get("/login")
        self.assertEqual(r.status_code, 200)
        html = r.get_data(as_text=True)
        self.assertIn("Work Email Address", html)
        self.assertIn("Sign In to Command Center", html)
        self.assertIn("BASHFLOW CLOUD", html)

    def test_invalid_login_rejected(self):
        """Invalid credentials must be rejected with 400 or 401."""
        r = self.client.post("/login", json={"email": "hacker@test.com", "password": "wrongpassword"})
        self.assertIn(r.status_code, [400, 401])

    def test_master_admin_login_grants_access(self):
        """Master admin credentials authenticate successfully and unlock / and /dashboard."""
        r_login = self.client.post(
            "/login",
            json={"email": "Bashirahmad00047@gmail.com", "password": "bashir@12."}
        )
        self.assertEqual(r_login.status_code, 200)
        data = r_login.get_json()
        self.assertEqual(data.get("status"), "success")

        # After logging in, GET / must return 200 (dashboard) without redirect
        r_dash = self.client.get("/")
        self.assertEqual(r_dash.status_code, 200)

        # Logout must invalidate session and redirect to /login
        r_logout = self.client.get("/logout")
        self.assertEqual(r_logout.status_code, 302)
        self.assertIn("/login", r_logout.headers.get("Location", ""))

        # After logout, GET / must redirect to /login again
        r_after = self.client.get("/")
        self.assertEqual(r_after.status_code, 302)
        self.assertIn("/login", r_after.headers.get("Location", ""))

    def test_root_route_resilience_rollback_on_error(self):
        """When an exception occurs during root handling, it safely rolls back and redirects without 500."""
        from unittest.mock import patch
        with self.client.session_transaction() as sess:
            sess["user_id"] = "admin-user-id"
            sess["is_super_admin"] = True
        with patch("app.render_template", side_effect=Exception("Simulated template failure")):
            r = self.client.get("/")
            self.assertEqual(r.status_code, 302)
            self.assertIn("/login", r.headers.get("Location", ""))



if __name__ == "__main__":
    unittest.main()
