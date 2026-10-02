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
import os
import re
import threading
import time
import uuid
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
        self._schedule_tracker: Dict[str, float] = {}

        # In-memory circular buffer for real-time frontend streaming (last 50 events)
        self.event_stream: List[Dict[str, Any]] = []

        # Production Execution Job Manager State
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._active_workers: Dict[str, int] = {}
        self._max_concurrent_per_tenant = 5

        # Dead-Letter Queue (DLQ) State
        self._dlq: List[Dict[str, Any]] = []
        self._dlq_file = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "automation_storage", "dlq.json"
        )
        self._load_dlq_from_disk()

        # Background worker thread for periodic automated health/sentinel evaluations & schedules
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
        if event_name in ("incident.created", "incident.reported"):
            matching_events.add("incident.created")
            matching_events.add("incident.reported")
        if event_name in ("lead.created", "lead.ingested"):
            matching_events.add("lead.created")
            matching_events.add("lead.ingested")

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

                    elif st_type in ("ai_generate", "ai_prompt"):
                        ai_provider = get_ai_provider(st_config.get("provider"))
                        prompt_tmpl = st_config.get("prompt_template") or st_config.get("prompt") or "Operational inquiry"
                        rendered_prompt = self.action_runner._interpolate_string(prompt_tmpl, context)
                        gen_text = ai_provider.generate_text(rendered_prompt, system_prompt=st_config.get("system_prompt"))
                        step_output = {
                            "prompt": rendered_prompt,
                            "generated_text": gen_text,
                            "provider": ai_provider.get_info().get("id"),
                            "model": ai_provider.get_info().get("model")
                        }
                        context.setdefault("steps_output", {})[st_name] = step_output
                        context["ai_generated"] = gen_text

                    elif st_type in ("ai_summarize", "ai_incident_rca"):
                        ai_provider = get_ai_provider(st_config.get("provider"))
                        src_field = st_config.get("source_field")
                        error_val = ""
                        if src_field:
                            error_val = self.action_runner._interpolate_string(f"{{{{ {src_field} }}}}", context)
                        if not error_val:
                            error_val = context.get("payload", {}).get("error") or context.get("payload", {}).get("message") or "System crash detected"
                        rca_res = ai_provider.summarize_incident(str(error_val), context)
                        step_output = rca_res
                        context.setdefault("steps_output", {})[st_name] = step_output
                        context["rca"] = rca_res

                    elif st_type in ("ai_classify", "ai_smart_router"):
                        ai_provider = get_ai_provider(st_config.get("provider"))
                        categories = st_config.get("categories") or ["Support", "DevOps", "Billing", "Security", "Sales"]
                        text_val = context.get("payload", {}).get("message") or context.get("payload", {}).get("text") or ""
                        classify_res = ai_provider.classify_text(str(text_val), categories)
                        step_output = classify_res
                        context.setdefault("steps_output", {})[st_name] = step_output
                        context["classification"] = classify_res
                        context.setdefault("route", {})["department"] = classify_res.get("category", "Support")

                    elif st_type in ("ai_extract_entities", "ai_extraction"):
                        text_val = context.get("payload", {}).get("message") or context.get("payload", {}).get("text") or context.get("payload", {}).get("error") or ""
                        parsed = self.nlp.parse(str(text_val))
                        entities = parsed.get("entities", {})
                        step_output = {"extracted_entities": entities}
                        context.setdefault("steps_output", {})[st_name] = step_output
                        context["extracted_entities"] = entities

                    elif st_type == "ai_sentiment_guard":
                        text_val = context.get("payload", {}).get("message") or ""
                        parsed = self.nlp.parse(str(text_val))
                        urgency = parsed.get("urgency", 50)
                        sentiment = parsed.get("sentiment_label", "neutral")
                        min_urgency = int(st_config.get("min_urgency", 0))
                        passed = urgency >= min_urgency
                        step_output = {"urgency": urgency, "sentiment": sentiment, "guard_passed": passed}
                        context.setdefault("steps_output", {})[st_name] = step_output

                    elif st_type in ("http_request", "api_call"):
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

                    elif st_type == "log_entry":
                        log_res = self.action_runner.execute_action(
                            {"type": "log_entry", "params": st_config},
                            context,
                            self.storage,
                            dry_run=dry_run
                        )
                        step_output = log_res.get("output", {})
                        action_results.append(log_res)

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

            # Dead-Letter Queue recording on failure
            if overall_status == "failed":
                self.add_to_dlq({
                    "rule_id": rule_id,
                    "rule_name": rule_name,
                    "organization_id": context.get("organization_id"),
                    "event_name": event_name,
                    "payload": context.get("payload", {}),
                    "error": error_message or "Step execution failed",
                    "execution_id": f"exec-{exec_id}",
                    "steps_trace": steps_trace
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

    # ==========================================
    # Dead-Letter Queue (DLQ) Management
    # ==========================================

    def _load_dlq_from_disk(self):
        try:
            if os.path.exists(self._dlq_file):
                with open(self._dlq_file, "r", encoding="utf-8") as f:
                    self._dlq = json.load(f)
        except Exception:
            self._dlq = []

    def _save_dlq_to_disk(self):
        try:
            os.makedirs(os.path.dirname(self._dlq_file), exist_ok=True)
            with open(self._dlq_file, "w", encoding="utf-8") as f:
                json.dump(self._dlq, f, indent=2, default=str)
        except Exception:
            pass

    def add_to_dlq(self, item: Dict[str, Any]) -> str:
        """Stores a failed execution payload in the Dead-Letter Queue."""
        dlq_id = f"dlq-{int(time.time() * 1000)}-{uuid.uuid4().hex[:6]}"
        record = {
            "id": dlq_id,
            "dlq_id": dlq_id,
            "rule_id": item.get("rule_id"),
            "workflow_id": item.get("rule_id"),
            "rule_name": item.get("rule_name", "Unknown Workflow"),
            "organization_id": item.get("organization_id"),
            "event_name": item.get("event_name", "unknown.event"),
            "payload": item.get("payload", {}),
            "error": item.get("error", "Execution failed"),
            "status": "pending",
            "execution_id": item.get("execution_id"),
            "timestamp": datetime.datetime.utcnow().isoformat(),
            "retry_count": 0
        }
        with self._lock:
            self._dlq.insert(0, record)
            if len(self._dlq) > 100:
                self._dlq.pop()
            self._save_dlq_to_disk()
        return dlq_id

    def get_dlq(
        self,
        organization_id: Optional[str] = None,
        status: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Returns filtered Dead-Letter Queue items."""
        with self._lock:
            items = list(self._dlq)
        if organization_id:
            items = [i for i in items if i.get("organization_id") == organization_id or not i.get("organization_id")]
        if status:
            items = [i for i in items if i.get("status") == status]
        return items

    def replay_dlq(self, dlq_id: str, organization_id: Optional[str] = None) -> Dict[str, Any]:
        """Re-dispatches a dead-lettered item through its target workflow."""
        target_item = None
        with self._lock:
            for item in self._dlq:
                if item.get("id") == dlq_id or item.get("dlq_id") == dlq_id:
                    if organization_id and item.get("organization_id") and item.get("organization_id") != organization_id:
                        return {"success": False, "error": "Access denied.", "code": "FORBIDDEN"}
                    target_item = item
                    break

        if not target_item:
            return {"success": False, "error": f"DLQ item '{dlq_id}' not found.", "code": "NOT_FOUND"}

        rule_id = target_item.get("rule_id")
        payload = target_item.get("payload", {})
        org_id = target_item.get("organization_id") or organization_id

        # Re-execute rule
        result = self.execute_rule_manually(rule_id, payload, dry_run=False, organization_id=org_id)

        with self._lock:
            target_item["status"] = "replayed" if result.get("status") == "success" else "retry_failed"
            target_item["replayed_at"] = datetime.datetime.utcnow().isoformat()
            target_item["retry_count"] = target_item.get("retry_count", 0) + 1
            target_item["last_replay_result"] = result.get("status")
            self._save_dlq_to_disk()

        return {
            "success": True,
            "dlq_id": dlq_id,
            "status": target_item["status"],
            "execution_result": result
        }

    def delete_dlq(self, dlq_id: str, organization_id: Optional[str] = None) -> bool:
        """Purges an item from the Dead-Letter Queue."""
        with self._lock:
            for idx, item in enumerate(self._dlq):
                if item.get("id") == dlq_id or item.get("dlq_id") == dlq_id:
                    if organization_id and item.get("organization_id") and item.get("organization_id") != organization_id:
                        return False
                    self._dlq.pop(idx)
                    self._save_dlq_to_disk()
                    return True
        return False

    # ==========================================
    # Asynchronous Execution Job Manager
    # ==========================================

    def dispatch_job_async(
        self,
        rule_id: str,
        custom_payload: Optional[Dict[str, Any]] = None,
        dry_run: bool = False,
        organization_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Queues a workflow for background asynchronous execution."""
        rule = self.storage.get_rule(rule_id, organization_id=organization_id)
        if not rule:
            return {"success": False, "error": f"Workflow '{rule_id}' not found.", "code": "NOT_FOUND"}

        org_id = organization_id or rule.get("organization_id", "org-enterprise-default")
        current_active = self._active_workers.get(org_id, 0)
        if current_active >= self._max_concurrent_per_tenant:
            return {
                "success": False,
                "error": f"Maximum concurrent job execution limit reached ({self._max_concurrent_per_tenant} active jobs). Please wait for active jobs to complete.",
                "code": "CONCURRENCY_LIMIT"
            }

        job_id = f"job-{uuid.uuid4().hex[:12]}"
        steps = rule.get("steps") or rule.get("actions") or []
        job_record = {
            "id": job_id,
            "job_id": job_id,
            "rule_id": rule_id,
            "workflow_id": rule_id,
            "rule_name": rule.get("name", "Workflow"),
            "workflow_name": rule.get("name", "Workflow"),
            "organization_id": org_id,
            "status": "QUEUED",
            "created_at": datetime.datetime.utcnow().isoformat(),
            "started_at": None,
            "completed_at": None,
            "current_step_index": 0,
            "total_steps": len(steps),
            "current_step_name": "Queued in runner",
            "steps_trace": [],
            "result": None,
            "error": None,
            "dry_run": dry_run,
            "payload": custom_payload or {}
        }

        with self._lock:
            self._jobs[job_id] = job_record

        # Spawn asynchronous execution worker thread
        worker = threading.Thread(
            target=self._run_job_worker,
            args=(job_id, rule, custom_payload, dry_run, org_id),
            daemon=True
        )
        worker.start()

        return {
            "success": True,
            "job_id": job_id,
            "status": "QUEUED",
            "workflow_id": rule_id,
            "workflow_name": rule.get("name"),
            "message": "Workflow queued for background asynchronous execution."
        }

    def _run_job_worker(
        self,
        job_id: str,
        rule: Dict[str, Any],
        payload: Optional[Dict[str, Any]],
        dry_run: bool,
        organization_id: Optional[str]
    ):
        org_id = organization_id or rule.get("organization_id", "org-enterprise-default")
        with self._lock:
            self._active_workers[org_id] = self._active_workers.get(org_id, 0) + 1
            if job_id in self._jobs:
                self._jobs[job_id]["status"] = "RUNNING"
                self._jobs[job_id]["started_at"] = datetime.datetime.utcnow().isoformat()
                self._jobs[job_id]["current_step_name"] = "Executing steps"

        try:
            result = self.execute_rule_manually(rule["id"], payload, dry_run=dry_run, organization_id=org_id)
            with self._lock:
                if job_id in self._jobs:
                    # If job was cancelled while running, retain CANCELLED state
                    if self._jobs[job_id]["status"] != "CANCELLED":
                        self._jobs[job_id]["status"] = "COMPLETED" if result.get("status") in ("success", "skipped") else "FAILED"
                    self._jobs[job_id]["completed_at"] = datetime.datetime.utcnow().isoformat()
                    self._jobs[job_id]["result"] = result
                    self._jobs[job_id]["steps_trace"] = result.get("steps_trace", [])
                    self._jobs[job_id]["current_step_name"] = "Completed"
                    self._jobs[job_id]["current_step_index"] = self._jobs[job_id]["total_steps"]
                    if result.get("error_message"):
                        self._jobs[job_id]["error"] = result.get("error_message")
        except Exception as exc:
            with self._lock:
                if job_id in self._jobs:
                    self._jobs[job_id]["status"] = "FAILED"
                    self._jobs[job_id]["error"] = str(exc)
                    self._jobs[job_id]["completed_at"] = datetime.datetime.utcnow().isoformat()
        finally:
            with self._lock:
                self._active_workers[org_id] = max(0, self._active_workers.get(org_id, 1) - 1)

    def get_job(self, job_id: str, organization_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Retrieves a background job with tenant isolation scoping."""
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None
            if organization_id and job.get("organization_id") and job.get("organization_id") != organization_id:
                return None
            return dict(job)

    def list_jobs(
        self,
        organization_id: Optional[str] = None,
        limit: int = 50,
        status: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Lists background execution jobs for a given tenant."""
        with self._lock:
            jobs = list(self._jobs.values())
        if organization_id:
            jobs = [j for j in jobs if j.get("organization_id") == organization_id or not j.get("organization_id")]
        if status:
            jobs = [j for j in jobs if j.get("status") == status.upper()]
        jobs.sort(key=lambda j: j.get("created_at", ""), reverse=True)
        return jobs[:limit]

    def cancel_job(self, job_id: str, organization_id: Optional[str] = None) -> bool:
        """Cancels a queued or currently executing background job."""
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return False
            if organization_id and job.get("organization_id") and job.get("organization_id") != organization_id:
                return False
            if job["status"] in ("QUEUED", "RUNNING"):
                job["status"] = "CANCELLED"
                job["completed_at"] = datetime.datetime.utcnow().isoformat()
                job["error"] = "Job cancelled by operator request."
                return True
        return False

    def _push_event_stream(self, evt: Dict[str, Any]):
        with self._lock:
            self.event_stream.append(evt)
            if len(self.event_stream) > 50:
                self.event_stream.pop(0)

    def get_event_stream(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self.event_stream)

    def evaluate_scheduled_workflows(self, organization_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Evaluates scheduled/interval triggers for workflows and executes due workflows."""
        now_ts = time.time()
        executed = []
        try:
            rules = self.storage.get_rules(enabled_only=True, organization_id=organization_id)
            for rule in rules:
                trigger = rule.get("trigger", {})
                t_type = trigger.get("type", "")
                interval_min = trigger.get("interval_minutes") or trigger.get("interval")
                if t_type in ("schedule", "cron", "interval") or bool(interval_min):
                    interval_sec = max(30, float(interval_min or 60) * 60)
                    last_exec = self._schedule_tracker.get(rule["id"], 0.0)
                    if (now_ts - last_exec) >= interval_sec:
                        self._schedule_tracker[rule["id"]] = now_ts
                        res = self.execute_rule_manually(
                            rule["id"],
                            custom_payload={
                                "scheduled": True,
                                "interval_minutes": interval_min or 60,
                                "triggered_at": datetime.datetime.utcnow().isoformat()
                            },
                            dry_run=False,
                            organization_id=rule.get("organization_id")
                        )
                        executed.append({"rule_id": rule["id"], "result": res})
        except Exception:
            pass
        return executed

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


