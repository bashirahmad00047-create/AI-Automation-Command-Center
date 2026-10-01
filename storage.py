"""Storage Layer for AI Automation Command Center.

Provides thread-safe SQLite persistence for:
- Automation Rules
- Execution Logs & Audit Trail
- In-App Alerts & Notifications
- Default Preset Blueprints Seeding
"""

from __future__ import annotations

import datetime
import json
import os
import sqlite3
import threading
from typing import Any, Dict, List, Optional


class Storage:
    """Thread-safe SQLite storage for rules, logs, and telemetry."""

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            db_path = os.path.join(base_dir, "command_center.db")
        self.db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=15.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                # 1. Rules table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS rules (
                        id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        description TEXT,
                        category TEXT NOT NULL DEFAULT 'System',
                        enabled INTEGER NOT NULL DEFAULT 1,
                        priority INTEGER NOT NULL DEFAULT 10,
                        cooldown_seconds INTEGER NOT NULL DEFAULT 0,
                        trigger_json TEXT NOT NULL,
                        condition_json TEXT NOT NULL,
                        actions_json TEXT NOT NULL,
                        last_triggered TEXT,
                        execution_count INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL
                    )
                """)

                # 2. Execution Logs table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS execution_logs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        rule_id TEXT,
                        rule_name TEXT NOT NULL,
                        timestamp TEXT NOT NULL,
                        trigger_type TEXT NOT NULL,
                        event_name TEXT NOT NULL,
                        matched INTEGER NOT NULL,
                        status TEXT NOT NULL,
                        duration_ms REAL NOT NULL,
                        trace_json TEXT,
                        results_json TEXT,
                        error_message TEXT
                    )
                """)

                # 3. Notifications table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS notifications (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        title TEXT NOT NULL,
                        message TEXT NOT NULL,
                        severity TEXT NOT NULL DEFAULT 'info',
                        timestamp TEXT NOT NULL,
                        read INTEGER NOT NULL DEFAULT 0
                    )
                """)

                # Align CPU Sentinel condition to > 85 and standard naming
                cursor.execute("""
                    UPDATE rules
                    SET condition_json = REPLACE(condition_json, '"operator": ">="', '"operator": ">"')
                    WHERE (id LIKE '%cpu%' OR name LIKE '%CPU%') AND condition_json LIKE '%cpu_percent%' AND condition_json LIKE '%85%'
                """)
                cursor.execute("""
                    UPDATE rules
                    SET name = 'High CPU Resource Sentinel'
                    WHERE id = 'rule-cpu-sentinel'
                """)

                conn.commit()

        # Seed presets if database is freshly created and has no rules
        self._seed_default_rules()

    def _seed_default_rules(self):
        """Seeds initial production-grade automation rules if empty."""
        rules = self.get_rules()
        if rules:
            return

        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        preset_rules = [
            {
                "id": "rule-cpu-sentinel",
                "name": "High CPU Resource Sentinel",
                "description": "Alerts operations and records diagnostics whenever CPU utilization exceeds 85%.",
                "category": "System",
                "enabled": 1,
                "priority": 90,
                "cooldown_seconds": 30,
                "trigger": {"type": "event", "event_name": "system.metrics"},
                "condition": {
                    "logic": "AND",
                    "conditions": [
                        {"field": "payload.cpu_percent", "operator": ">", "value": 85}
                    ]
                },
                "actions": [
                    {
                        "type": "notification",
                        "params": {
                            "title": "CPU Spike Detected ({{ payload.cpu_percent }}%)",
                            "message": "Resource usage exceeded critical threshold on host {{ payload.host }}.",
                            "severity": "critical"
                        }
                    },
                    {
                        "type": "log_entry",
                        "params": {
                            "level": "CRITICAL",
                            "message": "High CPU utilization: {{ payload.cpu_percent }}% recorded on {{ payload.host }}."
                        }
                    }
                ],
                "created_at": now
            },
            {
                "id": "rule-security-quarantine",
                "name": "Security Threat & Intrusion Quarantine",
                "description": "Detects unauthorized login attempts or malicious intrusion IPs and dispatches security alert.",
                "category": "Security",
                "enabled": 1,
                "priority": 100,
                "cooldown_seconds": 15,
                "trigger": {"type": "event", "event_name": "auth.failed"},
                "condition": {
                    "logic": "OR",
                    "conditions": [
                        {"field": "payload.attempts", "operator": ">=", "value": 3},
                        {"field": "nlp.intent", "operator": "equals", "value": "security_threat"}
                    ]
                },
                "actions": [
                    {
                        "type": "notification",
                        "params": {
                            "title": "Intrusion Alert: IP Flagged",
                            "message": "Multiple failed attempts from {{ payload.ip }}. Auto-quarantine initiated.",
                            "severity": "critical"
                        }
                    },
                    {
                        "type": "email_dispatch",
                        "params": {
                            "to": "soc-alerts@commandcenter.internal",
                            "subject": "[SEV-1] Security Intrusion Flagged: {{ payload.ip }}",
                            "body": "Host IP {{ payload.ip }} triggered quarantine rule after repeated unauthorized attempts."
                        }
                    },
                    {
                        "type": "log_entry",
                        "params": {
                            "level": "WARNING",
                            "message": "Quarantined threat candidate IP {{ payload.ip }} with {{ payload.attempts }} attempts."
                        }
                    }
                ],
                "created_at": now
            },
            {
                "id": "rule-nlp-triage",
                "name": "Smart NLP Emergency Ticket Router",
                "description": "Scans incoming textual reports, computes intent & urgency, and escalates high-urgency incidents.",
                "category": "NLP",
                "enabled": 1,
                "priority": 85,
                "cooldown_seconds": 10,
                "trigger": {"type": "natural_text", "event_name": "user.prompt"},
                "condition": {
                    "logic": "AND",
                    "conditions": [
                        {"field": "nlp.urgency", "operator": ">=", "value": 60}
                    ]
                },
                "actions": [
                    {
                        "type": "notification",
                        "params": {
                            "title": "Urgent Incident Escalate (Urgency: {{ nlp.urgency }})",
                            "message": "NLP classified intent '{{ nlp.intent }}' with urgency {{ nlp.urgency }}/100.",
                            "severity": "warning"
                        }
                    },
                    {
                        "type": "file_append",
                        "params": {
                            "filename": "urgent_nlp_escalations.log",
                            "content": "[{{ nlp.severity_level }}] Intent={{ nlp.intent }}, Urgency={{ nlp.urgency }}, Text={{ nlp.text }}"
                        }
                    }
                ],
                "created_at": now
            },
            {
                "id": "rule-api-outage",
                "name": "API Service Outage Auto-Recovery",
                "description": "Monitors HTTP errors (500/502/503) and dispatches webhook diagnostic ping.",
                "category": "DevOps",
                "enabled": 1,
                "priority": 75,
                "cooldown_seconds": 20,
                "trigger": {"type": "event", "event_name": "api.error"},
                "condition": {
                    "logic": "OR",
                    "conditions": [
                        {"field": "payload.status_code", "operator": "greater_than_or_equal", "value": 500},
                        {"field": "payload.status_code", "operator": "in_list", "value": "500,502,503,504"}
                    ]
                },
                "actions": [
                    {
                        "type": "webhook_call",
                        "params": {
                            "url": "https://api.internal/v1/auto-restart",
                            "method": "POST"
                        }
                    },
                    {
                        "type": "notification",
                        "params": {
                            "title": "API Outage Auto-Recovery",
                            "message": "Gateway reported error {{ payload.status_code }} on endpoint {{ payload.endpoint }}.",
                            "severity": "critical"
                        }
                    }
                ],
                "created_at": now
            },
            {
                "id": "rule-daily-backup",
                "name": "Automated Backup & Archive Verification",
                "description": "Validates database backup success and logs archive verification digest.",
                "category": "DevOps",
                "enabled": 1,
                "priority": 50,
                "cooldown_seconds": 60,
                "trigger": {"type": "event", "event_name": "backup.completed"},
                "condition": {
                    "logic": "AND",
                    "conditions": [
                        {"field": "payload.status", "operator": "equals", "value": "success"}
                    ]
                },
                "actions": [
                    {
                        "type": "notification",
                        "params": {
                            "title": "Backup Completed Successfully",
                            "message": "Snapshot for {{ payload.database }} verified ({{ payload.size_mb }} MB).",
                            "severity": "success"
                        }
                    },
                    {
                        "type": "file_append",
                        "params": {
                            "filename": "backup_audit.log",
                            "content": "Database: {{ payload.database }} | Size: {{ payload.size_mb }}MB | Verified: True"
                        }
                    }
                ],
                "created_at": now
            }
        ]

        for p in preset_rules:
            self.save_rule(p)

    def get_rules(self, category: Optional[str] = None, enabled_only: bool = False) -> List[Dict[str, Any]]:
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                query = "SELECT * FROM rules WHERE 1=1"
                params: List[Any] = []

                if category and category.lower() != "all":
                    query += " AND category = ?"
                    params.append(category)

                if enabled_only:
                    query += " AND enabled = 1"

                query += " ORDER BY priority DESC, created_at DESC"
                cursor.execute(query, params)
                rows = cursor.fetchall()

                rules = []
                for row in rows:
                    rules.append({
                        "id": row["id"],
                        "name": row["name"],
                        "description": row["description"],
                        "category": row["category"],
                        "enabled": bool(row["enabled"]),
                        "priority": row["priority"],
                        "cooldown_seconds": row["cooldown_seconds"],
                        "trigger": json.loads(row["trigger_json"]),
                        "condition": json.loads(row["condition_json"]),
                        "actions": json.loads(row["actions_json"]),
                        "last_triggered": row["last_triggered"],
                        "execution_count": row["execution_count"],
                        "created_at": row["created_at"]
                    })
                return rules

    def get_rule(self, rule_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM rules WHERE id = ?", (rule_id,))
                row = cursor.fetchone()
                if not row:
                    return None
                return {
                    "id": row["id"],
                    "name": row["name"],
                    "description": row["description"],
                    "category": row["category"],
                    "enabled": bool(row["enabled"]),
                    "priority": row["priority"],
                    "cooldown_seconds": row["cooldown_seconds"],
                    "trigger": json.loads(row["trigger_json"]),
                    "condition": json.loads(row["condition_json"]),
                    "actions": json.loads(row["actions_json"]),
                    "last_triggered": row["last_triggered"],
                    "execution_count": row["execution_count"],
                    "created_at": row["created_at"]
                }

    def save_rule(self, rule: Dict[str, Any]) -> str:
        rule_id = rule.get("id") or f"rule-{int(datetime.datetime.now().timestamp() * 1000)}"
        name = rule.get("name", "Untitled Rule")
        desc = rule.get("description", "")
        category = rule.get("category", "System")
        enabled = 1 if rule.get("enabled", True) else 0
        priority = int(rule.get("priority", 10))
        cooldown = int(rule.get("cooldown_seconds", 0))

        trigger_json = json.dumps(rule.get("trigger", {"type": "event", "event_name": "*"}))
        condition_json = json.dumps(rule.get("condition", {"logic": "AND", "conditions": []}))
        actions_json = json.dumps(rule.get("actions", []))
        created_at = rule.get("created_at") or datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO rules (
                        id, name, description, category, enabled, priority,
                        cooldown_seconds, trigger_json, condition_json, actions_json,
                        created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        name=excluded.name,
                        description=excluded.description,
                        category=excluded.category,
                        enabled=excluded.enabled,
                        priority=excluded.priority,
                        cooldown_seconds=excluded.cooldown_seconds,
                        trigger_json=excluded.trigger_json,
                        condition_json=excluded.condition_json,
                        actions_json=excluded.actions_json
                """, (
                    rule_id, name, desc, category, enabled, priority,
                    cooldown, trigger_json, condition_json, actions_json,
                    created_at
                ))
                conn.commit()
        return rule_id

    def delete_rule(self, rule_id: str) -> bool:
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM rules WHERE id = ?", (rule_id,))
                conn.commit()
                return cursor.rowcount > 0

    def toggle_rule(self, rule_id: str, enabled: Optional[bool] = None) -> Optional[bool]:
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                if enabled is None:
                    cursor.execute("SELECT enabled FROM rules WHERE id = ?", (rule_id,))
                    row = cursor.fetchone()
                    if not row:
                        return None
                    new_state = 0 if row["enabled"] else 1
                else:
                    new_state = 1 if enabled else 0

                cursor.execute("UPDATE rules SET enabled = ? WHERE id = ?", (new_state, rule_id))
                conn.commit()
                return bool(new_state)

    def record_rule_trigger(self, rule_id: str):
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE rules
                    SET execution_count = execution_count + 1,
                        last_triggered = ?
                    WHERE id = ?
                """, (now, rule_id))
                conn.commit()

    def log_execution(self, log_entry: Dict[str, Any]) -> int:
        rule_id = log_entry.get("rule_id", "unknown")
        rule_name = log_entry.get("rule_name", "Unknown Rule")
        timestamp = log_entry.get("timestamp") or datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        trigger_type = log_entry.get("trigger_type", "event")
        event_name = log_entry.get("event_name", "unspecified")
        matched = 1 if log_entry.get("matched", True) else 0
        status = log_entry.get("status", "success")
        duration_ms = float(log_entry.get("duration_ms", 0.0))
        trace_json = json.dumps(log_entry.get("trace", []))
        results_json = json.dumps(log_entry.get("results", []))
        error_msg = log_entry.get("error_message")

        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO execution_logs (
                        rule_id, rule_name, timestamp, trigger_type, event_name,
                        matched, status, duration_ms, trace_json, results_json, error_message
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    rule_id, rule_name, timestamp, trigger_type, event_name,
                    matched, status, duration_ms, trace_json, results_json, error_msg
                ))
                conn.commit()
                return cursor.lastrowid

    def get_logs(
        self,
        limit: int = 50,
        offset: int = 0,
        status: Optional[str] = None,
        rule_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                query = "SELECT * FROM execution_logs WHERE 1=1"
                params: List[Any] = []

                if status and status.lower() != "all":
                    query += " AND status = ?"
                    params.append(status.lower())

                if rule_id:
                    query += " AND rule_id = ?"
                    params.append(rule_id)

                query += " ORDER BY id DESC LIMIT ? OFFSET ?"
                params.extend([limit, offset])

                cursor.execute(query, params)
                rows = cursor.fetchall()

                logs = []
                for row in rows:
                    logs.append({
                        "id": row["id"],
                        "rule_id": row["rule_id"],
                        "rule_name": row["rule_name"],
                        "timestamp": row["timestamp"],
                        "trigger_type": row["trigger_type"],
                        "event_name": row["event_name"],
                        "matched": bool(row["matched"]),
                        "status": row["status"],
                        "duration_ms": row["duration_ms"],
                        "trace": json.loads(row["trace_json"]) if row["trace_json"] else [],
                        "results": json.loads(row["results_json"]) if row["results_json"] else [],
                        "error_message": row["error_message"]
                    })
                return logs

    def clear_logs(self):
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM execution_logs")
                conn.commit()

    def add_notification(self, title: str, message: str, severity: str = "info") -> int:
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO notifications (title, message, severity, timestamp, read)
                    VALUES (?, ?, ?, ?, 0)
                """, (title, message, severity, now))
                conn.commit()
                return cursor.lastrowid

    def get_notifications(self, limit: int = 20, unread_only: bool = False) -> List[Dict[str, Any]]:
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                query = "SELECT * FROM notifications"
                if unread_only:
                    query += " WHERE read = 0"
                query += " ORDER BY id DESC LIMIT ?"
                cursor.execute(query, (limit,))
                rows = cursor.fetchall()
                return [
                    {
                        "id": row["id"],
                        "title": row["title"],
                        "message": row["message"],
                        "severity": row["severity"],
                        "timestamp": row["timestamp"],
                        "read": bool(row["read"])
                    }
                    for row in rows
                ]

    def mark_notifications_read(self):
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("UPDATE notifications SET read = 1 WHERE read = 0")
                conn.commit()

    def clear_notifications(self):
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM notifications")
                conn.commit()

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()

                # Rules stats
                cursor.execute("SELECT COUNT(*) FROM rules")
                total_rules = cursor.fetchone()[0]

                cursor.execute("SELECT COUNT(*) FROM rules WHERE enabled = 1")
                active_rules = cursor.fetchone()[0]

                # Executions stats
                cursor.execute("SELECT COUNT(*) FROM execution_logs")
                total_executions = cursor.fetchone()[0]

                cursor.execute("SELECT COUNT(*) FROM execution_logs WHERE status = 'success'")
                successful_executions = cursor.fetchone()[0]

                cursor.execute("SELECT COUNT(*) FROM notifications WHERE read = 0")
                unread_notifications = cursor.fetchone()[0]

                # Category breakdown
                cursor.execute("SELECT category, COUNT(*) as cnt FROM rules GROUP BY category")
                cat_rows = cursor.fetchall()
                category_counts = {row["category"]: row["cnt"] for row in cat_rows}

                success_rate = 100.0 if total_executions == 0 else round((successful_executions / total_executions) * 100, 1)

                return {
                    "total_rules": total_rules,
                    "active_rules": active_rules,
                    "total_executions": total_executions,
                    "successful_executions": successful_executions,
                    "success_rate": success_rate,
                    "unread_notifications": unread_notifications,
                    "categories": category_counts
                }
