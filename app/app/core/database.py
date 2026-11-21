"""Database engine and session factory (SQLite)."""

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.core.config import DATABASE_URL

connect_args = {"check_same_thread": False}
if DATABASE_URL.startswith("sqlite"):
    connect_args["timeout"] = 30

engine = create_engine(DATABASE_URL, connect_args=connect_args)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

Base = declarative_base()


def get_db():
    """FastAPI dependency that yields a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def initialize_database():
    """Create all tables (idempotent)."""
    from app.core import models  # noqa: F401  (register tables)

    Base.metadata.create_all(bind=engine)
