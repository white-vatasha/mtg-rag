from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from api.config import get_settings

settings = get_settings()
connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from api import models  # noqa: F401
    from api.config import DEFAULT_DB

    DEFAULT_DB.parent.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)
