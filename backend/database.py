from sqlmodel import SQLModel, Session, create_engine
from pathlib import Path
import os
from dotenv import load_dotenv

load_dotenv()

DB_PATH = Path(__file__).parent.parent / "claim_triage.db"
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DB_PATH}")

engine = create_engine(DATABASE_URL, echo=False)


def init_db():
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session
