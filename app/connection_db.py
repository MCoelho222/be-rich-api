import os
from sqlmodel import Session, create_engine
from dotenv import load_dotenv

load_dotenv()

DB_URL = os.environ.get('DB_URL')
if not DB_URL:
    raise ValueError("DB_URL environment variable is not set")

# Create the database engine
engine = create_engine(DB_URL, echo=True)
def get_session():
    with Session(engine) as session:
        yield session