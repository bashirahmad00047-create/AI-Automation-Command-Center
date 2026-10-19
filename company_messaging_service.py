"""Company Messaging Command Center Service for OpsFlow Cloud.

Provides high-throughput, multi-tenant internal communication:
- Scoped channels (#general, #incidents, #sre-alerts, #announcements)
- Direct messaging and priority message streams (normal, urgent, critical)
- Operational announcements & company broadcasts with mandatory employee acknowledgment
- RBAC validation & tenant isolation
- Compliance audit trail logging
"""

from __future__ import annotations

import datetime
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from auth import log_audit_event
from database import db
from models import (
    CompanyBroadcast,
    CompanyBroadcastAck,
    CompanyChannel,
    CompanyMessage,
    Organization,
    User,
    generate_uuid,
)

logger = logging.getLogger("opsflow.company_messaging")


class CompanyMessagingService:
    """Core enterprise business logic for Company Messaging Command Center."""

    DEFAULT_CHANNELS = [
        {
            "name": "general",
            "display_name": "#general",
            "description": "Company-wide operational collaboration and team discussions.",
            "channel_type": "public",
            "is_system": True,
        },
        {
            "name": "incidents",
            "display_name": "#incidents",
            "description": "Real-time production incident war room and automated triage alerts.",
            "channel_type": "public",
            "is_system": True,
        },
        {
            "name": "sre-alerts",
            "display_name": "#sre-alerts",
            "description": "Automated infrastructure telemetry, CPU/memory warnings, and webhook triggers.",
            "channel_type": "public",
            "is_system": True,
        },
        {
            "name": "announcements",
            "display_name": "#announcements",
            "description": "Official company broadcasts, executive updates, and maintenance windows.",
            "channel_type": "announcement",
            "is_system": True,
        },
    ]

    @classmethod
    def ensure_default_channels(cls, organization_id: str) -> List[CompanyChannel]:
        """Ensures the core foundational channels exist for a tenant workspace."""
        if not organization_id:
            return []

        channels = []
        for def_ch in cls.DEFAULT_CHANNELS:
            existing = CompanyChannel.query.filter_by(
                organization_id=organization_id,
                name=def_ch["name"]
            ).first()
            if not existing:
                ch = CompanyChannel(
                    id=generate_uuid("chn"),
                    organization_id=organization_id,
                    name=def_ch["name"],
                    display_name=def_ch["display_name"],
                    description=def_ch["description"],
                    channel_type=def_ch["channel_type"],
                    is_system=def_ch.get("is_system", False),
                    is_archived=False,
                )
                db.session.add(ch)
                channels.append(ch)
            else:
                channels.append(existing)

        if channels:
            try:
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                logger.error(f"Failed to commit default channels for org {organization_id}: {e}")

        return CompanyChannel.query.filter_by(
            organization_id=organization_id,
            is_archived=False
        ).order_by(CompanyChannel.created_at.asc()).all()

    @classmethod
    def list_channels(
        cls,
        organization_id: str,
        include_archived: bool = False
    ) -> List[Dict[str, Any]]:
        """Lists all channels for a tenant workspace, auto-initializing default channels if missing."""
        if not organization_id:
            return []

        query = CompanyChannel.query.filter_by(organization_id=organization_id)
        if not include_archived:
            query = query.filter_by(is_archived=False)

        channels = query.order_by(CompanyChannel.created_at.asc()).all()
        if not channels:
            channels = cls.ensure_default_channels(organization_id)

        return [c.to_dict() for c in channels]

    @classmethod
    def get_channel(cls, channel_id: str, organization_id: str) -> Optional[CompanyChannel]:
        """Fetches a channel with strict tenant isolation."""
        if not channel_id or not organization_id:
            return None
        return CompanyChannel.query.filter(
            (CompanyChannel.id == channel_id) | (CompanyChannel.name == channel_id),
            CompanyChannel.organization_id == organization_id
        ).first()

    @classmethod
    def create_channel(
        cls,
        organization_id: str,
        name: str,
        display_name: Optional[str] = None,
        description: Optional[str] = None,
        channel_type: str = "public",
        user_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Creates a new company messaging channel with validation and audit logging."""
        if not organization_id or not name:
            return {"success": False, "error": "Channel name is required", "code": "VALIDATION_ERROR"}

        clean_slug = re.sub(r"[^a-z0-9_-]", "-", name.strip().lower()).strip("-")
        if len(clean_slug) < 2 or len(clean_slug) > 64:
            return {"success": False, "error": "Channel name must be between 2 and 64 alphanumeric characters.", "code": "VALIDATION_ERROR"}

        existing = CompanyChannel.query.filter_by(
            organization_id=organization_id,
            name=clean_slug
        ).first()
        if existing:
            if existing.is_archived:
                existing.is_archived = False
                existing.description = description or existing.description
                db.session.commit()
                return {"success": True, "channel": existing.to_dict(), "message": f"Channel '#{clean_slug}' restored from archive."}
            return {"success": False, "error": f"Channel '#{clean_slug}' already exists in workspace.", "code": "CONFLICT"}

        disp = display_name.strip() if display_name else f"#{clean_slug}"
        if not disp.startswith("#"):
            disp = f"#{disp}"

        new_ch = CompanyChannel(
            id=generate_uuid("chn"),
            organization_id=organization_id,
            name=clean_slug,
            display_name=disp,
            description=(description or "").strip(),
            channel_type=channel_type if channel_type in ("public", "announcement", "private") else "public",
            created_by_user_id=user_id,
            is_system=False,
            is_archived=False
        )
        db.session.add(new_ch)
        db.session.commit()

        log_audit_event("messaging.channel_created", "channel", new_ch.id, {
            "name": clean_slug,
            "display_name": disp,
            "type": new_ch.channel_type
        })

        return {"success": True, "channel": new_ch.to_dict(), "message": f"Channel '{disp}' created successfully."}

    @classmethod
    def archive_channel(
        cls,
        channel_id: str,
        organization_id: str,
        user_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Archives a channel. System channels like #general cannot be archived."""
        ch = cls.get_channel(channel_id, organization_id)
        if not ch:
            return {"success": False, "error": "Channel not found in workspace.", "code": "NOT_FOUND"}

        if ch.is_system or ch.name in ("general", "incidents"):
            return {"success": False, "error": f"Core system channel '{ch.display_name}' cannot be archived.", "code": "IMMUTABLE"}

        ch.is_archived = True
        db.session.commit()

        log_audit_event("messaging.channel_archived", "channel", ch.id, {
            "name": ch.name,
            "archived_by": user_id
        })

        return {"success": True, "message": f"Channel '{ch.display_name}' archived successfully.", "channel_id": ch.id}

    @classmethod
    def post_message(
        cls,
        organization_id: str,
        channel_id: str,
        body: str,
        sender_id: Optional[str] = None,
        sender_name: Optional[str] = None,
        sender_role: str = "member",
        priority: str = "normal",
        is_system: bool = False,
        execution_id: Optional[int] = None,
        parent_message_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Posts a message to a channel with strict tenant isolation, validation, and audit recording."""
        if not organization_id or not channel_id or not body:
            return {"success": False, "error": "channel_id and message body are required.", "code": "VALIDATION_ERROR"}

        clean_body = body.strip()
        if not clean_body:
            return {"success": False, "error": "Message body cannot be empty.", "code": "VALIDATION_ERROR"}

        ch = cls.get_channel(channel_id, organization_id)
        if not ch:
            return {"success": False, "error": "Channel not found in workspace.", "code": "NOT_FOUND"}

        if ch.is_archived:
            return {"success": False, "error": "Cannot post messages to an archived channel.", "code": "CHANNEL_ARCHIVED"}

        # Announcement channels restrict posting to admin/owner/system
        if ch.channel_type == "announcement" and not is_system and sender_role not in ("owner", "admin"):
            return {"success": False, "error": "Only Admins and Owners can post to Announcement channels.", "code": "PERMISSION_DENIED"}

        s_name = (sender_name or "OpsFlow Member").strip()
        clean_priority = priority.lower() if priority in ("normal", "urgent", "critical") else "normal"

        msg = CompanyMessage(
            id=generate_uuid("cmsg"),
            organization_id=organization_id,
            channel_id=ch.id,
            sender_id=sender_id,
            sender_name=s_name,
            sender_role=sender_role,
            body=clean_body,
            priority=clean_priority,
            is_system=is_system,
            parent_message_id=parent_message_id,
            execution_id=execution_id
        )
        db.session.add(msg)
        db.session.commit()

        log_audit_event("messaging.message_posted", "message", msg.id, {
            "channel": ch.name,
            "sender": s_name,
            "priority": clean_priority,
            "is_system": is_system
        })

        return {"success": True, "message": msg.to_dict()}

    @classmethod
    def list_messages(
        cls,
        channel_id: str,
        organization_id: str,
        limit: int = 50,
        before_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Lists chronological messages for a channel with multi-tenant isolation."""
        ch = cls.get_channel(channel_id, organization_id)
        if not ch:
            return []

        limit = max(1, min(limit, 200))
        query = CompanyMessage.query.filter_by(
            organization_id=organization_id,
            channel_id=ch.id
        )

        if before_id:
            ref_msg = CompanyMessage.query.filter_by(id=before_id, organization_id=organization_id).first()
            if ref_msg:
                query = query.filter(CompanyMessage.created_at < ref_msg.created_at)

        messages = query.order_by(CompanyMessage.created_at.desc()).limit(limit).all()
        # Return in chronological order (oldest to newest for chat stream)
        messages.reverse()
        return [m.to_dict() for m in messages]

    @classmethod
    def delete_message(
        cls,
        message_id: str,
        organization_id: str,
        user_id: Optional[str] = None,
        user_role: str = "member"
    ) -> Dict[str, Any]:
        """Deletes a message with RBAC validation (admins delete any; members delete own)."""
        if not message_id or not organization_id:
            return {"success": False, "error": "message_id is required", "code": "VALIDATION_ERROR"}

        msg = CompanyMessage.query.filter_by(
            id=message_id,
            organization_id=organization_id
        ).first()

        if not msg:
            return {"success": False, "error": "Message not found in workspace.", "code": "NOT_FOUND"}

        # RBAC Check: Admins/Owners delete any; others only own
        is_admin = user_role in ("owner", "admin")
        is_author = user_id and msg.sender_id == user_id
        if not (is_admin or is_author):
            return {"success": False, "error": "Permission denied. You can only delete your own messages.", "code": "FORBIDDEN"}

        db.session.delete(msg)
        db.session.commit()

        log_audit_event("messaging.message_deleted", "message", message_id, {
            "channel_id": msg.channel_id,
            "deleted_by": user_id,
            "sender_id": msg.sender_id
        })

        return {"success": True, "message": "Message deleted successfully.", "deleted_id": message_id}

    @classmethod
    def create_broadcast(
        cls,
        organization_id: str,
        title: str,
        body: str,
        severity: str = "info",
        requires_acknowledgment: bool = False,
        created_by_user_id: Optional[str] = None,
        created_by_name: str = "Admin",
        expires_hours: Optional[int] = 48
    ) -> Dict[str, Any]:
        """Creates an urgent company-wide broadcast announcement with optional acknowledgment requirement."""
        if not organization_id or not title or not body:
            return {"success": False, "error": "Title and body are required for company broadcast.", "code": "VALIDATION_ERROR"}

        sev = severity.lower() if severity in ("info", "warning", "critical", "urgent") else "info"
        expires_at = datetime.datetime.utcnow() + datetime.timedelta(hours=expires_hours) if expires_hours else None

        bc = CompanyBroadcast(
            id=generate_uuid("bc"),
            organization_id=organization_id,
            title=title.strip(),
            body=body.strip(),
            severity=sev,
            requires_acknowledgment=bool(requires_acknowledgment),
            is_active=True,
            created_by_user_id=created_by_user_id,
            created_by_name=created_by_name.strip() or "Administrator",
            expires_at=expires_at
        )
        db.session.add(bc)
        db.session.commit()

        # Also auto-post broadcast notice into #announcements channel
        ann_ch = CompanyChannel.query.filter_by(organization_id=organization_id, name="announcements").first()
        if ann_ch:
            cls.post_message(
                organization_id=organization_id,
                channel_id=ann_ch.id,
                body=f"📢 **{bc.title}**\n\n{bc.body}\n\n*(Severity: {bc.severity.upper()}{' | Mandatory Acknowledgment Required' if bc.requires_acknowledgment else ''})*",
                sender_id=created_by_user_id,
                sender_name=f"{created_by_name} [Broadcast]",
                sender_role="admin",
                priority="critical" if sev in ("critical", "urgent") else "urgent",
                is_system=True
            )

        log_audit_event("messaging.broadcast_dispatched", "broadcast", bc.id, {
            "title": bc.title,
            "severity": bc.severity,
            "requires_ack": bc.requires_acknowledgment
        })

        return {"success": True, "broadcast": bc.to_dict(user_id=created_by_user_id)}

    @classmethod
    def list_broadcasts(
        cls,
        organization_id: str,
        active_only: bool = True,
        user_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Lists operational broadcasts for the tenant."""
        if not organization_id:
            return []

        query = CompanyBroadcast.query.filter_by(organization_id=organization_id)
        if active_only:
            now = datetime.datetime.utcnow()
            query = query.filter(
                CompanyBroadcast.is_active == True,
                (CompanyBroadcast.expires_at == None) | (CompanyBroadcast.expires_at > now)
            )

        broadcasts = query.order_by(CompanyBroadcast.created_at.desc()).all()
        return [b.to_dict(user_id=user_id) for b in broadcasts]

    @classmethod
    def acknowledge_broadcast(
        cls,
        broadcast_id: str,
        organization_id: str,
        user_id: str,
        user_name: str
    ) -> Dict[str, Any]:
        """Acknowledge receipt of a mandatory company broadcast."""
        if not broadcast_id or not organization_id or not user_id:
            return {"success": False, "error": "broadcast_id, organization_id, and user_id are required", "code": "VALIDATION_ERROR"}

        bc = CompanyBroadcast.query.filter_by(id=broadcast_id, organization_id=organization_id).first()
        if not bc:
            return {"success": False, "error": "Broadcast not found in workspace.", "code": "NOT_FOUND"}

        existing_ack = CompanyBroadcastAck.query.filter_by(
            broadcast_id=bc.id,
            user_id=user_id
        ).first()

        if existing_ack:
            return {"success": True, "message": "Broadcast already acknowledged.", "ack": existing_ack.to_dict()}

        ack = CompanyBroadcastAck(
            id=generate_uuid("back"),
            organization_id=organization_id,
            broadcast_id=bc.id,
            user_id=user_id,
            user_name=user_name.strip() or "Employee"
        )
        db.session.add(ack)
        db.session.commit()

        log_audit_event("messaging.broadcast_acknowledged", "broadcast", bc.id, {
            "user_id": user_id,
            "user_name": user_name
        })

        return {"success": True, "message": "Broadcast acknowledged.", "ack": ack.to_dict()}

    @classmethod
    def get_summary(cls, organization_id: str, user_id: Optional[str] = None) -> Dict[str, Any]:
        """Provides operational metrics for Command Center badges."""
        if not organization_id:
            return {"channels_count": 0, "active_broadcasts": 0, "unacknowledged_broadcasts": 0}

        channels_count = CompanyChannel.query.filter_by(organization_id=organization_id, is_archived=False).count()
        broadcasts = cls.list_broadcasts(organization_id, active_only=True, user_id=user_id)
        unacked = [b for b in broadcasts if b.get("requires_acknowledgment") and not b.get("is_acknowledged")]

        return {
            "channels_count": channels_count,
            "active_broadcasts_count": len(broadcasts),
            "unacknowledged_broadcasts_count": len(unacked),
            "critical_broadcast": next((b for b in broadcasts if b.get("severity") in ("critical", "urgent")), None)
        }
