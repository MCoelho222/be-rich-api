import os
from sqlmodel import Session, create_engine
from dotenv import load_dotenv

load_dotenv()

POSTGRES_USER = os.environ.get('POSTGRES_USER')
POSTGRES_DB = os.environ.get('POSTGRES_DB')
POSTGRES_PASSWORD = os.environ.get('POSTGRES_PASSWORD')
# DATABASE_URL = os.environ.get('DATABASE_URL')
DATABASE_URL = 'postgresql://' + POSTGRES_USER + ':' + POSTGRES_PASSWORD + '@localhost:5432/' + POSTGRES_DB

# Create the database engine
engine = create_engine(DATABASE_URL, echo=True)
def get_session():
    with Session(engine) as session:
        yield session