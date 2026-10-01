"""Central Automation Engine Core for AI Command Center.

Orchestrates rule matching, event ingestion, condition evaluation,
action execution, cooldown throttles, and automated background telemetry sweeps.
"""

from __future__ import annotations

import datetime
import re
import threading
import time
from typing import Any, Dict, List, Optional

from actions import ActionRunner
from evaluator import ConditionEvaluator
from nlp_engine import NLPEngine
from storage import Storage
from telemetry import TelemetryMonitor


class AutomationEngine:
    """Core rule execution engine and event broker."""

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
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """Ingests an event, matches active rules, evaluates conditions, and runs actions."""
        payload = payload or {}
        now_dt = datetime.datetime.now()
        timestamp_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")

        # 1. NLP parsing if text prompt or event contains natural language
        nlp_data: Dict[str, Any] = {}
        text_content = payload.get("text") or payload.get("message") or payload.get("prompt")
        if text_content and isinstance(text_content, str):
            nlp_data = self.nlp.parse(text_content)
        elif event_name in ("user.prompt", "nlp.query", "chat.message"):
            nlp_data = self.nlp.parse(str(payload.get("query", "")))

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
            "system": self.telemetry.get_metrics()
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
        rules = self.storage.get_rules(enabled_only=True)
        executed_rules = []

        # Determine all matching event triggers (direct event + inferred from NLP intent/entities)
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

            # Trigger matching
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

            # Condition Evaluation
            cond_group = rule.get("condition", {})
            start_eval = time.time()
            matched, trace = self.evaluator.evaluate_group(cond_group, context)
            duration_ms = round((time.time() - start_eval) * 1000, 2)

            if not matched:
                executed_rules.append({
                    "rule_id": rule_id,
                    "rule_name": rule["name"],
                    "priority": rule.get("priority", 10),
                    "category": rule.get("category", "System"),
                    "matched": False,
                    "status": "skipped",
                    "trace": trace
                })
                continue

            # Execute Actions
            action_results = []
            overall_status = "success"
            error_message = None

            actions = rule.get("actions", [])
            for act in actions:
                if dry_run:
                    action_results.append({
                        "type": act.get("type"),
                        "params": act.get("params"),
                        "status": "dry_run_simulated"
                    })
                else:
                    res = self.action_runner.execute_action(act, context, self.storage)
                    action_results.append(res)
                    if res.get("status") == "failed":
                        overall_status = "failed"
                        error_message = res.get("error")

            if not dry_run:
                self._cooldown_tracker[rule_id] = now_ts
                self.storage.record_rule_trigger(rule_id)

                # Persist to execution log
                self.storage.log_execution({
                    "rule_id": rule_id,
                    "rule_name": rule["name"],
                    "timestamp": timestamp_str,
                    "trigger_type": trigger_type,
                    "event_name": event_name,
                    "matched": True,
                    "status": overall_status,
                    "duration_ms": duration_ms,
                    "trace": trace,
                    "results": action_results,
                    "error_message": error_message
                })

            executed_rules.append({
                "rule_id": rule_id,
                "rule_name": rule["name"],
                "priority": rule.get("priority", 10),
                "category": rule.get("category", "System"),
                "matched": True,
                "status": overall_status,
                "duration_ms": duration_ms,
                "trace": trace,
                "action_results": action_results
            })

        return {
            "status": "completed",
            "event_name": event_name,
            "executed_rules": executed_rules,
            "nlp": nlp_data,
            "dry_run": dry_run
        }

    def execute_rule_manually(self, rule_id: str, custom_payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Directly forces execution of a single rule, evaluating conditions."""
        rule = self.storage.get_rule(rule_id)
        if not rule:
            return {"status": "error", "message": f"Rule '{rule_id}' not found."}

        payload = custom_payload or {}
        event_name = rule.get("trigger", {}).get("event_name", "manual.trigger")
        if event_name == "*":
            event_name = "manual.trigger"

        # Ingest with forced matching
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
            "system": self.telemetry.get_metrics()
        }

        # Evaluate condition
        cond_group = rule.get("condition", {})
        start_eval = time.time()
        matched, trace = self.evaluator.evaluate_group(cond_group, context)
        duration_ms = round((time.time() - start_eval) * 1000, 2)

        action_results = []
        overall_status = "success"
        error_message = None

        if matched:
            for act in rule.get("actions", []):
                res = self.action_runner.execute_action(act, context, self.storage)
                action_results.append(res)
                if res.get("status") == "failed":
                    overall_status = "failed"
                    error_message = res.get("error")

            self._cooldown_tracker[rule_id] = time.time()
            self.storage.record_rule_trigger(rule_id)

            self.storage.log_execution({
                "rule_id": rule_id,
                "rule_name": rule["name"],
                "timestamp": timestamp_str,
                "trigger_type": "manual",
                "event_name": event_name,
                "matched": True,
                "status": overall_status,
                "duration_ms": duration_ms,
                "trace": trace,
                "results": action_results,
                "error_message": error_message
            })
        else:
            overall_status = "condition_not_met"

        return {
            "status": overall_status,
            "rule_id": rule_id,
            "rule_name": rule["name"],
            "matched": matched,
            "duration_ms": duration_ms,
            "trace": trace,
            "action_results": action_results,
            "error_message": error_message
        }

    def _push_event_stream(self, evt: Dict[str, Any]):
        with self._lock:
            self.event_stream.insert(0, evt)
            if len(self.event_stream) > 50:
                self.event_stream = self.event_stream[:50]

    def _background_loop(self):
        """Periodic background monitor (every 15s) checking system thresholds."""
        while True:
            time.sleep(15)
            if not self.is_running:
                continue

            try:
                metrics = self.telemetry.get_metrics()
                # If CPU > 85%, trigger system.metrics event
                if metrics.get("cpu_percent", 0) >= 85:
                    self.ingest_event(
                        event_name="system.metrics",
                        payload={
                            "cpu_percent": metrics.get("cpu_percent"),
                            "host": "localhost",
                            "memory_percent": metrics.get("memory_percent"),
                            "source": "background_sentinel"
                        },
                        source="background_sentinel"
                    )
            except Exception:
                pass
