# Create User
from fastapi import APIRouter, HTTPException, Depends
from sqlmodel import Session, select
from typing import List
from uuid import UUID
from app.models.models import User
from app.utils.pydantic_models import UserCreate, UserRead
from app.connection_db import get_session

router = APIRouter()


@router.post("/", response_model=UserRead, status_code=201)
def create_user(user: UserCreate, session: Session = Depends(get_session)):
    existing_user = session.exec(select(User).where(User.email == user.email)).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")

    db_user = User.model_validate(user)
    session.add(db_user)
    session.commit()
    session.refresh(db_user)

    return db_user

# Read Users
@router.get("/", response_model=List[UserRead])
def read_users(session: Session = Depends(get_session)):
    users = session.exec(select(User)).all()

    return users


@router.get("/{user_id}", response_model=UserRead)
def get_user(user_id: UUID, session: Session = Depends(get_session)):
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


# Update User
@router.put("/{user_id}", response_model=UserRead)
def update_user(user_id: UUID, user: UserCreate, session: Session = Depends(get_session)):
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
@router.delete("/{user_id}")
def delete_user(user_id: UUID, session: Session = Depends(get_session)):
    db_user = session.get(User, user_id)
    
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")

    session.delete(db_user)
    session.commit()

    return db_user
