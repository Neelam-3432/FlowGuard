# FlowGuard

> **A Configurable Workflow Decision Platform**

FlowGuard is a modular and extensible decision platform designed to execute configurable business workflows, rule evaluations, and decision pipelines without hardcoded logic.

---

## 🛠 Tech Stack

- **Language:** Python 3.10+
- **Web Framework:** [FastAPI](https://fastapi.tiangolo.com/)
- **ASGI Server:** [Uvicorn](https://www.uvicorn.org/)
- **Database ORM:** [SQLAlchemy](https://www.sqlalchemy.org/) 2.0+
- **Database Engine:** SQLite (embedded)
- **Data Validation & Settings:** [Pydantic](https://docs.pydantic.dev/) v2 & [Pydantic-Settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)
- **Testing:** [Pytest](https://docs.pytest.org/) & [HTTPX](https://www.python-httpx.org/)

---

## 📁 Project Structure

```text
FlowGuard/
├── app/
│   ├── __init__.py               # Application package definition
│   ├── main.py                   # FastAPI application factory & route registration
│   ├── api/                      # API routing layer
│   │   ├── __init__.py
│   │   └── v1/
│   │       ├── __init__.py
│   │       ├── router.py         # v1 API router aggregator
│   │       └── endpoints/        # Route handlers
│   │           ├── __init__.py
│   │           └── health.py     # Health check endpoint (GET /health)
│   ├── core/                     # Core system configurations
│   │   ├── __init__.py
│   │   ├── config.py             # App settings (Pydantic BaseSettings)
│   │   └── database.py           # SQLite connection and session management
│   ├── models/                   # SQLAlchemy ORM models (for future phases)
│   │   └── __init__.py
│   ├── schemas/                  # Pydantic validation schemas
│   │   ├── __init__.py
│   │   └── health.py             # Health check payload schema
│   └── services/                 # Business logic & workflow execution services
│       └── __init__.py
├── tests/                        # Automated test suite
│   ├── __init__.py
│   ├── conftest.py               # Pytest fixtures (TestClient)
│   └── test_health.py            # Health and documentation tests
├── .gitignore                    # Git ignore file for Python, SQLite, caches
├── README.md                     # Project documentation
├── requirements.txt              # Production and development dependencies
└── run.py                        # Clean entry point script to run the server
```

---

## 🚀 Quick Start & Setup Instructions

### 1. Prerequisites

- Python 3.10 or higher installed on your system.

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

### Option B: Using Uvicorn Directly

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

The server will start at: `http://127.0.0.1:8000`

---

## 🔍 Verification Endpoints

Once the application is running, verify the following endpoints:

| Endpoint | Method | Description | URL |
| :--- | :--- | :--- | :--- |
| **Health Check** | `GET` | Operational health and version metadata | [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health) |
| **API v1 Health** | `GET` | Health endpoint scoped under API v1 | [http://127.0.0.1:8000/api/v1/health](http://127.0.0.1:8000/api/v1/health) |
| **Interactive Docs (Swagger UI)** | `GET` | Interactive API documentation | [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs) |
| **ReDoc Documentation** | `GET` | Alternative API reference documentation | [http://127.0.0.1:8000/redoc](http://127.0.0.1:8000/redoc) |
| **OpenAPI Schema** | `GET` | Raw OpenAPI JSON specification | [http://127.0.0.1:8000/openapi.json](http://127.0.0.1:8000/openapi.json) |

### Sample Health Check Response (`GET /health`):

```json
{
  "status": "ok",
  "app_name": "FlowGuard",
  "version": "0.1.0"
}
```

---

## 🧪 Running Tests

To run the automated tests with pytest:

```bash
pytest -v
```

This will run all tests in the `tests/` directory verifying:
- `GET /health` returns HTTP 200 with the correct JSON payload.
- `GET /api/v1/health` returns HTTP 200 with the correct JSON payload.
- `GET /docs` serves the Swagger UI successfully.
- `GET /openapi.json` returns valid OpenAPI documentation schema.

---

## 📌 Phase Roadmap

- [x] **Phase 0:** Project scaffolding, modular architecture, dependencies, minimal FastAPI setup, `/health`, `/docs`, `.gitignore`, and entry point.
- [ ] **Phase 1:** Configurable workflow & rule data models (SQLAlchemy) and Pydantic schemas.
- [ ] **Phase 2:** Workflow definition parser and dynamic rule evaluation engine.
- [ ] **Phase 3:** Workflow execution lifecycle, audit logging, and state management.
- [ ] **Phase 4:** Advanced operators, validation, and simulated decision testing.

