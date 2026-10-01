"""Local Rule-Based & Heuristic NLP Engine.

Zero external APIs, zero costs, 100% offline.
Provides intent classification, urgency/sentiment scoring, entity extraction,
and token analysis using optimized heuristic pattern matching.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List


class NLPEngine:
    """Smart offline rule-based NLP engine."""

    INTENT_KEYWORDS: Dict[str, Dict[str, Any]] = {
        "server_alert": {
            "keywords": [
                "cpu", "memory", "ram", "disk", "crash", "spike", "down", "outage",
                "oom", "restart", "timeout", "slow", "overload", "unresponsive",
                "hung", "throttled", "utilization", "capacity", "load", "deadlock"
            ],
            "weight": 1.2
        },
        "security_threat": {
            "keywords": [
                "unauthorized", "intrusion", "brute", "brute-force", "ddos", "hack",
                "attack", "injection", "malware", "compromise", "firewall", "blocked",
                "banned", "suspicious", "forbidden", "exploit", "breach", "leak", "phishing"
            ],
            "weight": 1.4
        },
        "deploy_request": {
            "keywords": [
                "deploy", "deployment", "release", "rollout", "build", "pipeline",
                "staging", "production", "prod", "publish", "ci/cd", "merge", "artifact"
            ],
            "weight": 1.1
        },
        "backup_request": {
            "keywords": [
                "backup", "archive", "dump", "snapshot", "replicate", "replication",
                "tar", "zip", "restore", "cold-storage"
            ],
            "weight": 1.0
        },
        "incident_ticket": {
            "keywords": [
                "incident", "ticket", "issue", "bug", "broken", "glitch", "error",
                "failure", "sev-1", "sev-2", "p1", "p2", "urgent", "help", "escalate"
            ],
            "weight": 1.1
        },
        "status_inquiry": {
            "keywords": [
                "status", "health", "ping", "uptime", "report", "overview", "metrics",
                "telemetry", "check", "alive", "heartbeat", "stats"
            ],
            "weight": 1.0
        }
    }

    URGENCY_KEYWORDS = {
        "critical": 35,
        "emergency": 35,
        "fatal": 40,
        "outage": 30,
        "down": 25,
        "crash": 25,
        "oom": 30,
        "surge": 20,
        "spike": 15,
        "sev-1": 35,
        "p1": 30,
        "immediately": 25,
        "urgent": 25,
        "breach": 30,
        "compromised": 30,
        "panic": 25,
        "catastrophic": 40,
        "failed": 15,
        "error": 12,
        "warning": 8,
        "alert": 10,
        "degraded": 12,
        "slow": 5,
        "routine": -15,
        "info": -10,
        "success": -20,
        "normal": -20,
        "resolved": -25
    }

    SENTIMENT_LEXICON = {
        "positive": [
            "success", "resolved", "stable", "optimal", "healthy", "good", "great",
            "passed", "restored", "normal", "fine", "complete", "completed", "finished",
            "smoothly", "successful", "successfully"
        ],
        "negative": [
            "error", "failure", "failed", "crash", "corrupted", "down", "fatal",
            "broken", "critical", "breached", "unstable", "degraded", "threat",
            "denied", "lost", "compromised", "bad", "slow", "severe"
        ]
    }

    VALID_HTTP_STATUS_CODES = {
        # 1xx Informational
        "100", "101", "102", "103",
        # 2xx Success
        "200", "201", "202", "203", "204", "205", "206", "207", "208", "226",
        # 3xx Redirection
        "300", "301", "302", "303", "304", "305", "307", "308",
        # 4xx Client Error
        "400", "401", "402", "403", "404", "405", "406", "407", "408", "409",
        "410", "411", "412", "413", "414", "415", "416", "417", "418", "421",
        "422", "423", "424", "425", "426", "428", "429", "431", "451",
        # 5xx Server Error
        "500", "501", "502", "503", "504", "505", "506", "507", "508", "510", "511"
    }

    # Entity RegEx patterns
    REGEX_IPV4 = re.compile(r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b")
    REGEX_HOSTNAME = re.compile(r"\b([a-zA-Z0-9_\-]+(?:-db|-srv|-worker|-prod|-stg|-web|-api)[a-zA-Z0-9_\-]*|[a-zA-Z0-9_\-]+\.internal|\b[a-z]{2}-[a-z]+-\d+[a-z]?)\b", re.IGNORECASE)
    REGEX_HTTP_CODE = re.compile(r"(?<![\.\d])(?:HTTP(?:/[0-9.]+|[\s_-]+)?)?([1-5][0-9]{2})(?![\.\d])", re.IGNORECASE)
    REGEX_PERCENT = re.compile(r"\b(\d+(?:\.\d+)?)\s*%")
    REGEX_MEMORY_SIZE = re.compile(r"\b(\d+(?:\.\d+)?)\s*(?:KB|MB|GB|TB)\b", re.IGNORECASE)
    REGEX_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")

    def __init__(self):
        pass

    def parse(self, text: str) -> Dict[str, Any]:
        """Analyzes text and returns structured NLP insights."""
        if not text:
            return {
                "text": "",
                "intent": "general_query",
                "confidence": 0.0,
                "urgency": 0,
                "severity_level": "LOW",
                "sentiment": 0.0,
                "sentiment_label": "neutral",
                "entities": {},
                "tokens": [],
                "matched_keywords": []
            }

        text_clean = text.strip()
        lower_text = text_clean.lower()
        tokens = re.findall(r"\b[\w\-']+\b", lower_text)

        # 1. Intent Detection
        intent, confidence, matched_keywords = self._classify_intent(tokens, lower_text)

        # 2. Urgency Scoring (0 - 100)
        urgency, severity_level = self._compute_urgency(tokens, lower_text)

        # 3. Sentiment Polarity (-1.0 to 1.0)
        sentiment, sentiment_label = self._compute_sentiment(tokens)

        # 4. Entity Extraction
        entities = self._extract_entities(text_clean)

        return {
            "text": text_clean,
            "intent": intent,
            "confidence": round(confidence, 2),
            "urgency": urgency,
            "severity_level": severity_level,
            "sentiment": round(sentiment, 2),
            "sentiment_label": sentiment_label,
            "entities": entities,
            "tokens": tokens[:20],
            "matched_keywords": matched_keywords
        }

    def _classify_intent(self, tokens: List[str], text: str) -> tuple[str, float, List[str]]:
        scores: Dict[str, float] = {}
        matched_map: Dict[str, List[str]] = {}

        token_set = set(tokens)

        for intent, config in self.INTENT_KEYWORDS.items():
            score = 0.0
            matched = []
            for kw in config["keywords"]:
                if kw in token_set or kw in text:
                    score += config["weight"]
                    matched.append(kw)
            scores[intent] = score
            matched_map[intent] = matched

        best_intent = "general_query"
        max_score = 0.0

        for intent, score in scores.items():
            if score > max_score:
                max_score = score
                best_intent = intent

        if max_score == 0.0:
            confidence = 0.35
            return "general_query", confidence, []

        # Normalized confidence capped at 0.98
        confidence = min(0.98, max(0.45, 0.40 + (max_score * 0.15)))
        return best_intent, confidence, matched_map.get(best_intent, [])

    def _compute_urgency(self, tokens: List[str], text: str) -> tuple[int, str]:
        urgency = 20  # Base level

        for kw, boost in self.URGENCY_KEYWORDS.items():
            if kw in tokens or kw in text:
                urgency += boost

        # Additional regex heuristic: 90%+ CPU/Disk indicates higher urgency
        percentages = [float(p) for p in self.REGEX_PERCENT.findall(text)]
        if any(p >= 90 for p in percentages):
            urgency += 25
        elif any(p >= 75 for p in percentages):
            urgency += 15

        # Check for 5xx errors
        status_codes = self._extract_http_codes(text)
        if any(code.startswith("5") for code in status_codes):
            urgency += 20

        urgency = max(0, min(100, urgency))

        if urgency >= 75:
            severity = "CRITICAL"
        elif urgency >= 50:
            severity = "HIGH"
        elif urgency >= 25:
            severity = "MEDIUM"
        else:
            severity = "LOW"

        return urgency, severity

    def _compute_sentiment(self, tokens: List[str]) -> tuple[float, str]:
        pos_count = sum(1 for t in tokens if t in self.SENTIMENT_LEXICON["positive"])
        neg_count = sum(1 for t in tokens if t in self.SENTIMENT_LEXICON["negative"])

        total = pos_count + neg_count
        if total == 0:
            return 0.0, "neutral"

        polarity = (pos_count - neg_count) / total

        if polarity > 0.15:
            label = "positive"
        elif polarity < -0.15:
            label = "negative"
        else:
            label = "neutral"

        return polarity, label

    def _extract_ipv4(self, text: str) -> List[str]:
        """Extracts valid IPv4 addresses."""
        raw_matches = self.REGEX_IPV4.findall(text)
        valid_ips = []
        for ip in raw_matches:
            octets = ip.split(".")
            if len(octets) == 4 and all(o.isdigit() and 0 <= int(o) <= 255 for o in octets):
                valid_ips.append(ip)
        return list(dict.fromkeys(valid_ips))

    def _extract_http_codes(self, text: str) -> List[str]:
        """Extracts only valid 3-digit HTTP status codes, ignoring IP octets and other numbers."""
        # Mask out IPv4 occurrences so octets (e.g. 192, 168 in 192.168.1.50) are never extracted as HTTP codes
        text_without_ips = self.REGEX_IPV4.sub(" ", text)
        matches = self.REGEX_HTTP_CODE.findall(text_without_ips)
        valid_codes = [code for code in matches if code in self.VALID_HTTP_STATUS_CODES]
        return list(dict.fromkeys(valid_codes))

    def _extract_entities(self, text: str) -> Dict[str, List[Any]]:
        entities: Dict[str, List[Any]] = {
            "ipv4": self._extract_ipv4(text),
            "hostnames": list(set(self.REGEX_HOSTNAME.findall(text))),
            "http_status": self._extract_http_codes(text),
            "percentages": list(set(self.REGEX_PERCENT.findall(text))),
            "memory_sizes": list(set(self.REGEX_MEMORY_SIZE.findall(text))),
            "emails": list(set(self.REGEX_EMAIL.findall(text)))
        }

        # Filter out empty lists for compact output
        return {k: v for k, v in entities.items() if v}
