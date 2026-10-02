"""OpsFlow Enterprise AI Automation SaaS Flask Application.

Production WSGI application supporting:
- Multi-tenant enterprise workflow orchestration
- Visual step execution engine & CRM lead pipeline
- Deterministic local AI intelligence engine (zero API key required)
- PostgreSQL production compatibility & SQLite local development
- Gunicorn WSGI production runner (`gunicorn app:app`)
- Dynamic Render cloud environment binding ($PORT, 0.0.0.0)
- Backward-compatible REST APIs & modern /api/v1 endpoints
"""

from __future__ import annotations

import datetime
import json
import os
from typing import Any, Dict, Optional
from flask import Flask, Response, g, jsonify, render_template, request, session

from api_v1 import api_v1
from auth import require_auth
from automation_engine import AutomationEngine
from config import config_by_name
from database import db
from entitlements import QuotaService, check_feature_entitlement, check_resource_quota
from models import Membership, Organization, User
from presets import PRESET_BLUEPRINTS
from storage import Storage


def create_app(config_name: Optional[str] = None) -> Flask:
    """Application factory for OpsFlow SaaS."""
    application = Flask(__name__)

    # Load environment configuration
    env_name = config_name or os.environ.get("FLASK_ENV") or ("production" if os.environ.get("RENDER") else "development")
    cfg = config_by_name.get(env_name, config_by_name["default"])
    application.config.from_object(cfg)

    # Initialize SQLAlchemy
    db.init_app(application)

    # Initialize persistence and automation engine inside app context
    with application.app_context():
        db.create_all()

        # Seed initial database if empty on fresh cloud deployment
        if not application.config.get("TESTING"):
            try:
                from models import Organization
                if not Organization.query.first():
                    from init_db import init_and_seed_database
                    init_and_seed_database()
            except Exception as _seed_err:
                application.logger.warning(f"Database auto-seed check: {_seed_err}")

        storage_instance = Storage()
        engine_instance = AutomationEngine(storage=storage_instance)
        application.config["STORAGE_ENGINE"] = storage_instance
        application.config["AUTOMATION_ENGINE"] = engine_instance

    # Register API v1 Blueprint
    application.register_blueprint(api_v1)

    # Security Headers Middleware
    @application.after_request
    def add_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        csp = (
            "default-src 'self' 'unsafe-inline' 'unsafe-eval' https://fonts.googleapis.com https://fonts.gstatic.com https://cdn.jsdelivr.net; "
            "img-src 'self' data:; "
            "connect-src 'self';"
        )
        response.headers["Content-Security-Policy"] = csp
        if application.config.get("SESSION_COOKIE_SECURE"):
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

    # Global Health Check (Render, K8s, Cloud Load Balancers)
    @application.route("/health", methods=["GET"])
    def root_health_check():
        db_uri = application.config.get("SQLALCHEMY_DATABASE_URI", "")
        dialect = "postgresql" if "postgres" in db_uri else "sqlite_wal"
        eng = application.config.get("AUTOMATION_ENGINE")
        return jsonify({
            "status": "healthy",
            "service": "opsflow-enterprise",
            "database": dialect,
            "engine_online": eng.is_running if eng else True,
            "timestamp": datetime.datetime.utcnow().isoformat(),
            "version": "2.4.0-enterprise"
        }), 200

    # Frontend Dashboard View
    @application.route("/")
    def index():
        if "user_id" not in session and not session.get("logged_out"):
            admin_user = User.query.filter_by(email="admin@opsflow.io").first()
            if admin_user:
                membership = Membership.query.filter_by(user_id=admin_user.id).first()
                session["user_id"] = admin_user.id
                if membership:
                    session["active_org_id"] = membership.organization_id
                    session["org_id"] = membership.organization_id
        return render_template("index.html")

    # Top-Level Authentication Endpoints
    @application.route("/login", methods=["GET", "POST"])
    def top_level_login():
        if request.method == "POST":
            from api_v1 import auth_login
            return auth_login()
        return render_template("index.html")

    @application.route("/register", methods=["GET", "POST"])
    def top_level_register():
        if request.method == "POST":
            from api_v1 import auth_register
            return auth_register()
        return render_template("index.html")

    # ==========================================
    # Backward-Compatible Legacy Endpoints
    # ==========================================

    @application.route("/api/status", methods=["GET"])
    @require_auth
    def legacy_status():
        st = application.config.get("STORAGE_ENGINE")
        eng = application.config.get("AUTOMATION_ENGINE")
        stats = st.get_stats() if st else {}
        metrics = eng.telemetry.get_metrics() if eng else {}
        return jsonify({
            "engine_running": eng.is_running if eng else False,
            "stats": stats,
            "telemetry": metrics,
            "uptime": metrics.get("uptime_formatted")
        })

    @application.route("/api/engine/toggle", methods=["POST"])
    @require_auth
    def legacy_toggle_engine():
        eng = application.config.get("AUTOMATION_ENGINE")
        data = request.get_json(silent=True) or {}
        desired_state = data.get("online")
        new_state = eng.toggle_state(desired_state) if eng else False
        return jsonify({
            "success": True,
            "engine_running": new_state,
            "message": f"Automation Engine is now {'ONLINE' if new_state else 'PAUSED'}."
        })

    @application.route("/api/telemetry", methods=["GET"])
    @require_auth
    def legacy_telemetry():
        eng = application.config.get("AUTOMATION_ENGINE")
        return jsonify(eng.telemetry.get_metrics() if eng else {})

    @application.route("/api/rules", methods=["GET"])
    @application.route("/api/workflows", methods=["GET"])
    @require_auth
    def legacy_list_rules():
        st = application.config.get("STORAGE_ENGINE")
        category = request.args.get("category")
        enabled_only = request.args.get("enabled", "").lower() == "true"
        rules = st.get_rules(category=category, enabled_only=enabled_only) if st else []
        return jsonify({"rules": rules, "workflows": rules, "count": len(rules)})

    @application.route("/api/rules/<rule_id>", methods=["GET"])
    @application.route("/api/workflows/<rule_id>", methods=["GET"])
    @require_auth
    def legacy_get_rule(rule_id: str):
        st = application.config.get("STORAGE_ENGINE")
        rule = st.get_rule(rule_id) if st else None
        if not rule:
            return jsonify({"error": f"Rule '{rule_id}' not found."}), 404
        return jsonify({"rule": rule, "workflow": rule})

    @application.route("/api/rules", methods=["POST"])
    @application.route("/api/workflows", methods=["POST"])
    @require_auth
    def legacy_create_rule():
        st = application.config.get("STORAGE_ENGINE")
        rule_data = request.get_json(silent=True)
        if not rule_data or not isinstance(rule_data, dict):
            return jsonify({"error": "Invalid JSON payload."}), 400

        name = rule_data.get("name")
        if not name or not name.strip():
            return jsonify({"error": "Rule name is required."}), 400

        org = getattr(g, "current_org", None)
        if org:
            allowed, violation = check_resource_quota(org, "rules", delta=1)
            if not allowed:
                return jsonify({
                    "error": "Rule limit exceeded for your current plan.",
                    "code": "PLAN_LIMIT_EXCEEDED",
                    "plan": org.plan_tier.upper(),
                    "quota": violation
                }), 403

        rule_id = st.save_rule(rule_data, organization_id=org.id if org else None)
        saved_rule = st.get_rule(rule_id)
        return jsonify({
            "success": True,
            "message": "Rule saved successfully.",
            "rule_id": rule_id,
            "rule": saved_rule,
            "workflow": saved_rule
        }), 201

    @application.route("/api/rules/<rule_id>", methods=["PUT"])
    @application.route("/api/workflows/<rule_id>", methods=["PUT"])
    @require_auth
    def legacy_update_rule(rule_id: str):
        st = application.config.get("STORAGE_ENGINE")
        rule_data = request.get_json(silent=True)
        if not rule_data or not isinstance(rule_data, dict):
            return jsonify({"error": "Invalid JSON payload."}), 400

        rule_data["id"] = rule_id
        st.save_rule(rule_data)
        updated = st.get_rule(rule_id)
        return jsonify({"success": True, "rule": updated, "workflow": updated})

    @application.route("/api/rules/<rule_id>", methods=["DELETE"])
    @application.route("/api/workflows/<rule_id>", methods=["DELETE"])
    @require_auth
    def legacy_delete_rule(rule_id: str):
        st = application.config.get("STORAGE_ENGINE")
        success = st.delete_rule(rule_id)
        if not success:
            return jsonify({"error": f"Rule '{rule_id}' not found."}), 404
        return jsonify({"success": True, "message": f"Rule '{rule_id}' deleted."})

    @application.route("/api/rules/<rule_id>/toggle", methods=["POST"])
    @application.route("/api/workflows/<rule_id>/toggle", methods=["POST"])
    @require_auth
    def legacy_toggle_rule(rule_id: str):
        st = application.config.get("STORAGE_ENGINE")
        data = request.get_json(silent=True) or {}
        new_state = st.toggle_rule(rule_id, data.get("enabled"))
        if new_state is None:
            return jsonify({"error": f"Rule '{rule_id}' not found."}), 404
        return jsonify({"success": True, "enabled": new_state})

    @application.route("/api/rules/<rule_id>/run", methods=["POST"])
    @application.route("/api/rules/<rule_id>/execute", methods=["POST"])
    @application.route("/api/workflows/<rule_id>/run", methods=["POST"])
    @application.route("/api/workflows/<rule_id>/execute", methods=["POST"])
    @require_auth
    def legacy_run_rule(rule_id: str):
        eng = application.config.get("AUTOMATION_ENGINE")
        data = request.get_json(silent=True) or {}
        custom_payload = data.get("payload", {})
        dry_run = bool(data.get("dry_run", False))
        result = eng.execute_rule_manually(rule_id, custom_payload, dry_run=dry_run)
        return jsonify(result)

    @application.route("/api/events/dispatch", methods=["POST"])
    @require_auth
    def legacy_dispatch_event():
        eng = application.config.get("AUTOMATION_ENGINE")
        data = request.get_json(silent=True)
        if not data or not isinstance(data, dict):
            return jsonify({"error": "Invalid event payload."}), 400

        event_name = data.get("event_name") or data.get("event") or "custom.event"
        payload = data.get("payload")
        if payload is None:
            payload = {k: v for k, v in data.items() if k not in ("event", "event_name", "source", "dry_run")}

        source = data.get("source", "api_dispatch")
        dry_run = bool(data.get("dry_run", False))

        org = getattr(g, "current_org", None)
        if not dry_run and org:
            quota_ok, violation = check_resource_quota(org, "monthly_events", delta=1)
            if not quota_ok:
                return jsonify({
                    "error": "Monthly event quota exceeded.",
                    "code": "QUOTA_EXCEEDED",
                    "plan": org.plan_tier.upper(),
                    "quota": violation
                }), 429

        result = eng.ingest_event(
            event_name=event_name,
            payload=payload,
            source=source,
            dry_run=dry_run
        )

        if not dry_run and org:
            QuotaService.record_event(org, event_name, payload, source=source)

        return jsonify(result)

    @application.route("/api/nlp/analyze", methods=["POST"])
    @require_auth
    def legacy_nlp_analyze():
        eng = application.config.get("AUTOMATION_ENGINE")
        data = request.get_json(silent=True) or {}
        text = data.get("text", "")
        dry_run = bool(data.get("dry_run", True))

        if not text.strip():
            return jsonify({"error": "Text prompt cannot be empty."}), 400

        nlp_result = eng.nlp.parse(text)

        event_name = "user.prompt"
        intent = nlp_result.get("intent")
        text_lower = text.lower()
        entities = nlp_result.get("entities", {})

        if intent in ("lead_inquiry", "sales"):
            event_name = "lead.created"
        elif intent == "server_alert" or any(w in text_lower for w in ("cpu", "metrics", "sentinel", "utilization", "load", "memory")):
            event_name = "system.metrics"
        elif intent == "security_threat" or entities.get("ipv4"):
            event_name = "auth.failed"
        elif intent == "backup_request":
            event_name = "backup.completed"
        elif intent == "deploy_request":
            event_name = "deploy.pipeline"
        elif entities.get("http_status"):
            event_name = "api.error"

        ingest_result = eng.ingest_event(
            event_name=event_name,
            payload={
                "text": text,
                "message": text,
                "prompt": text,
                "intent": nlp_result.get("intent"),
                "urgency": nlp_result.get("urgency")
            },
            source="nlp_sandbox",
            dry_run=dry_run
        )

        return jsonify({
            "nlp": nlp_result,
            "simulation": ingest_result
        })

    @application.route("/api/events/stream", methods=["GET"])
    @require_auth
    def legacy_event_stream():
        eng = application.config.get("AUTOMATION_ENGINE")
        return jsonify({"events": eng.event_stream if eng else []})

    @application.route("/api/logs", methods=["GET"])
    @application.route("/api/executions", methods=["GET"])
    @require_auth
    def legacy_get_logs():
        st = application.config.get("STORAGE_ENGINE")
        limit = int(request.args.get("limit", 50))
        offset = int(request.args.get("offset", 0))
        status_val = request.args.get("status")
        rule_id = request.args.get("rule_id")

        logs = st.get_logs(limit=limit, offset=offset, status=status_val, rule_id=rule_id) if st else []
        return jsonify({"logs": logs, "executions": logs, "count": len(logs)})

    @application.route("/api/logs", methods=["DELETE"])
    @application.route("/api/executions", methods=["DELETE"])
    @require_auth
    def legacy_clear_logs():
        st = application.config.get("STORAGE_ENGINE")
        if st:
            st.clear_logs()
        return jsonify({"success": True, "message": "Execution logs cleared."})

    @application.route("/api/notifications", methods=["GET"])
    @require_auth
    def legacy_get_notifications():
        st = application.config.get("STORAGE_ENGINE")
        unread_only = request.args.get("unread", "").lower() == "true"
        limit = int(request.args.get("limit", 30))
        notifications = st.get_notifications(limit=limit, unread_only=unread_only) if st else []
        return jsonify({"notifications": notifications, "count": len(notifications)})

    @application.route("/api/notifications/read", methods=["POST"])
    @require_auth
    def legacy_mark_notifications_read():
        st = application.config.get("STORAGE_ENGINE")
        if st:
            st.mark_notifications_read()
        return jsonify({"success": True})

    @application.route("/api/notifications", methods=["DELETE"])
    @require_auth
    def legacy_clear_notifications():
        st = application.config.get("STORAGE_ENGINE")
        if st:
            st.clear_notifications()
        return jsonify({"success": True})

    @application.route("/api/presets", methods=["GET"])
    @application.route("/api/templates", methods=["GET"])
    @require_auth
    def legacy_get_presets():
        return jsonify({"presets": PRESET_BLUEPRINTS, "templates": PRESET_BLUEPRINTS})

    @application.route("/api/presets/install", methods=["POST"])
    @require_auth
    def legacy_install_preset():
        st = application.config.get("STORAGE_ENGINE")
        data = request.get_json(silent=True) or {}
        preset_id = data.get("preset_id") or data.get("template_id")

        selected = next((p for p in PRESET_BLUEPRINTS if p["id"] == preset_id), None)
        if not selected:
            return jsonify({"error": f"Preset '{preset_id}' not found."}), 404

        org = getattr(g, "current_org", None)
        if org:
            allowed, violation = check_resource_quota(org, "rules", delta=1)
            if not allowed:
                return jsonify({
                    "error": "Rule limit exceeded for your current plan.",
                    "code": "PLAN_LIMIT_EXCEEDED",
                    "plan": org.plan_tier.upper(),
                    "quota": violation
                }), 403

        new_rule = dict(selected)
        new_rule["id"] = f"rule-{int(os.times()[4] * 1000)}" if hasattr(os, "times") else f"rule-{os.urandom(4).hex()}"
        new_rule["enabled"] = 1
        new_rule["name"] = f"{selected['name']}"

        rule_id = st.save_rule(new_rule, organization_id=org.id if org else None)
        return jsonify({
            "success": True,
            "message": f"Blueprint '{selected['name']}' installed successfully.",
            "rule_id": rule_id
        }), 201

    @application.route("/api/leads", methods=["GET"])
    @require_auth
    def legacy_get_leads():
        st = application.config.get("STORAGE_ENGINE")
        status_val = request.args.get("status")
        search_val = request.args.get("search")
        leads = st.get_leads(status=status_val, search=search_val) if st else []
        return jsonify({"leads": leads, "count": len(leads)})

    @application.route("/api/analytics", methods=["GET"])
    @require_auth
    def legacy_get_analytics():
        st = application.config.get("STORAGE_ENGINE")
        analytics = st.get_analytics_summary() if st else {}
        return jsonify({"analytics": analytics})

    @application.route("/api/export", methods=["GET"])
    @require_auth
    def legacy_export_rules():
        org = getattr(g, "current_org", None)
        if org:
            allowed, required_tier = check_feature_entitlement(org, "export_rules")
            if not allowed:
                return jsonify({
                    "error": "This feature is not available on your current plan.",
                    "code": "FEATURE_NOT_AVAILABLE",
                    "plan": org.plan_tier.upper(),
                    "feature": "export_rules",
                    "required_plan": required_tier.upper()
                }), 403

        st = application.config.get("STORAGE_ENGINE")
        rules = st.get_rules() if st else []
        export_payload = {
            "version": "2.4",
            "exported_at": str(os.environ.get("CURRENT_TIME", "")),
            "rules": rules
        }
        return Response(
            json.dumps(export_payload, indent=2),
            mimetype="application/json",
            headers={"Content-Disposition": "attachment;filename=opsflow_rules.json"}
        )

    @application.route("/api/import", methods=["POST"])
    @require_auth
    def legacy_import_rules():
        st = application.config.get("STORAGE_ENGINE")
        data = request.get_json(silent=True)
        if not data or "rules" not in data or not isinstance(data["rules"], list):
            return jsonify({"error": "Invalid format. Expected JSON with 'rules' array."}), 400

        org = getattr(g, "current_org", None)
        if org:
            allowed, violation = check_resource_quota(org, "rules", delta=len(data["rules"]))
            if not allowed:
                return jsonify({
                    "error": "Rule limit exceeded for your current plan.",
                    "code": "PLAN_LIMIT_EXCEEDED",
                    "plan": org.plan_tier.upper(),
                    "quota": violation
                }), 403

        imported_count = 0
        for r in data["rules"]:
            if isinstance(r, dict) and "name" in r:
                st.save_rule(r, organization_id=org.id if org else None)
                imported_count += 1

        return jsonify({
            "success": True,
            "message": f"Successfully imported {imported_count} rules."
        })

    # Error Handlers
    @application.errorhandler(400)
    def handle_bad_request(e):
        return jsonify({
            "error": "Bad Request",
            "message": "The request payload or parameters were invalid.",
            "code": "BAD_REQUEST"
        }), 400

    @application.errorhandler(401)
    def handle_unauthorized(e):
        return jsonify({
            "error": "Unauthorized",
            "message": "Authentication required. Please log in or provide a valid API key.",
            "code": "UNAUTHORIZED"
        }), 401

    @application.errorhandler(403)
    def handle_forbidden(e):
        return jsonify({
            "error": "Forbidden",
            "message": "You do not have permission to perform this action.",
            "code": "FORBIDDEN"
        }), 403

    @application.errorhandler(404)
    def handle_not_found(e):
        if request.path.startswith("/api"):
            return jsonify({
                "error": "Resource Not Found",
                "path": request.path,
                "code": "NOT_FOUND"
            }), 404
        return render_template("index.html"), 404

    @application.errorhandler(429)
    def handle_too_many_requests(e):
        return jsonify({
            "error": "Too Many Requests",
            "message": "Rate limit exceeded. Please retry after some time.",
            "code": "TOO_MANY_REQUESTS"
        }), 429

    @application.errorhandler(500)
    def handle_server_error(e):
        return jsonify({
            "error": "Internal Server Error",
            "message": "An internal server error occurred.",
            "code": "INTERNAL_SERVER_ERROR"
        }), 500

    @application.errorhandler(Exception)
    def handle_unhandled_exception(e):
        application.logger.error("Unhandled Exception: %s", e, exc_info=True)
        return jsonify({
            "error": "Internal Server Error",
            "message": "An internal server error occurred.",
            "code": "INTERNAL_SERVER_ERROR"
        }), 500

    return application


# Global WSGI application instance for Gunicorn (`gunicorn app:app`)
app = create_app()

# Expose global storage and engine for backwards compatibility with test fixtures
storage = app.config.get("STORAGE_ENGINE")
engine = app.config.get("AUTOMATION_ENGINE")


if __name__ == "__main__":
    # Render cloud platform dynamically binds PORT via environment
    port = int(os.environ.get("PORT", 5000))
    debug_mode = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug_mode)
