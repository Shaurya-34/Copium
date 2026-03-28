# CloudCFO — Project Status

> **Last updated:** 2026-03-28 01:10 IST

---

## 📋 Project Description

**CloudCFO** is an AWS cost-optimization automation platform that detects cost anomalies, identifies idle resources, and delivers actionable alerts via Slack — complete with interactive "Fix" buttons for one-click remediation.

### Core Goals
- **Detect** cost spikes and anomalies across AWS accounts in real time
- **Identify** idle/underutilized resources (EC2, EBS, etc.)
- **Alert** teams via Slack with rich Block Kit messages
- **Remediate** with one-click "Fix" buttons that trigger safe, audited actions
- **Report** daily cost summaries with forecasts and savings opportunities

### Tech Stack
| Layer | Technology |
|---|---|
| Language | Python 3.12+ |
| Config | pydantic-settings + `.env` |
| Messaging | Slack Block Kit via Incoming Webhooks |
| Cloud | AWS (boto3) — EC2, S3, CloudFront, EBS, Lambda, RDS |
| API (future) | FastAPI + Uvicorn |
| Testing | pytest |

---

## 📁 Project Structure

```
cloudcfo/
├── .env                       # Your Slack secrets (gitignored)
├── .env.example               # Template showing what secrets are needed
├── .gitignore                 # Python + Node + secrets exclusions
├── requirements.txt           # All dependencies (phased)
├── STATUS.md                  # This file — project roadmap & progress
├── config/
│   ├── __init__.py
│   └── settings.py            # pydantic-settings config loader
└── automation/
    ├── __init__.py
    ├── anomaly/
    │   ├── __init__.py
    │   ├── detector.py        # Phase 3 — Cost Explorer anomaly detection
    │   └── runner.py          # Phase 3 — daily scan orchestration
    ├── cicd/
    │   └── __init__.py
    ├── remediation/
    │   ├── __init__.py
    │   └── remediator.py      # Phase 2 — boto3 remediation engine + audit log
    └── slack/
        ├── __init__.py
        ├── models.py          # Data models (CostAnomaly, IdleResource, etc.)
        ├── webhook.py         # Slack webhook client with retry logic
        ├── message_builder.py # Block Kit message builder
        └── alert_service.py   # High-level alert orchestrator
```

---

## 🏗️ Phases & Roadmap

### ✅ Phase 1 — Slack Integration (COMPLETE)

**Goal:** Build the notification pipeline so CloudCFO can send rich alerts to Slack.

#### What was built:

**Data Models** (`models.py`)
- [x] `CostAnomaly` — represents a cost spike (service, cost, expected cost, region, severity auto-calculated)
- [x] `IdleResource` — represents a wasted resource (CPU %, idle hours, monthly waste computed automatically)
- [x] `RemediationAction` — represents a fix action (stop, delete, rightsize with estimated savings)
- [x] `AlertPayload` — combines anomalies + idle resources + actions into one alert
- [x] `AlertSeverity` — enum: INFO, WARNING, CRITICAL (auto-assigned based on cost increase %)

**Slack Webhook Client** (`webhook.py`)
- [x] URL validation — ensures webhook URL starts with `https://hooks.slack.com/`
- [x] HTTP POST with `requests.Session` for connection pooling
- [x] Automatic retry — retries up to 3 times on transient failures
- [x] Rate-limit handling — respects Slack's `429 Retry-After` header
- [x] `test()` method for quick connectivity checks

**Message Builder** (`message_builder.py`)
- [x] `build_alert()` — full composite alert with anomalies, idle resources, actions, and savings
- [x] `build_simple_alert()` — single-issue alert with severity color-coding
- [x] `build_daily_summary()` — end-of-day cost report with top services breakdown
- [x] Block Kit formatting with emoji indicators, dividers, and markdown sections

**Alert Service** (`alert_service.py`)
- [x] `AlertService` class — high-level facade that ties models + builder + webhook together
- [x] `send_anomaly_alert()` — one-call anomaly notification
- [x] `send_idle_resource_alert()` — one-call idle resource digest
- [x] `send_daily_summary()` — one-call daily cost report
- [x] Error handling — catches webhook errors and returns `False` instead of crashing

**Configuration** (`settings.py`)
- [x] `SlackSettings` class using `pydantic-settings` — loads from `.env` file
- [x] Fields: `webhook_url`, `channel`, `bot_name`, `bot_emoji`, `timeout_seconds`, `max_retries`
- [x] Validates on startup — missing webhook URL gives a clear error

