import os

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config.settings import settings


class Base(DeclarativeBase):
    pass


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _engine_kwargs(url: str) -> dict:
    if url.startswith("sqlite"):
        return {"connect_args": {"check_same_thread": False}}
    # Postgres gerenciado (ex.: Aiven free) aceita poucas conexões: pool pequeno e configurável,
    # pre_ping para descartar conexões derrubadas pelo provedor e recycle abaixo do idle timeout.
    return {
        "pool_size": _env_int("DB_POOL_SIZE", 5),
        "max_overflow": _env_int("DB_MAX_OVERFLOW", 5),
        "pool_recycle": _env_int("DB_POOL_RECYCLE", 1800),
        "pool_pre_ping": True,
    }


engine = create_engine(settings.database_url, **_engine_kwargs(settings.database_url))
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
