"""Application entry point for running the FlowGuard server."""

import uvicorn


def main() -> None:
    """Run the Uvicorn ASGI server."""
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
    )


if __name__ == "__main__":
    main()

