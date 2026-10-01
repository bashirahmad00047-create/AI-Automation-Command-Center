"""Action Execution Engine for Rule Automations.

Provides built-in, secure, offline-first action handlers:
- notification: Dispatches in-app alerts and notifications
- log_entry: Writes structured diagnostic log entries
- file_write / file_append: Persists data safely to local storage
- email_dispatch: Simulates dispatching enterprise email alerts
- webhook_call: Simulates or triggers HTTP webhooks
- data_transform: Enriches or modifies data payloads
- system_command: Runs safe command diagnostics / simulations
"""

from __future__ import annotations

import datetime
import json
import os
import re
import time
from typing import Any, Dict, Tuple


class ActionRunner:
    """Dispatches and tracks automation actions."""

    STORAGE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "automation_storage")

    def __init__(self):
        os.makedirs(self.STORAGE_DIR, exist_ok=True)
        os.makedirs(os.path.join(self.STORAGE_DIR, "logs"), exist_ok=True)
        os.makedirs(os.path.join(self.STORAGE_DIR, "output"), exist_ok=True)

    def execute_action(
        self,
        action: Dict[str, Any],
        context: Dict[str, Any],
        storage_engine: Any = None
    ) -> Dict[str, Any]:
        """Executes a single action and returns execution telemetry."""
        action_type = action.get("type", "").lower()
        params = action.get("params", {})

        start_time = time.time()
        status = "success"
        output: Any = None
        error_msg: str | None = None

        try:
            # Template substitution in string parameters
            rendered_params = self._render_template_params(params, context)

            if action_type == "notification":
                output = self._action_notification(rendered_params, context, storage_engine)
            elif action_type == "log_entry":
                output = self._action_log_entry(rendered_params, context)
            elif action_type in ("file_write", "file_append"):
                output = self._action_file_io(action_type, rendered_params, context)
            elif action_type == "email_dispatch":
                output = self._action_email_dispatch(rendered_params, context)
            elif action_type == "webhook_call":
                output = self._action_webhook_call(rendered_params, context)
            elif action_type == "data_transform":
                output = self._action_data_transform(rendered_params, context)
            elif action_type == "system_command":
                output = self._action_system_command(rendered_params, context)
            else:
                status = "failed"
                error_msg = f"Unknown action type: '{action_type}'"

        except Exception as exc:
            status = "failed"
            error_msg = str(exc)

        duration_ms = round((time.time() - start_time) * 1000, 2)

        return {
            "type": action_type,
            "params": params,
            "status": status,
            "output": output,
            "error": error_msg,
            "duration_ms": duration_ms
        }

    def _render_template_params(self, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """Replaces {{ path.to.field }} with actual values from context."""
        rendered = {}
        for key, val in params.items():
            if isinstance(val, str):
                rendered[key] = self._interpolate_string(val, context)
            elif isinstance(val, dict):
                rendered[key] = self._render_template_params(val, context)
            else:
                rendered[key] = val
        return rendered

    def _interpolate_string(self, template: str, context: Dict[str, Any]) -> str:
        """Finds all {{ var.path }} and substitutes them."""
        def repl(match: re.Match) -> str:
            path = match.group(1).strip()
            # Simple resolver
            parts = path.split(".")
            curr = context
            for p in parts:
                if isinstance(curr, dict) and p in curr:
                    curr = curr[p]
                else:
                    return match.group(0)  # leave as is if not found
            return str(curr)

        return re.sub(r"\{\{\s*([a-zA-Z0-9_\.]+)\s*\}\}", repl, template)

    def _action_notification(
        self,
        params: Dict[str, Any],
        context: Dict[str, Any],
        storage_engine: Any = None
    ) -> Dict[str, Any]:
        title = params.get("title", "Command Center Alert")
        message = params.get("message", "Triggered automation alert.")
        severity = params.get("severity", "info").lower()

        notif_record = {
            "title": title,
            "message": message,
            "severity": severity,
            "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

        if storage_engine and hasattr(storage_engine, "add_notification"):
            storage_engine.add_notification(title, message, severity)

        return notif_record

    def _action_log_entry(self, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        level = params.get("level", "INFO").upper()
        message = params.get("message", "")
        log_file = os.path.join(self.STORAGE_DIR, "logs", "command_center_audit.log")

        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_line = f"[{timestamp}] [{level}] {message}\n"

        with open(log_file, "a", encoding="utf-8") as f:
            f.write(log_line)

        return {"level": level, "message": message, "file": log_file}

    def _action_file_io(
        self,
        mode: str,
        params: Dict[str, Any],
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        filename = params.get("filename", "output.txt")
        # Sanitize filename to prevent directory traversal
        clean_filename = os.path.basename(filename)
        if not clean_filename:
            clean_filename = "output.txt"

        filepath = os.path.join(self.STORAGE_DIR, "output", clean_filename)
        content = params.get("content", "")

        write_mode = "a" if mode == "file_append" else "w"
        with open(filepath, write_mode, encoding="utf-8") as f:
            if write_mode == "a":
                f.write(content + "\n")
            else:
                f.write(content)

        return {
            "mode": mode,
            "path": filepath,
            "bytes_written": len(content)
        }

    def _action_email_dispatch(self, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        recipient = params.get("to", "ops-team@company.internal")
        subject = params.get("subject", "Automated Security Alert")
        body = params.get("body", "Automation condition met.")

        # Local simulated email queue
        email_record = {
            "id": f"mail_{int(time.time() * 1000)}",
            "to": recipient,
            "subject": subject,
            "body": body,
            "status": "DISPATCHED_SIMULATED",
            "sent_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

        # Also write simulated email to storage mailbox file
        mail_log = os.path.join(self.STORAGE_DIR, "logs", "simulated_mailbox.jsonl")
        with open(mail_log, "a", encoding="utf-8") as f:
            f.write(json.dumps(email_record) + "\n")

        return email_record

    def _action_webhook_call(self, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        url = params.get("url", "https://api.internal/webhook")
        method = params.get("method", "POST").upper()
        payload = params.get("payload", {"event": context.get("event", {}), "triggered_at": time.time()})

        # Safe simulation of webhook
        return {
            "url": url,
            "method": method,
            "payload": payload,
            "status_code": 200,
            "simulated": True,
            "response": "Webhook payload received and queued."
        }

    def _action_data_transform(self, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        target_key = params.get("target_key", "transformed_data")
        transform_type = params.get("transform", "summarize")

        transformed_val: Any = None
        if transform_type == "summarize":
            transformed_val = f"Event Summary: severity={context.get('event', {}).get('severity', 'normal')}, rules_checked=1"
        elif transform_type == "tag":
            tag = params.get("tag", "PROCESSED_BY_COMMAND_CENTER")
            transformed_val = [tag]
        elif transform_type == "json_pack":
            transformed_val = json.dumps(context)
        else:
            transformed_val = params.get("value", "custom_transform")

        context[target_key] = transformed_val
        return {"key": target_key, "value": transformed_val}

    def _action_system_command(self, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        # Safe simulated command runner
        cmd = params.get("command", "echo 'Command Center Auto Diagnostic'")
        return {
            "command": cmd,
            "exit_code": 0,
            "simulated": True,
            "output": f"Diagnostic executed successfully at {datetime.datetime.now().isoformat()}"
        }
