"""AI Automation Command Center Flask Application.

Provides RESTful APIs and UI dashboard for local rule-based automation,
offline NLP parsing, telemetry monitoring, and execution auditing.
"""

from __future__ import annotations

import json
import os
from flask import Flask, jsonify, render_template, request, Response

from automation_engine import AutomationEngine
from presets import PRESET_BLUEPRINTS
from storage import Storage

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "command-center-local-key-2026")

# Initialize persistence and engine
storage = Storage()
engine = AutomationEngine(storage=storage)


# ==========================================
# Frontend Dashboard View
# ==========================================

@app.route("/")
def index():
    return render_template("index.html")


# ==========================================
# Engine & System Telemetry Endpoints
# ==========================================

@app.route("/api/status", methods=["GET"])
def get_engine_status():
    stats = storage.get_stats()
    metrics = engine.telemetry.get_metrics()
    return jsonify({
        "engine_running": engine.is_running,
        "stats": stats,
        "telemetry": metrics,
        "uptime": metrics.get("uptime_formatted")
    })


@app.route("/api/engine/toggle", methods=["POST"])
def toggle_engine():
    data = request.get_json(silent=True) or {}
    desired_state = data.get("online")
    new_state = engine.toggle_state(desired_state)
    return jsonify({
        "success": True,
        "engine_running": new_state,
        "message": f"Automation Engine is now {'ONLINE' if new_state else 'PAUSED'}."
    })


@app.route("/api/telemetry", methods=["GET"])
def get_telemetry():
    return jsonify(engine.telemetry.get_metrics())


# ==========================================
# Rules Management Endpoints
# ==========================================

@app.route("/api/rules", methods=["GET"])
def list_rules():
    category = request.args.get("category")
    enabled_only = request.args.get("enabled", "").lower() == "true"
    rules = storage.get_rules(category=category, enabled_only=enabled_only)
    return jsonify({"rules": rules, "count": len(rules)})


@app.route("/api/rules/<rule_id>", methods=["GET"])
def get_rule_details(rule_id: str):
    rule = storage.get_rule(rule_id)
    if not rule:
        return jsonify({"error": f"Rule '{rule_id}' not found."}), 404
    return jsonify({"rule": rule})


@app.route("/api/rules", methods=["POST"])
def create_or_update_rule():
    rule_data = request.get_json(silent=True)
    if not rule_data or not isinstance(rule_data, dict):
        return jsonify({"error": "Invalid JSON payload."}), 400

    name = rule_data.get("name")
    if not name or not name.strip():
        return jsonify({"error": "Rule name is required."}), 400

    rule_id = storage.save_rule(rule_data)
    saved_rule = storage.get_rule(rule_id)
    return jsonify({
        "success": True,
        "message": "Rule saved successfully.",
        "rule_id": rule_id,
        "rule": saved_rule
    }), 201


@app.route("/api/rules/<rule_id>", methods=["PUT"])
def update_rule(rule_id: str):
    rule_data = request.get_json(silent=True)
    if not rule_data or not isinstance(rule_data, dict):
        return jsonify({"error": "Invalid JSON payload."}), 400

    rule_data["id"] = rule_id
    storage.save_rule(rule_data)
    updated = storage.get_rule(rule_id)
    return jsonify({"success": True, "rule": updated})


@app.route("/api/rules/<rule_id>", methods=["DELETE"])
def delete_rule(rule_id: str):
    success = storage.delete_rule(rule_id)
    if not success:
        return jsonify({"error": f"Rule '{rule_id}' not found."}), 404
    return jsonify({"success": True, "message": f"Rule '{rule_id}' deleted."})


@app.route("/api/rules/<rule_id>/toggle", methods=["POST"])
def toggle_rule(rule_id: str):
    data = request.get_json(silent=True) or {}
    new_state = storage.toggle_rule(rule_id, data.get("enabled"))
    if new_state is None:
        return jsonify({"error": f"Rule '{rule_id}' not found."}), 404
    return jsonify({"success": True, "enabled": new_state})


@app.route("/api/rules/<rule_id>/run", methods=["POST"])
def run_rule_manually(rule_id: str):
    data = request.get_json(silent=True) or {}
    custom_payload = data.get("payload", {})
    result = engine.execute_rule_manually(rule_id, custom_payload)
    return jsonify(result)


# ==========================================
# Event Ingestion & Simulation Endpoints
# ==========================================

