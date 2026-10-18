"""Comprehensive test suite for WhatsApp Inbox Actions: Forward, Delete, Unread, RBAC & Multi-Tenant Isolation.

Verifies:
1. WhatsAppService.forward_message() and POST /api/v1/whatsapp/messages/<id>/forward.
   - Successful dispatch (simulated and remote).
   - Provider failure returns HTTP 502 with honest details.
   - Forwarding payload tags original message metadata.
2. WhatsAppService.delete_message() and DELETE /api/v1/whatsapp/messages/<id>.
   - Local DB deletion.
   - Remote Green-API deleteMessage dispatch when configured.
   - Honest remote failure and unsupported provider reporting.
3. WhatsAppService.mark_chat_as_unread() / mark_message_as_unread() and API endpoints.
   - Transitions read inbound messages back to status="received".
4. Security & Permissions:
   - Unauthorized (401) on missing credentials.
   - Viewer role blocked (403) from forward, delete, and unread.
   - Cross-tenant isolation (404) prevents interacting with other tenant messages.
5. Audit Logging:
   - whatsapp.message_forwarded, whatsapp.message_deleted, whatsapp.conversation_marked_unread, whatsapp.message_marked_unread.
"""

from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch, MagicMock

from app import create_app
from database import db
from models import Organization, User, Membership, WhatsAppMessage, SystemSetting, AuditLog
from whatsapp_service import WhatsAppService


