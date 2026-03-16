from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from dotenv import load_dotenv
import os

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
GENNIS_DB_URL = os.getenv("GENNIS_DB_URL")
TURON_DB_URL = os.getenv("TURON_DB_URL")

# Management DB (read/write)
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Gennis education center DB (read-only for stats)
gennis_engine = create_engine(GENNIS_DB_URL, execution_options={"postgresql_readonly": True})
GennisSession = sessionmaker(autocommit=False, autoflush=False, bind=gennis_engine)

# Gennis write engine (only used for dividend sync)
gennis_write_engine = create_engine(GENNIS_DB_URL)
GennisWriteSession = sessionmaker(autocommit=False, autoflush=False, bind=gennis_write_engine)

# Turon school DB (read-only for stats)
turon_engine = create_engine(TURON_DB_URL, execution_options={"postgresql_readonly": True})
TuronSession = sessionmaker(autocommit=False, autoflush=False, bind=turon_engine)

# Turon write engine (only used for dividend sync)
turon_write_engine = create_engine(TURON_DB_URL)
TuronWriteSession = sessionmaker(autocommit=False, autoflush=False, bind=turon_write_engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_gennis_db():
    db = GennisSession()
    try:
        yield db
    finally:
        db.close()


def get_turon_db():
    db = TuronSession()
    try:
        yield db
    finally:
        db.close()


def get_gennis_write_db():
    db = GennisWriteSession()
    try:
        yield db
    finally:
        db.close()


def get_turon_write_db():
    db = TuronWriteSession()
    try:
        yield db
    finally:
        db.close()
