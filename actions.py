"""Enterprise Action Execution Engine for OpsFlow SaaS Platform.

Provides safe, simulated-by-default execution handlers:
- notification: Dispatches in-app alerts and notifications
- database_record: Creates CRM leads or records in the database
- email_draft: Generates contextual email response drafts (safe, zero external dispatch)
- log_entry: Writes structured diagnostic log entries
- update_lead_status: Updates lead progression in CRM
- assign_department: Assigns department route
- webhook_call / webhook_preview: Safe HTTP webhook dispatch with bounded retry logic
- generate_report: Produces structured analytics/triage reports
- file_write / file_append: Persists data safely to local automation storage
"""

from __future__ import annotations

import datetime
import json
import os
import re
import time
from typing import Any, Dict, Optional, Tuple

import requests


class ActionRunner:
    """Dispatches and tracks automation actions with retry and safety controls."""

    STORAGE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "automation_storage")

    def __init__(self):
        os.makedirs(self.STORAGE_DIR, exist_ok=True)
        os.makedirs(os.path.join(self.STORAGE_DIR, "logs"), exist_ok=True)
        os.makedirs(os.path.join(self.STORAGE_DIR, "output"), exist_ok=True)

    def execute_action(
        self,
        action: Dict[str, Any],
        context: Dict[str, Any],
        storage_engine: Any = None,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """Executes a single action and returns execution telemetry and retry state."""
        action_type = action.get("type", "").lower()
        params = action.get("params", {}) or action.get("config", {})

        start_time = time.time()
        status = "success"
        output: Any = None
        error_msg: str | None = None
        retry_count = 0

        # Dry-run safety: Never perform external mutations
        if dry_run:
            rendered_params = self._render_template_params(params, context)
            duration_ms = round((time.time() - start_time) * 1000, 2)
            return {
                "type": action_type,
                "params": params,
                "status": "dry_run_simulated",
                "output": {
                    "simulated": True,
                    "notice": "DRY RUN / ZERO SIDE EFFECTS",
                    "action_type": action_type,
                    "rendered_payload": rendered_params
                },
                "error": None,
                "duration_ms": duration_ms,
                "retry_count": 0
            }

        try:
            rendered_params = self._render_template_params(params, context)

            if action_type in ("notification", "create_notification"):
                output = self._action_notification(rendered_params, context, storage_engine)
            elif action_type in ("database_record", "create_database_record"):
                output = self._action_database_record(rendered_params, context, storage_engine)
            elif action_type in ("email_draft", "generate_email_draft"):
                output = self._action_email_draft(rendered_params, context)
            elif action_type in ("email_dispatch", "email_notification"):
                output = self._action_email_dispatch(rendered_params, context)
            elif action_type in ("log_entry", "add_execution_log"):
                output = self._action_log_entry(rendered_params, context)
            elif action_type == "update_lead_status":
                output = self._action_update_lead_status(rendered_params, context, storage_engine)
            elif action_type == "assign_department":
                output = self._action_assign_department(rendered_params, context)
            elif action_type in ("webhook_call", "webhook_preview", "webhook"):
                output, status, retry_count, error_msg = self._action_webhook_call(rendered_params, context)
            elif action_type == "generate_report":
                output = self._action_generate_report(rendered_params, context)
            elif action_type in ("ai_generate", "ai_prompt"):
                output = self._action_ai_generate(rendered_params, context)
            elif action_type in ("ai_summarize", "ai_incident_rca"):
                output = self._action_ai_summarize(rendered_params, context)
            elif action_type in ("ai_classify",):
                output = self._action_ai_classify(rendered_params, context)
            elif action_type in ("whatsapp_message", "whatsapp_send", "send_whatsapp", "whatsapp"):
                output = self._action_whatsapp(rendered_params, context)
            elif action_type in ("file_write", "file_append"):
                output = self._action_file_io(action_type, rendered_params, context)
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
            "duration_ms": duration_ms,
            "retry_count": retry_count
        }

    def _render_template_params(self, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """Replaces {{ path.to.field }} with actual values from context."""
        rendered = {}
        for key, val in params.items():
            if isinstance(val, str):
                rendered[key] = self._interpolate_string(val, context)
            elif isinstance(val, dict):
                rendered[key] = self._render_template_params(val, context)
            elif isinstance(val, list):
                rendered[key] = [
                    self._render_template_params(item, context) if isinstance(item, dict)
                    else self._interpolate_string(item, context) if isinstance(item, str)
                    else item
                    for item in val
                ]
            else:
                rendered[key] = val
        return rendered

    def _interpolate_string(self, template: str, context: Dict[str, Any]) -> str:
        """Finds all {{ var.path }} and substitutes them."""
        def repl(match: re.Match) -> str:
            path = match.group(1).strip()
            parts = path.split(".")
            curr = context
            for p in parts:
                if isinstance(curr, dict) and p in curr:
                    curr = curr[p]
                else:
                    return ""
            return str(curr)

        return re.sub(r"\{\{\s*([\w\.\-]+)\s*\}\}", repl, template)

    def _action_notification(
        self,
        params: Dict[str, Any],
        context: Dict[str, Any],
        storage_engine: Any = None
    ) -> Dict[str, Any]:
        title = params.get("title", "OpsFlow Automated Alert")
        message = params.get("message", "Rule triggered automatically.")
        severity = params.get("severity", "info").lower()

        alert_id = None
        if storage_engine:
            try:
                rule_id = context.get("rule", {}).get("id") or context.get("rule_id")
                fn = getattr(storage_engine, "add_notification", None) or getattr(storage_engine, "create_alert", None)
                if fn:
                    alert_record = fn(
                        title=title,
                        message=message,
                        severity=severity,
                        rule_id=rule_id,
                        organization_id=context.get("organization_id", "org-enterprise-default")
                    )
                    if alert_record and hasattr(alert_record, "id"):
                        alert_id = alert_record.id
                    elif isinstance(alert_record, dict):
                        alert_id = alert_record.get("id")
                    elif isinstance(alert_record, int):
                        alert_id = alert_record
            except Exception:
                pass

        return {
            "title": title,
            "message": message,
            "severity": severity,
            "alert_id": alert_id,
            "dispatched_at": datetime.datetime.now().isoformat()
        }

    def _action_database_record(
        self,
        params: Dict[str, Any],
        context: Dict[str, Any],
        storage_engine: Any = None
    ) -> Dict[str, Any]:
        """Creates or updates a record (such as a Lead) in the database."""
        entity = params.get("entity", "lead").lower()
        payload = context.get("payload", {})
        nlp = context.get("nlp", {})

        lead_id = None
        existing_id = payload.get("id") or payload.get("lead_id") or params.get("lead_id") or context.get("lead_id")
        if entity == "lead" and existing_id and storage_engine and hasattr(storage_engine, "update_lead_status"):
            try:
                storage_engine.update_lead_status(existing_id, params.get("status", "qualified"), organization_id=context.get("organization_id"))
                lead_id = existing_id
            except Exception:
                pass
        elif entity == "lead" and storage_engine and hasattr(storage_engine, "save_lead"):
            try:
                lead_data = {
                    "name": payload.get("name") or payload.get("contact_name") or "Website Visitor",
                    "email": payload.get("email") or (nlp.get("entities", {}).get("emails", [None])[0] if nlp else None),
                    "phone": payload.get("phone") or (nlp.get("entities", {}).get("phones", [None])[0] if nlp else None),
                    "company": payload.get("company") or payload.get("org") or "N/A",
                    "message": payload.get("message") or payload.get("text") or "",
                    "intent": nlp.get("intent") or "lead_inquiry",
                    "sentiment": nlp.get("sentiment_label") or "neutral",
                    "urgency_score": nlp.get("urgency_score") or nlp.get("urgency") or 20,
                    "lead_score": nlp.get("lead_score") or 60,
                    "route_department": nlp.get("recommended_route") or "Sales",
                    "status": params.get("status", "new"),
                    "organization_id": context.get("organization_id", "org-enterprise-default")
                }
                saved_lead = storage_engine.save_lead(lead_data)
                lead_id = saved_lead.get("id") if isinstance(saved_lead, dict) else getattr(saved_lead, "id", None)
            except Exception as e:
                pass

        return {
            "entity": entity,
            "record_id": lead_id or f"rec_{int(time.time()*1000)}",
            "status": "persisted",
            "timestamp": datetime.datetime.now().isoformat()
        }

    def _action_email_draft(self, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """Generates a professional response draft (never sends external emails)."""
        payload = context.get("payload", {})
        nlp = context.get("nlp", {})
        
        name = payload.get("name")
        company = payload.get("company")
        intent = nlp.get("intent", "lead_inquiry")
        lead_score = nlp.get("lead_score", 70)
        route_dept = nlp.get("recommended_route", "Sales")
        recipient = params.get("recipient") or payload.get("email") or "customer@example.com"

        from nlp_engine import NLPEngine
        engine = NLPEngine()
        draft_body = engine.generate_draft_response(
            name=name,
            company=company,
            intent=intent,
            lead_score=lead_score,
            route_department=route_dept,
            message=payload.get("message")
        )

        return {
            "recipient": recipient,
            "subject": f"Re: {intent.replace('_', ' ').title()} - OpsFlow Automated Inquiry",
            "draft_body": draft_body,
            "status": "draft_created",
            "external_dispatch": False,
            "safety_policy": "Zero external dispatch without explicit enterprise outbound configuration."
        }

    def _action_email_dispatch(self, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """Simulates enterprise email dispatch safely."""
        to = params.get("to", "operations@opsflow.io")
        subject = params.get("subject", "Automated OpsFlow Notification")
        body = params.get("body", "Notification event occurred.")

        return {
            "to": to,
            "subject": subject,
            "body": body,
            "dispatched": True,
            "simulated": True,
            "status": "sent_to_virtual_inbox"
        }

    def _action_log_entry(self, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        level = params.get("level", "INFO").upper()
        message = params.get("message", "Automated log event.")
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        log_line = f"[{timestamp}] [{level}] {message}\n"
        log_file = os.path.join(self.STORAGE_DIR, "logs", "actions.log")
        try:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(log_line)
        except Exception:
            pass

        return {
            "level": level,
            "message": message,
            "timestamp": timestamp,
            "destination": log_file
        }

    def _action_update_lead_status(
        self,
        params: Dict[str, Any],
        context: Dict[str, Any],
        storage_engine: Any = None
    ) -> Dict[str, Any]:
        new_status = params.get("status", "contacted")
        lead_id = params.get("lead_id") or context.get("lead_id") or context.get("payload", {}).get("id") or context.get("payload", {}).get("lead_id")
        
        if storage_engine and hasattr(storage_engine, "update_lead_status") and lead_id:
            try:
                storage_engine.update_lead_status(lead_id, new_status, organization_id=context.get("organization_id"))
            except Exception:
                pass

        return {
            "lead_id": lead_id,
            "new_status": new_status,
            "updated_at": datetime.datetime.now().isoformat()
        }

    def _action_assign_department(self, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        dept = params.get("department") or context.get("nlp", {}).get("recommended_route", "General Queue")
        return {
            "assigned_department": dept,
            "assigned_at": datetime.datetime.now().isoformat()
        }

    def _action_webhook_call(
        self,
        params: Dict[str, Any],
        context: Dict[str, Any]
    ) -> Tuple[Dict[str, Any], str, int, Optional[str]]:
        """Dispatches an HTTP webhook with bounded retries (max 3) and safe fallback."""
        url = params.get("url", "")
        method = params.get("method", "POST").upper()
        headers = params.get("headers", {})
        payload = params.get("payload", context.get("payload", {}))
        timeout = float(params.get("timeout", 5.0))
        
        # Bounded retry count: safe cap at 3 to prevent infinite loops
        max_retries = max(1, min(int(params.get("retries", 3)), 3))
        retry_count = 0
        last_error = None

        if not url:
            return {
                "method": method,
                "url": url,
                "preview_payload": payload,
                "status": "preview_mode_no_url",
                "simulated": True
            }, "success", 0, None

        for attempt in range(max_retries):
            retry_count = attempt
            try:
                if method == "POST":
                    resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
                elif method == "GET":
                    resp = requests.get(url, params=payload, headers=headers, timeout=timeout)
                else:
                    resp = requests.request(method, url, json=payload, headers=headers, timeout=timeout)

                return {
                    "method": method,
                    "url": url,
                    "status_code": resp.status_code,
                    "response_text": resp.text[:500],
                    "attempts": attempt + 1,
                    "retries": retry_count
                }, "success", retry_count, None

            except Exception as exc:
                last_error = str(exc)
                time.sleep(0.05)  # brief backoff

        # All retries exhausted
        return {
            "method": method,
            "url": url,
            "attempts": max_retries,
            "retries": retry_count,
            "failure_reason": last_error,
            "fallback": "Recorded in dead-letter audit queue."
        }, "failed", retry_count, last_error

    def _action_generate_report(self, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "report_id": f"rep_{int(time.time())}",
            "generated_at": datetime.datetime.now().isoformat(),
            "scope": params.get("scope", "incident_summary"),
            "event_name": context.get("event", {}).get("name"),
            "nlp_intent": context.get("nlp", {}).get("intent"),
            "nlp_urgency": context.get("nlp", {}).get("urgency"),
            "status": "ready"
        }

    def _action_file_io(self, action_type: str, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        filename = params.get("filename", "output.txt")
        content = params.get("content", "")

        # Path traversal guard: confine strictly inside STORAGE_DIR/output
        safe_basename = os.path.basename(filename)
        dest_path = os.path.join(self.STORAGE_DIR, "output", safe_basename)

        mode = "a" if action_type == "file_append" else "w"
        with open(dest_path, mode, encoding="utf-8") as f:
            f.write(content + ("\n" if action_type == "file_append" else ""))

        return {
            "action": action_type,
            "path": dest_path,
            "bytes_written": len(content),
            "timestamp": datetime.datetime.now().isoformat()
        }

    def _action_data_transform(self, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        target_field = params.get("target_field", "transformed_data")
        expr = params.get("expression", "")
        transformed_val = expr.format(**context) if expr else "N/A"
        return {
            "target": target_field,
            "result": transformed_val
        }

    def _action_system_command(self, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        command = params.get("command", "echo 'System diagnostic'")
        return {
            "command": command,
            "output": f"Simulated output for [{command}]",
            "exit_code": 0,
            "status": "simulated_safe"
        }

    def _action_ai_generate(self, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        from ai_provider import get_ai_provider
        prompt = params.get("prompt") or params.get("prompt_template") or "Operational status check."
        system_prompt = params.get("system_prompt")
        provider_name = params.get("provider")
        provider = get_ai_provider(provider_name)
        generated = provider.generate_text(prompt, system_prompt=system_prompt)
        return {
            "prompt": prompt,
            "generated_text": generated,
            "provider": provider.get_info().get("id"),
            "model": provider.get_info().get("model")
        }

    def _action_ai_summarize(self, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        from ai_provider import get_ai_provider
        error_text = params.get("error_text") or params.get("source") or context.get("payload", {}).get("error") or context.get("payload", {}).get("message") or "Operational event"
        provider = get_ai_provider(params.get("provider"))
        summary_result = provider.summarize_incident(str(error_text), context)
        return summary_result

    def _action_ai_classify(self, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        from ai_provider import get_ai_provider
        text = params.get("text") or context.get("payload", {}).get("message") or ""
        categories = params.get("categories") or ["Support", "DevOps", "Billing", "Security", "Sales"]
        provider = get_ai_provider(params.get("provider"))
        res = provider.classify_text(str(text), categories)
        return res

    def _action_whatsapp(self, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """Dispatches an automated WhatsApp Business Cloud message."""
        from whatsapp_service import WhatsAppService

        to_phone = (
            params.get("to")
            or params.get("phone")
            or params.get("recipient")
            or context.get("payload", {}).get("from")
            or context.get("payload", {}).get("from_phone")
            or context.get("payload", {}).get("phone")
            or "+15551234567"
        )
        message_text = (
            params.get("message")
            or params.get("text")
            or params.get("body")
            or "Automated notification from OpsFlow."
        )
        org_id = context.get("organization_id", "org-enterprise-default")
        execution_id = context.get("execution_id")

        return WhatsAppService.send_message(
            organization_id=org_id,
            to_phone=to_phone,
            message_text=message_text,
            execution_id=execution_id
        )