class TestWhatsAppInboxActions(unittest.TestCase):
    def setUp(self):
        self.env_patcher = patch.dict(os.environ, {
            "GREEN_API_ID_INSTANCE": "",
            "GREEN_API_TOKEN_INSTANCE": "",
            "WHATSAPP_SIMULATOR_FALLBACK": "true"
        })
        self.env_patcher.start()

        self.app = create_app("testing")
        self.app.config["RATELIMIT_ENABLED"] = False
        self.app.config["WTF_CSRF_ENABLED"] = False
        self.client = self.app.test_client()
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()

        # Primary Tenant Org A
        self.org_a = Organization(
            id="org-pk-alpha",
            name="Alpha Corp",
            slug="alpha-corp",
            plan_tier="enterprise",
            is_active=True
        )
        db.session.add(self.org_a)

        # Secondary Tenant Org B (for cross-tenant tests)
        self.org_b = Organization(
            id="org-pk-beta",
            name="Beta Industries",
            slug="beta-ind",
            plan_tier="enterprise",
            is_active=True
        )
        db.session.add(self.org_b)

        # Admin User in Org A
        self.admin_user = User(
            id="usr-alpha-admin",
            email="admin@alpha.pk",
            full_name="Alpha Admin",
            is_active=True
        )
        self.admin_user.set_password("AdminPass2026!")
        db.session.add(self.admin_user)

        self.member_admin = Membership(
            id="mem-alpha-admin",
            organization_id=self.org_a.id,
            user_id=self.admin_user.id,
            role="admin"
        )
        db.session.add(self.member_admin)

        # Viewer User in Org A
        self.viewer_user = User(
            id="usr-alpha-viewer",
            email="viewer@alpha.pk",
            full_name="Alpha Viewer",
            is_active=True
        )
        self.viewer_user.set_password("ViewerPass2026!")
        db.session.add(self.viewer_user)

        self.member_viewer = Membership(
            id="mem-alpha-viewer",
            organization_id=self.org_a.id,
            user_id=self.viewer_user.id,
            role="viewer"
        )
        db.session.add(self.member_viewer)

        db.session.commit()

        # Explicitly configure default tenant to simulator mode
        SystemSetting.set_val(f"ORG_{self.org_a.id}_WHATSAPP_PROVIDER", "simulator", is_secret=False)
        SystemSetting.set_val(f"ORG_{self.org_a.id}_GREEN_API_ID_INSTANCE", "", is_secret=False)

        # Login as Admin by default
        login_res = self.client.post("/api/v1/auth/login", json={
            "email": "admin@alpha.pk",
            "password": "AdminPass2026!"
        })
        self.assertEqual(login_res.status_code, 200)

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()
        self.env_patcher.stop()

    def _login_as(self, email, password):
        self.client.post("/api/v1/auth/logout")
        return self.client.post("/api/v1/auth/login", json={
            "email": email,
            "password": password
        })

    # =========================================================================
    # 1. FORWARD MESSAGE TESTS
    # =========================================================================

    def test_forward_message_simulation_success(self):
        """Verifies message forwarding creates a new outbound message and tags forwarding metadata."""
        orig_msg = WhatsAppService.record_message(
            organization_id=self.org_a.id,
            sender="923001234567",
            recipient="system",
            direction="inbound",
            body="Original customer inquiry regarding enterprise workflow automation.",
            status="received",
            whatsapp_message_id="wamid.orig_01"
        )

        res = self.client.post(f"/api/v1/whatsapp/messages/{orig_msg.id}/forward", json={
            "to": "923219876543"
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data.get("recipient"), "923219876543")
        self.assertEqual(data.get("forwarded_from_id"), orig_msg.id)

        # Verify new outbound message exists in DB
        fwd_record_id = data.get("new_record_id")
        self.assertIsNotNone(fwd_record_id)
        fwd_msg = db.session.get(WhatsAppMessage, fwd_record_id)
        self.assertIsNotNone(fwd_msg)
        self.assertEqual(fwd_msg.recipient, "923219876543")
        self.assertIn("Original customer inquiry", fwd_msg.body)

        # Verify payload contains forwarding metadata
        self.assertTrue(fwd_msg.raw_payload_json)
        payload = json.loads(fwd_msg.raw_payload_json)
        self.assertTrue(payload.get("is_forwarded"))
        self.assertEqual(payload.get("forwarded_from_id"), orig_msg.id)
        self.assertEqual(payload.get("original_sender"), "923001234567")

        # Verify Audit Log
        audit = AuditLog.query.filter_by(
            organization_id=self.org_a.id,
            action="whatsapp.message_forwarded"
        ).first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.resource_id, orig_msg.id)

    def test_forward_message_provider_failure_returns_502(self):
        """Verifies provider failure during forward returns HTTP 502 with honest details without faking success."""
        orig_msg = WhatsAppService.record_message(
            organization_id=self.org_a.id,
            sender="923001234567",
            recipient="system",
            direction="inbound",
            body="Important inquiry to forward",
            status="received",
            whatsapp_message_id="wamid.fwd_fail_01"
        )

        with patch.object(WhatsAppService, "send_message", return_value={
            "success": False,
            "status": "failed",
            "error": "Upstream WhatsApp provider timeout (504)",
            "provider": "green_api"
        }):
            res = self.client.post(f"/api/v1/whatsapp/messages/{orig_msg.id}/forward", json={
                "to": "923219876543"
            })
            self.assertEqual(res.status_code, 502)
            data = res.get_json()
            self.assertFalse(data.get("success"))
            self.assertFalse(data.get("remote_success"))
            self.assertIn("timeout", data.get("remote_detail", "").lower())

    def test_forward_message_validation_error(self):
        """Verifies forward without destination phone returns 400 validation error."""
        orig_msg = WhatsAppService.record_message(
            organization_id=self.org_a.id,
            sender="923001234567",
            recipient="system",
            direction="inbound",
            body="Text",
            status="received",
            whatsapp_message_id="wamid.valid_01"
        )

        res = self.client.post(f"/api/v1/whatsapp/messages/{orig_msg.id}/forward", json={})
        self.assertEqual(res.status_code, 400)
        data = res.get_json()
        self.assertEqual(data.get("code"), "VALIDATION_ERROR")

    # =========================================================================
    # 2. DELETE MESSAGE TESTS
    # =========================================================================

    def test_delete_message_local_and_green_api_remote_success(self):
        """Verifies delete removes message locally and executes remote Green-API deleteMessage when configured."""
        msg = WhatsAppService.record_message(
            organization_id=self.org_a.id,
            sender="923001234567",
            recipient="system",
            direction="inbound",
            body="Spam or unwanted message",
            status="received",
            whatsapp_message_id="BAE5912345678901"
        )
        msg_id = msg.id

        # Set up real Green-API config for org A (non-mock ID)
        SystemSetting.set_val(f"ORG_{self.org_a.id}_WHATSAPP_PROVIDER", "green_api", is_secret=False)
        SystemSetting.set_val(f"ORG_{self.org_a.id}_GREEN_API_ID_INSTANCE", "1101999999", is_secret=False)
        SystemSetting.set_val(f"ORG_{self.org_a.id}_GREEN_API_TOKEN_INSTANCE", "secret-token-test", is_secret=True)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = json.dumps({"result": True})
        mock_resp.json.return_value = {"result": True}

        with patch("requests.Session.post", return_value=mock_resp) as mock_post:
            res = self.client.delete(f"/api/v1/whatsapp/messages/{msg_id}")
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertTrue(data.get("success"))
            self.assertTrue(data.get("remote_success"))
            self.assertIn("Green-API", data.get("remote_detail", ""))

            # Verify Green-API endpoint was invoked with expected parameters
            mock_post.assert_called_once()
            call_url = mock_post.call_args[0][0]
            call_json = mock_post.call_args[1].get("json", {})
            self.assertIn("/waInstance1101999999/deleteMessage/secret-token-test", call_url)
            self.assertEqual(call_json.get("idMessage"), "BAE5912345678901")

        # Verify message is gone from database
        deleted_record = db.session.get(WhatsAppMessage, msg_id)
        self.assertIsNone(deleted_record)

        # Verify audit log
        audit = AuditLog.query.filter_by(
            organization_id=self.org_a.id,
            action="whatsapp.message_deleted"
        ).first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.resource_id, msg_id)

    def test_delete_message_provider_error_still_deletes_locally_with_honest_report(self):
        """Verifies remote provider error does not block local deletion, reporting honest failure."""
        msg = WhatsAppService.record_message(
            organization_id=self.org_a.id,
            sender="923001234567",
            recipient="system",
            direction="inbound",
            body="Message with provider delete failure",
            status="received",
            whatsapp_message_id="BAE5_FAIL_MSG"
        )
        msg_id = msg.id

        SystemSetting.set_val(f"ORG_{self.org_a.id}_WHATSAPP_PROVIDER", "green_api", is_secret=False)
        SystemSetting.set_val(f"ORG_{self.org_a.id}_GREEN_API_ID_INSTANCE", "1101999999", is_secret=False)
        SystemSetting.set_val(f"ORG_{self.org_a.id}_GREEN_API_TOKEN_INSTANCE", "secret-token", is_secret=True)

        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.text = "Message was sent more than 24 hours ago and cannot be deleted remotely"

        with patch("requests.Session.post", return_value=mock_resp):
            res = self.client.delete(f"/api/v1/whatsapp/messages/{msg_id}")
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertTrue(data.get("success"))
            self.assertFalse(data.get("remote_success"))
            self.assertIn("400", data.get("remote_detail", ""))

        # Local DB record is deleted
        self.assertIsNone(db.session.get(WhatsAppMessage, msg_id))

    def test_delete_message_meta_or_sim_reports_honest_unsupported(self):
        """Verifies deletion in Meta or simulator mode explicitly notes remote deletion is unsupported."""
        # 1. Simulator mode
        msg = WhatsAppService.record_message(
            organization_id=self.org_a.id,
            sender="923001234567",
            recipient="system",
            direction="inbound",
            body="Delete in simulator mode",
            status="received",
            whatsapp_message_id="wamid.sim_del_01"
        )
        msg_id = msg.id

        res = self.client.delete(f"/api/v1/whatsapp/messages/{msg_id}")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("success"))
        self.assertFalse(data.get("remote_success"))
        self.assertIn("does not dispatch remote deletion", data.get("remote_detail", ""))
        self.assertIsNone(db.session.get(WhatsAppMessage, msg_id))

        # 2. Meta Cloud API mode
        SystemSetting.set_val(f"ORG_{self.org_a.id}_WHATSAPP_PROVIDER", "meta", is_secret=False)
        SystemSetting.set_val(f"ORG_{self.org_a.id}_WHATSAPP_PHONE_NUMBER_ID", "10987654321", is_secret=False)
        SystemSetting.set_val(f"ORG_{self.org_a.id}_WHATSAPP_ACCESS_TOKEN", "meta-token", is_secret=True)

        meta_msg = WhatsAppService.record_message(
            organization_id=self.org_a.id,
            sender="923001234567",
            recipient="system",
            direction="inbound",
            body="Delete in Meta mode",
            status="received",
            whatsapp_message_id="wamid.meta_del_01"
        )
        res_meta = self.client.delete(f"/api/v1/whatsapp/messages/{meta_msg.id}")
        self.assertEqual(res_meta.status_code, 200)
        data_meta = res_meta.get_json()
        self.assertTrue(data_meta.get("success"))
        self.assertFalse(data_meta.get("remote_success"))
        self.assertIn("Meta Cloud API does not support remote message deletion", data_meta.get("remote_detail", ""))
        self.assertIsNone(db.session.get(WhatsAppMessage, meta_msg.id))

    # =========================================================================
    # 3. UNREAD CONVERSATION & MESSAGE TESTS
    # =========================================================================

    def test_mark_conversation_as_unread_transitions_read_messages(self):
        """Verifies POST /api/v1/whatsapp/conversations/<phone>/unread flips read inbound messages to 'received'."""
        sender_phone = "923005554433"
        msg1 = WhatsAppService.record_message(
            organization_id=self.org_a.id,
            sender=sender_phone,
            recipient="system",
            direction="inbound",
            body="Msg 1 read",
            status="read",
            whatsapp_message_id="wamid.unread_01"
        )
        msg2 = WhatsAppService.record_message(
            organization_id=self.org_a.id,
            sender=sender_phone,
            recipient="system",
            direction="inbound",
            body="Msg 2 read",
            status="read",
            whatsapp_message_id="wamid.unread_02"
        )
        outbound = WhatsAppService.record_message(
            organization_id=self.org_a.id,
            sender="system",
            recipient=sender_phone,
            direction="outbound",
            body="Agent reply",
            status="read",
            whatsapp_message_id="wamid.unread_out"
        )

        res = self.client.post(f"/api/v1/whatsapp/conversations/{sender_phone}/unread")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data.get("updated_count"), 2)

        # Verify DB records
        db.session.expire_all()
        self.assertEqual(db.session.get(WhatsAppMessage, msg1.id).status, "received")
        self.assertEqual(db.session.get(WhatsAppMessage, msg2.id).status, "received")
        # Outbound remains read
        self.assertEqual(db.session.get(WhatsAppMessage, outbound.id).status, "read")

        # Verify Audit Log
        audit = AuditLog.query.filter_by(
            organization_id=self.org_a.id,
            action="whatsapp.conversation_marked_unread"
        ).first()
        self.assertIsNotNone(audit)

    def test_mark_single_message_as_unread(self):
        """Verifies POST /api/v1/whatsapp/messages/<id>/unread flips a single message to 'received'."""
        msg = WhatsAppService.record_message(
            organization_id=self.org_a.id,
            sender="923001234567",
            recipient="system",
            direction="inbound",
            body="Read message to mark unread",
            status="read",
            whatsapp_message_id="wamid.single_unread"
        )

        res = self.client.post(f"/api/v1/whatsapp/messages/{msg.id}/unread")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data.get("updated_count"), 1)

        db.session.expire_all()
        self.assertEqual(db.session.get(WhatsAppMessage, msg.id).status, "received")

        # Audit Log
        audit = AuditLog.query.filter_by(
            organization_id=self.org_a.id,
            action="whatsapp.message_marked_unread"
        ).first()
        self.assertIsNotNone(audit)

    # =========================================================================
    # 4. SECURITY, RBAC & TENANT ISOLATION TESTS
    # =========================================================================

    def test_unauthenticated_requests_return_401(self):
        """Verifies unauthenticated callers receive HTTP 401 on inbox actions."""
        self.client.post("/api/v1/auth/logout")

        res_del = self.client.delete("/api/v1/whatsapp/messages/fake-id")
        self.assertEqual(res_del.status_code, 401)

        res_fwd = self.client.post("/api/v1/whatsapp/messages/fake-id/forward", json={"to": "923001112233"})
        self.assertEqual(res_fwd.status_code, 401)

        res_unr = self.client.post("/api/v1/whatsapp/conversations/923001112233/unread")
        self.assertEqual(res_unr.status_code, 401)

    def test_viewer_role_blocked_with_403(self):
        """Verifies users with viewer role are forbidden (403) from mutating inbox actions."""
        self._login_as("viewer@alpha.pk", "ViewerPass2026!")

        msg = WhatsAppService.record_message(
            organization_id=self.org_a.id,
            sender="923001234567",
            recipient="system",
            direction="inbound",
            body="Viewer test message",
            status="received",
            whatsapp_message_id="wamid.viewer_test"
        )

        # Delete -> 403
        res_del = self.client.delete(f"/api/v1/whatsapp/messages/{msg.id}")
        self.assertEqual(res_del.status_code, 403)

        # Forward -> 403
        res_fwd = self.client.post(f"/api/v1/whatsapp/messages/{msg.id}/forward", json={"to": "923219876543"})
        self.assertEqual(res_fwd.status_code, 403)

        # Mark unread -> 403
        res_unr = self.client.post(f"/api/v1/whatsapp/conversations/923001234567/unread")
        self.assertEqual(res_unr.status_code, 403)

    def test_cross_tenant_isolation_returns_404(self):
        """Verifies tenant Alpha cannot forward, delete, or mark unread messages owned by tenant Beta."""
        # Record message owned by Beta
        beta_msg = WhatsAppService.record_message(
            organization_id=self.org_b.id,
            sender="923337778899",
            recipient="system",
            direction="inbound",
            body="Beta confidential client message",
            status="read",
            whatsapp_message_id="wamid.beta_secret"
        )

        # Alpha admin is currently logged in
        self._login_as("admin@alpha.pk", "AdminPass2026!")

        # Attempt to delete Beta's message
        del_res = self.client.delete(f"/api/v1/whatsapp/messages/{beta_msg.id}")
        self.assertEqual(del_res.status_code, 404)

        # Attempt to forward Beta's message
        fwd_res = self.client.post(f"/api/v1/whatsapp/messages/{beta_msg.id}/forward", json={"to": "923001112233"})
        self.assertEqual(fwd_res.status_code, 404)

        # Attempt to mark Beta's message as unread
        unr_res = self.client.post(f"/api/v1/whatsapp/messages/{beta_msg.id}/unread")
        self.assertEqual(unr_res.status_code, 404)

        # Beta's message is still intact in DB
        db.session.expire_all()
        refreshed_beta_msg = db.session.get(WhatsAppMessage, beta_msg.id)
        self.assertIsNotNone(refreshed_beta_msg)
        self.assertEqual(refreshed_beta_msg.organization_id, self.org_b.id)
        self.assertEqual(refreshed_beta_msg.status, "read")


if __name__ == "__main__":
    unittest.main()
