from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, Session

from raconteur.config import config

engine = create_engine(config.db_uri, future=True)
Base = declarative_base()


def get_session() -> Session:
    return Session(engine)
