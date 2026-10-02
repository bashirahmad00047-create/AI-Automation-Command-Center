"""Preset Automation Blueprints & Production Templates for OpsFlow Cloud.

Includes 8 Working Enterprise SaaS Templates:
1. AI Lead Qualification
2. Customer Support Router
3. Critical Incident Router
4. Sales Lead Follow-up
5. Website Contact Form Automation
6. API Failure Alert
7. Security Incident Detection
8. Document/Inquiry Triage
Plus diagnostic blueprints (High CPU Resource Sentinel, Security Threat Quarantine) for infrastructure telemetry.
"""

from __future__ import annotations

from typing import Any, Dict, List


PRESET_BLUEPRINTS: List[Dict[str, Any]] = [
    # 1. AI Lead Qualification
    {
        "id": "template-ai-lead-qualification",
        "name": "AI Lead Qualification",
        "description": "Ingests incoming customer leads, analyzes buyer intent & budget, scores lead readiness, and routes hot leads directly to Sales CRM.",
        "category": "Sales",
        "priority": 95,
        "cooldown_seconds": 5,
        "trigger": {
            "type": "event",
            "event_name": "lead.created"
        },
        "condition": {
            "logic": "OR",
            "conditions": [
                {"field": "payload.message", "operator": "exists", "value": True},
                {"field": "nlp.lead_score", "operator": ">=", "value": 40}
            ]
        },
        "actions": [
            {
                "type": "database_record",
                "params": {
                    "entity": "lead",
                    "status": "qualified"
                }
            },
            {
                "type": "email_draft",
                "params": {
                    "template": "sales_discovery",
                    "recipient": "{{ payload.email }}"
                }
            },
            {
                "type": "notification",
                "params": {
                    "title": "Qualified Lead Received (Score: {{ nlp.lead_score }})",
                    "message": "Inquiry from {{ payload.name }} ({{ payload.email }}) routed to Sales queue.",
                    "severity": "info"
                }
            },
            {
                "type": "log_entry",
                "params": {
                    "level": "INFO",
                    "message": "AI Lead Qualification executed for {{ payload.email }}."
                }
            }
        ],
        "steps": [
            {"type": "trigger", "name": "Event: lead.created", "config": {"event_name": "lead.created"}},
            {"type": "ai_analysis", "name": "Extract Intent & Entities", "config": {"field": "payload.message"}},
            {"type": "lead_scoring", "name": "Compute Predictive Lead Score", "config": {"threshold": 50}},
            {"type": "route", "name": "Smart Department Route", "config": {"destination": "Sales"}},
            {"type": "email_draft", "name": "Draft Tailored Sales Response", "config": {}},
            {"type": "database_record", "name": "Persist Lead in CRM", "config": {"table": "leads"}},
            {"type": "notification", "name": "Notify Sales Channel", "config": {}},
            {"type": "end", "name": "Workflow Complete", "config": {}}
        ]
    },

    # 2. Customer Support Router
    {
        "id": "template-customer-support-router",
        "name": "Customer Support Router",
        "description": "Analyzes inbound support tickets, detects negative sentiment or urgent bugs, and routes to Support specialists.",
        "category": "Support",
        "priority": 85,
        "cooldown_seconds": 5,
        "trigger": {
            "type": "event",
            "event_name": "support.inquiry"
        },
        "condition": {
            "logic": "AND",
            "conditions": [
                {"field": "payload.message", "operator": "exists", "value": True}
            ]
        },
        "actions": [
            {
                "type": "email_draft",
                "params": {
                    "template": "support_ack",
                    "recipient": "{{ payload.email }}"
                }
            },
            {
                "type": "notification",
                "params": {
                    "title": "Support Ticket Ingested",
                    "message": "Inquiry from {{ payload.name }} categorized as {{ nlp.intent }}.",
                    "severity": "info"
                }
            },
            {
                "type": "log_entry",
                "params": {
                    "level": "INFO",
                    "message": "Support router dispatched ticket for {{ payload.email }}."
                }
            }
        ],
        "steps": [
            {"type": "trigger", "name": "Event: support.inquiry", "config": {"event_name": "support.inquiry"}},
            {"type": "ai_analysis", "name": "Analyze Issue Severity", "config": {}},
            {"type": "sentiment_detection", "name": "Detect Customer Sentiment", "config": {}},
            {"type": "route", "name": "Route to Support Tier", "config": {"destination": "Support"}},
            {"type": "email_draft", "name": "Generate Acknowledgment Draft", "config": {}},
            {"type": "notification", "name": "In-App Notification", "config": {}},
            {"type": "end", "name": "Workflow Complete", "config": {}}
        ]
    },

    # 3. Critical Incident Router
    {
        "id": "template-critical-incident-router",
        "name": "Critical Incident Router",
        "description": "Detects P1/Sev-1 outages, data errors, or system crashes; immediately triggers high-priority alerts and incident response.",
        "category": "Incident",
        "priority": 100,
        "cooldown_seconds": 15,
        "trigger": {
            "type": "event",
            "event_name": "incident.reported"
        },
        "condition": {
            "logic": "OR",
            "conditions": [
                {"field": "nlp.urgency", "operator": ">=", "value": 70},
                {"field": "payload.severity", "operator": "equals", "value": "critical"},
                {"field": "nlp.intent", "operator": "equals", "value": "critical_incident"}
            ]
        },
        "actions": [
            {
                "type": "notification",
                "params": {
                    "title": "[SEV-1 CRITICAL] Incident Detected",
                    "message": "Immediate attention required: {{ payload.message }}.",
                    "severity": "critical"
                }
            },
            {
                "type": "log_entry",
                "params": {
                    "level": "CRITICAL",
                    "message": "Critical Incident Router triggered for payload {{ payload }}."
                }
            }
        ],
        "steps": [
            {"type": "trigger", "name": "Event: incident.reported", "config": {}},
            {"type": "ai_analysis", "name": "Triage Incident Urgency", "config": {}},
            {"type": "urgency_detection", "name": "Verify SEV-1 Threshold", "config": {"min_urgency": 70}},
            {"type": "route", "name": "Route to Priority Support", "config": {"destination": "Priority Support"}},
            {"type": "notification", "name": "Dispatch Critical Alert", "config": {"severity": "critical"}},
            {"type": "end", "name": "Workflow Complete", "config": {}}
        ]
    },

    # 4. Sales Lead Follow-up
    {
        "id": "template-sales-lead-followup",
        "name": "Sales Lead Follow-up",
        "description": "Triggers automated follow-up drafting and account executive task generation whenever a lead requests a quote or demo.",
        "category": "Sales",
        "priority": 90,
        "cooldown_seconds": 10,
        "trigger": {
            "type": "event",
            "event_name": "sales.demo_requested"
        },
        "condition": {
            "logic": "AND",
            "conditions": [
                {"field": "payload.email", "operator": "exists", "value": True}
            ]
        },
        "actions": [
            {
                "type": "database_record",
                "params": {
                    "entity": "lead",
                    "status": "contacted"
                }
            },
            {
                "type": "email_draft",
                "params": {
                    "template": "demo_scheduling",
                    "recipient": "{{ payload.email }}"
                }
            },
            {
                "type": "notification",
                "params": {
                    "title": "Demo Follow-up Drafted",
                    "message": "Demo scheduling response drafted for {{ payload.name }} ({{ payload.email }}).",
                    "severity": "info"
                }
            }
        ],
        "steps": [
            {"type": "trigger", "name": "Event: sales.demo_requested", "config": {}},
            {"type": "ai_analysis", "name": "Parse Company & Timing", "config": {}},
            {"type": "email_draft", "name": "Draft Demo Invitation", "config": {}},
            {"type": "database_record", "name": "Update Lead Status", "config": {}},
            {"type": "notification", "name": "Alert Account Exec", "config": {}},
            {"type": "end", "name": "Workflow Complete", "config": {}}
        ]
    },

    # 5. Website Contact Form Automation
    {
        "id": "template-contact-form-automation",
        "name": "Website Contact Form Automation",
        "description": "Processes public web contact submissions, extracts emails and phone numbers, and stores clean CRM records.",
        "category": "Webhooks",
        "priority": 80,
        "cooldown_seconds": 0,
        "trigger": {
            "type": "event",
            "event_name": "contact.submitted"
        },
        "condition": {
            "logic": "AND",
            "conditions": [
                {"field": "payload.message", "operator": "exists", "value": True}
            ]
        },
        "actions": [
            {
                "type": "database_record",
                "params": {
                    "entity": "lead",
                    "status": "new"
                }
            },
            {
                "type": "notification",
                "params": {
                    "title": "Website Contact Submission",
                    "message": "Submission from {{ payload.name }} ({{ payload.email }}).",
                    "severity": "info"
                }
            }
        ],
        "steps": [
            {"type": "trigger", "name": "Inbound Webhook: contact.submitted", "config": {}},
            {"type": "entity_extraction", "name": "Extract Contact Channels", "config": {}},
            {"type": "database_record", "name": "Create Lead in CRM", "config": {}},
            {"type": "notification", "name": "Broadcast In-App Alert", "config": {}},
            {"type": "end", "name": "Workflow Complete", "config": {}}
        ]
    },

    # 6. API Failure Alert
    {
        "id": "template-api-failure-alert",
        "name": "API Failure Alert",
        "description": "Monitors API error events (HTTP 500, 502, 503, 504), extracts error codes and hostnames, and alerts SRE engineers.",
        "category": "System",
        "priority": 95,
        "cooldown_seconds": 20,
        "trigger": {
            "type": "event",
            "event_name": "api.error"
        },
        "condition": {
            "logic": "OR",
            "conditions": [
                {"field": "payload.status_code", "operator": ">=", "value": 500},
                {"field": "payload.error", "operator": "exists", "value": True}
            ]
        },
        "actions": [
            {
                "type": "notification",
                "params": {
                    "title": "API Gateway Failure ({{ payload.status_code }})",
                    "message": "Service error detected on route {{ payload.path }}: {{ payload.error }}.",
                    "severity": "critical"
                }
            },
            {
                "type": "log_entry",
                "params": {
                    "level": "ERROR",
                    "message": "API Failure Alert: HTTP {{ payload.status_code }} on {{ payload.path }}."
                }
            }
        ],
        "steps": [
            {"type": "trigger", "name": "Event: api.error", "config": {}},
            {"type": "condition", "name": "Verify HTTP 5xx Status", "config": {}},
            {"type": "notification", "name": "Dispatch SRE Notification", "config": {}},
            {"type": "log_entry", "name": "Log Diagnostic Record", "config": {}},
            {"type": "end", "name": "Workflow Complete", "config": {}}
        ]
    },

    # 7. Security Incident Detection
    {
        "id": "template-security-incident-detection",
        "name": "Security Incident Detection",
        "description": "Detects repeated failed logins, brute-force attempts, or suspicious IPs and triggers quarantine protocols.",
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
                    "title": "Security Threat Quarantined",
                    "message": "Host IP {{ payload.ip }} flagged after repeated failed authentication.",
                    "severity": "critical"
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
        "steps": [
            {"type": "trigger", "name": "Event: auth.failed", "config": {}},
            {"type": "entity_extraction", "name": "Extract Offending IPv4", "config": {}},
            {"type": "condition", "name": "Check Attempt Threshold (>=3)", "config": {}},
            {"type": "route", "name": "Route to Security Operations", "config": {"destination": "Security Operations"}},
            {"type": "notification", "name": "Trigger SOC Alert", "config": {}},
            {"type": "end", "name": "Workflow Complete", "config": {}}
        ]
    },

    # 8. Document/Inquiry Triage
    {
        "id": "template-inquiry-triage",
        "name": "Document/Inquiry Triage",
        "description": "Scans unstructured natural language documents, parses key entities and metadata, and routes to appropriate queues.",
        "category": "NLP",
        "priority": 75,
        "cooldown_seconds": 5,
        "trigger": {
            "type": "event",
            "event_name": "document.submitted"
        },
        "condition": {
            "logic": "AND",
            "conditions": [
                {"field": "payload.text", "operator": "exists", "value": True}
            ]
        },
        "actions": [
            {
                "type": "notification",
                "params": {
                    "title": "Document Triage Complete",
                    "message": "Document triaged into {{ nlp.intent }} queue (Route: {{ nlp.recommended_route }}).",
                    "severity": "info"
                }
            },
            {
                "type": "log_entry",
                "params": {
                    "level": "INFO",
                    "message": "Document inquiry processed with sentiment {{ nlp.sentiment_label }}."
                }
            }
        ],
        "steps": [
            {"type": "trigger", "name": "Event: document.submitted", "config": {}},
            {"type": "ai_analysis", "name": "Extract Metadata & Entities", "config": {}},
            {"type": "intent_detection", "name": "Determine Inquiry Intent", "config": {}},
            {"type": "route", "name": "Route to Matching Queue", "config": {}},
            {"type": "notification", "name": "Notify Queue Lead", "config": {}},
            {"type": "end", "name": "Workflow Complete", "config": {}}
        ]
    },

    # Legacy blueprint compatibility (asserted in test_command_center.py)
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
        "steps": [
            {"type": "trigger", "name": "Event: system.metrics", "config": {}},
            {"type": "condition", "name": "CPU > 85%", "config": {}},
            {"type": "notification", "name": "Send Spike Alert", "config": {}},
            {"type": "end", "name": "Workflow Complete", "config": {}}
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
    # 9. Autonomous Incident RCA & Multi-Channel Mitigation
    {
        "id": "template-autonomous-incident-rca",
        "name": "Autonomous Incident RCA & Multi-Channel Mitigation",
        "description": "Ingests server crashes or error logs, executes instant AI Root Cause Analysis (RCA), generates SRE post-mortems, and dispatches multi-channel alerts.",
        "category": "Incident",
        "priority": 100,
        "cooldown_seconds": 10,
        "trigger": {
            "type": "event",
            "event_name": "system.crash"
        },
        "condition": {
            "logic": "OR",
            "conditions": [
                {"field": "payload.error", "operator": "exists", "value": True},
                {"field": "payload.message", "operator": "exists", "value": True}
            ]
        },
        "actions": [
            {
                "type": "notification",
                "params": {
                    "title": "[SEV-1] Autonomous Incident RCA Ready",
                    "message": "AI RCA completed for {{ payload.host }}: {{ nlp.intent }}.",
                    "severity": "critical"
                }
            },
            {
                "type": "log_entry",
                "params": {
                    "level": "CRITICAL",
                    "message": "Autonomous Incident RCA triggered for host {{ payload.host }}."
                }
            }
        ],
        "steps": [
            {"type": "trigger", "name": "Event: system.crash", "config": {"event_name": "system.crash"}},
            {"type": "ai_analysis", "name": "Triage Incident Urgency", "config": {}},
            {"type": "ai_summarize", "name": "Generate Automated RCA & Mitigation", "config": {"source_field": "payload.error"}},
            {"type": "notification", "name": "Dispatch SEV-1 Alert", "config": {"severity": "critical", "title": "[SEV-1] Incident RCA Ready"}},
            {"type": "webhook_call", "name": "Broadcast to SRE Webhook", "config": {"url": "https://api.opsflow.internal/hooks/sre-incident"}},
            {"type": "ai_generate", "name": "Draft Executive Post-Mortem", "config": {"prompt_template": "Draft incident postmortem for {{ payload.error }} on {{ payload.host }}."}},
            {"type": "end", "name": "Mitigation Pipeline Complete", "config": {}}
        ]
    },
    # 10. Intelligent Multi-Category Support Triage
    {
        "id": "template-intelligent-support-triage",
        "name": "Intelligent Multi-Category Support Triage",
        "description": "Multi-category customer ticket routing using AI classification, sentiment guardrails, and automated contextual reply drafting.",
        "category": "Support",
        "priority": 85,
        "cooldown_seconds": 5,
        "trigger": {
            "type": "event",
            "event_name": "support.ticket_created"
        },
        "condition": {
            "logic": "AND",
            "conditions": [
                {"field": "payload.message", "operator": "exists", "value": True}
            ]
        },
        "actions": [
            {
                "type": "database_record",
                "params": {
                    "entity": "lead",
                    "status": "new"
                }
            },
            {
                "type": "notification",
                "params": {
                    "title": "Customer Ticket Triaged (AI Route: {{ route.department }})",
                    "message": "Assigned ticket from {{ payload.name }} to {{ route.department }}.",
                    "severity": "info"
                }
            }
        ],
        "steps": [
            {"type": "trigger", "name": "Event: support.ticket_created", "config": {"event_name": "support.ticket_created"}},
            {"type": "ai_classify", "name": "Classify Ticket Category", "config": {"categories": ["DevOps", "Billing", "Security", "Support", "Sales"]}},
            {"type": "ai_sentiment_guard", "name": "Sentiment & Urgency Guard", "config": {"min_urgency": 40}},
            {"type": "ai_generate", "name": "Draft Contextual AI Reply", "config": {"prompt_template": "Draft courteous response to {{ payload.message }}."}},
            {"type": "database_record", "name": "Store Ticket in CRM", "config": {"entity": "lead"}},
            {"type": "notification", "name": "Notify Department Lead", "config": {"title": "New Support Ticket Assigned", "severity": "info"}},
            {"type": "end", "name": "Triage Complete", "config": {}}
        ]
    },
    # 11. Autonomous Threat Intelligence & IP Quarantine
    {
        "id": "template-threat-intel-sentinel",
        "name": "Autonomous Threat Intelligence & IP Quarantine",
        "description": "Scans security audit events, extracts attack indicators and malicious IPs via AI, and initiates automated isolation protocols.",
        "category": "Security",
        "priority": 95,
        "cooldown_seconds": 15,
        "trigger": {
            "type": "event",
            "event_name": "security.audit_alert"
        },
        "condition": {
            "logic": "OR",
            "conditions": [
                {"field": "payload.threat_level", "operator": "equals", "value": "high"},
                {"field": "nlp.intent", "operator": "equals", "value": "security_threat"}
            ]
        },
        "actions": [
            {
                "type": "notification",
                "params": {
                    "title": "[SECURITY] Threat Isolated: {{ payload.ip }}",
                    "message": "Automated security quarantine active for host {{ payload.ip }}.",
                    "severity": "critical"
                }
            },
            {
                "type": "log_entry",
                "params": {
                    "level": "CRITICAL",
                    "message": "Threat quarantined for IP {{ payload.ip }}."
                }
            }
        ],
        "steps": [
            {"type": "trigger", "name": "Event: security.audit_alert", "config": {"event_name": "security.audit_alert"}},
            {"type": "ai_extract_entities", "name": "Extract Threat Entities", "config": {"fields": ["ipv4", "hostnames"]}},
            {"type": "ai_analysis", "name": "Assess Threat Severity", "config": {}},
            {"type": "notification", "name": "Trigger Firewall Isolation Alert", "config": {"severity": "critical", "title": "IP Quarantined"}},
            {"type": "log_entry", "name": "Record Forensic Audit Entry", "config": {"level": "CRITICAL"}},
            {"type": "end", "name": "Quarantine Complete", "config": {}}
        ]
    },
    # 12. Scheduled Operations Health & Performance Digest
    {
        "id": "template-scheduled-ops-digest",
        "name": "Scheduled Operations Health & Performance Digest",
        "description": "Periodically synthesizes system health metrics, computes operational trend summaries, and publishes scheduled executive briefings.",
        "category": "System",
        "priority": 70,
        "cooldown_seconds": 30,
        "trigger": {
            "type": "schedule",
            "event_name": "schedule.digest",
            "interval_minutes": 60
        },
        "condition": {
            "logic": "AND",
            "conditions": [
                {"field": "system.cpu_percent", "operator": ">=", "value": 0}
            ]
        },
        "actions": [
            {
                "type": "notification",
                "params": {
                    "title": "Scheduled Operations Digest",
                    "message": "System operational briefing compiled successfully.",
                    "severity": "info"
                }
            }
        ],
        "steps": [
            {"type": "trigger", "name": "Schedule: Operations Digest", "config": {"event_name": "schedule.digest", "interval_minutes": 60}},
            {"type": "ai_summarize", "name": "Synthesize Health Trends", "config": {"source_field": "payload.metrics_summary"}},
            {"type": "ai_generate", "name": "Generate Executive Briefing", "config": {"prompt_template": "Generate executive briefing for system health."}},
            {"type": "notification", "name": "Publish Operations Digest", "config": {"title": "Operations Digest Published", "severity": "info"}},
            {"type": "end", "name": "Digest Dispatched", "config": {}}
        ]
    }
]

