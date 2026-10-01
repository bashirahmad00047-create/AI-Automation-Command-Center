"""Comprehensive Test Suite for AI Automation Command Center.

Tests NLP parser, Condition Evaluator, Action Runner, SQLite Storage,
Automation Engine orchestrator, and Flask REST API endpoints.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest

from actions import ActionRunner
from automation_engine import AutomationEngine
from evaluator import ConditionEvaluator
from nlp_engine import NLPEngine
from presets import PRESET_BLUEPRINTS
from storage import Storage
import app as flask_app_module


class TestNLPEngine(unittest.TestCase):
    def setUp(self):
        self.nlp = NLPEngine()

    def test_empty_input(self):
        res = self.nlp.parse("")
        self.assertEqual(res["intent"], "general_query")
        self.assertEqual(res["urgency"], 0)
        self.assertEqual(res["severity_level"], "LOW")

    def test_server_alert_intent(self):
        res = self.nlp.parse("Critical server crash: CPU spike at 96% and memory OOM on prod-srv-01")
        self.assertEqual(res["intent"], "server_alert")
        self.assertGreaterEqual(res["urgency"], 70)
        self.assertIn(res["severity_level"], ["HIGH", "CRITICAL"])
        self.assertIn("96", res["entities"].get("percentages", []))

    def test_security_threat_intent(self):
        res = self.nlp.parse("Unauthorized intrusion detected: brute-force login attack from 192.168.1.100")
        self.assertEqual(res["intent"], "security_threat")
        self.assertIn("192.168.1.100", res["entities"].get("ipv4", []))

    def test_backup_and_deploy_intent(self):
        backup_res = self.nlp.parse("Perform database snapshot dump and archive to cold-storage")
        self.assertEqual(backup_res["intent"], "backup_request")

        deploy_res = self.nlp.parse("Deploy release rollout to staging and production pipeline")
        self.assertEqual(deploy_res["intent"], "deploy_request")

    def test_sentiment_analysis(self):
        pos_res = self.nlp.parse("System restored to optimal healthy state and backup finished successfully")
        self.assertEqual(pos_res["sentiment_label"], "positive")
        self.assertGreater(pos_res["sentiment"], 0)

        neg_res = self.nlp.parse("Fatal error: database corrupted and broken down")
        self.assertEqual(neg_res["sentiment_label"], "negative")
        self.assertLess(neg_res["sentiment"], 0)

    def test_ipv4_extraction_not_http_status(self):
        # IPv4 addresses like 192.168.1.50 must only be extracted as ipv4 and NEVER as http_status
        res = self.nlp.parse("Intrusion detected from host 192.168.1.50 in subnet")
        self.assertIn("192.168.1.50", res["entities"].get("ipv4", []))
        http_statuses = res["entities"].get("http_status", [])
        self.assertEqual(http_statuses, [])
        self.assertNotIn("192", http_statuses)
        self.assertNotIn("168", http_statuses)
        self.assertNotIn("50", http_statuses)

    def test_valid_http_status_codes_extraction(self):
        # Valid 3-digit HTTP codes such as 400, 401, 403, 404, 500, 502, 503
        sample_text = "Encountered 400 Bad Request, 401 Unauthorized, 403 Forbidden, 404 Not Found, 500 Internal, 502 Bad Gateway, and 503 Unavailable"
        res = self.nlp.parse(sample_text)
        http_statuses = set(res["entities"].get("http_status", []))
        expected_codes = {"400", "401", "403", "404", "500", "502", "503"}
        self.assertTrue(expected_codes.issubset(http_statuses))

    def test_invalid_http_status_codes_ignored(self):
        # Arbitrary 3-digit numbers like 123, 999, 399 should NOT be detected as http_status
        res = self.nlp.parse("Order number 123 processed item 999 with code 399 and count 600")
        http_statuses = res["entities"].get("http_status", [])
        self.assertEqual(http_statuses, [])

    def test_mixed_ipv4_and_http_status(self):
        # Mixed IP address and HTTP status code
        res = self.nlp.parse("Host 192.168.1.50 triggered HTTP 500 server error and 404 missing resource")
        self.assertEqual(res["entities"].get("ipv4"), ["192.168.1.50"])
        http_statuses = res["entities"].get("http_status", [])
        self.assertEqual(sorted(http_statuses), ["404", "500"])
        self.assertNotIn("192", http_statuses)
        self.assertNotIn("168", http_statuses)


class TestConditionEvaluator(unittest.TestCase):
    def test_dot_notation(self):
        context = {
            "payload": {
                "metrics": {
                    "cpu": 88.5,
                    "disks": ["c:", "d:"]
                }
            }
        }
        self.assertEqual(ConditionEvaluator.get_field_value(context, "payload.metrics.cpu"), 88.5)
        self.assertEqual(ConditionEvaluator.get_field_value(context, "payload.metrics.disks.0"), "c:")
        self.assertIsNone(ConditionEvaluator.get_field_value(context, "payload.nonexistent.field"))

    def test_operators(self):
        ctx = {"payload": {"cpu": 90, "host": "prod-01", "tags": "db,primary"}}

        # greater_than
        p1, _ = ConditionEvaluator.evaluate_single({"field": "payload.cpu", "operator": ">=", "value": 90}, ctx)
        self.assertTrue(p1)

        p2, _ = ConditionEvaluator.evaluate_single({"field": "payload.cpu", "operator": "<", "value": 50}, ctx)
        self.assertFalse(p2)

        # contains
        p3, _ = ConditionEvaluator.evaluate_single({"field": "payload.host", "operator": "contains", "value": "prod"}, ctx)
        self.assertTrue(p3)

        # regex
        p4, _ = ConditionEvaluator.evaluate_single({"field": "payload.host", "operator": "regex_match", "value": r"prod-\d+"}, ctx)
        self.assertTrue(p4)

        # in_list
        p5, _ = ConditionEvaluator.evaluate_single({"field": "payload.cpu", "operator": "in_list", "value": "80, 90, 100"}, ctx)
        self.assertTrue(p5)

    def test_and_or_groups(self):
        ctx = {"payload": {"cpu": 95, "status": "down"}}

        and_group = {
            "logic": "AND",
            "conditions": [
                {"field": "payload.cpu", "operator": ">=", "value": 90},
                {"field": "payload.status", "operator": "equals", "value": "down"}
            ]
        }
        passed_and, _ = ConditionEvaluator.evaluate_group(and_group, ctx)
        self.assertTrue(passed_and)

        or_group = {
            "logic": "OR",
            "conditions": [
                {"field": "payload.cpu", "operator": "<", "value": 50},  # False
                {"field": "payload.status", "operator": "equals", "value": "down"}  # True
            ]
        }
        passed_or, _ = ConditionEvaluator.evaluate_group(or_group, ctx)
        self.assertTrue(passed_or)


class TestActionRunner(unittest.TestCase):
    def setUp(self):
        self.runner = ActionRunner()
        self.temp_db_file = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        self.temp_db_file.close()
        self.storage = Storage(db_path=self.temp_db_file.name)

    def tearDown(self):
        if os.path.exists(self.temp_db_file.name):
            try:
                os.remove(self.temp_db_file.name)
            except OSError:
                pass

    def test_notification_and_template_interpolation(self):
        ctx = {"payload": {"host": "srv-test", "val": 42}}
        action = {
            "type": "notification",
            "params": {
                "title": "Alert for {{ payload.host }}",
                "message": "Value is {{ payload.val }}",
                "severity": "critical"
            }
        }
        result = self.runner.execute_action(action, ctx, self.storage)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["output"]["title"], "Alert for srv-test")
        self.assertEqual(result["output"]["message"], "Value is 42")

        # Verify persisted in storage notifications
        notifs = self.storage.get_notifications()
        self.assertGreaterEqual(len(notifs), 1)
        self.assertEqual(notifs[0]["title"], "Alert for srv-test")

    def test_file_io_action(self):
        ctx = {"event": {"name": "test.file"}}
        action = {
            "type": "file_append",
            "params": {
                "filename": "test_unit_output.txt",
                "content": "Automated Unit Test Line"
            }
        }
        result = self.runner.execute_action(action, ctx)
        self.assertEqual(result["status"], "success")
        self.assertTrue(os.path.exists(result["output"]["path"]))


class TestStorage(unittest.TestCase):
    def setUp(self):
        self.temp_db_file = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        self.temp_db_file.close()
        self.storage = Storage(db_path=self.temp_db_file.name)

    def tearDown(self):
        if os.path.exists(self.temp_db_file.name):
            try:
                os.remove(self.temp_db_file.name)
            except OSError:
                pass

    def test_seeded_rules(self):
        rules = self.storage.get_rules()
        self.assertGreaterEqual(len(rules), 3)

    def test_save_and_get_rule(self):
        rule_data = {
            "id": "test-rule-custom",
            "name": "Custom Test Rule",
            "category": "DevOps",
            "priority": 77,
            "trigger": {"type": "event", "event_name": "custom.event"},
            "condition": {"logic": "AND", "conditions": [{"field": "payload.x", "operator": "==", "value": 1}]},
            "actions": [{"type": "log_entry", "params": {"message": "Test"}}]
        }
        rule_id = self.storage.save_rule(rule_data)
        self.assertEqual(rule_id, "test-rule-custom")

        fetched = self.storage.get_rule(rule_id)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched["name"], "Custom Test Rule")
        self.assertEqual(fetched["priority"], 77)

    def test_toggle_and_delete_rule(self):
        rule_id = "test-toggle-rule"
        self.storage.save_rule({
            "id": rule_id,
            "name": "Toggle Me",
            "enabled": True
        })

        new_state = self.storage.toggle_rule(rule_id, False)
        self.assertFalse(new_state)

        deleted = self.storage.delete_rule(rule_id)
        self.assertTrue(deleted)
        self.assertIsNone(self.storage.get_rule(rule_id))

    def test_log_execution_and_retrieval(self):
        log_entry = {
            "rule_id": "rule-cpu-sentinel",
            "rule_name": "High CPU Sentinel",
            "trigger_type": "event",
            "event_name": "system.metrics",
            "matched": True,
            "status": "success",
            "duration_ms": 4.5,
            "trace": [{"passed": True}],
            "results": [{"type": "notification", "status": "success"}]
        }
        log_id = self.storage.log_execution(log_entry)
        self.assertIsInstance(log_id, int)

        logs = self.storage.get_logs()
        self.assertGreaterEqual(len(logs), 1)
        self.assertEqual(logs[0]["rule_name"], "High CPU Sentinel")


class TestAutomationEngine(unittest.TestCase):
    def setUp(self):
        self.temp_db_file = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        self.temp_db_file.close()
        self.storage = Storage(db_path=self.temp_db_file.name)
        self.engine = AutomationEngine(storage=self.storage)

    def tearDown(self):
        if os.path.exists(self.temp_db_file.name):
            try:
                os.remove(self.temp_db_file.name)
            except OSError:
                pass

    def test_ingest_event_matching_rule(self):
        # Trigger CPU rule (>=85)
        res = self.engine.ingest_event(
            event_name="system.metrics",
            payload={"cpu_percent": 92.0, "host": "prod-web-01"},
            source="test"
        )
        self.assertEqual(res["status"], "completed")
        matched_rules = [r for r in res["executed_rules"] if r.get("matched")]
        self.assertGreaterEqual(len(matched_rules), 1)
        self.assertEqual(matched_rules[0]["status"], "success")

    def test_ingest_event_not_matching_condition(self):
        # CPU is low (40.0), rule condition >= 85 should fail
        res = self.engine.ingest_event(
            event_name="system.metrics",
            payload={"cpu_percent": 40.0, "host": "prod-web-01"},
            source="test"
        )
        unmatched = [r for r in res["executed_rules"] if not r.get("matched")]
        self.assertGreaterEqual(len(unmatched), 1)

    def test_manual_rule_execution(self):
        res = self.engine.execute_rule_manually(
            rule_id="rule-daily-backup",
            custom_payload={"status": "success", "database": "orders_db", "size_mb": 128}
        )
        self.assertEqual(res["status"], "success")
        self.assertTrue(res["matched"])

    def test_system_metrics_cpu_below_or_equal_85(self):
        """Verify that CPU <= 85% does NOT trigger High CPU Resource Sentinel."""
        # 1. CPU below 85 (e.g. 75.0%)
        res_75 = self.engine.ingest_event(
            event_name="system.metrics",
            payload={"cpu_percent": 75.0, "host": "prod-api-01"},
            source="system_metrics_simulator",
            dry_run=True
        )
        cpu_rules_75 = [r for r in res_75["executed_rules"] if "CPU" in r["rule_name"] or r.get("priority") == 90]
        self.assertTrue(len(cpu_rules_75) >= 1)
        for r in cpu_rules_75:
            self.assertFalse(r["matched"])
            self.assertEqual(r["status"], "skipped")
            # Trace should report passed == False
            self.assertFalse(r["trace"][0]["passed"])

        # 2. CPU exactly equal to 85 (85.0% boundary)
        res_85 = self.engine.ingest_event(
            event_name="system.metrics",
            payload={"cpu_percent": 85.0, "host": "prod-api-01"},
            source="system_metrics_simulator",
            dry_run=True
        )
        cpu_rules_85 = [r for r in res_85["executed_rules"] if "CPU" in r["rule_name"] or r.get("priority") == 90]
        self.assertTrue(len(cpu_rules_85) >= 1)
        for r in cpu_rules_85:
            self.assertFalse(r["matched"])
            self.assertEqual(r["status"], "skipped")
            self.assertFalse(r["trace"][0]["passed"])

    def test_system_metrics_cpu_above_85(self):
        """Verify that CPU > 85% matches High CPU Resource Sentinel and returns PASS/TRIGGERED in trace."""
        # 1. CPU marginally above 85 (85.1%)
        res_851 = self.engine.ingest_event(
            event_name="system.metrics",
            payload={"cpu_percent": 85.1, "host": "prod-api-01"},
            source="system_metrics_simulator",
            dry_run=True
        )
        cpu_rules_851 = [r for r in res_851["executed_rules"] if "CPU" in r["rule_name"] or r.get("priority") == 90]
        self.assertTrue(len(cpu_rules_851) >= 1)
        for r in cpu_rules_851:
            self.assertTrue(r["matched"])
            self.assertEqual(r["status"], "success")
            self.assertTrue(r["trace"][0]["passed"])

        # 2. CPU well above 85 (94.5%)
        res_94 = self.engine.ingest_event(
            event_name="system.metrics",
            payload={"cpu_percent": 94.5, "host": "prod-api-01"},
            source="system_metrics_simulator",
            dry_run=True
        )
        cpu_rules_94 = [r for r in res_94["executed_rules"] if "CPU" in r["rule_name"] or r.get("priority") == 90]
        self.assertTrue(len(cpu_rules_94) >= 1)
        for r in cpu_rules_94:
            self.assertTrue(r["matched"])
            self.assertEqual(r["status"], "success")
            self.assertTrue(r["trace"][0]["passed"])

    def test_system_metrics_dry_run_safety(self):
        """Verify that dry-run executions produce zero side effects (no logs or notifications saved)."""
        initial_logs = len(self.storage.get_logs())
        initial_notifs = len(self.storage.get_notifications())

        res = self.engine.ingest_event(
            event_name="system.metrics",
            payload={"cpu_percent": 96.0, "host": "test-host"},
            source="system_metrics_simulator",
            dry_run=True
        )
        self.assertTrue(res["dry_run"])
        matched_cpu = [r for r in res["executed_rules"] if r.get("matched")]
        self.assertTrue(len(matched_cpu) >= 1)
        for r in matched_cpu:
            for act in r["action_results"]:
                self.assertEqual(act["status"], "dry_run_simulated")

        # Zero persistent side effects in database
        self.assertEqual(len(self.storage.get_logs()), initial_logs)
        self.assertEqual(len(self.storage.get_notifications()), initial_notifs)


class TestFlaskAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        flask_app_module.app.config["TESTING"] = True
        cls.client = flask_app_module.app.test_client()

    def test_index_route(self):
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"AI AUTOMATION COMMAND CENTER", res.data)

    def test_api_status_and_telemetry(self):
        res_status = self.client.get("/api/status")
        self.assertEqual(res_status.status_code, 200)
        status_data = res_status.get_json()
        self.assertIn("engine_running", status_data)
        self.assertIn("stats", status_data)

        res_telem = self.client.get("/api/telemetry")
        self.assertEqual(res_telem.status_code, 200)
        telem_data = res_telem.get_json()
        self.assertIn("cpu_percent", telem_data)

    def test_api_rules_crud(self):
        # List rules
        res_list = self.client.get("/api/rules")
        self.assertEqual(res_list.status_code, 200)
        rules = res_list.get_json()["rules"]
        self.assertIsInstance(rules, list)

        # Create rule
        new_rule = {
            "name": "API Created Rule",
            "category": "DevOps",
            "priority": 50,
            "trigger": {"type": "event", "event_name": "test.api"},
            "condition": {"logic": "AND", "conditions": []},
            "actions": [{"type": "notification", "params": {"message": "Test"}}]
        }
        res_create = self.client.post("/api/rules", json=new_rule)
        self.assertEqual(res_create.status_code, 201)
        created_id = res_create.get_json()["rule_id"]

        # Toggle rule
        res_toggle = self.client.post(f"/api/rules/{created_id}/toggle", json={"enabled": False})
        self.assertEqual(res_toggle.status_code, 200)
        self.assertFalse(res_toggle.get_json()["enabled"])

        # Delete rule
        res_del = self.client.delete(f"/api/rules/{created_id}")
        self.assertEqual(res_del.status_code, 200)

    def test_api_event_dispatch(self):
        res = self.client.post("/api/events/dispatch", json={
            "event_name": "auth.failed",
            "payload": {"ip": "10.0.0.99", "attempts": 6},
            "source": "api_test"
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["status"], "completed")

    def test_api_nlp_analyze(self):
        res = self.client.post("/api/nlp/analyze", json={
            "text": "Emergency: high memory surge and server crash on worker-node-03",
            "dry_run": True
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("nlp", data)
        self.assertEqual(data["nlp"]["intent"], "server_alert")

    def test_api_presets(self):
        res = self.client.get("/api/presets")
        self.assertEqual(res.status_code, 200)
        presets = res.get_json()["presets"]
        self.assertGreaterEqual(len(presets), 4)

    def test_nlp_sandbox_triggers_cpu_sentinel(self):
        # Verify that natural language prompts trigger the High CPU Resource Sentinel blueprint
        self.client.post("/api/presets/install", json={"preset_id": "blueprint-cpu-sentinel"})

        res = self.client.post("/api/nlp/analyze", json={
            "text": "Critical emergency: database memory utilization surged to 96% on prod-db-01",
            "dry_run": True
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        executed = data.get("simulation", {}).get("executed_rules", [])
        matched_names = [r["rule_name"] for r in executed if r.get("matched")]
        self.assertTrue(any("CPU" in name for name in matched_names))

    def test_api_dispatch_system_metrics_simulation_path(self):
        # 1. Dispatch below/equal 85% via API with dry_run
        res_85 = self.client.post("/api/events/dispatch", json={
            "event_name": "system.metrics",
            "payload": {"cpu_percent": 85.0, "host": "prod-api-01"},
            "source": "system_metrics_simulator",
            "dry_run": True
        })
        self.assertEqual(res_85.status_code, 200)
        data_85 = res_85.get_json()
        cpu_rule_85 = next(r for r in data_85["executed_rules"] if "CPU" in r["rule_name"] or r.get("priority") == 90)
        self.assertFalse(cpu_rule_85["matched"])
        self.assertEqual(cpu_rule_85["status"], "skipped")
        self.assertFalse(cpu_rule_85["trace"][0]["passed"])

        # 2. Dispatch above 85% via API with dry_run
        res_95 = self.client.post("/api/events/dispatch", json={
            "event_name": "system.metrics",
            "payload": {"cpu_percent": 95.0, "host": "prod-api-01"},
            "source": "system_metrics_simulator",
            "dry_run": True
        })
        self.assertEqual(res_95.status_code, 200)
        data_95 = res_95.get_json()
        cpu_rule_95 = next(r for r in data_95["executed_rules"] if "CPU" in r["rule_name"] or r.get("priority") == 90)
        self.assertTrue(cpu_rule_95["matched"])
        self.assertEqual(cpu_rule_95["status"], "success")
        self.assertTrue(cpu_rule_95["trace"][0]["passed"])
        for act in cpu_rule_95["action_results"]:
            self.assertEqual(act["status"], "dry_run_simulated")

    def test_nlp_sandbox_p90_triggers_cpu_sentinel(self):
        """Verify that prompts referencing P90 or High CPU Sentinel trigger High CPU Resource Sentinel."""
        self.client.post("/api/presets/install", json={"preset_id": "blueprint-cpu-sentinel"})

        res = self.client.post("/api/nlp/analyze", json={
            "text": "Critical alert: High CPU Resource Sentinel P90 load surge detected on prod-api-01",
            "dry_run": True
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()

        # The simulated event should be mapped to system.metrics
        self.assertEqual(data.get("simulation", {}).get("event_name"), "system.metrics")

        # The High CPU Resource Sentinel rule should be MATCHED & TRIGGERED
        executed = data.get("simulation", {}).get("executed_rules", [])
        cpu_rules = [r for r in executed if "CPU" in r["rule_name"] or r.get("priority") == 90]
        self.assertTrue(any(r.get("matched") for r in cpu_rules))

        # Check that P90 was extracted as percentage
        percentages = data.get("nlp", {}).get("entities", {}).get("percentages", [])
        self.assertIn("90", percentages)


if __name__ == "__main__":
    unittest.main()

