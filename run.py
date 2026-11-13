"""Application entry point for running the FlowGuard server."""

import uvicorn
from app.core.database import init_db


def main() -> None:
    """Initialize database and run the Uvicorn ASGI server."""
    # Ensure database tables exist in development
    init_db()

    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8000,
        # reload=True,
    )


if __name__ == "__main__":
    main()
