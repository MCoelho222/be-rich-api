import os
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import Session, create_engine, select
from typing import List
from app.models import User, Expense, Income
from app.pydantic_models import UserCreate, UserRead, ExpenseCreate, ExpenseRead, IncomeCreate, IncomeRead
from dotenv import load_dotenv
load_dotenv()

POSTGRES_USER = os.environ.get('POSTGRES_USER')
POSTGRES_DB = os.environ.get('POSTGRES_DB')
POSTGRES_PASSWORD = os.environ.get('POSTGRES_PASSWORD')
# AWS_USER = os.environ.get('AWS_USER')
# AWS_DB = os.environ.get('AWS_DB')
# AWS_PASSWORD = os.environ.get('AWS_PASSWORD')
# AWS_DB_URL = os.environ.get('AWS_DB_URL')
# AWS_PORT = os.environ.get('AWS_PORT')


# DATABASE_URL = os.environ.get('DATABASE_URL')
DATABASE_URL = 'postgresql://' + POSTGRES_USER + ':' + POSTGRES_PASSWORD + '@localhost:5432/' + POSTGRES_DB

# Create the database engine
engine = create_engine(DATABASE_URL, echo=True)

# Initialize FastAPI with the lifespan context manager
app = FastAPI()

# Configure CORS
origins = [
    "http://localhost:3000",  # Your Next.js frontend URL
    # Add other origins if needed
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,            # Allow specific origins
    allow_credentials=True,           # Allow cookies, authorization headers
    allow_methods=["*"],              # Allow all HTTP methods
    allow_headers=["*"],              # Allow all headers
)

# Dependency to get a session
def get_session():
    with Session(engine) as session:
        yield session


# CRUD Endpoints

# Create User
@app.post("/users/", response_model=UserRead)
def create_user(user: UserCreate, session: Session = Depends(get_session)):
    db_user = User.model_validate(user)
    session.add(db_user)
    session.commit()
    session.refresh(db_user)
    return db_user

# Read Users
@app.get("/users/", response_model=List[UserRead])
def read_users(session: Session = Depends(get_session)):
    users = session.exec(select(User)).all()
    return users

# Update User
@app.put("/users/{user_id}", response_model=UserRead)
def update_user(user_id: int, user: UserCreate, session: Session = Depends(get_session)):
    db_user = session.get(User, user_id)
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")
    user_data = user.model_dump(exclude_unset=True)
    for key, value in user_data.items():
        setattr(db_user, key, value)
    session.add(db_user)
    session.commit()
    session.refresh(db_user)
    return db_user

# Delete User
@app.delete("/users/{user_id}")
def delete_user(user_id: int, session: Session = Depends(get_session)):
    db_user = session.get(User, user_id)
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")
    session.delete(db_user)
    session.commit()
    return {"ok": True}

# Create Expense
@app.post("/expenses/", response_model=ExpenseRead)
def create_expense(expense: ExpenseCreate, session: Session = Depends(get_session)):
    db_expense = Expense.model_validate(expense)
    session.add(db_expense)
    session.commit()
    session.refresh(db_expense)
    return db_expense

# Read Expenses
@app.get("/expenses/", response_model=List[ExpenseRead])
def read_expenses(session: Session = Depends(get_session)):
    expenses = session.exec(select(Expense)).all()
    return expenses

# Create Income
@app.post("/incomes/", response_model=IncomeRead)
def create_income(income: IncomeCreate, session: Session = Depends(get_session)):
    db_income = Income.model_validate(income)
    session.add(db_income)
    session.commit()
    session.refresh(db_income)
    return db_income

# Read Incomes
@app.get("/incomes/", response_model=List[IncomeRead])
def read_incomes(session: Session = Depends(get_session)):
    incomes = session.exec(select(Income)).all()
    return incomes

# Update and Delete endpoints for Expense and Income can be added similarly