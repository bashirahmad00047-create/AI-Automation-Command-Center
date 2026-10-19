import unittest
from app import create_app
from database import db
from models import Organization, User, Membership, CompanyChannel, CompanyMessage, generate_uuid
from company_messaging_service import CompanyMessagingService


class TestCompanyMessagingUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app("testing")
        cls.app.config["TESTING"] = True
        cls.client = cls.app.test_client()

    def setUp(self):
        self.ctx = self.app.app_context()
        self.ctx.push()
        self.client = self.app.test_client()

        # Create 2 separate tenant orgs and users to test tenant isolation
        self.org_a = Organization(
            id=generate_uuid("org"),
            name="Alpha Corp",
            slug=f"alpha-corp-{generate_uuid()[:6]}",
            plan_tier="pro"
        )
        self.org_b = Organization(
            id=generate_uuid("org"),
            name="Beta Ltd",
            slug=f"beta-ltd-{generate_uuid()[:6]}",
            plan_tier="pro"
        )
        db.session.add_all([self.org_a, self.org_b])

        self.user_a = User(
            id=generate_uuid("usr"),
            email=f"alice-{generate_uuid()[:6]}@alphacorp.io",
            full_name="Alice Admin",
            password_hash="hash",
            is_active=True
        )
        self.user_b = User(
            id=generate_uuid("usr"),
            email=f"bob-{generate_uuid()[:6]}@betaltd.io",
            full_name="Bob User",
            password_hash="hash",
            is_active=True
        )
        db.session.add_all([self.user_a, self.user_b])
        db.session.flush()

        mem_a = Membership(
            id=generate_uuid("mem"),
            user_id=self.user_a.id,
            organization_id=self.org_a.id,
            role="owner"
        )
        mem_b = Membership(
            id=generate_uuid("mem"),
            user_id=self.user_b.id,
            organization_id=self.org_b.id,
            role="member"
        )
        db.session.add_all([mem_a, mem_b])
        db.session.commit()

    def tearDown(self):
        db.session.rollback()
        self.ctx.pop()

    def test_unauthenticated_channels_access_denied(self):
        """Unauthenticated requests must be rejected with 401."""
        res = self.client.get("/api/v1/company-messaging/channels")
        self.assertIn(res.status_code, [401, 302])

    def test_authenticated_tenant_isolation(self):
        """Users must only receive channels belonging to their active tenant."""
        # Ensure default channels exist
        CompanyMessagingService.ensure_default_channels(self.org_a.id)
        CompanyMessagingService.ensure_default_channels(self.org_b.id)

        # Authenticate as Alice in Alpha Corp
        with self.client.session_transaction() as sess:
            sess["user_id"] = self.user_a.id
            sess["active_organization_id"] = self.org_a.id

        res = self.client.get("/api/v1/company-messaging/channels")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("success"))
        channels = data.get("channels", [])
        self.assertGreaterEqual(len(channels), 3)

        # Verify all returned channels strictly belong to org_a
        for ch in channels:
            self.assertEqual(ch["organization_id"], self.org_a.id)

    def test_channel_messaging_and_isolation(self):
        """Messages posted in Org A channel must not be accessible to Org B."""
        channels_a = CompanyMessagingService.ensure_default_channels(self.org_a.id)
        channel_a = channels_a[0]

        with self.client.session_transaction() as sess:
            sess["user_id"] = self.user_a.id
            sess["active_organization_id"] = self.org_a.id

        # Post message to Org A channel
        post_res = self.client.post(
            f"/api/v1/company-messaging/channels/{channel_a.id}/messages",
            json={"body": "Hello Alpha Team!", "priority": "normal"}
        )
        self.assertEqual(post_res.status_code, 200)

        # Switch to Bob in Org B and try to access Org A channel messages
        with self.client.session_transaction() as sess:
            sess["user_id"] = self.user_b.id
            sess["active_organization_id"] = self.org_b.id

        get_res = self.client.get(f"/api/v1/company-messaging/channels/{channel_a.id}/messages")
        # Should be 404 or empty because channel_a doesn't belong to Org B
        if get_res.status_code == 200:
            msgs = get_res.get_json().get("messages", [])
            self.assertEqual(len(msgs), 0)
        else:
            self.assertEqual(get_res.status_code, 404)


if __name__ == "__main__":
    unittest.main()