@app.route("/api/events/dispatch", methods=["POST"])
def dispatch_event():
    data = request.get_json(silent=True)
    if not data or not isinstance(data, dict):
        return jsonify({"error": "Invalid event payload."}), 400

    event_name = data.get("event_name", "custom.event")
    payload = data.get("payload", {})
    source = data.get("source", "api_dispatch")
    dry_run = bool(data.get("dry_run", False))

    result = engine.ingest_event(
        event_name=event_name,
        payload=payload,
        source=source,
        dry_run=dry_run
    )
    return jsonify(result)


@app.route("/api/nlp/analyze", methods=["POST"])
def analyze_nlp_and_simulate():
    data = request.get_json(silent=True) or {}
    text = data.get("text", "")
    dry_run = bool(data.get("dry_run", True))

    if not text.strip():
        return jsonify({"error": "Text prompt cannot be empty."}), 400

    nlp_result = engine.nlp.parse(text)

    # Ingest as user.prompt
    ingest_result = engine.ingest_event(
        event_name="user.prompt",
        payload={
            "text": text,
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


@app.route("/api/events/stream", methods=["GET"])
def get_event_stream():
    return jsonify({"events": engine.event_stream})


# ==========================================
# Execution Audit Logs Endpoints
# ==========================================

@app.route("/api/logs", methods=["GET"])
def get_logs():
    limit = int(request.args.get("limit", 50))
    offset = int(request.args.get("offset", 0))
    status = request.args.get("status")
    rule_id = request.args.get("rule_id")

    logs = storage.get_logs(limit=limit, offset=offset, status=status, rule_id=rule_id)
    return jsonify({"logs": logs, "count": len(logs)})


@app.route("/api/logs", methods=["DELETE"])
def clear_logs():
    storage.clear_logs()
    return jsonify({"success": True, "message": "Execution logs cleared."})


# ==========================================
# In-App Alerts & Notifications
# ==========================================

@app.route("/api/notifications", methods=["GET"])
def get_notifications():
    unread_only = request.args.get("unread", "").lower() == "true"
    limit = int(request.args.get("limit", 30))
    notifications = storage.get_notifications(limit=limit, unread_only=unread_only)
    return jsonify({"notifications": notifications, "count": len(notifications)})


@app.route("/api/notifications/read", methods=["POST"])
def mark_notifications_read():
    storage.mark_notifications_read()
    return jsonify({"success": True})


@app.route("/api/notifications", methods=["DELETE"])
def clear_notifications():
    storage.clear_notifications()
    return jsonify({"success": True})


# ==========================================
# Preset Blueprints
# ==========================================

@app.route("/api/presets", methods=["GET"])
def get_presets():
    return jsonify({"presets": PRESET_BLUEPRINTS})


@app.route("/api/presets/install", methods=["POST"])
def install_preset():
    data = request.get_json(silent=True) or {}
    preset_id = data.get("preset_id")

    selected = next((p for p in PRESET_BLUEPRINTS if p["id"] == preset_id), None)
    if not selected:
        return jsonify({"error": f"Preset '{preset_id}' not found."}), 404

    # Clone preset as a new rule
    new_rule = dict(selected)
    new_rule["id"] = f"rule-{int(os.times()[4] * 1000)}" if hasattr(os, "times") else f"rule-{os.urandom(4).hex()}"
    new_rule["enabled"] = 1
    new_rule["name"] = f"{selected['name']}"

    rule_id = storage.save_rule(new_rule)
    return jsonify({
        "success": True,
        "message": f"Blueprint '{selected['name']}' installed successfully.",
        "rule_id": rule_id
    }), 201


# ==========================================
# Import / Export Rules
# ==========================================

@app.route("/api/export", methods=["GET"])
def export_rules():
    rules = storage.get_rules()
    export_payload = {
        "version": "1.0",
        "exported_at": str(os.environ.get("CURRENT_TIME", "")),
        "rules": rules
    }
    return Response(
        json.dumps(export_payload, indent=2),
        mimetype="application/json",
        headers={"Content-Disposition": "attachment;filename=command_center_rules.json"}
    )


@app.route("/api/import", methods=["POST"])
def import_rules():
    data = request.get_json(silent=True)
    if not data or "rules" not in data or not isinstance(data["rules"], list):
        return jsonify({"error": "Invalid format. Expected JSON with 'rules' array."}), 400

    imported_count = 0
    for r in data["rules"]:
        if isinstance(r, dict) and "name" in r:
            storage.save_rule(r)
            imported_count += 1

    return jsonify({
        "success": True,
        "message": f"Successfully imported {imported_count} rules."
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug_mode = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug_mode)
