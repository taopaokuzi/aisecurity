from __future__ import annotations

from contextlib import contextmanager
from functools import lru_cache
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from config.loader import load_runtime_env


def get_database_url(env_name: str | None = None) -> str:
    return load_runtime_env(env_name)["DATABASE_URL"]


def create_sync_engine(
    database_url: str | None = None,
    *,
    echo: bool = False,
    pool_pre_ping: bool = True,
) -> Engine:
    return create_engine(
        database_url or get_database_url(),
        echo=echo,
        pool_pre_ping=pool_pre_ping,
    )


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    return create_sync_engine()


@lru_cache(maxsize=1)
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False, class_=Session)


@contextmanager
def session_scope(
    session_factory: sessionmaker[Session] | None = None,
) -> Iterator[Session]:
    factory = session_factory or get_session_factory()
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
