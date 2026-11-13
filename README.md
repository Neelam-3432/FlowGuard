# FlowGuard

> **A Configurable Workflow Decision Platform**

FlowGuard is a modular and extensible decision platform designed to execute configurable business workflows, rule evaluations, and decision pipelines without hardcoded logic.

---

## 🛠 Tech Stack

- **Language:** Python 3.12 (Python 3.10+ supported)
- **Web Framework:** [FastAPI](https://fastapi.tiangolo.com/)
- **ASGI Server:** [Uvicorn](https://www.uvicorn.org/)
- **Database ORM:** [SQLAlchemy](https://www.sqlalchemy.org/) 2.0+
- **Database Engine:** SQLite (embedded, foreign keys enforced)
- **Data Validation & Settings:** [Pydantic](https://docs.pydantic.dev/) v2 & [Pydantic-Settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)
- **Testing:** [Pytest](https://docs.pytest.org/) & [HTTPX](https://www.python-httpx.org/)

---

## 📁 Project Structure

```text
FlowGuard/
├── app/
│   ├── __init__.py                     # Application package definition
│   ├── main.py                         # FastAPI application factory & route registration
│   ├── api/                            # API routing layer
│   │   ├── __init__.py
│   │   └── v1/
│   │       ├── __init__.py
│   │       ├── router.py               # v1 API router aggregator
│   │       └── endpoints/              # Route handlers
│   │           ├── __init__.py
│   │           └── health.py           # Health check endpoint (GET /health)
│   ├── core/                           # Core system configurations
│   │   ├── __init__.py
│   │   ├── config.py                   # App settings (Pydantic BaseSettings)
│   │   └── database.py                 # SQLite connection, FK PRAGMA, session factory
│   ├── models/                         # SQLAlchemy 2.0 ORM models (Phase 1)
│   │   ├── __init__.py
│   │   ├── application.py              # Application decision entity
│   │   ├── audit_log.py                # State transition & decision audit trail
│   │   └── workflow_config.py          # Versioned immutable workflow configuration
│   ├── rules/                          # Standalone Rules Engine (Phase 2)
│   │   ├── __init__.py                 # Rules engine public API exports
│   │   ├── decision.py                 # DecisionResult & RuleEvaluationResult schemas
│   │   ├── evaluator.py                # Deterministic RulesEvaluator & trace generator
│   │   ├── exceptions.py               # RulesEngineError hierarchy
│   │   ├── operators.py                # Safe whitelisted operator registry & functions
│   │   └── schemas.py                  # Pydantic schemas for Mandatory, Threshold, Conditional, Group rules
│   ├── schemas/                        # System-wide Pydantic schemas
│   │   ├── __init__.py
│   │   └── health.py                   # Health check payload schema
│   └── services/                       # Service layer & atomic transaction support (Phase 1)
│       ├── __init__.py
│       ├── application_service.py      # Atomic application & audit updates
│       └── workflow_config_service.py  # Configuration versioning and immutability
├── tests/                              # Automated test suite
│   ├── __init__.py
│   ├── conftest.py                     # Pytest fixtures (TestClient, isolated DB sessions)
│   ├── test_database.py                # Database initialization & FK PRAGMA tests
│   ├── test_decision_traces.py         # Decision trace structure, metadata, & privacy tests
│   ├── test_health.py                  # Health and documentation tests (Phase 0)
│   ├── test_models.py                  # Model insertion, relationships, FKs, constraints
│   ├── test_operators.py               # Safe operator whitelist & operand type tests
│   ├── test_rule_evaluator.py          # Comprehensive rules evaluation engine tests
│   ├── test_rule_schemas.py            # Pydantic schema validation & bounds tests
│   └── test_transactions.py            # Atomic transaction & rollback tests
├── .gitignore                          # Git ignore file for Python, SQLite, caches
├── README.md                           # Project documentation
├── requirements.txt                    # Production and development dependencies
└── run.py                              # Clean application entry point script
```

---

## ⚡ Rules Engine (Phase 2)

FlowGuard includes a standalone, deterministic, and secure rules engine that evaluates incoming application payloads against versioned workflow configurations without external code execution.

### Supported Rule Categories:

1. **Mandatory Field Rules (`mandatory`):** Verifies required fields exist, are not null, and (optionally) non-empty strings.
2. **Threshold Rules (`threshold`):** Performs numeric comparisons (`gt`, `gte`, `lt`, `lte`, `eq`, `ne`) against configured numeric boundaries.
3. **Conditional Rules (`conditional`):** Evaluates logical implications (`when` antecedent $\to$ `then` assertion). If the precondition is not met, the rule passes vacuously.
4. **Group Rules (`group`):** Evaluates composite conditions using `AND` and `OR` combinators with bounded recursion depth (max depth $\le 3$).

### Safe Operator Whitelist:

No `eval()` or `exec()` is ever used. Only predefined, registered operators are allowed:
- `eq`: Strict equality (with boolean/integer strictness guard).
- `ne`: Strict inequality.
- `gt`, `gte`: Numeric greater than / greater than or equal.
- `lt`, `lte`: Numeric less than / less than or equal.
- `in`, `not_in`: Collection membership validation.
- `exists`, `not_exists`: Field presence and non-null/non-empty checking.

### Decision Aggregation & Traces:

- **All-or-Nothing Rule Precedence:** If any mandatory rule fails, or if any configured rule fails, the overall status is `"rejected"` (`passed=False`). Only when all configured rules pass is the status `"approved"` (`passed=True`).
- **Privacy Preservation:** Traces record rule identifiers, fields inspected, operators, expected thresholds, and human-readable reasons without dumping raw sensitive payload secrets.

---

## 🗄 Database Models & Relationships (Phase 1)

### 1. `WorkflowConfig` (`workflow_configs`)
- **Fields:** `id` (PK), `workflow_id` (Indexed), `version`, `config_data` (JSON), `is_active`, `created_at`.
- **Constraints:** Unique `(workflow_id, version)`.
- **Immutability:** Historical versions are immutable. An event listener and service logic prevent modifying `config_data`, `version`, or `workflow_id` on existing persisted records.
- **Relationship:** One configuration version can be referenced by multiple applications (`workflow_config.applications`).

### 2. `Application` (`applications`)
- **Fields:** `id` (PK), `request_id` (Indexed), `workflow_id` (Indexed), `workflow_config_id` (FK to `workflow_configs.id`, `ondelete="RESTRICT"`), `idempotency_key` (Indexed), `payload_hash`, `input_data` (JSON), `status` (Indexed), `retry_count`, `created_at`, `updated_at`.
- **Constraints:** Unique `(workflow_id, idempotency_key)`.
- **Relationships:**
  - Belongs to `WorkflowConfig` (`application.workflow_config`).
  - Has many `AuditLog` records (`application.audit_logs`, cascade delete).

### 3. `AuditLog` (`audit_logs`)
- **Fields:** `id` (PK), `application_id` (FK to `applications.id`, `ondelete="CASCADE"`), `event_type` (Indexed), `previous_state`, `new_state`, `details` (JSON), `created_at` (Indexed).
- **Relationship:** Belongs to `Application` (`audit_log.application`).

---

## 🚀 Quick Start & Setup Instructions

### 1. Prerequisites

- Python 3.10+ (Python 3.12 recommended) installed on your system.

### 2. Clone the Repository

```bash
git clone <repository-url>
cd FlowGuard
```

### 3. Create and Activate a Virtual Environment

**On Windows (PowerShell):**
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

**On Linux / macOS:**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 4. Install Dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

---

## 🏃 Running the Application

```bash
python run.py
```

Server URL: `http://127.0.0.1:8000`  
Interactive Docs: `http://127.0.0.1:8000/docs`

---

## 🧪 Running Tests

To run the complete automated test suite (56 tests across Phase 0, Phase 1, and Phase 2):

```bash
pytest -v
```

---

## 📌 Phase Roadmap

- [x] **Phase 0:** Project scaffolding, modular architecture, dependencies, minimal FastAPI setup, `/health`, `/docs`, `.gitignore`, and entry point.
- [x] **Phase 1:** Database setup, SQLite foreign key constraints, SQLAlchemy 2.0 models (`Application`, `AuditLog`, `WorkflowConfig`), relationships, immutability, atomic transactions, and test suite.
- [x] **Phase 2:** Standalone, deterministic, secure Rules Engine, whitelisted operator registry, mandatory/threshold/conditional/group rules, decision traces, and 36 new tests (56 total).
- [ ] **Phase 3:** Workflow execution lifecycle, audit logging, and state management.
- [ ] **Phase 4:** Advanced operators, validation, and simulated decision testing.
