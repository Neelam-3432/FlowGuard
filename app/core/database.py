"""Database session and connection management."""

from typing import Generator, Optional
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Session
from app.core.config import settings

# SQLite requires check_same_thread=False when used across multiple threads in FastAPI
connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}

engine = create_engine(
    settings.database_url,
    connect_args=connect_args,
)


@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record) -> None:
    """Enable foreign key constraints for all SQLite database connections."""
    try:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
    except Exception:
        # Ignore for non-sqlite backends if switched in the future
        pass


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy declarative models."""
    pass


def get_db() -> Generator[Session, None, None]:
    """Yield a database session and ensure it is closed after request completion."""
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db(target_engine: Optional[Engine] = None) -> None:
    """Initialize database tables for all registered models."""
    import app.models  # noqa: F401

    eng = target_engine or engine
    Base.metadata.create_all(bind=eng)