**Infrastructure & DevOps**
- [x] `.env.example` — template with all required/optional env vars
- [x] `.gitignore` — covers `.env`, `.venv`, `__pycache__`, `node_modules`, IDE files
- [x] `requirements.txt` — pinned dependencies (requests, pydantic, pydantic-settings, pytest, boto3)
- [x] Python virtualenv created (`.venv/`)
- [x] Git repo initialized and pushed to GitHub: [Shaurya-34/Copium](https://github.com/Shaurya-34/Copium)

**End-to-End Verification**
- [x] Created Slack workspace "Cloudcfo" with `#new-channel`
- [x] Created Slack app "webhooks" with Incoming Webhook
- [x] Sent 5 live alerts to Slack and verified delivery:
  - ✅ Webhook connection test
  - 🚨 Cost Anomaly alert (EC2 +290% spike)
  - ⚠️ Idle Resources digest (3 resources, ~$210/mo waste)
  - 📊 Daily Cost Summary ($1,247.83 spend)
  - 🚨 Full composite alert (anomalies + idle + actions + savings)
- [x] All alerts rendered correctly with Block Kit formatting

#### What was removed after verification:
- Removed `demo_slack.py` (demo script — no longer needed)
- Removed `automation/tests/` (unit tests — 19 tests were passing before removal)

---

### ✅ Phase 2 — Remediation Scripts (COMPLETE)
- [x] boto3 remediation engine scaffolded in `automation/remediation/remediator.py`
- [x] EC2 stop action with dry-run support and estimated daily savings logging
- [x] EBS delete action with unattached-volume safety checks and audit logging
- [x] EC2 rightsizing action with monthly savings estimation and safe stop/modify/start flow
- [x] Local JSON audit log for every remediation attempt
- [x] `ConfirmationGate` — operator approval layer (propose → approve → execute workflow)
- [x] `start_ec2()` — start previously stopped instances
- [x] `snapshot_and_delete_ebs()` — safe delete with backup snapshot first
- [x] `list_actions()` — returns all supported action types
- [x] `PendingAction` dataclass for tracking action lifecycle (pending → approved/rejected → executed)

### ✅ Phase 3 — Cost Anomaly Detection (COMPLETE)
- [x] AWS Cost Explorer detector scaffolded in `automation/anomaly/detector.py`
- [x] Service-level daily anomaly scoring using baseline-average comparisons
- [x] Daily scan runner added in `automation/anomaly/runner.py`
- [x] Configurable anomaly thresholds added to `config/settings.py`
- [x] Scheduled daily scans (Lambda handler `lambda_handler.py` and demo script implemented)
- [x] Robust error handling for `DataUnavailableException` on new AWS accounts
- [ ] Multi-account / linked-account anomaly coverage (Deferred pending Organization setup)

### ✅ Phase 4 — Webhook Listener (COMPLETE)
- [x] FastAPI endpoint built (`automation/api/main.py`) to receive Slack interactions
- [x] Slack App Signature verification using `slack_sdk.signature`
- [x] Action parser bridging Slack clicks directly to `boto3` engine actions
- [x] Background threaded AWS remediation for instantaneous Slack response
- [x] Final outcome thread reply mapping successful/failed Boto3 responses back to Slack

### 🔲 Phase 5 — Dashboard & Reporting
- [ ] Daily/weekly cost trend summaries
- [ ] Savings tracking over time
- [ ] Multi-account support

---

## 📝 Action Log

| Date | Action | Details |
|---|---|---|
| 2026-03-27 | **Project init** | Created `requirements.txt`, `.gitignore`, `.env.example`, `config/settings.py` |
| 2026-03-27 | **Data models** | Built `models.py` with 5 Pydantic models: `CostAnomaly`, `IdleResource`, `RemediationAction`, `AlertPayload`, `AlertSeverity` |
| 2026-03-27 | **Webhook client** | Built `webhook.py` with retry logic, rate-limit handling, and URL validation |
| 2026-03-27 | **Message builder** | Built `message_builder.py` with 3 Block Kit message types |
| 2026-03-27 | **Alert service** | Built `alert_service.py` facade combining models + builder + webhook |
| 2026-03-27 | **Demo & tests** | Created `demo_slack.py` (5 demo modes) and `test_slack.py` (19 unit tests, all passing) |
| 2026-03-27 | **Venv + Git** | Created `.venv`, initialized git, connected to GitHub remote |
| 2026-03-27 | **First push** | Force-pushed Phase 1 to `main` branch on GitHub |
| 2026-03-27 | **Slack workspace** | Created "Cloudcfo" Slack workspace, `#new-channel`, and "webhooks" app |
| 2026-03-27 | **Live E2E test** | Sent 5 alerts to Slack — all delivered and formatted correctly |
| 2026-03-27 | **Cleanup** | Removed demo script and test files, pushed cleanup commit to GitHub |
| 2026-03-28 | **Phase 2 scaffold** | Added `RemediationEngine` with EC2 stop, EBS delete, EC2 rightsize, dry-run handling, and JSON audit logging |
| 2026-03-28 | **Phase 3 scaffold** | Added Cost Explorer anomaly detector, threshold settings, and daily scan runner for Slack alerts |
| 2026-03-28 | **Phase 2 complete** | Added `ConfirmationGate`, `start_ec2()`, `snapshot_and_delete_ebs()`, `list_actions()`, `PendingAction` lifecycle tracking |
| 2026-03-28 | **Phase 4 complete** | Built FastAPI server, hooked up Slack signature verification, mapped buttons to boto3 background execution, pushed final results back to Slack. |

---

## 🚀 Quick Start

```bash
# 1. Clone & enter
git clone https://github.com/Shaurya-34/Copium.git
cd Copium

# 2. Create venv & install deps
python -m venv .venv
.venv\Scripts\activate      # Windows
pip install -r requirements.txt

# 3. Configure
copy .env.example .env
# Edit .env → paste your Slack webhook URL

# 4. Use in Python
from automation.slack.alert_service import AlertService
service = AlertService()
service.send_daily_summary(total_cost=1247.83, top_services=[("EC2", 487.50)])
```

---

## 🔑 Key Design Decisions

1. **pydantic-settings** for config — type-safe, `.env`-aware, validates on startup
2. **Computed properties** on models (e.g. `cost_increase_pct`, `severity`) — no raw data duplication
3. **Retry + rate-limit handling** in webhook client — production-ready from day one
4. **Block Kit attachments** (not just `text`) — enables colours, buttons, rich formatting
5. **AlertService facade** — insulates callers from webhook/builder internals
6. **ConfirmationGate pattern** — enforces propose → approve → execute workflow so no live AWS action runs without explicit operator consent
7. **Snapshot-before-delete** — `snapshot_and_delete_ebs` creates a backup before destroying volumes, making EBS cleanup reversible
