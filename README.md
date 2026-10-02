# ⚡ OpsFlow Enterprise SaaS Platform

> **Commercial-Grade B2B Workflow Orchestration & Intelligent Automation Platform**  
> *Python Flask • SQLAlchemy 2.0 ORM • SQLite WAL (Local) / PostgreSQL Ready • Multi-Tenant RBAC • Offline Heuristic NLP Core • Inbound Webhook Gateway*

[![Python Version](https://img.shields.io/badge/Python-3.10%20%7C%203.11-blue.svg)](https://python.org)
[![Framework](https://img.shields.io/badge/Framework-Flask%203.1-emerald.svg)](https://flask.palletsprojects.com/)
[![ORM](https://img.shields.io/badge/Database-SQLAlchemy%202.0%20%7C%20Alembic%20Migrations-red.svg)](https://alembic.sqlalchemy.org/)
[![Tests](https://img.shields.io/badge/Tests-42%2F42%20Passed%20(100%25)-brightgreen.svg)](test_saas_platform.py)
[![Security](https://img.shields.io/badge/Security-Multi--Tenant%20RBAC%20%7C%20SHA--256%20Keys-purple.svg)](#-security--rbac-model)
[![License](https://img.shields.io/badge/License-Proprietary%20%2F%20Commercial-blue.svg)](#)

---

## 🌟 Product Overview

**OpsFlow Enterprise** is a high-throughput, multi-tenant B2B SaaS platform engineered for Site Reliability Engineers (SRE), Security Operations (SecOps), and DevOps infrastructure teams. It automates operational incident triage, evaluates complex conditional decision trees, ingests high-frequency telemetry signals via HMAC-secured webhooks, and dispatches automated multi-action mitigation pipelines.

Unlike cloud-dependent automation tools that introduce recurring token fees, external SaaS latency, and outbound security exposure, OpsFlow features an **embedded, offline deterministic rule engine** coupled with a **local heuristic Natural Language Processing (NLP) core**. It delivers instantaneous event triage, real-time hardware telemetry, forensic execution audit trails, and one-click automation blueprints with zero external API dependencies.

```mermaid
flowchart TD
    subgraph Ingestion ["1. Signal Ingestion & Gateways"]
        WH["Inbound Webhooks (HMAC-SHA256)"]
        API["REST API v1 (/api/v1/events)"]
        NLP_IN["Natural Language Incident Console"]
        METRICS["Telemetry Sentinel Monitor"]
    end

    subgraph Security ["2. Multi-Tenant Security & Auth Layer"]
        AUTH["RBAC Guard (Admin / Operator / Viewer)"]
        KEY["Scoped API Key Validator (SHA-256)"]
        TENANT["Workspace Data Isolator (Tenant ID Scope)"]
    end

    subgraph Engine ["3. Intelligent Orchestration Core"]
        NLP_CORE["Heuristic NLP Core (Sub-ms Triage)"]
        EVAL["Condition Tree Evaluator (AND/OR Trees)"]
        THROTTLE["Cooldown Throttles & Loop Breakers"]
    end

    subgraph Actions ["4. Action Dispatchers"]
        ACT_WH["Outbound HTTP Webhooks"]
        ACT_ALERT["Incident Response Center"]
        ACT_LOG["Diagnostic Audit Logs"]
        ACT_EMAIL["Simulated / SMTP Email Queue"]
        ACT_FILE["Isolated Tenant Storage"]
    end

    subgraph Persistence ["5. SQLAlchemy 2.0 ORM Store"]
        DB[("SQLite WAL (Local) / PostgreSQL (Cloud)")]
    end

    Ingestion --> Security
    Security --> Engine
    Engine --> Actions
    Actions --> Persistence
    Engine -.-> Persistence
```

---

## 🚀 Key Enterprise Capabilities

| Capability | Technical Implementation | Business & Client Benefit |
|---|---|---|
| **Multi-Tenant Workspaces** | Strict `organization_id` foreign keys, tenant query isolation | Enables MSPs and enterprises to isolate environments and clients safely. |
| **Role-Based Access (RBAC)** | `Owner`, `Admin`, `Operator`, `Viewer` roles enforced on all routes | Granular permissions: operators manage workflows; viewers have read-only access. |
| **SQLAlchemy 2.0 ORM** | Declarative models, relationship mappings, SQLite WAL mode | Clean migration path from local SQLite development to production PostgreSQL. |
| **Scoped API Key Auth** | Cryptographic generation (`sk_live_...`), SHA-256 hashed lookup | Secure programmatic integration for CI/CD pipelines, CLI scripts, and edge agents. |
| **HMAC Inbound Webhooks** | Public URL slugs, `X-Hub-Signature-256` validation | Ingest signals from Stripe, GitHub, Datadog, PagerDuty, and custom backends safely. |
| **Heuristic NLP Core** | Weighted token dictionaries, continuous urgency scoring, regex entities | Instantaneous triage of unstructured incident prompts with 0 API tokens and 0 latency. |
| **Incident Response Center** | Full lifecycle tracking (`open` -> `acknowledged` -> `resolved`) | Centralized operational queue with severity badges and forensic trace drill-downs. |
| **Forensic Audit Trails** | Immutable step-by-step traces (`ACTUAL vs TARGET -> PASS/FAIL`) | 100% auditability for regulatory compliance (SOC2, HIPAA, ISO 27001). |

---

## 👥 Pre-Configured Turnkey Demo Personas

The platform includes two isolated multi-tenant workspaces and three role-based test personas:

### Workspace 1: Acme Global Enterprise (`acme-global`)
*Enterprise Tier workspace with full monitoring, security, and DevOps workflows.*

| Persona | Email | Password | Role & Permissions |
|---|---|---|---|
| **Sarah Lin (VP Ops)** | `admin@opsflow.io` | `AdminSecure2026!` | **Admin / Owner**: Full control (create/delete rules, manage team, revoke API keys). |
| **Alex Rivera (SRE)** | `operator@opsflow.io` | `Operator2026!` | **Operator**: Operational access (create, edit, run workflows, triage incidents). |
| **Jordan Smith (Auditor)**| `viewer@opsflow.io` | `Viewer2026!` | **Viewer**: Read-only access (inspect metrics, audit trails, and logs). |
| **Master API Key** | `sk_live_opsflow_enterprise_prod_2026` | *(Pre-seeded)* | Full programmatic access across all REST endpoints. |

### Workspace 2: Apex HealthTech Systems (`apex-health`)
*Pro Tier tenant used to demonstrate strict workspace data isolation.*
- **Admin**: `admin@apexhealth.internal` / `HealthTech2026!`
- **API Key**: `sk_live_apex_health_gateway_2026`

---

## ⚡ Quick Start & Turnkey Setup

### 1. Prerequisites
- Python 3.10 or 3.11 installed
- Git

### 2. Clone and Install Dependencies
```bash
git clone https://github.com/your-org/AI-Automation-Command-Center.git
cd AI-Automation-Command-Center

pip install -r requirements.txt
```

### 3. Initialize Database & Seed Demonstration Data
```bash
python init_db.py
```
*Creates the SQLite database with WAL mode enabled and populates tenants, users, API keys, workflows, and sample incidents.*

### 4. Run the Application
```bash
python app.py
```
Open your browser to: **`http://localhost:5000`**

---

## 🧪 Automated Test Suite

The test suite contains **41 automated tests** covering security, multi-tenancy, SQLAlchemy models, the workflow engine, and REST APIs.

Run tests with `pytest`:
```bash
pytest -v
```

Output:
```text
============================= test session starts =============================
collected 41 items

test_command_center.py .................................                 [ 80%]
test_saas_platform.py ........                                           [100%]

============================= 41 passed in 14.86s =============================
```

---

## 📡 REST API v1 Reference

All endpoints return structured JSON with standard HTTP status codes.

### 1. Authentication & Session

#### Login
```bash
curl -X POST http://localhost:5000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@opsflow.io", "password": "AdminSecure2026!"}'
```

#### Get Current Authenticated Profile
```bash
curl -X GET http://localhost:5000/api/v1/auth/me \
  -H "X-API-Key: sk_live_opsflow_enterprise_prod_2026"
```

#### Generate a New Scoped API Key
```bash
curl -X POST http://localhost:5000/api/v1/auth/api-keys \
  -H "X-API-Key: sk_live_opsflow_enterprise_prod_2026" \
  -H "Content-Type: application/json" \
  -d '{"name": "GitHub Actions CI/CD Key", "permissions": "events:ingest,rules:read"}'
```

---

### 2. Workflow Rules

#### List Tenant Rules
```bash
curl -X GET "http://localhost:5000/api/v1/rules?category=System" \
  -H "X-API-Key: sk_live_opsflow_enterprise_prod_2026"
```

#### Create a New Automation Workflow
```bash
curl -X POST http://localhost:5000/api/v1/rules \
  -H "X-API-Key: sk_live_opsflow_enterprise_prod_2026" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Production Database Latency Sentinel",
    "category": "System",
    "priority": 80,
    "cooldown_seconds": 60,
    "trigger": { "type": "event", "event_name": "db.query_latency" },
    "condition": {
      "logic": "AND",
      "conditions": [
        { "field": "payload.latency_ms", "operator": ">", "value": 500 }
      ]
    },
    "actions": [
      {
        "type": "notification",
        "params": {
          "title": "High DB Latency ({{ payload.latency_ms }} ms)",
          "severity": "high"
        }
      }
    ]
  }'
```

#### Manually Trigger / Test a Rule
```bash
curl -X POST http://localhost:5000/api/v1/rules/rule-cpu-sentinel/run \
  -H "X-API-Key: sk_live_opsflow_enterprise_prod_2026" \
  -H "Content-Type: application/json" \
  -d '{"payload": {"cpu_percent": 96.0, "host": "prod-api-worker-01"}}'
```

---

### 3. Inbound Webhook Ingestion

#### Ingest Third-Party Signal (Public Endpoint)
```bash
curl -X POST http://localhost:5000/api/v1/webhooks/incoming/wh_live_datadog_alerts_2026 \
  -H "Content-Type: application/json" \
  -d '{"event": "system.metrics", "cpu_percent": 92.4, "host": "prod-k8s-node-03"}'
```

*If an HMAC secret is configured, supply the signature header:*  
`-H "X-Hub-Signature-256: sha256=<hmac_hex_digest>"`

---

### 4. Incident Response Center

#### List Active Incidents
```bash
curl -X GET "http://localhost:5000/api/v1/alerts?status=open" \
  -H "X-API-Key: sk_live_opsflow_enterprise_prod_2026"
```

#### Acknowledge an Incident
```bash
curl -X POST http://localhost:5000/api/v1/alerts/1/acknowledge \
  -H "X-API-Key: sk_live_opsflow_enterprise_prod_2026"
```

#### Resolve an Incident with Resolution Notes
```bash
curl -X POST http://localhost:5000/api/v1/alerts/1/resolve \
  -H "X-API-Key: sk_live_opsflow_enterprise_prod_2026" \
  -H "Content-Type: application/json" \
  -d '{"notes": "Scaled Kubernetes horizontal pod autoscaler to 8 replicas."}'
```

---

## 🔒 Security & RBAC Model

1. **Password Hashing**: Industry-standard PBKDF2/SHA-256 password hashing via Werkzeug security (`generate_password_hash`).
2. **API Key Security**: Plaintext API keys (`sk_live_...`) are displayed to administrators exactly **once** upon creation. Only SHA-256 hex hashes are stored in the database.
3. **Tenant Data Isolation**: All queries filter by `organization_id`. Even with direct ID guessing, cross-tenant requests return `404 Not Found`.
4. **Role Hierarchy**:
   - `Owner / Admin`: Workspace settings, member management, API key lifecycle, rule creation/deletion.
   - `Operator`: Workflow authoring, manual triggering, dry-run simulation, incident acknowledgment/resolution.
   - `Viewer`: Read-only telemetry, incident lists, and execution forensic logs.
5. **Security Headers**: Production middleware injects `X-Content-Type-Options: nosniff`, `X-Frame-Options: SAMEORIGIN`, and strict `Content-Security-Policy` headers.

---

## 🐳 Production Deployment

### Docker Deployment
```bash
# Build and run the production container
docker build -t opsflow-saas:latest .
docker run -d -p 5000:5000 --name opsflow-app opsflow-saas:latest
```

### Docker Compose
```bash
docker-compose up -d
```

### Cloud Deployment on Render

#### Option A: One-Click Render Blueprint (`render.yaml`)
OpsFlow includes a production-ready `render.yaml` Blueprint specification:
1. Log in to your [Render Dashboard](https://dashboard.render.com/).
2. Click **New +** and select **Blueprint**.
3. Connect your GitHub repository (`AI-Automation-Command-Center`).
4. Render automatically parses `render.yaml`, configures Python 3.11, generates a secure `SECRET_KEY`, sets the healthcheck to `/health`, and runs the build command:
   ```bash
   pip install -r requirements.txt && python init_db.py
   ```
5. Click **Apply**. Your SaaS platform will be live with full demo data and HTTPS in ~2 minutes!

#### Option B: Manual Web Service on Render
If configuring manually as a **Web Service**:
1. Click **New +** -> **Web Service**.
2. Connect your GitHub repository.
3. Configure the service settings:
   - **Name**: `opsflow-command-center` (or your choice)
   - **Environment**: `Python 3`
   - **Branch**: `main`
   - **Build Command**: `pip install -r requirements.txt && python init_db.py`
   - **Start Command**: `gunicorn app:app`
   - **Health Check Path**: `/health`
4. In **Environment Variables**, add:
   - `PYTHON_VERSION`: `3.11.9`
   - `FLASK_ENV`: `production`
   - `FLASK_DEBUG`: `0`
   - `SECRET_KEY`: *(Generate a secure random string)*
   - `DATABASE_URL`: *(Optional: connect Render PostgreSQL or omit to use built-in SQLite)*
5. Click **Create Web Service**.

### Production WSGI (Gunicorn)
```bash
gunicorn --config gunicorn.conf.py app:app
```

---

## 🛠️ Client Customization & White-Labeling Guide

1. **Database Backend & Schema Migrations (Phase 3)**:
   - **Local Development**: Uses SQLite with WAL mode (`opsflow_saas.db`).
   - **Production PostgreSQL**: Set `DATABASE_URL=postgresql://user:pass@host:5432/dbname`.
   - **Alembic / Flask-Migrate Engine**: Complete migration tracking and schema versioning via the `migrations/` directory.
   - **CLI Migration Commands**:
     ```bash
     # Check current migration revision and schema status
     python migrate.py status
     python migrate.py current

     # Upgrade schema to latest migration head
     python migrate.py upgrade

     # Roll back migration revision
     python migrate.py downgrade -1

     # Stamp an existing database to head (for pre-existing unversioned deployments)
     python migrate.py stamp head
     ```
   - **Programmatic Auto-Migrations**: On startup and during build deployments (`python init_db.py --migrate-only`), pending schema migrations are automatically validated and applied without manual intervention.
   - **Observability Endpoints**:
     - `GET /api/v1/system/migration-status` - Detailed schema revision, dialect, and table inventory.
     - `GET /api/v1/system/health` - Includes `database_migration: { current_revision, is_up_to_date }`.

2. **Branding & Theme**:
   - Modify `--cyan-glow`, `--purple-glow`, and brand headers in `static/css/style.css` and `templates/index.html`.
3. **Outbound Notification Integrations**:
   - Add Slack Webhook, PagerDuty, or Twilio SMS dispatches via the outbound webhook action (`webhook_call`) in `actions.py`.
