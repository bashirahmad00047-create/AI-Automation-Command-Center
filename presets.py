"""Preset Automation Blueprints for the AI Automation Command Center.

Pre-configured, production-ready rule templates across System, Security,
DevOps, NLP, and Data management domains.
"""

from __future__ import annotations

from typing import Any, Dict, List


PRESET_BLUEPRINTS: List[Dict[str, Any]] = [
    {
        "id": "blueprint-cpu-sentinel",
        "name": "High CPU Resource Sentinel",
        "description": "Continuously monitors system CPU load. Fires critical alerts and captures diagnostics whenever CPU exceeds 85%.",
        "category": "System",
        "priority": 90,
        "cooldown_seconds": 30,
        "trigger": {
            "type": "event",
            "event_name": "system.metrics"
        },
        "condition": {
            "logic": "AND",
            "conditions": [
                {"field": "payload.cpu_percent", "operator": ">=", "value": 85}
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
        ]
    },
    {
        "id": "blueprint-security-quarantine",
        "name": "Security Threat & Intrusion Quarantine",
        "description": "Detects multiple failed login attempts or NLP security flags; triggers incident alerts and audit logging.",
        "category": "Security",
        "priority": 100,
        "cooldown_seconds": 15,
        "trigger": {
            "type": "event",
            "event_name": "auth.failed"
        },
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
                    "title": "Security Intrusion Flagged",
                    "message": "Host IP {{ payload.ip }} flagged after repeated failed authentication.",
                    "severity": "critical"
                }
            },
            {
                "type": "email_dispatch",
                "params": {
                    "to": "soc-team@commandcenter.internal",
                    "subject": "[SEV-1] Security Intrusion Flagged: {{ payload.ip }}",
                    "body": "IP {{ payload.ip }} triggered quarantine rule after {{ payload.attempts }} attempts."
                }
            },
            {
                "type": "log_entry",
                "params": {
                    "level": "WARNING",
                    "message": "Quarantined threat candidate IP {{ payload.ip }} with {{ payload.attempts }} attempts."
                }
            }
        ]
    },
    {
        "id": "blueprint-nlp-triage",
        "name": "Smart NLP Emergency Ticket Router",
        "description": "Scans incoming textual reports, computes intent & urgency scores, and automatically routes critical reports.",
        "category": "NLP",
        "priority": 85,
        "cooldown_seconds": 10,
        "trigger": {
            "type": "natural_text",
            "event_name": "user.prompt"
        },
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
                    "title": "Urgent Incident Escalated (Score: {{ nlp.urgency }})",
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
        ]
    },
    {
        "id": "blueprint-api-outage",
        "name": "API Service Outage Auto-Recovery",
        "description": "Monitors gateway HTTP error codes (500, 502, 503) and dispatches auto-recovery webhooks.",
        "category": "DevOps",
        "priority": 75,
        "cooldown_seconds": 20,
        "trigger": {
            "type": "event",
            "event_name": "api.error"
        },
        "condition": {
            "logic": "OR",
            "conditions": [
                {"field": "payload.status_code", "operator": ">=", "value": 500}
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
                    "title": "API Gateway Outage Detected",
                    "message": "Encountered HTTP {{ payload.status_code }} on endpoint {{ payload.endpoint }}. Dispatching recovery hook.",
                    "severity": "critical"
                }
            }
        ]
    },
    {
        "id": "blueprint-daily-backup",
        "name": "Automated Backup & Archive Verification",
        "description": "Verifies scheduled database snapshots and automatically records audit logs.",
        "category": "DevOps",
        "priority": 50,
        "cooldown_seconds": 60,
        "trigger": {
            "type": "event",
            "event_name": "backup.completed"
        },
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
                    "title": "Database Snapshot Verified",
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
        ]
    },
    {
        "id": "blueprint-disk-cleaner",
        "name": "Disk Storage Pressure Guard",
        "description": "Alerts operations and runs log cleanup scripts whenever disk storage utilization exceeds 90%.",
        "category": "System",
        "priority": 80,
        "cooldown_seconds": 60,
        "trigger": {
            "type": "event",
            "event_name": "system.metrics"
        },
        "condition": {
            "logic": "AND",
            "conditions": [
                {"field": "payload.disk_percent", "operator": ">=", "value": 90}
            ]
        },
        "actions": [
            {
                "type": "notification",
                "params": {
                    "title": "Disk Space Critical ({{ payload.disk_percent }}%)",
                    "message": "Storage volume capacity exceeded 90%. Automatic cleanup recommended.",
                    "severity": "critical"
                }
            },
            {
                "type": "system_command",
                "params": {
                    "command": "clean_temp_logs --retention 7d"
                }
            }
        ]
    },
    {
        "id": "blueprint-data-anomaly",
        "name": "Data Ingestion Pipeline Anomaly Filter",
        "description": "Validates ETL batch ingest metrics and flags batches containing high corruption or error rates.",
        "category": "Data",
        "priority": 65,
        "cooldown_seconds": 30,
        "trigger": {
            "type": "event",
            "event_name": "etl.batch_processed"
        },
        "condition": {
            "logic": "AND",
            "conditions": [
                {"field": "payload.error_rate_pct", "operator": ">", "value": 5.0}
            ]
        },
        "actions": [
            {
                "type": "notification",
                "params": {
                    "title": "ETL Batch Anomaly Flagged",
                    "message": "Batch {{ payload.batch_id }} rejected with error rate {{ payload.error_rate_pct }}%.",
                    "severity": "warning"
                }
            },
            {
                "type": "data_transform",
                "params": {
                    "target_key": "etl_status",
                    "transform": "tag",
                    "tag": "BATCH_REQUIRES_MANUAL_REVIEW"
                }
            }
        ]
    }
]
