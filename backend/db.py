from functools import lru_cache
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from backend.config import settings


def sqlalchemy_url(url: str) -> str:
    return url.replace("postgres://", "postgresql+psycopg://", 1).replace(
        "postgresql://", "postgresql+psycopg://", 1
    )


@lru_cache
def engine():
    return create_engine(sqlalchemy_url(settings().database_url), pool_pre_ping=True,
                         pool_size=5, max_overflow=5, hide_parameters=True,
                         connect_args={"connect_timeout": 10})


def get_db():
    with Session(engine()) as session:
        yield session
