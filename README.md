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
│   ├── models/                         # SQLAlchemy 2.0 ORM models
│   │   ├── __init__.py
│   │   ├── application.py              # Application decision entity
│   │   ├── audit_log.py                # State transition & decision audit trail
│   │   └── workflow_config.py          # Versioned immutable workflow configuration
│   ├── schemas/                        # Pydantic validation schemas
│   │   ├── __init__.py
│   │   └── health.py                   # Health check payload schema
│   └── services/                       # Service layer & atomic transaction support
│       ├── __init__.py
│       ├── application_service.py      # Atomic application & audit updates
│       └── workflow_config_service.py  # Configuration versioning and immutability
├── tests/                              # Automated test suite (isolated temporary DB)
│   ├── __init__.py
│   ├── conftest.py                     # Pytest fixtures (TestClient, isolated DB sessions)
│   ├── test_database.py                # Database initialization & FK PRAGMA tests
│   ├── test_health.py                  # Health and documentation tests (Phase 0)
│   ├── test_models.py                  # Model insertion, relationships, FKs, constraints
│   └── test_transactions.py            # Atomic transaction & rollback tests
├── .gitignore                          # Git ignore file for Python, SQLite, caches
├── README.md                           # Project documentation
├── requirements.txt                    # Production and development dependencies
└── run.py                              # Clean application entry point script
```

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

## 🔒 Transaction Management

Atomic persistence guarantees are encapsulated in the service layer (`app/services/application_service.py`):
- Application status updates and corresponding audit log records are always persisted within a single atomic database transaction.
- If any operation fails (e.g. database error, validation failure, or simulated interruption), the entire transaction rolls back via `db.rollback()`.
- Helper methods avoid committing independently, ensuring strict all-or-nothing consistency.
- No external API or network calls are made within the database transaction boundary.

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

**On Windows (Command Prompt):**
```cmd
python -m venv .venv
.\.venv\Scripts\activate.bat
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

### Option A: Using the Application Entry Point (Recommended)

```bash
python run.py
```
This automatically initializes the database tables in `flowguard.db` and launches the Uvicorn ASGI server with live reloading enabled.

### Option B: Using Uvicorn Directly

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

The server will start at: `http://127.0.0.1:8000`

---

## 🔍 Verification Endpoints

| Endpoint | Method | Description | URL |
| :--- | :--- | :--- | :--- |
| **Health Check** | `GET` | Operational health and version metadata | [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health) |
| **API v1 Health** | `GET` | Health endpoint scoped under API v1 | [http://127.0.0.1:8000/api/v1/health](http://127.0.0.1:8000/api/v1/health) |
| **Interactive Docs (Swagger UI)** | `GET` | Interactive API documentation | [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs) |
| **ReDoc Documentation** | `GET` | Alternative API reference documentation | [http://127.0.0.1:8000/redoc](http://127.0.0.1:8000/redoc) |
| **OpenAPI Schema** | `GET` | Raw OpenAPI JSON specification | [http://127.0.0.1:8000/openapi.json](http://127.0.0.1:8000/openapi.json) |

---

## 🧪 Running Tests

To run the full automated test suite with pytest:

```bash
pytest -v
```

> **Note on Test Isolation:** Tests run against isolated, temporary SQLite databases in `tmp_path`. The development database (`flowguard.db`) is protected and never modified during test execution.

---

## 📌 Phase Roadmap

- [x] **Phase 0:** Project scaffolding, modular architecture, dependencies, minimal FastAPI setup, `/health`, `/docs`, `.gitignore`, and entry point.
- [x] **Phase 1:** Database setup, SQLite foreign key constraints, SQLAlchemy 2.0 models (`Application`, `AuditLog`, `WorkflowConfig`), relationships, immutability, atomic transactions, and comprehensive pytest suite.
- [ ] **Phase 2:** Workflow definition parser and dynamic rule evaluation engine.
- [ ] **Phase 3:** Workflow execution lifecycle, audit logging, and state management.
- [ ] **Phase 4:** Advanced operators, validation, and simulated decision testing.
