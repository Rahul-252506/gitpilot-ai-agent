"""SQLite engine/session setup."""
from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.models.db import Base


def _ensure_db_dir(database_path: str) -> None:
    if database_path and database_path != ":memory:":
        parent = Path(database_path).parent
        if str(parent) and not parent.exists():
            parent.mkdir(parents=True, exist_ok=True)


def create_engine_for(path: str):
    _ensure_db_dir(path)
    if path == ":memory:":
        # Keep a single in-memory DB alive for the process lifetime.
        return create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            future=True,
        )
    return create_engine(
        f"sqlite:///{os.path.abspath(path)}",
        connect_args={"check_same_thread": False},
        future=True,
    )


def init_db(engine) -> None:
    Base.metadata.create_all(bind=engine)


def make_session_factory(engine):
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)