"""Central Automation Engine Core for OpsFlow SaaS Platform.

Orchestrates:
- Visual step pipeline execution (Trigger -> AI Analysis -> Lead Scoring -> Routing -> Draft -> Record -> Webhook)
- Event ingestion & webhook dispatching
- Deterministic heuristic AI analysis & entity extraction
- Condition evaluation (AND/OR, dot notation, comparison operators)
- Bounded action retries & safe simulations
- Dry-run execution mode with "DRY RUN / ZERO SIDE EFFECTS" guarantees
- Real-time event streaming buffer & background sweeps
"""

from __future__ import annotations

import datetime
import json
import re
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from actions import ActionRunner
from ai_provider import get_ai_provider
from evaluator import ConditionEvaluator
from nlp_engine import NLPEngine
from storage import Storage
from telemetry import TelemetryMonitor


class AutomationEngine:
    """Core workflow execution engine, event broker, and step pipeline orchestrator."""

    def __init__(self, storage: Optional[Storage] = None):
        self.storage = storage or Storage()
        self.nlp = NLPEngine()
        self.evaluator = ConditionEvaluator()
        self.action_runner = ActionRunner()
        self.telemetry = TelemetryMonitor()

        self.is_running = True
        self._lock = threading.Lock()
        self._cooldown_tracker: Dict[str, float] = {}

        # In-memory circular buffer for real-time frontend streaming (last 50 events)
        self.event_stream: List[Dict[str, Any]] = []

        # Background worker thread for periodic automated health/sentinel evaluations
        self._worker_thread = threading.Thread(target=self._background_loop, daemon=True)
        self._worker_thread.start()

    def toggle_state(self, online: Optional[bool] = None) -> bool:
        with self._lock:
            if online is None:
                self.is_running = not self.is_running
            else:
                self.is_running = online
            return self.is_running

    def ingest_event(
        self,
        event_name: str,
        payload: Optional[Dict[str, Any]] = None,
        source: str = "manual",
        dry_run: bool = False,
        organization_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Ingests an event, matches active rules, evaluates conditions, and runs actions/steps."""
        payload = payload or {}
        now_dt = datetime.datetime.now()
        timestamp_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")
        org_id = organization_id or self.storage.get_default_org_id()

        # 1. AI & NLP parsing if payload contains text/prompt/message
        nlp_data: Dict[str, Any] = {}
        text_content = payload.get("text") or payload.get("message") or payload.get("prompt") or payload.get("query")
        if text_content and isinstance(text_content, str):
            ai_provider = get_ai_provider()
            nlp_data = ai_provider.analyze_text(text_content)
        elif event_name in ("user.prompt", "nlp.query", "chat.message"):
            ai_provider = get_ai_provider()
            nlp_data = ai_provider.analyze_text(str(payload.get("query", "")))

        # 1b. Synthesize / enrich payload fields from NLP entities if not explicitly provided
        enriched_payload = dict(payload)
        is_nlp_source = (event_name in ("user.prompt", "nlp.query", "chat.message") or source == "nlp_sandbox" or bool(nlp_data))
        if nlp_data and is_nlp_source:
            entities = nlp_data.get("entities", {})
            if "cpu_percent" not in enriched_payload:
                if entities.get("percentages"):
                    try:
                        pct_val = float(entities["percentages"][0])
                        enriched_payload["cpu_percent"] = pct_val
                        enriched_payload.setdefault("memory_percent", pct_val)
                        enriched_payload.setdefault("disk_percent", pct_val)
                    except (ValueError, TypeError):
                        pass
                elif any(w in (text_content or "").lower() for w in ("high cpu", "cpu spike", "cpu surge", "cpu sentinel", "resource sentinel", "cpu critical", "cpu overload", "cpu load high", "p90")):
                    enriched_payload["cpu_percent"] = 92.0
                    enriched_payload.setdefault("memory_percent", 92.0)
                    enriched_payload.setdefault("disk_percent", 92.0)

            if "host" not in enriched_payload and entities.get("hostnames"):
                enriched_payload["host"] = entities["hostnames"][0]

            if "ip" not in enriched_payload and entities.get("ipv4"):
                enriched_payload["ip"] = entities["ipv4"][0]

            if "attempts" not in enriched_payload and nlp_data.get("intent") == "security_threat":
                enriched_payload["attempts"] = 5

            if "status_code" not in enriched_payload and entities.get("http_status"):
                try:
                    enriched_payload["status_code"] = int(entities["http_status"][0])
                except (ValueError, TypeError):
                    pass

            if "status" not in enriched_payload:
                if nlp_data.get("sentiment_label") == "positive" or any(w in (text_content or "").lower() for w in ("success", "completed", "smoothly", "finished", "verified")):
                    enriched_payload["status"] = "success"

            if "database" not in enriched_payload and nlp_data.get("intent") == "backup_request":
                if entities.get("hostnames"):
                    enriched_payload["database"] = entities["hostnames"][0]
                else:
                    vault_match = re.search(r"\b([a-zA-Z0-9_\-]+(?:-vault|-db|_db|cluster))\b", text_content or "", re.IGNORECASE)
                    enriched_payload["database"] = vault_match.group(1) if vault_match else "primary_db"

            if "size_mb" not in enriched_payload and entities.get("memory_sizes"):
                try:
                    enriched_payload["size_mb"] = float(entities["memory_sizes"][0])
                except (ValueError, TypeError):
                    pass

        # 2. Build full evaluation context
        context: Dict[str, Any] = {
            "event": {
                "name": event_name,
                "source": source,
                "timestamp": timestamp_str
            },
            "payload": enriched_payload,
            "nlp": nlp_data,
            "system": self.telemetry.get_metrics(),
            "organization_id": org_id
        }

        # 3. Add to recent event stream
        self._push_event_stream({
            "id": f"evt_{int(time.time() * 1000)}",
            "name": event_name,
            "source": source,
            "timestamp": timestamp_str,
            "payload": enriched_payload,
            "nlp_intent": nlp_data.get("intent"),
            "nlp_urgency": nlp_data.get("urgency"),
            "dry_run": dry_run
        })

        if not self.is_running and not dry_run:
            return {
                "status": "ENGINE_PAUSED",
                "event_name": event_name,
                "executed_rules": [],
                "context": context
            }

        # 4. Fetch enabled rules
        rules = self.storage.get_rules(enabled_only=True, organization_id=org_id)
        executed_rules = []

        matching_events = {event_name, "*"}
        if nlp_data and is_nlp_source:
            matching_events.add("user.prompt")
            intent = nlp_data.get("intent")
            lower_txt = (text_content or "").lower()
            if intent in ("server_alert", "status_inquiry") or any(w in lower_txt for w in ("cpu", "metrics", "sentinel", "utilization")):
                matching_events.add("system.metrics")
            elif intent == "security_threat":
                matching_events.add("auth.failed")
            elif intent == "backup_request":
                matching_events.add("backup.completed")
            elif intent == "deploy_request":
                matching_events.add("deploy.pipeline")

            entities = nlp_data.get("entities", {})
            if entities.get("percentages"):
                matching_events.add("system.metrics")
            if entities.get("http_status"):
                matching_events.add("api.error")
            if entities.get("ipv4"):
                matching_events.add("auth.failed")

        for rule in rules:
            rule_id = rule["id"]
            trigger = rule.get("trigger", {})

            trigger_type = trigger.get("type", "event")
            trigger_event = trigger.get("event_name", "*")

            matches_trigger = False
            if trigger_event == "*" or trigger_event in matching_events:
                matches_trigger = True
            elif trigger_type == "natural_text" and bool(nlp_data):
                matches_trigger = True

            if not matches_trigger:
                continue

            # Check Cooldown
            cooldown_sec = rule.get("cooldown_seconds", 0)
            now_ts = time.time()
            last_run_ts = self._cooldown_tracker.get(rule_id, 0.0)

            if not dry_run and cooldown_sec > 0 and (now_ts - last_run_ts) < cooldown_sec:
                executed_rules.append({
                    "rule_id": rule_id,
                    "rule_name": rule["name"],
                    "priority": rule.get("priority", 10),
                    "category": rule.get("category", "System"),
                    "matched": True,
                    "status": "skipped",
                    "reason": f"Cooldown active ({int(cooldown_sec - (now_ts - last_run_ts))}s remaining)",
                    "trace": []
                })
                continue

            # Execute workflow pipeline (handles both visual steps and condition/actions)
            exec_result = self._execute_workflow_pipeline(rule, context, dry_run=dry_run)
            executed_rules.append(exec_result)

        return {
            "status": "completed",
            "event_name": event_name,
            "executed_rules": executed_rules,
            "nlp": nlp_data,
            "dry_run": dry_run
        }

    def _execute_workflow_pipeline(
        self,
        rule: Dict[str, Any],
        context: Dict[str, Any],
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """Executes a workflow pipeline through its steps or condition/actions with trace logging."""
        rule_id = rule["id"]
        rule_name = rule["name"]
        event_name = context.get("event", {}).get("name", "workflow.execute")
        trigger_type = rule.get("trigger", {}).get("type", "event")
        now_dt = datetime.datetime.now()
        timestamp_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")

        start_time = time.time()
        overall_status = "success"
        error_message = None
        steps_trace: List[Dict[str, Any]] = []
        action_results: List[Dict[str, Any]] = []
        condition_trace: List[Dict[str, Any]] = []
        matched = True

        # Check if rule has explicit visual steps
        configured_steps = rule.get("steps") or []

        # 1. Condition evaluation
        cond_group = rule.get("condition", {})
        if cond_group and cond_group.get("conditions"):
            matched, condition_trace = self.evaluator.evaluate_group(cond_group, context)
            steps_trace.append({
                "step_name": "Condition Filter",
                "step_type": "condition",
                "status": "SUCCESS" if matched else "SKIPPED",
                "input": cond_group,
                "output": {"matched": matched, "trace": condition_trace},
                "duration_ms": 1.2
            })
            if not matched:
                return {
                    "rule_id": rule_id,
                    "rule_name": rule_name,
                    "priority": rule.get("priority", 10),
                    "category": rule.get("category", "System"),
                    "matched": False,
                    "status": "skipped",
                    "trace": condition_trace,
                    "steps_trace": steps_trace
                }

        # 2. Execute Visual Step Pipeline if configured
        if configured_steps:
            for idx, step in enumerate(configured_steps):
                st_type = step.get("type", "").lower()
                st_name = step.get("name") or f"Step {idx+1} ({st_type})"
                st_config = step.get("config", {})

                step_start = time.time()
                step_status = "SUCCESS" if not dry_run else "DRY_RUN"
                step_error = None
                step_output: Any = {}

                try:
                    if st_type == "trigger":
                        step_output = {"event": event_name, "matched": True}

                    elif st_type in ("ai_analysis", "intent_detection", "sentiment_detection", "urgency_detection", "entity_extraction"):
                        text_val = context.get("payload", {}).get("message") or context.get("payload", {}).get("text") or ""
                        ai_res = self.nlp.parse(text_val)
                        context["nlp"] = ai_res
                        step_output = {
                            "intent": ai_res.get("intent"),
                            "urgency": ai_res.get("urgency"),
                            "sentiment": ai_res.get("sentiment_label"),
                            "lead_score": ai_res.get("lead_score"),
                            "route": ai_res.get("recommended_route"),
                            "entities": ai_res.get("entities")
                        }

                    elif st_type == "lead_scoring":
                        ai_res = context.get("nlp", {})
                        score = ai_res.get("lead_score", 50)
                        step_output = {"lead_score": score, "qualification": "Hot Lead" if score >= 70 else "Standard Lead"}

                    elif st_type == "route":
                        dest = st_config.get("destination") or context.get("nlp", {}).get("recommended_route", "General Queue")
                        context.setdefault("route", {})["department"] = dest
                        step_output = {"destination_department": dest}

                    elif st_type == "email_draft":
                        draft_res = self.action_runner.execute_action(
                            {"type": "email_draft", "params": st_config},
                            context,
                            self.storage,
                            dry_run=dry_run
                        )
                        step_output = draft_res.get("output", {})
                        action_results.append(draft_res)

                    elif st_type == "database_record":
                        db_res = self.action_runner.execute_action(
                            {"type": "database_record", "params": st_config},
                            context,
                            self.storage,
                            dry_run=dry_run
                        )
                        step_output = db_res.get("output", {})
                        action_results.append(db_res)

                    elif st_type == "notification":
                        notif_res = self.action_runner.execute_action(
                            {"type": "notification", "params": st_config},
                            context,
                            self.storage,
                            dry_run=dry_run
                        )
                        step_output = notif_res.get("output", {})
                        action_results.append(notif_res)

                    elif st_type in ("webhook", "webhook_call"):
                        wh_res = self.action_runner.execute_action(
                            {"type": "webhook_call", "params": st_config},
                            context,
                            self.storage,
                            dry_run=dry_run
                        )
                        step_output = wh_res.get("output", {})
                        action_results.append(wh_res)
                        if wh_res.get("status") == "failed":
                            step_status = "FAILED"
                            step_error = wh_res.get("error")

                    elif st_type == "delay":
                        step_output = {"delayed_seconds": min(float(st_config.get("seconds", 1)), 5.0), "simulated": True}

                    elif st_type == "end":
                        step_output = {"workflow_status": "completed"}

                except Exception as exc:
                    step_status = "FAILED"
                    step_error = str(exc)
                    overall_status = "failed"
                    error_message = step_error

                step_duration_ms = round((time.time() - step_start) * 1000, 2)
                steps_trace.append({
                    "name": st_name,
                    "type": st_type,
                    "status": step_status,
                    "input": st_config,
                    "output": step_output,
                    "error": step_error,
                    "duration_ms": step_duration_ms
                })

                if step_status == "FAILED":
                    break

        # 3. Actions execution (execute actions if configured)
        actions = rule.get("actions", [])
        if actions:
            for act in actions:
                res = self.action_runner.execute_action(act, context, self.storage, dry_run=dry_run)
                action_results.append(res)
                steps_trace.append({
                    "name": act.get("type", "Action"),
                    "type": act.get("type", "action"),
                    "status": "DRY_RUN" if dry_run else ("SUCCESS" if res.get("status") == "success" else "FAILED"),
                    "input": act.get("params", {}),
                    "output": res.get("output", {}),
                    "error": res.get("error"),
                    "duration_ms": res.get("duration_ms", 1.0),
                    "retry_count": res.get("retry_count", 0)
                })
                if res.get("status") == "failed":
                    overall_status = "failed"
                    error_message = res.get("error")

        total_duration_ms = round((time.time() - start_time) * 1000, 2)

        # Update cooldown and execution count if not dry run
        exec_id = 0
        if not dry_run:
            self._cooldown_tracker[rule_id] = time.time()
            self.storage.record_rule_trigger(rule_id)

            # Log execution trace in database
            exec_id = self.storage.log_execution({
                "rule_id": rule_id,
                "rule_name": rule_name,
                "timestamp": timestamp_str,
                "trigger_type": trigger_type,
                "event_name": event_name,
                "matched": True,
                "status": overall_status,
                "duration_ms": total_duration_ms,
                "trace": condition_trace,
                "results": action_results,
                "steps_trace": steps_trace,
                "ai_result": context.get("nlp"),
                "is_dry_run": False,
                "error_message": error_message,
                "organization_id": context.get("organization_id")
            })

        return {
            "execution_id": f"exec-simulated" if dry_run else f"exec-{exec_id}",
            "rule_id": rule_id,
            "workflow_id": rule_id,
            "rule_name": rule_name,
            "workflow_name": rule_name,
            "priority": rule.get("priority", 10),
            "category": rule.get("category", "System"),
            "matched": True,
            "status": overall_status,
            "duration_ms": total_duration_ms,
            "trace": condition_trace,
            "action_results": action_results,
            "steps_trace": steps_trace,
            "ai_result": context.get("nlp"),
            "is_dry_run": dry_run,
            "error_message": error_message
        }

    def execute_rule_manually(
        self,
        rule_id: str,
        custom_payload: Optional[Dict[str, Any]] = None,
        dry_run: bool = False,
        organization_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Directly forces execution of a single rule, evaluating conditions."""
        rule = self.storage.get_rule(rule_id, organization_id=organization_id)
        if not rule:
            return {"status": "error", "message": f"Rule '{rule_id}' not found."}

        payload = custom_payload or {}
        event_name = rule.get("trigger", {}).get("event_name", "manual.trigger")
        if event_name == "*":
            event_name = "manual.trigger"

        now_dt = datetime.datetime.now()
        timestamp_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")

        nlp_data: Dict[str, Any] = {}
        text_content = payload.get("text") or payload.get("message")
        if text_content and isinstance(text_content, str):
            nlp_data = self.nlp.parse(text_content)

        context: Dict[str, Any] = {
            "event": {
                "name": event_name,
                "source": "manual_ui",
                "timestamp": timestamp_str
            },
            "payload": payload,
            "nlp": nlp_data,
            "system": self.telemetry.get_metrics(),
            "organization_id": organization_id or rule.get("organization_id")
        }

        return self._execute_workflow_pipeline(rule, context, dry_run=dry_run)

    # Alias for modern workflow nomenclature
    execute_workflow = execute_rule_manually

    def _push_event_stream(self, evt: Dict[str, Any]):
        with self._lock:
            self.event_stream.append(evt)
            if len(self.event_stream) > 50:
                self.event_stream.pop(0)

    def get_event_stream(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self.event_stream)

    def _background_loop(self):
        """Background thread executing periodic health monitoring events."""
        while True:
            time.sleep(15)
            if not self.is_running:
                continue
            try:
                metrics = self.telemetry.get_metrics()
                # If CPU spikes over 85%, dispatch background event automatically
                if metrics.get("cpu_percent", 0) > 85:
                    self.ingest_event(
                        event_name="system.metrics",
                        payload={
                            "host": "localhost",
                            "cpu_percent": metrics.get("cpu_percent"),
                            "memory_percent": metrics.get("memory_percent"),
                            "source": "telemetry_daemon"
                        },
                        source="daemon"
                    )
            except Exception:
                pass
